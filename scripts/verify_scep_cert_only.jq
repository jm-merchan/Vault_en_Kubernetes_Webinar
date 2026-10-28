# Offline checks for cert-only SCEP: pre-provisioned certificate -> first SCEP
# issuance -> renewal 1 -> renewal 2. Input: lifecycle-operations.json.
def row($name): first(.[] | select(.step == $name));
def cohort($prefix): [.[] | select(.step | startswith($prefix))];
def identities: [.[].entity_id | select(. != null)] | unique;
def serial: ascii_upcase | sub("^0+"; "");
def follows($previous; $current):
  . as $ops | all(["01", "02", "03"][]; . as $i
    | ($ops | row($previous + $i)) as $old
    | ($ops | row($current + $i)) as $new
    | $new.signer_reference == $old.step and
      $new.signer_sha256 == $old.result.sha256 and
      ($new.signer_serial | serial) == ($old.result.serial | serial) and
      $new.signer_public_key_sha256 == $old.csr_public_key_sha256 and
      $new.entity_id == $old.entity_id);

. as $ops
| {
    nine_operations: (length == 9),
    exact_steps: (([.[].step] | sort) ==
      ([ ["cert-first-", "cert-renew1-", "cert-renew2-"][] as $prefix
         | ["01", "02", "03"][] | $prefix + . ] | sort)),
    all_success: all(.[]; .http_status == 200 and .result.pki_status == "0"),
    signatures_and_nonces: all(.[]; .result.signature_verified and .result.nonce_verified),
    no_challenge: all(.[]; .challenge_present == false and .request.challenge_present == false),
    renewalreq_from_first_request: all(.[]; .request.message_type == "17"),
    same_device_cn: all(.[]; .request.signer_cn == .request.csr_cn and .request.csr_cn == .result.common_name),
    fresh_keys: all(.[]; .signer_public_key_sha256 != .csr_public_key_sha256),
    nine_distinct_keys: (([.[].csr_public_key_sha256] | unique | length) == 9),
    nine_distinct_serials: (([.[].result.serial] | unique | length) == 9),
    nine_distinct_fingerprints: (([.[].result.sha256] | unique | length) == 9),
    cert_auth_verified: all(.[]; .expected_auth == "cert" and .auth_verified and
      (.auth_paths | length) == 1 and (.auth_paths[0] | startswith("auth/scep-cert-cli-"))),
    one_auth_mount: (([.[].auth_paths[]] | unique | length) == 1),
    client_equals_entity: all(.[]; .entity_id != null and .entity_id == .client_id),
    bootstrap_used_initially: all(["01", "02", "03"][]; . as $i
      | ($ops | row("cert-first-" + $i).signer_reference) == ("bootstrap-" + $i)),
    first_renewal_uses_previous_leaf_and_identity: follows("cert-first-"; "cert-renew1-"),
    second_renewal_uses_previous_leaf_and_identity: follows("cert-renew1-"; "cert-renew2-")
  } as $checks
| ($ops | {
    initial_entities: (cohort("cert-first-") | identities),
    first_renewal_entities: (cohort("cert-renew1-") | identities),
    second_renewal_entities: (cohort("cert-renew2-") | identities),
    total_entities: identities
  }) as $observations
| {status: (if ($checks | all(. == true)) then "PASS" else "FAIL" end), checks: $checks,
    observations: ($observations + {
      new_entities_on_first_renewal: ($observations.first_renewal_entities - $observations.initial_entities | length),
      new_entities_on_second_renewal: ($observations.second_renewal_entities - $observations.first_renewal_entities - $observations.initial_entities | length)
    })}
| if .status == "PASS" then . else error(tojson) end
