# Validate the correct bootstrap -> issued leaf -> renewed leaf lifecycle offline.
def row($name): first(.[] | select(.step == $name));
def cohort($prefix): [.[] | select(.step | startswith($prefix))];
def identities: [.[].entity_id | select(. != null)] | unique;

. as $ops
| {
    request_count: (length == 9),
    exact_steps: (([.[].step] | sort) ==
      ([ ["lifecycle-enroll-", "lifecycle-renew1-", "lifecycle-renew2-"][] as $prefix
         | ["01", "02", "03"][] | $prefix + . ] | sort)),
    all_http_200: all(.[]; .http == 200),
    no_basic_auth: all(.[]; .basic_user == "none"),
    all_cert_auth: all(.[]; (.auth_paths | length) == 1 and
      (.auth_paths[0] | test("^auth/est-matrix-cert-[0-9TZ]+/login$"))),
    one_auth_mount: (([.[].auth_paths[]] | unique | length) == 1),
    client_equals_entity: all(.[]; .entity_id != null and .client_id == .entity_id),
    unique_serials: (([.[].serial] | unique | length) == 9),
    unique_fingerprints: (([.[].sha256] | unique | length) == 9),
    unique_requested_keys: (([.[].csr_public_key_sha256] | unique | length) == 9),
    shared_bootstrap_on_enroll: all(cohort("lifecycle-enroll-")[];
      .operation == "simpleenroll" and .tls_certificate == "shared-auth"),
    renewal_preflight_passed: all(cohort("lifecycle-renew")[];
      .operation == "simplereenroll" and .renewal_preflight == true and
      .tls_subject == .csr_subject and .tls_public_key_sha256 != .csr_public_key_sha256),
    issued_leaf_used_on_first_renewal: all(["01", "02", "03"][]; . as $i
      | ($ops | row("lifecycle-enroll-" + $i)) as $old
      | ($ops | row("lifecycle-renew1-" + $i)) as $new
      | $new.tls_certificate == $old.step and $new.tls_serial == $old.serial and
        $new.tls_sha256 == $old.sha256 and $new.tls_public_key_sha256 == $old.csr_public_key_sha256),
    renewed_leaf_used_on_second_renewal: all(["01", "02", "03"][]; . as $i
      | ($ops | row("lifecycle-renew1-" + $i)) as $old
      | ($ops | row("lifecycle-renew2-" + $i)) as $new
      | $new.tls_certificate == $old.step and $new.tls_serial == $old.serial and
        $new.tls_sha256 == $old.sha256 and $new.tls_public_key_sha256 == $old.csr_public_key_sha256),
    identity_stable_on_second_renewal: all(["01", "02", "03"][]; . as $i
      | ($ops | row("lifecycle-renew1-" + $i).entity_id) ==
        ($ops | row("lifecycle-renew2-" + $i).entity_id))
  } as $checks
| ($ops | {
    enrollment_entities: (cohort("lifecycle-enroll-") | identities),
    first_renewal_entities: (cohort("lifecycle-renew1-") | identities),
    second_renewal_entities: (cohort("lifecycle-renew2-") | identities),
    total_entities: identities
  }) as $observed
| {status: (if ($checks | all(. == true)) then "PASS" else "FAIL" end), checks: $checks,
    observations: ($observed + {
      new_entities_on_first_renewal: ($observed.first_renewal_entities - $observed.enrollment_entities | length),
      new_entities_on_second_renewal: ($observed.second_renewal_entities - $observed.first_renewal_entities - $observed.enrollment_entities | length)
    })}
| if .status == "PASS" then . else error(tojson) end
