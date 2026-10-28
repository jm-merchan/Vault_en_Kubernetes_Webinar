# Vault PKI EST, SCEP CLI and SCEP/Intune validation report

Date: 2026-10-28  
Target observed: Vault Enterprise 2.2.0, root namespace, cluster `vault-cluster-a6baed9a`  
Source notebook reviewed without modification: `2_PKI_API_EST.ipynb`  
SHA-256 before and after review: `1b54d023f47e24d8e1b2031287c67741d9b88b00c3ed75db122d61adf3e85f56`

## Executive conclusion

The EST implementation is technically substantial, but the original notebook contains no executed outputs and is not safe to run end-to-end unattended. A separate isolated validation reproduced the core EST flows successfully without changing the source notebook. A focused follow-up then issued three distinct EST certificates and re-enrolled one device with the same userpass credential: all four requests resolved to one entity/client ID and increased the entity-client counter by one.

The full EST authentication matrix, run `20261028T143051Z`, completed **41 requests: 29 successful issuances and 12 rejections**. Shared Basic credentials represented three devices as one entity during enrollment and re-enrollment. Certificate-based bootstrap also worked correctly: one shared TLS certificate/key authenticated three initial enrollments, then each device successfully re-enrolled using its own issued certificate/key. The first transition created three device identities in addition to the historical bootstrap identity; subsequent renewals added none. Attempting renewal with the bootstrap certificate instead of the issued device certificate was a separate negative control, not the valid lifecycle. When Basic and a certificate were both supplied, Basic selected the Vault identity. The detailed results and reproducible Bash-only workflow are below and in `EST_Auth_Matrix_Validation.ipynb`.

After the scope was broadened to permit SCEP without Intune, a real curl-based SCEP test issued three distinct certificates and renewed one with a shared static challenge. It produced **three entity clients**, with aliases matching the device CNs. Renewal retained the first device's identity and added **zero clients**. The shared-credential/one-client hypothesis observed with EST userpass therefore does **not** hold for this SCEP configuration.

The extended run `20261028T140639Z` also tested challenge-free renewal through a dedicated `cert` auth mount. Switching all three devices from SCEP challenge authentication to cert authentication created **three additional entities**, despite unchanged device CN/SANs. A subsequent cert-auth renewal preserved its cert-auth entity and added **zero clients**. No aliases were manually linked or merged between the two mounts. The result is six counted identities for three devices using these two unlinked authentication methods, not a new client on every renewal.

The new cert-only run `20261028T165249Z` used a pre-provisioned individual certificate/key for each of three devices, with **no challenge and no SCEP challenge authenticator at any stage**. The first three SCEP requests and two subsequent renewal rounds all succeeded. All nine requests used the same cert auth mount, and each renewal was signed with the exact certificate/key returned in the previous step. The client counter moved **29 → 32 → 32 → 32**: three clients in total and zero additional clients on either renewal round. The first SCEP requests were protocol-level `RenewalReq` messages because trusted device certificates already existed; this was not unauthenticated first-ever certificate provisioning.

The earlier `SCEP_Intune_Validation.ipynb` configured an isolated SCEP/Intune setup and validated GetCACerts, but no Intune app credential, deployed profile, or enrolled devices were available. Its Intune-specific external validation remains untested; the new SCEP CLI test does not require it.

Vault's non-entity-token deduplication rules are not the explanation for the measured SCEP behavior: this run used batch tokens **with entities**, and each distinct CN had a distinct alias/client ID despite sharing the challenge, auth mount, role, policies, and namespace. Intune-specific identity behavior must be measured separately before extrapolating this result to that authentication type.

PKI Only is different: Vault 1.21+ does not deduplicate certificate issuance. Every emitted certificate, including a renewal, increments the certificate count after the asynchronous persistence interval.

## 1. Static review of the EST notebook

### Scope and execution state

- 132 cells; EST starts at cell 63.
- No code cell has an execution count or preserved output.
- The first half also creates a generic root/intermediate PKI demo. EST is not an independent notebook.
- No Vault version or edition is pinned in the notebook. The text requires Enterprise; the live target was Enterprise 2.2.0.
- The effective namespace is root. Several later cells explicitly run `unset VAULT_NAMESPACE`.

### PKI resources

| Layer | Mount / issuer / role | Configuration in the source notebook |
|---|---|---|
| Root CA | `pki/`, issuer `root-2026` | Internal root, `ttl=87600h` |
| Generic intermediate | `pki_int/`, issuer `example-dot-com-intermediate` | Signed by `pki/`; role `example-dot-com` |
| EST intermediate | `pki_est/`, issuer `est-intermediate` | Internal RSA key, signed by `pki/`, `max_lease_ttl=43800h` |
| Default EST role | `pki_est/roles/est-clients` | RSA 2048, client auth only, `ttl=12h`, `max_ttl=24h`, CSR CN/SAN enabled |
| Label A | `pki_est/roles/est-perfil-a` | `*.perfil-a.est.example.com`, organization `CustPerfilA`, OU `cust-perfil-a`, `ttl=12h`, `max_ttl=24h` |
| Label B | `pki_est/roles/est-perfil-b` | `*.perfil-b.est.example.com`, organization `CustPerfilB`, OU `cust-perfil-b`, `ttl=2h`, `max_ttl=4h` |

The notebook renews immediately after enrollment to exercise the protocol. It does not wait for a percentage of the certificate lifetime, so there is no operational renewal schedule to document.

### EST routing configuration

The first EST configuration writes:

- `enabled=true`
- `default_mount=true`
- `default_path_policy="role:est-clients"`
- `label_to_path_policy={"est-clients":"role:est-clients"}`
- userpass and cert delegated authenticators
- Sentinel parsing plus audit fields

Later, cell 109 replaces that routing with:

- `default_mount=false`
- `default_path_policy` remains `role:est-clients` but is no longer used by the unlabelled well-known path
- `label_to_path_policy={"cust-perfil-a":"role:est-perfil-a","cust-perfil-b":"role:est-perfil-b"}`

Consequently, the final intended state rejects `/.well-known/est/cacerts` and exposes only the two labelled paths. The NGINX proof of concept maps two hostnames back to those labels while clients use an unlabelled URL.

### Authentication and tokens

| EST credential | Delegated auth mount | Token |
|---|---|---|
| HTTP Basic | `est-userpass/` (`userpass`) | batch, TTL 5 minutes |
| TLS client certificate | `est-cert/` (`cert`) | batch, TTL 5 minutes |

The default Basic user is `estuser`. The notebook embeds the test password `estpass` in source cells. The labelled users generate random passwords in local files. For re-enrollment, Basic selects the Vault auth path, but the current leaf and matching private key are still presented in TLS. A Basic-only `simplereenroll` is expected to fail with HTTP 400 and `no certificate found in TLS state`.

The configured protocol paths are:

- `/.well-known/est/{cacerts,simpleenroll,simplereenroll}` while `default_mount=true`;
- `/.well-known/est/{label}/{cacerts,simpleenroll,simplereenroll}` for registered labels;
- `/v1/pki_est/roles/{role}/est/{cacerts,simpleenroll,simplereenroll}` for explicit API paths.

### Environment and external dependencies

- `/tmp/vault/config.env` with `VAULT_ADDR`, `VAULT_CACERT`, and `VAULT_TOKEN`.
- `WORKDIR=/tmp/vault`, `CERT_NAME=2026`.
- Vault CLI, curl, jq, OpenSSL, Python 3, kubectl, Kubernetes context `workshop-k8s`, and namespace `vault`.
- Existing Kubernetes Vault TLS Secret `vault-ha-tls`, ConfigMap `vault-config`, HA pods `vault-0..2`, and `/tmp/vault/cluster-keys.json` for manual unseal.
- The proxy flow creates an NGINX deployment/service, client pod, ConfigMap, five Secrets, local CA/key files, password files, CSRs, keys, certificates, and response artifacts.

### Cleanup review

The cleanup cells are `raw`, so Jupyter does not execute them as code. The EST cleanup deletes the EST mount, two auth mounts, policies, local directory, and labelled Kubernetes resources. It does **not** restore the modified Vault listener; it only leaves a comment instructing the operator to restore a previous HCL file and restart/unseal each pod. The generic PKI cleanup is also raw and would delete shared `pki/` and `pki_int/` mounts if manually converted and run.

### Material findings

1. **No preserved evidence in the source notebook.** All expected results are assertions in code, not observations.
2. **TLS verification is disabled in early EST cells.** Multiple calls use `curl -k`; later label tests correctly use `VAULT_CACERT`.
3. **Hard-coded Basic credential.** `estuser:estpass` is acceptable only as an explicit throwaway lab credential, but it should be generated at runtime.
4. **Unsafe listener mutation.** Cell 124 patches a shared listener with hard-coded `10.244.0.0/24`, restarts all Vault pods, reads an unseal key from disk, and has no executable rollback.
5. **Not fully idempotent.** Some enable commands tolerate existing mounts but then overwrite roles/config; reruns can mix old issuers, certificates, passwords, and labels.
6. **Portability issue reproduced.** macOS LibreSSL does not implement the same `openssl x509 -ext` CLI behavior as OpenSSL 3. A missing newline between concatenated PEM certificates also breaks cert-auth trust loading and `openssl verify`.
7. **Audit evidence is incomplete.** The notebook configures parsed EST fields but does not collect request IDs, entity/client IDs, alias, auth accessor, namespace, policies, or a redacted audit evidence bundle.
8. **No client or certificate counters.** The source notebook does not call the activity or certificate-billing endpoints, so it cannot support a licensing conclusion.

## 2. Live EST validation using isolated resources

The source notebook was not executed or modified. `scripts/validate_est_isolated.sh` created separate resources, tested them, preserved redacted evidence, and removed the temporary mounts/auth methods/audit device.

### Observed protocol results

| Test | Observed |
|---|---|
| `cacerts` | HTTP 200; EST Review Intermediate CA issued by EST Review Root CA |
| HTTP Basic `simpleenroll` | HTTP 200 |
| No credential | HTTP 401 |
| Wrong password | HTTP 401 |
| Basic-only `simplereenroll` | HTTP 400, current TLS certificate required |
| Basic + current leaf/key `simplereenroll` | HTTP 200; serial changed from `03C79874...` to `61A7A6E3...` |
| TLS cert-auth `simpleenroll` | HTTP 200 |

The issued leaf had CN and DNS SAN `device-a.est-review.example.test`, issuer `EST Review Intermediate CA`, RSA 2048, client-auth policy, and approximately one hour of validity. The renewal used a new key and produced a new serial.

### Audit and identity evidence

- Userpass accessor: `auth_userpass_34a061a3`.
- Cert accessor: `auth_cert_de49e71e`.
- Basic `simpleenroll` request ID `45b8904e-610b-8759-ab14-69263429190d` used entity ID `04c0e8d0-d2fe-f796-0501-3f0d98631909`, batch token, and policies `default`, `est-review-enroll`.
- Successful Basic re-enrollment request ID `f8fcbc1a-3289-9514-6ecb-d79e45dd1fe6` retained that same entity ID and policy set.
- Cert-auth enrollment request ID `19f5be1e-14f2-584c-030a-17736ad098cf` used a different entity ID, `b63ec8f4-18cd-4900-b933-92664de7cd5e`.

This proves the EST authentication method affects Vault identity. It does not prove the SCEP/Intune constructed-client behavior.

### Counters

The certificate counter moved from 4 to 9 after approximately 40 seconds in the successful isolated pass. The delta was five: one root CA, one intermediate CA, and three leaf certificates. This is consistent with the documented non-deduplicating certificate count.

The activity total moved from one to three entity clients across the two EST attempts. The additional historical entry came from the first, failed validation attempt using a now-deleted mount accessor. This illustrates why repeated test setup with new auth accessors can itself create extra client identities and why the activity export/audit must be correlated per run.

### Shared-credential hypothesis test

On 2026-10-28, `scripts/test_est_shared_credential.sh` performed three independent EST `simpleenroll` requests using one userpass mount and the same `shared-fleet` username/password. Each request used a new private key, CSR, CN, and DNS SAN.

| Device | HTTP | Certificate serial |
|---|---:|---|
| `device-01.est-shared.example.test` | 200 | `424078F676EF31D710F10976DE2DC1D458E879DE` |
| `device-02.est-shared.example.test` | 200 | `4D64FB4C4D6325DB435EE6ABF68429C7D59C379F` |
| `device-03.est-shared.example.test` | 200 | `14648CF94360794E9804DC24B84B324279743D1D` |

The three certificates also had distinct SHA-256 fingerprints. Audit correlation produced three successful request IDs, but all three resolved to client ID and entity ID `accb890e-c749-2c3b-b33b-8bf3aa993fff`, display name `est-shared-userpass-shared-fleet`, and batch tokens. The activity counter moved from three to four entity clients: a delta of one, not three. The activity export contains exactly one row for alias `shared-fleet` and accessor `auth_userpass_f266aa93`. This confirms the tested hypothesis for this Vault 2.2.0 cluster: three devices using the same userpass credential on the same auth mount and namespace are represented as one Vault entity client.

The PKI certificate counter moved from 11 to 16 because the isolated run created one root, one intermediate, and three leaf certificates. Certificate counting remains per certificate and is not deduplicated by the shared Vault identity. All temporary EST resources and private keys were removed; public certificates and redacted evidence remain under `evidence/est-shared-credential-20261028T132013Z/`.

### Shared-credential re-enrollment test

A second isolated run extended the case with `simplereenroll`. `device-01` used the same `shared-fleet` Basic credential and presented its current certificate/key at the TLS layer, as required by EST. No certificate-auth mount or second Vault authentication method was configured.

- Three `simpleenroll` responses: HTTP 200.
- One `simplereenroll` response: HTTP 200.
- Original serial: `6CA8E3ECF82B140FCF55AC3E8076B8E82F080D95`.
- Re-enrolled serial: `33131CF211D15FE4ACD27A67A4D93B3D40689F44`.
- Four distinct request IDs, one client/entity ID: `8988017b-68fd-4f0e-b7bc-7b91c835e2c6`.
- Activity counter: four to five entity clients, delta one for the complete run. The re-enrollment did not create another client.
- PKI certificate counter: 16 to 22, delta six: one root, one intermediate, three initial leaves, and one re-enrolled leaf.

The detailed activity export had not published the new row after a bounded three-minute polling window, although the aggregate activity counter and audit correlation were already complete. This lag is recorded rather than treated as a failed identity test. Temporary Vault resources and private keys were removed; the public certificate chain, four leaf certificates, redacted audit correlation, counters, and status are preserved under `evidence/est-shared-credential-20261028T132333Z/`.

### EST authentication matrix: enrollment and re-enrollment

Run `20261028T143051Z` used `scripts/test_est_auth_matrix.sh` against Vault Enterprise 2.2.0. It created an isolated PKI mount, one test CA, one `userpass` mount, one `cert` mount and one narrowly scoped policy in the root namespace. Both authenticators used five-minute batch tokens. The role-qualified EST URL avoided global routing changes (`default_mount=false`, no labels). Existing listeners, other PKI mounts and Intune resources were not changed. The script uses Bash, curl, jq, OpenSSL 3, Vault CLI and kubectl; nothing was installed and no Python application code was used.

Each device had a distinct CN and DNS SAN (`device-01/02/03.est-matrix.example.test`). Every successful issuance used a fresh CSR key. The shared bootstrap certificate had a different CN/SAN, `shared-auth.est-matrix.example.test`, and was signed by the isolated CA. Curl verified server TLS throughout; EST requests never carried the administrative Vault token. The PKI role permits this test domain but does not enforce per-device ownership within it.

#### Successful flows and identity transitions

| Scenario | `simpleenroll` result | `simplereenroll` result | Observed client identity |
|---|---|---|---|
| One shared Basic user/password, three device CNs | 3 × HTTP 200 | 3 × HTTP 200, each with its current device certificate/key in TLS | One userpass entity; renewal adds zero |
| One Basic user/password per device | 3 × HTTP 200 | 3 × HTTP 200, each with matching device certificate/key | Three userpass entities; renewal adds zero |
| Shared TLS certificate/key for bootstrap, then the issued device certificate/key; no Basic | 3 × HTTP 200 for distinct device CNs | 3 × HTTP 200, each authenticated with its own issued leaf/key | One bootstrap entity, then three additional device entities |
| Subsequent operations with device-specific TLS certificates, no Basic | 3 × HTTP 200 | 3 × HTTP 200 on the next renewal | The same three device cert-auth entities; zero additional clients |
| Rotate the shared authentication certificate itself | Renewed shared certificate then enrolls device-01: HTTP 200 | HTTP 200 for the shared certificate's own unchanged Subject/SAN, with a new key | Same bootstrap cert-auth entity; zero additional clients |
| Basic and a trusted TLS certificate together | HTTP 200 with shared Basic and shared TLS certificate | HTTP 200 with shared Basic and device-01 TLS certificate | Delegated `userpass` login, same shared-user entity, not two identities |

The device-cert sequence was deliberately: shared-cert enrollment → own-cert re-enrollment → own-cert enrollment → own-cert re-enrollment. Its additional three clients appeared on the first transition, not on every certificate issuance. The shared bootstrap identity remains in historical usage, so that cohort totals **four identities**, not three, after the transition. No aliases were linked or merged.

#### Negative controls and authentication precedence

| Request | HTTP | Evidence / interpretation |
|---|---:|---|
| No authentication: enroll and re-enroll | 401 / 401 | No delegated identity |
| Wrong Basic password: enroll | 401 | Userpass rejected |
| Correct Basic but no TLS certificate: re-enroll | 400 | `no certificate found in TLS state` |
| Wrong Basic plus valid certificate: enroll and re-enroll | 401 / 401 | Userpass attempted; no fallback to cert auth |
| Untrusted self-signed TLS certificate without Basic: enroll and re-enroll | 401 / 401 | Cert authenticator rejected |
| Correct Basic plus untrusted TLS certificate: enroll | 200 | Userpass selected; the presented certificate is not a second authentication factor in this configuration |
| Correct Basic plus shared TLS certificate, CSR for device-01: re-enroll | 400 | `CSR Subject field does not match client certificate` |
| Shared TLS certificate alone, CSR for device-01: re-enroll | 400 | Same Subject mismatch, despite successful cert authentication |
| Own trusted TLS certificate, changed CSR CN: re-enroll | 400 | Subject mismatch |
| Own trusted TLS certificate, same CN but changed DNS SAN: re-enroll | 400 | `CSR SubjectAltName Extension does not match client certificate` |

These rejection cases are negative controls, not a claim that a correctly implemented bootstrap-to-device lifecycle fails. For the certificate-only lifecycle, the correct request presents the previously issued device certificate and its matching key, not the shared bootstrap certificate.

Thus, **the credential selecting the Vault entity and the certificate required by the re-enrollment protocol are separate concerns**. With Basic, different TLS device certificates do not select additional cert-auth identities. Without Basic, those same device certificates select their own cert-auth identities. Supplying Basic does not bypass the tested Subject/SAN checks.

#### Audit, counters and independent verification

The per-request `operations.json` contains all 41 HTTP results, unique request IDs, delegated login paths, entity/client IDs, serials and fingerprints. Its ordered correlation is valid for sequential requests on these isolated paths; the analyzer checks audit/request counts and operation paths. `entity-aliases.json` records four userpass aliases (`shared`, `device-01`, `device-02`, `device-03`) under `auth_userpass_dbea77fb`, and four cert aliases (the shared CN and three device CNs) under `auth_cert_b80e474d`.

| Checkpoint | Entity clients | New clients in phase |
|---|---:|---:|
| Before matrix | 17 | — |
| Shared-user enrollment | 18 | 1 |
| Shared-user renewal | 18 | 0 |
| Individual-user enrollment | 21 | 3 |
| Individual-user renewal | 21 | 0 |
| Shared-cert enrollment | 22 | 1 |
| Shared-cert/device renewal rejected | 22 | 0 |
| Transition to individual device cert authentication | 25 | 3 |
| Own-cert enrollments and subsequent renewals | 25 | 0 |
| Shared-auth rotation, combined authentication and controls | 25 | 0 |

There were **eight distinct entity/client IDs**, no non-entity clients. The detailed activity export contains eight matching rows; its client-ID set equals the audit set. This is not inferred from the aggregate counter alone. OpenSSL verified all 29 issued leaf chains, Subject and CSR public keys during the run; an independent post-run pass reverified their chains and expected DNS SANs. All 29 serials and SHA-256 fingerprints are distinct. Offline regression checks in `scripts/verify_est_auth_matrix.jq` validate HTTP outcomes, identity stability, transitions and authenticator routing.

The certificate counter moved **41 → 72 (+31)**: 29 successful EST leaf issuances, one bootstrap leaf and one CA. Re-enrollment therefore preserved identity where applicable but still issued/counts a new certificate. Aggregate counters could include other workloads; this run's exact issuance inventory and isolated audit support the attribution.

All HTTP operations completed on the first run. A `jq` summary assertion then failed due to an array-selection error, triggering cleanup. The assertion was corrected and `--analyze` replayed the saved requests/audit without reissuing any certificates. `summary.json` explicitly records `analyzed_from_saved_requests=true`. The current analyzer and offline assertions both pass.

Evidence: `evidence/est-auth-matrix-20261028T143051Z/`, particularly `summary.json`, `assertions.json`, `operations.json`, `phase-deltas.json`, `entity-aliases.json`, `activity-export-focused.jsonl`, `independent-certificate-verification.txt` and `cleanup-*.json`. Read-only post-cleanup checks confirmed the exact PKI mount, two auth mounts, policy and audit device were absent. Local temporary keys/passwords were deleted. Public certificates, redacted local evidence, HMAC-protected server audit files, historical counters and residual Identity records remain; deleting mounts does not erase historical usage.

Scope: these are measured Vault 2.2.0 outcomes for this CA-trust cert-auth configuration and root namespace. The alias observed was the authentication certificate's CN **within its auth accessor**, not a globally unique CN across Vault. Different mounts/namespaces, alias linking, leaf-pinned cert roles, other alias configurations, expired/revoked certificates, listener/proxy variants, device vendor clients and long-term renewal scheduling were not tested. Sharing a private key is a lab hypothesis, not a production security recommendation. Technical counter observations do not replace contractual licensing terms. Official context: [Vault EST](https://developer.hashicorp.com/vault/docs/secrets/pki/est) and [EST API configuration](https://developer.hashicorp.com/vault/api-docs/secret/pki/issuance#est-certificate-issuance).

### Correct EST certificate lifecycle: focused repeat

The previous summary table placed a negative control (using the shared bootstrap certificate to renew a different device Subject) in the lifecycle row. That presentation was misleading. The correct implementation uses the certificate issued to the device and its matching private key for re-enrollment. The table above has been corrected; the invalid request remains only in the negative-controls section.

At the user's request, run **`20261028T145228Z`** repeated only this correct lifecycle from a clean isolated setup, using `bash scripts/test_est_auth_matrix.sh --cert-lifecycle`. No HTTP Basic, userpass authenticator or negative test was used. EST delegated all nine requests to the **same cert auth mount**, accessor `auth_cert_88b40eca`, trusting the isolated CA with the same `devices` cert role, policy and root namespace throughout.

| Phase | TLS client credential actually presented | Result | Entity-client counter | New clients |
|---|---|---|---:|---:|
| Before | — | — | 25 | — |
| Three initial `simpleenroll` requests | Same shared bootstrap certificate/key; three distinct device CSRs | 3 × HTTP 200 | 26 | 1 |
| First `simplereenroll` for each device | That device's issued enrollment certificate and matching private key | 3 × HTTP 200 | 29 | 3 |
| Second `simplereenroll` for each device | That device's first-renewal certificate and matching private key | 3 × HTTP 200 | 29 | 0 |

Before each renewal, the script verifies that the TLS certificate is not the bootstrap certificate, its private key matches, its chain is valid for TLS client authentication, and its Subject/SAN match the new CSR. The CSR requests a freshly generated key. The saved serial and SHA-256 fingerprint of the TLS credential are checked against the exact certificate returned by the previous request for that device. The second renewal therefore tests the newly issued certificate, not reuse of the original enrollment credential.

| Identity | Enrollment entity | First-renewal entity | Second-renewal entity |
|---|---|---|---|
| device-01 | `2907df3a-8d4f-eef2-5aec-5b3fef1d724c` | `a4896b1a-de0c-efbd-4d94-7320728fd506` | `a4896b1a-de0c-efbd-4d94-7320728fd506` |
| device-02 | `2907df3a-8d4f-eef2-5aec-5b3fef1d724c` | `ad68e1f8-bfd7-626e-62a6-09bcd5afa3a5` | `ad68e1f8-bfd7-626e-62a6-09bcd5afa3a5` |
| device-03 | `2907df3a-8d4f-eef2-5aec-5b3fef1d724c` | `5de37b0d-5c3c-e925-8f91-7f11413863cc` | `5de37b0d-5c3c-e925-8f91-7f11413863cc` |

**The valid lifecycle succeeds in all nine requests.** The measured total is four historical identities for this cohort: one shared bootstrap identity and three device identities. The first renewal changes the authenticated certificate identity; subsequent key/serial rotation preserves each device's identity. No new auth mount, policy or namespace was introduced between these phases, and no aliases were linked/merged.

All nine leaf serials, fingerprints and CSR public keys are distinct. OpenSSL independently reverified the nine certificate chains, CSR signatures, Subject/DNS SAN and issued-public-key/CSR matching after the run. `scripts/verify_est_cert_lifecycle.jq` passes all checks, including the precise previous-certificate chain of use and stable identity on the second renewal. Unlike the earlier full matrix, this run completed successfully without analysis replay (`analyzed_from_saved_requests=false`).

The certificate counter moved **72 → 83 (+11)** after bounded polling: nine successful EST leaf issuances, one bootstrap leaf and one test CA. The detailed client activity export was still pending when sampled (zero rows for this new accessor); identity attribution is supported by all nine audit request IDs, four Identity records and per-request activity counters. Export propagation is not presented as completed.

Evidence: `evidence/est-auth-matrix-20261028T145228Z/`, including `summary.json`, `assertions.json`, `lifecycle-comparison.json`, `operations.json`, the nine public CSRs/certificates, `entity-aliases.json`, `phase-deltas.json` and `independent-certificate-verification.txt`. Read-only cleanup checks confirmed the test PKI/auth mount, policy and audit device were removed. The temporary private-key directory was removed; public/redacted evidence, residual Identity records, HMAC-protected server audit files and historical usage remain. The original EST notebook's SHA-256 is unchanged.

The tested certificate-capable-client lifecycle follows the re-enrollment path described in [RFC 7030, section 4.2.2](https://datatracker.ietf.org/doc/html/rfc7030#section-4.2.2). This is a measurement of this Vault configuration, not a blanket assertion about every EST client or all RFC authentication alternatives.

### SCEP without Intune: curl validation

Run `20261028T133434Z` used `scripts/test_scep_shared_credential.sh` and Vault Enterprise 2.2.0. `SCEP_CLI_Validation.ipynb` documents this repeatable workflow. It uses Bash, OpenSSL, curl and jq; the Go helper in `scripts/scep-message/` only creates/verifies the RFC 8894 CMS envelope. No Python application code or Intune infrastructure is involved. The notebook uses `%%bash` cells with the repository's usual Jupyter kernel.

`curl` called `GetCACaps`, `GetCACert`, and `PKIOperation` over verified HTTPS. Enrollment messages used PKCSReq (`messageType=19`), three independently generated RSA key pairs, distinct CSR CN/SANs and the same random challenge. Renewal used RenewalReq (`messageType=17`), a new CSR/key with the same device CN/SAN and challenge, signed with the existing device certificate/key. The only delegated authenticator was SCEP `static-challenge`; no cert-auth mount was used.

| Operation | CN | Serial | Client/entity ID |
|---|---|---|---|
| PKCSReq 1 | `device-01.scep-cli.example.test` | `271678C338AADBD5D6A8048BDC2C6BC685463784` | `4859cde2-98c6-6155-3f59-78aab84623f0` |
| PKCSReq 2 | `device-02.scep-cli.example.test` | `29F247975B932A5A64DDEAEBA2BED1E35F306454` | `7833a66e-8f3c-fe30-92c0-f8fec98203ad` |
| PKCSReq 3 | `device-03.scep-cli.example.test` | `6B1571B93CE7E579D90BEF0712B4E1699A072A25` | `11c26ab8-48ac-5e61-7958-df3ac9f8a0a4` |
| RenewalReq | `device-01.scep-cli.example.test` | `2C7466A0D59E9D76AD1FC451B635F2FCFD87C006` | `4859cde2-98c6-6155-3f59-78aab84623f0` |

All four valid messages returned HTTP 200 and SCEP `pkiStatus=0` (SUCCESS). The helper verified the response signature against the pinned CA, transaction ID, nonce, decrypted certificate, CSR public key and CN. OpenSSL independently verified all four CMS response signatures and certificate chains. A wrong-challenge control returned HTTP 200 but SCEP `pkiStatus=2` (FAILURE), demonstrating why HTTP status alone cannot validate SCEP enrollment.

Identity API reads confirmed three aliases, each named after its device CN, under the single accessor `auth_scep_02556b63`. Counters were captured between phases:

| Checkpoint | Entity clients | Non-entity clients |
|---|---:|---:|
| Before | 5 | 0 |
| After three enrollments | 8 | 0 |
| After renewal | 8 | 0 |
| After wrong-challenge control | 8 | 0 |

The certificate counter moved from 22 to 27: one short-lived isolated test CA plus four issued leaf certificates. The test succeeded, but the hypothesis that a shared SCEP credential implies one counted client was disproved for this configuration. The renewal did not add a client.

Evidence: `evidence/scep-shared-credential-20261028T133434Z/`, especially `summary.json`, `entity-aliases.json`, `operations.json`, `certificate-results.json`, and `audit-redacted.jsonl`. The detailed activity export was initially pending propagation; audit, identity API and aggregate counters were available. The isolated PKI/auth mounts, policy, audit device, challenge and local private keys were removed. Historical usage and public/encrypted evidence remain. Existing Intune resources were not changed.

### SCEP cert auth: renewal without challenge

Run `20261028T140639Z` extends the same script and `SCEP_CLI_Validation.ipynb`. The default now enables both native authenticators. Set `SCEP_TEST_CERT_AUTH=false` to run only the original shared-challenge baseline.

The run created one isolated 24-hour CA, a PKI role restricted to the test domain, a SCEP static-challenge mount, a cert-auth mount trusting only that CA with restricted CN/DNS SANs, and one narrowly scoped ACL policy. Both auth methods used batch tokens with identical policies in the root namespace. The PKI mount's delegated-accessor list and SCEP `authenticators` configuration included both mounts. Existing Vault listeners, Intune resources and device identities outside this run were not changed.

In the cert-auth requests, the CSR contained **no challengePassword attribute**. The old certificate and its matching private key signed the SCEP CMS message; curl used verified server TLS but sent no Vault token, Basic credential or TLS client certificate. All renewals were actual SCEP `RenewalReq` messages (`messageType=17`) with fresh keys/CSRs and unchanged device CN/SAN. Request metadata records the challenge's presence without exposing its value.

| Phase | Entity clients | New clients in phase | Successful leaf issuances in phase |
|---|---:|---:|---:|
| Before | 11 | — | — |
| Three PKCSReq with shared challenge | 14 | 3 | 3 |
| device-01 RenewalReq with challenge | 14 | 0 | 1 |
| Wrong-challenge control | 14 | 0 | 0 |
| Three RenewalReq without challenge, using cert auth | 17 | 3 | 3 |
| device-01 second cert-auth renewal, signed with its renewed cert/key | 17 | 0 | 1 |
| Untrusted signer and trusted signer with wrong challenge | 17 | 0 | 0 |

All eight valid requests returned HTTP 200 and signed SCEP `pkiStatus=0`. All three negative controls returned HTTP 200 but signed `pkiStatus=2`; none issued a certificate. The wrong-challenge request with a trusted signer was rejected by the SCEP challenge authenticator, rather than falling back to cert auth. The untrusted self-signed certificate was rejected by the cert authenticator.

The per-request audit correlation confirms four successful logins under `auth/scep-cli-20261028T140639Z/login` and four under `auth/scep-cert-cli-20261028T140639Z/login`. The challenge aliases use accessor `auth_scep_49ed9c61`; the cert aliases use `auth_cert_b5d1ee13`.

| Device | Entity with challenge | Entity with cert auth |
|---|---|---|
| device-01 | `794b7492-40d6-ec70-789b-148e356a8d84` | `d758e7d7-9f9c-d855-242b-4db6f5c0bf38` |
| device-02 | `075f8786-4539-e68f-1bcf-54182be3a487` | `f5bdfc13-320e-af95-bbe3-3de51a380ae8` |
| device-03 | `b7f98c02-4d21-aa39-245e-782b6359f8cc` | `2ca6890d-a080-86c2-4206-0cc9cdb9a725` |

All eight leaf serials and fingerprints were distinct. The aggregate certificate counter moved **32 to 41**, matching eight successful leaf issuances plus the isolated CA. The extra clients came from the authentication-method transition, not from serial/key rotation alone. Aggregate counters can include concurrent workloads, so the conclusion also relies on this run's isolated paths, request IDs, aliases and six distinct entity/client IDs.

Evidence: `evidence/scep-auth-methods-20261028T140639Z/`, especially `cert-auth-comparison.json`, `authentication-routing.json`, `request-results.jsonl`, `entity-aliases.json`, `operations.json` and the phase counters. OpenSSL independently verified all eight response CMS signatures and issued certificate chains. Post-cleanup reads confirmed that the run's PKI/auth mounts, policy and audit device no longer existed (`cleanup-*.json`); temporary local keys and challenge were removed. The HMAC-protected server audit files and historical client/certificate counts remain. The detailed activity export was still pending when sampled; this does not negate the audit, Identity API and aggregate-counter evidence.

Cert alias linking, external Intune validation, long-term scheduled renewal and other Vault versions remain untested. A device's aliases could be associated with one entity as a separate identity-management design; this run deliberately did not perform that change.

### SCEP cert-only from the first request

Run **`20261028T165249Z`** executed `bash scripts/test_scep_shared_credential.sh --cert-only`. Three devices had distinct CN/DNS SANs (`device-01` through `device-03.scep-cli.example.test`) and individual pre-provisioned certificates/keys. The administrative PKI API issued these bootstrap certificates under the same isolated CA used by SCEP. This simulates devices with existing trusted credentials; migration from an external CA was **not** tested. Provisioning the three bootstrap leaves did not change the client counter in this administrative context.

Only a `cert` auth mount was created: `scep-cert-cli-20261028T165249Z`, accessor `auth_cert_093c3e4d`, with the same CA-trust role, policy and root namespace throughout. The SCEP configuration contained only `authenticators.cert`. No challenge secret, `challengePassword` CSR attribute or SCEP challenge auth mount was used.

The certificate/key authenticated by signing the SCEP CMS message. Curl verified server TLS and sent no Vault token, HTTP Basic credential or TLS client certificate. Because the devices already held certificates from the issuing CA, even their first SCEP requests correctly used **`RenewalReq` (`messageType=17`)**, not a challenge-free self-signed `PKCSReq`. See [RFC 8894, client authentication](https://www.rfc-editor.org/rfc/rfc8894.html#section-2.3) and [Vault SCEP authentication](https://developer.hashicorp.com/vault/docs/secrets/pki/scep).

| Phase | Certificate/key signing the request | Successful SCEP issuances | Entity-client counter | New clients |
|---|---|---:|---:|---:|
| Baseline | — | — | 29 | — |
| Provision three bootstrap leaves through the administrative API | — | — | 29 | 0 |
| First SCEP request from each device | Its individual pre-provisioned certificate/key | 3 | 32 | 3 |
| First subsequent renewal round | Its certificate/key from the first SCEP request | 3 | 32 | 0 |
| Second subsequent renewal round | Its certificate/key from the preceding renewal | 3 | 32 | 0 |
| Untrusted signer, no challenge | Self-signed certificate/key | 0 | 32 | 0 |

**All nine valid requests returned HTTP 200 and signed SCEP `pkiStatus=0` (SUCCESS).** The untrusted signer returned HTTP 200 but `pkiStatus=2` (FAILURE), issued no certificate and added no client. Every valid issuance used a fresh CSR key while retaining the device Subject/SAN. Nine distinct serials, fingerprints and CSR public keys were observed.

| Device | Same entity/client ID across all three SCEP stages |
|---|---|
| device-01 | `86e4d367-9b78-e7fd-f960-2a2acc1ce0bb` |
| device-02 | `3e2036af-1855-7f25-bb7f-bb14601710fc` |
| device-03 | `6a921b2f-02ab-6471-f687-d28b5ec50ab2` |

Audit records prove delegated cert authentication for every valid request; Identity API reads show one device-CN alias per entity under the same accessor. The offline verifier checks protocol message type, absence of challenge, signature/nonce success, fresh keys, exact previous-certificate serial/fingerprint/public-key continuity and stable entity IDs. Independent OpenSSL verification passed for all nine request and response CMS signatures, signer chains, pinned response signer, issued leaf chains, CSR signatures, matching leaf/CSR public keys and unchanged Subject/SAN. Five intentionally corrupted evidence variants were rejected by the verifier.

The aggregate certificate counter moved **83 → 96 (+13)** after asynchronous persistence: one test CA, three administrative bootstrap leaves and nine SCEP-issued leaves. This is separate from the **three entity clients**. Aggregate counters alone can include concurrent workloads; the isolated audit paths, per-request inventory and entity aliases independently support the attribution. The detailed activity export was still `PENDING_PROPAGATION` when sampled; no export confirmation is claimed.

Evidence: [summary](evidence/scep-cert-only-20261028T165249Z/summary.json), [lifecycle operations](evidence/scep-cert-only-20261028T165249Z/lifecycle-operations.json), [offline assertions](evidence/scep-cert-only-20261028T165249Z/assertions.json), [phase deltas](evidence/scep-cert-only-20261028T165249Z/phase-deltas.json), [entity aliases](evidence/scep-cert-only-20261028T165249Z/entity-aliases.json) and [independent verification](evidence/scep-cert-only-20261028T165249Z/independent-verification.txt). Post-cleanup reads (`cleanup-*.json`) confirmed that the exact PKI mount, cert auth mount, policy and audit device were absent. Temporary local private keys were removed; public/encrypted evidence, historical usage, residual Identity records and the HMAC-protected server audit file remain.

This establishes that **cert authentication from the first SCEP request can retain one client per device across renewals** in the tested configuration. The six-client result in the preceding scenario was caused by switching between two unlinked authentication methods, not by an intrinsic SCEP renewal surcharge. No external CA migration, Intune challenge validation, alias linking, physical device client or long-term renewal scheduling is claimed.

### Validated EST and SCEP summary

Each row describes three simulated devices with distinct CN/DNS SANs. Counts are distinct entity clients attributable to that scenario in the same observed counting period, not certificates issued and not a lifetime exemption. Rows are separate scenarios and should not be added together. No aliases were manually linked across auth mounts.

| Scenario | Test performed | Aliases observed | Clients on initial requests | Additional clients on renewal | Final entities / clients |
|---|---|---|---:|---|---|
| EST — shared userpass | Three devices enrolled with one Basic username/password. All three re-enrolled using the same Basic credential plus their own issued certificate/key in TLS. | 1 username alias: `shared`; the three device CNs do not select userpass aliases | +1 | +0 | 1 entity / 1 client |
| EST — individual userpass | Three devices enrolled and re-enrolled with individual Basic credentials, presenting their current device certificate/key for re-enrollment. | 3 username aliases: `device-01`, `device-02`, `device-03` | +3 | +0 | 3 entities / 3 clients |
| EST — shared bootstrap cert, then device certs | Three enrollments used one shared TLS certificate/key. Each device then re-enrolled with its own issued certificate/key, and repeated using its renewed certificate/key. | 1 bootstrap-CN alias, then 3 additional device-CN aliases under the same cert accessor | +1 | +3 on the first transition; +0 on the second round | 4 entities / 4 clients: one bootstrap plus three devices |
| SCEP — shared static challenge | Three devices enrolled with the same challenge. One device renewed using that challenge and signing with its issued certificate/key. | 3 device-CN aliases from the CSRs under one SCEP accessor; the challenge is not the alias | +3 | +0 for the tested renewal | 3 entities / 3 clients |
| SCEP — challenge, then cert | Three challenge-based enrollments; a challenge renewal added zero. All three devices then renewed without a challenge through a separate cert auth mount. One device renewed again with its renewed certificate/key. | 6 aliases: each of the 3 device CNs appears under both the SCEP and cert accessors, with different canonical entity IDs | +3 | +3 when switching authenticator; +0 on the subsequent one-device renewal | 6 entities / 6 clients: three SCEP plus three cert-auth identities |
| SCEP — cert from the first request, no challenge | Three devices started with individual pre-provisioned trusted certificates. Each made its first SCEP request and completed two renewal rounds, always signing with its preceding certificate/key through the same cert auth mount. | 3 signing-certificate CN aliases under one cert accessor, unchanged across both renewal rounds | +3 | +0 in both three-device renewal rounds | 3 entities / 3 clients |

Evidence sources: EST matrix `20261028T143051Z`; focused EST cert lifecycle `20261028T145228Z`; SCEP challenge baseline `20261028T133434Z`; SCEP auth transition `20261028T140639Z`; SCEP cert-only lifecycle `20261028T165249Z`. The last row's first SCEP request is already a protocol-level `RenewalReq`; its initial credentials were provisioned outside SCEP.

### Entities, aliases and their relationship to client count

An **entity** is Vault's canonical identity. An **alias** identifies an authentication account within a particular auth mount. For the mount-bound aliases tested here, the lookup key is **alias name + auth mount accessor**, within the relevant namespace; a CN alone is not a global Vault identity. The same alias name on two auth mounts therefore represents two different aliases. [Vault Identity](https://developer.hashicorp.com/vault/docs/concepts/identity#mount-bound-aliases)

The alias field `canonical_id` points to its parent entity's ID. It is **not** the alias object's own `id`. The saved snapshots include alias names, accessors and canonical IDs, but omit alias-object UUIDs; no alias UUIDs are inferred below. [Entity Alias API](https://developer.hashicorp.com/vault/api-docs/secret/identity/entity-alias)

For all six tested cohorts, the audit `client_id` matched `entity_id`, which matched the alias's `canonical_id`. Every observed entity had one captured alias. Consequently, alias and entity totals happen to match in these tests; this is **not a general rule that every alias is a separate billable client**. Multiple aliases across different auth mounts can represent one entity. [Clients and entities](https://developer.hashicorp.com/vault/docs/concepts/billing/clients#identity-and-entity-assignment)

#### What the credentials selected in these tests

| Authentication used | Observed alias name | What did not create another alias/entity by itself |
|---|---|---|
| EST Basic / userpass | Basic username, e.g. `shared` | A different CSR CN, or the device certificate required in TLS for re-enrollment |
| EST cert | CN of the TLS certificate used for authentication | Rotating its serial/key while retaining that alias and accessor |
| SCEP static challenge | Device CN from the CSR | Reusing the shared challenge, or renewing with unchanged CN through that authenticator |
| SCEP cert | CN of the certificate signing the SCEP message | Rotating its serial/key while retaining that alias and accessor |

The issuance role, shared policy set and shared credential were not substitutes for checking the actual alias/entity mapping. The following inventory is extracted from saved Identity API responses and correlated with the recorded request entity/client IDs. It documents the test-time state in the **root namespace**, not a fresh inventory after cleanup. Independent runs used different auth accessors and generated different entity IDs.

#### Exact alias-to-entity evidence

**EST shared and individual userpass — `est-auth-matrix-20261028T143051Z`.** [Identity snapshot](evidence/est-auth-matrix-20261028T143051Z/entity-aliases.json) · [Request correlation](evidence/est-auth-matrix-20261028T143051Z/operations.json)

Only the four userpass entities are listed here: one for the shared-user scenario and three for the individual-user scenario. The focused certificate lifecycle below supplies the cert scenario's separate evidence.

| Alias name | Auth mount accessor | Entity ID = alias `canonical_id` |
|---|---|---|
| `device-01` | `auth_userpass_dbea77fb` | `3fc3b9d4-7e8a-58a2-41cd-f13eda987f37` |
| `device-02` | `auth_userpass_dbea77fb` | `0285dd8d-dc4b-dbee-55b8-660574000598` |
| `device-03` | `auth_userpass_dbea77fb` | `5b0264a9-e183-7d60-a372-b5b677f7f7cd` |
| `shared` | `auth_userpass_dbea77fb` | `9830b3f2-73f7-7b88-b721-df0db5e48497` |

**EST shared bootstrap cert to device certs — `est-auth-matrix-20261028T145228Z`.** [Identity snapshot](evidence/est-auth-matrix-20261028T145228Z/entity-aliases.json) · [Request correlation](evidence/est-auth-matrix-20261028T145228Z/operations.json)

| Alias name | Auth mount accessor | Entity ID = alias `canonical_id` |
|---|---|---|
| `device-01.est-matrix.example.test` | `auth_cert_88b40eca` | `a4896b1a-de0c-efbd-4d94-7320728fd506` |
| `device-02.est-matrix.example.test` | `auth_cert_88b40eca` | `ad68e1f8-bfd7-626e-62a6-09bcd5afa3a5` |
| `device-03.est-matrix.example.test` | `auth_cert_88b40eca` | `5de37b0d-5c3c-e925-8f91-7f11413863cc` |
| `shared-auth.est-matrix.example.test` | `auth_cert_88b40eca` | `2907df3a-8d4f-eef2-5aec-5b3fef1d724c` |

**SCEP shared static challenge — `scep-shared-credential-20261028T133434Z`.** [Identity snapshot](evidence/scep-shared-credential-20261028T133434Z/entity-aliases.json) · [Request correlation](evidence/scep-shared-credential-20261028T133434Z/operations.json)

| Alias name | Auth mount accessor | Entity ID = alias `canonical_id` |
|---|---|---|
| `device-01.scep-cli.example.test` | `auth_scep_02556b63` | `4859cde2-98c6-6155-3f59-78aab84623f0` |
| `device-02.scep-cli.example.test` | `auth_scep_02556b63` | `7833a66e-8f3c-fe30-92c0-f8fec98203ad` |
| `device-03.scep-cli.example.test` | `auth_scep_02556b63` | `11c26ab8-48ac-5e61-7958-df3ac9f8a0a4` |

**SCEP challenge to cert authentication — `scep-auth-methods-20261028T140639Z`.** [Identity snapshot](evidence/scep-auth-methods-20261028T140639Z/entity-aliases.json) · [Request correlation](evidence/scep-auth-methods-20261028T140639Z/operations.json)

| Alias name | Auth mount accessor | Entity ID = alias `canonical_id` |
|---|---|---|
| `device-01.scep-cli.example.test` | `auth_cert_b5d1ee13` | `d758e7d7-9f9c-d855-242b-4db6f5c0bf38` |
| `device-02.scep-cli.example.test` | `auth_cert_b5d1ee13` | `f5bdfc13-320e-af95-bbe3-3de51a380ae8` |
| `device-03.scep-cli.example.test` | `auth_cert_b5d1ee13` | `2ca6890d-a080-86c2-4206-0cc9cdb9a725` |
| `device-01.scep-cli.example.test` | `auth_scep_49ed9c61` | `794b7492-40d6-ec70-789b-148e356a8d84` |
| `device-02.scep-cli.example.test` | `auth_scep_49ed9c61` | `075f8786-4539-e68f-1bcf-54182be3a487` |
| `device-03.scep-cli.example.test` | `auth_scep_49ed9c61` | `b7f98c02-4d21-aa39-245e-782b6359f8cc` |

**SCEP cert from the first request — `scep-cert-only-20261028T165249Z`.** [Identity snapshot](evidence/scep-cert-only-20261028T165249Z/entity-aliases.json) · [Request correlation](evidence/scep-cert-only-20261028T165249Z/operations.json)

| Alias name | Auth mount accessor | Entity ID = alias `canonical_id` |
|---|---|---|
| `device-01.scep-cli.example.test` | `auth_cert_093c3e4d` | `86e4d367-9b78-e7fd-f960-2a2acc1ce0bb` |
| `device-02.scep-cli.example.test` | `auth_cert_093c3e4d` | `3e2036af-1855-7f25-bb7f-bb14601710fc` |
| `device-03.scep-cli.example.test` | `auth_cert_093c3e4d` | `6a921b2f-02ab-6471-f687-d28b5ec50ab2` |

In the challenge-to-cert run, `device-01.scep-cli.example.test` maps to entity `794b7492-40d6-ec70-789b-148e356a8d84` through `auth_scep_49ed9c61`, but to entity `d758e7d7-9f9c-d855-242b-4db6f5c0bf38` through `auth_cert_b5d1ee13`. The CN string is unchanged; both the accessor and canonical entity differ. This is the directly observed reason that this device contributed two historical clients in that scenario.

In the cert-only run, device-01 keeps the single pair `device-01.scep-cli.example.test` + `auth_cert_093c3e4d` and entity `86e4d367-9b78-e7fd-f960-2a2acc1ce0bb` across its first SCEP request and both renewal rounds. The other two devices behave identically with their own aliases/entities. New certificate serials and keys did not change those mappings.

#### Alias linking: supported model, not an executed scenario

Vault permits aliases from different auth mounts to point to one entity, but an entity cannot have two aliases from the same auth mount. [Entities and aliases](https://developer.hashicorp.com/vault/docs/concepts/identity#entities-and-aliases)

Accordingly, associating each device's SCEP alias and cert alias with the same canonical entity is a separate design that could avoid the cross-method identity split. **No alias linking, entity merging or counter validation of that design was performed here**, and no retroactive reduction of historical usage is claimed. It does not imply that the three different device-CN aliases under one cert mount can all be assigned to one entity.

The measured conclusion remains: renewals retaining the same alias/accessor and canonical entity added no clients; transitions to a new canonical entity did. These observations concern the active entities in the measured counting period, not the total number of stored Identity records or a lifetime exemption.

## 3. SCEP/Intune notebook delivered and observed state

`SCEP_Intune_Validation.ipynb` was executed against Vault Enterprise 2.2.0 with `SCEP_APPLY_CHANGES=true` and `INTUNE_CREDENTIAL_MODE=server-env`.

### Resources created

- PKI mounts `pki_scep_intune_root/`, `pki_scep_intune/`.
- RSA root and intermediate issuers.
- PKI roles `scep-intune-devices`, `scep-intune-devices-alt`.
- Policies `scep-intune-access`, `scep-intune-access-alt`.
- SCEP auth mounts `scep-intune/`, `scep-intune-alt/`.
- SCEP roles `intune`, `intune-alt`, all with `auth_type=intune` and `token_type=batch`.
- Cert auth mount `scep-intune-cert/` for renewal tests.
- Dedicated audit device `scep-intune-validation/` writing to `/tmp/scep-intune-validation-audit.json`.

The resources remain present so the missing Intune device tests can be completed. Cleanup is guarded and enumerated in the final notebook cell.

### SCEP configuration observed

- `enabled=true`.
- `default_path_policy=role:scep-intune-devices`.
- `restrict_ca_chain_to_issuer=true`.
- Primary SCEP accessor `auth_scep_d98c2db6`, role `intune`.
- Cert accessor `auth_cert_98381812`, role `scep-intune-devices`.
- `external_validation.intune` uses `env://AZURE_TENANT_ID`, `env://AZURE_CLIENT_ID`, `env://AZURE_CLIENT_SECRET`, and `env://AZURE_ENVIRONMENT`. The read API intentionally omits the secret field.

GetCACerts returned HTTP 200, content type `application/x-x509-ca-cert`, and the single `SCEP Intune Validation Intermediate` certificate issued by `SCEP Intune Validation Root`.

### Not validated

- Microsoft Entra app credential usable by the Vault server.
- Intune challenge validation and service connectivity.
- Trusted certificate profile and SCEP profile deployment.
- Emissions from device A and device B.
- Second request and renewal from device A.
- Alternative role/policy and alternative auth-mount cases.
- Certificate-auth renewal.
- SCEP request IDs, device identities/aliases, and SCEP `client_id` values.
- Per-test deltas for Vault Clients and PKI certificates.

No `static-challenge` substitute was used in that Intune-specific notebook. Its device cases remain `NOT VALIDATED`. The subsequent, separately documented SCEP CLI test uses `static-challenge` as explicitly permitted by the revised scope and successfully validates enrollment and renewal without Intune.

## 4. Answers to the licensing questions

1. **Do two Intune devices using one SCEP role receive the same client ID?** Intune-specific identity behavior remains untested. In the measured SCEP static-challenge configuration, three distinct CNs received three distinct entity/client IDs even with the same challenge and role. Shared integration credentials alone do not establish one counted client.
2. **Do renewals increment Vault Clients?** EST Basic renewals (shared or individual users), repeated EST device-cert renewals and SCEP renewals retaining their authenticator/alias added zero clients. The EST transition from a shared bootstrap certificate to three individual device certificates added three entities, even within the same cert mount. The SCEP transition from challenge to a separate cert authenticator also added three. The stable or changed entity ID, not the renewal operation itself, explains these results.
3. **Does every issuance/renewal increment PKI Only?** Yes, documented for Vault 1.21+ and corroborated by the isolated EST run. There is no CN/SAN deduplication.
4. **Does changing role, policies, namespace, or auth mount create another client?** Changing the policy set or namespace changes the documented inputs to constructed non-entity identity. Changing only the PKI role is not itself a documented identity key. For normal entity aliases, auth mount accessor plus alias matters. SCEP-specific outcomes remain to be measured with T5/T6.
5. **Does certificate renewal change counted identity?** Rotating serial/key while retaining the same authentication alias/accessor preserved identity in the tested EST and SCEP flows. Changing the authentication certificate's CN (shared bootstrap to individual device) or switching to a separate cert-auth mount changed identity. No cross-method alias linking was configured. For EST, a shared authentication certificate cannot directly re-enroll a different device Subject/SAN; shared Basic plus the current device TLS certificate did work as one shared userpass identity.
6. **Is it correct to size an Intune integration as one Vault Client?** No as a blanket rule. It may be the observed outcome for one exact non-entity configuration, but device-specific aliases, different policy sets, namespaces, auth paths, or certificate-auth renewals can change identity.
7. **What must remain exact for constructed-client deduplication?** Namespace, complete policy assignments, and assigned entity alias if one exists. Keep the same SCEP role/config as an operational control, then verify that Vault actually emits the same `client_id`; do not infer it merely from a shared PKI role or integration name.

These conclusions do not use ACME-specific certificate-identifier deduplication rules.

## 5. Pending external requirements

These requirements apply only to the optional Intune-specific test. They are not prerequisites for the completed generic SCEP CLI validation.

1. Entra app registration with application permissions `Intune > scep_challenge_provider` and `Microsoft Graph > Application.Read.All`, both with admin consent.
2. Tenant ID, client ID, and client credential available to every Vault server process, or a verified MSI configuration.
   The documented Vault SCEP API exposes client secret or `MSI`; it does not expose an application-certificate field. Certificate-based app credentials are therefore not implemented or claimed as supported here.
3. Public HTTPS endpoint for the role-qualified SCEP URL.
4. Intune trusted certificate profile and SCEP profiles compatible with the Vault role CN/SAN constraints.
5. Two enrolled, reachable devices and an operator able to force initial requests and renewal.
6. A test window long enough for the certificate counter (~2 minutes) and current-month activity export (up to ~20 minutes).

## 6. Commands to repeat

Load the Vault lab environment without printing secrets:

```bash
set -a
source /tmp/vault/config.env
set +a
unset VAULT_NAMESPACE
```

Repeat the isolated EST verification:

```bash
./scripts/validate_est_isolated.sh
```

Repeat the focused EST three-enrollments plus one-re-enrollment test with one shared credential (each run creates one new historical entity because it uses a new auth mount accessor):

```bash
./scripts/test_est_shared_credential.sh
```

Repeat the full EST authentication matrix (41 requests; the measured run added eight historical entity clients and 31 certificates, then removed its temporary resources):

```bash
bash scripts/test_est_auth_matrix.sh
```

Verify the saved matrix entirely offline, without any new requests:

```bash
jq -e -f scripts/verify_est_auth_matrix.jq evidence/est-auth-matrix-20261028T143051Z/operations.json
```

Repeat only the correct certificate lifecycle: three bootstrap enrollments, three renewals with the issued leaves, then three renewals with the first-renewal leaves. This creates fresh isolated resources and adds historical usage (four identities and 11 certificates in the measured run):

```bash
bash scripts/test_est_auth_matrix.sh --cert-lifecycle
```

Verify that lifecycle's saved evidence offline:

```bash
jq -e -f scripts/verify_est_cert_lifecycle.jq evidence/est-auth-matrix-20261028T145228Z/operations.json
```

Rebuild the analysis from saved requests/audit and refresh read-only Identity/counter/export queries, without issuing certificates:

```bash
bash scripts/test_est_auth_matrix.sh --analyze evidence/est-auth-matrix-20261028T143051Z
```

The last command samples current aggregate counters again; later unrelated activity can increase the delta. Use the preserved per-request inventory for run-specific issuance attribution.

Repeat SCEP without Intune, including cert auth (creates isolated resources, issues three initial certificates and five renewals, then cleans up; repeated runs add historical usage):

```bash
bash scripts/test_scep_shared_credential.sh
```

Repeat only the original static-challenge baseline (three enrollments and one renewal):

```bash
SCEP_TEST_CERT_AUTH=false bash scripts/test_scep_shared_credential.sh
```

Repeat SCEP with cert authentication from the first request and no challenge. This provisions three individual bootstrap certificates via the administrative API, makes nine SCEP requests and one negative control, then cleans up. A fresh run adds historical usage (three clients and 13 certificates in the measured run):

```bash
bash scripts/test_scep_shared_credential.sh --cert-only
```

Verify the saved cert-only lifecycle offline without issuing certificates:

```bash
jq -e -f scripts/verify_scep_cert_only.jq evidence/scep-cert-only-20261028T165249Z/lifecycle-operations.json
```

Execute the SCEP notebook after the Vault server has its `AZURE_*` variables and Intune is ready:

```bash
export SCEP_APPLY_CHANGES=true
export SCEP_ENABLE_AUDIT=true
export INTUNE_CREDENTIAL_MODE=server-env
export INTUNE_SERVER_ENV_READY=true
jupyter nbconvert --to notebook --execute --inplace \
  --ExecutePreprocessor.timeout=300 SCEP_Intune_Validation.ipynb
```

Capture current counters:

```bash
vault operator usage -format=json
vault read -format=json sys/internal/counters/activity
vault read -format=json sys/billing/certificates
```

Export distinct clients; the output is JSON Lines and may lag during the current month:

```bash
curl --silent --show-error \
  --cacert "$VAULT_CACERT" \
  --header "X-Vault-Token: $VAULT_TOKEN" \
  "$VAULT_ADDR/v1/sys/internal/counters/activity/export?format=json" \
  > evidence/scep-intune-validation/activity-export.jsonl
```

Clean only the SCEP validation resources by setting the confirmation and running the final notebook cell:

```bash
export SCEP_CONFIRM_CLEANUP=DELETE_SCEP_INTUNE_VALIDATION
```

The cleanup does not erase evidence and cannot reverse historical usage counters.

## Official references

- [Vault SCEP](https://developer.hashicorp.com/vault/docs/secrets/pki/scep)
- [Vault SCEP API](https://developer.hashicorp.com/vault/api-docs/secret/pki/issuance#scep-certificate-issuance)
- [Vault SCEP auth API](https://developer.hashicorp.com/vault/api-docs/auth/scep)
- [Vault clients and entities](https://developer.hashicorp.com/vault/docs/concepts/billing/clients)
- [Vault client count FAQ](https://developer.hashicorp.com/vault/docs/concepts/billing/clients/faq)
- [Vault certificate counting](https://developer.hashicorp.com/vault/docs/concepts/billing/certificate-counts)
- [Vault certificate-count API](https://developer.hashicorp.com/vault/api-docs/system/billing/certificates)
- [Microsoft Intune third-party CA with SCEP](https://learn.microsoft.com/en-us/intune/fundamentals/certificates/third-party-ca-scep)
