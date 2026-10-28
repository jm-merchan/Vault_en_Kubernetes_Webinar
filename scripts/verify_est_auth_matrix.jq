# Offline regression checks for the authentication behavior observed on Vault 2.2.0.
# Input: operations.json. No credentials, network calls or certificate issuance.
def row($name): first(.[] | select(.step == $name));
def cohort($pattern): [.[] | select(.step | test($pattern))];
def identities: [.[].entity_id | select(. != null)] | unique;
def matches($left; $right):
  . as $all | all(["01", "02", "03"][];
    . as $i | ($all | row($left + $i).entity_id) == ($all | row($right + $i).entity_id));
def routed($step; $method):
  row($step) | (.auth_paths | length == 1) and (.auth_paths[0] | contains("/est-matrix-" + $method + "-"));

. as $ops
| {
    "shared-cert-device-renew": 400,
    "no-auth-enroll": 401,
    "no-auth-renew": 401,
    "wrong-password-enroll": 401,
    "basic-only-renew": 400,
    "bad-basic-valid-cert-enroll": 401,
    "bad-basic-valid-cert-renew": 401,
    "untrusted-enroll": 401,
    "untrusted-renew": 401,
    "basic-shared-cert-renew": 400,
    "changed-cn-renew": 400,
    "changed-san-renew": 400
  } as $rejected
| ($ops | {
    request_count: (length == 41),
    unique_step_names: (([.[].step] | unique | length) == 41),
    exact_step_names: (([.[].step] | sort) ==
      ([(["up-shared-", "up-shared-renew-", "up-unique-", "up-unique-renew-", "cert-shared-",
          "cert-own-transition-", "cert-own-enroll-", "cert-own-renew-"][] as $prefix
          | ["01", "02", "03"][] | $prefix + .),
        "shared-cert-device-renew", "shared-auth-renew", "renewed-shared-auth-enroll",
        "both-enroll", "both-renew", "no-auth-enroll", "no-auth-renew", "wrong-password-enroll",
        "basic-only-renew", "bad-basic-valid-cert-enroll", "bad-basic-valid-cert-renew",
        "untrusted-enroll", "untrusted-renew", "valid-basic-untrusted-cert", "basic-shared-cert-renew",
        "changed-cn-renew", "changed-san-renew"] | sort)),
    exact_http_results: all(.[]; .http == ($rejected[.step] // 200)),
    successful_certificates: (([.[] | select(.http == 200)] | length) == 29),
    unique_serials: (([.[] | select(.http == 200) | .serial] | unique | length) == 29),
    unique_fingerprints: (([.[] | select(.http == 200) | .sha256] | unique | length) == 29),
    client_equals_entity: all(.[]; .client_id == .entity_id),
    total_identities: ((identities | length) == 8),
    shared_user_enroll_count: ((cohort("^up-shared-[0-9]+$") | length) == 3),
    shared_user_enroll_identity: ((cohort("^up-shared-[0-9]+$") | identities | length) == 1),
    shared_user_renewal_identity: matches("up-shared-"; "up-shared-renew-"),
    unique_users_enroll_identities: ((cohort("^up-unique-[0-9]+$") | identities | length) == 3),
    unique_users_renewal_identity: matches("up-unique-"; "up-unique-renew-"),
    shared_cert_enroll_count: ((cohort("^cert-shared-[0-9]+$") | length) == 3),
    shared_cert_enroll_identity: ((cohort("^cert-shared-[0-9]+$") | identities | length) == 1),
    own_cert_identities: ((cohort("^cert-own-transition-[0-9]+$") | identities | length) == 3),
    own_cert_distinct_from_shared: all(cohort("^cert-own-transition-[0-9]+$")[];
      .entity_id != ($ops | row("cert-shared-01").entity_id)),
    own_cert_enroll_identity: matches("cert-own-transition-"; "cert-own-enroll-"),
    own_cert_renewal_identity: matches("cert-own-enroll-"; "cert-own-renew-"),
    shared_auth_rotation_identity: (
      row("cert-shared-01").entity_id == row("shared-auth-renew").entity_id and
      row("cert-shared-01").entity_id == row("renewed-shared-auth-enroll").entity_id),
    basic_precedence: (routed("both-enroll"; "up") and routed("both-renew"; "up")),
    combined_identity: (row("both-enroll").entity_id == row("up-shared-01").entity_id and
      row("both-renew").entity_id == row("up-shared-01").entity_id),
    no_cert_fallback: (routed("bad-basic-valid-cert-enroll"; "up") and
      routed("bad-basic-valid-cert-renew"; "up")),
    cert_controls_use_cert_auth: (routed("untrusted-enroll"; "cert") and routed("untrusted-renew"; "cert")),
    basic_with_untrusted_cert: (routed("valid-basic-untrusted-cert"; "up") and
      row("valid-basic-untrusted-cert").entity_id == row("up-shared-01").entity_id)
  }) as $checks
| {status: (if ($checks | all(. == true)) then "PASS" else "FAIL" end), checks: $checks}
| if .status == "PASS" then . else error(tojson) end
