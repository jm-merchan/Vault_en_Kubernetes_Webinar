#!/usr/bin/env bash
set -euo pipefail

# Isolated, live EST validation for 2_PKI_API_EST.ipynb. This script deliberately
# uses different resource names and never edits or executes the source notebook.

VAULT_BIN="${VAULT_BIN:-/opt/homebrew/bin/vault}"
JQ_BIN="${JQ_BIN:-/usr/bin/jq}"
KUBE_CONTEXT="${KUBE_CONTEXT:-workshop-k8s}"
KUBE_NAMESPACE="${KUBE_NAMESPACE:-vault}"
WORKDIR="${EST_REVIEW_WORKDIR:-/tmp/vault/est-review-validation}"
EVIDENCE_DIR="${EST_REVIEW_EVIDENCE_DIR:-$(pwd)/evidence/est-review-validation}"
ROOT_MOUNT="pki_est_review_root"
PKI_MOUNT="pki_est_review"
USERPASS_MOUNT="est-review-userpass"
CERT_MOUNT="est-review-cert"
ROLE="est-review-clients"
POLICY="est-review-enroll"
AUDIT_PATH="est-review-validation"
AUDIT_FILE="/tmp/est-review-audit.json"
if [[ -x /opt/homebrew/opt/openssl@3/bin/openssl ]]; then
  OPENSSL_BIN=/opt/homebrew/opt/openssl@3/bin/openssl
else
  OPENSSL_BIN=openssl
fi

if [[ -f /tmp/vault/config.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source /tmp/vault/config.env
  set +a
fi
unset VAULT_NAMESPACE
: "${VAULT_ADDR:?VAULT_ADDR is required}"
: "${VAULT_TOKEN:?VAULT_TOKEN is required}"
: "${VAULT_CACERT:?VAULT_CACERT is required}"

mkdir -p "$WORKDIR" "$EVIDENCE_DIR"
chmod 700 "$WORKDIR" "$EVIDENCE_DIR"
umask 077

vault() { "$VAULT_BIN" "$@"; }

cleanup() {
  set +e
  vault write "${PKI_MOUNT}/config/est" enabled=false default_mount=false >/dev/null 2>&1
  vault auth disable "$USERPASS_MOUNT" >/dev/null 2>&1
  vault auth disable "$CERT_MOUNT" >/dev/null 2>&1
  vault secrets disable "$PKI_MOUNT" >/dev/null 2>&1
  vault secrets disable "$ROOT_MOUNT" >/dev/null 2>&1
  vault policy delete "$POLICY" >/dev/null 2>&1
  vault audit disable "$AUDIT_PATH" >/dev/null 2>&1
}
trap cleanup EXIT

cleanup
set -e
trap cleanup EXIT

vault status -format=json | "$JQ_BIN" '{version,cluster_name,sealed}' | tee "$EVIDENCE_DIR/vault-status.json"
vault read -format=json sys/internal/counters/activity | tee "$EVIDENCE_DIR/activity-before.json" >/dev/null
vault read -format=json sys/billing/certificates | tee "$EVIDENCE_DIR/certificates-before.json" >/dev/null

vault audit enable -path="$AUDIT_PATH" file file_path="$AUDIT_FILE" log_raw=false >/dev/null

vault secrets enable -path="$ROOT_MOUNT" pki >/dev/null
vault secrets tune -max-lease-ttl=87600h "$ROOT_MOUNT" >/dev/null
vault write -format=json "${ROOT_MOUNT}/root/generate/internal" \
  common_name="EST Review Root CA" issuer_name="est-review-root" \
  key_type=rsa key_bits=2048 ttl=87600h > "$WORKDIR/root.json"

vault secrets enable -path="$PKI_MOUNT" pki >/dev/null
vault secrets tune -max-lease-ttl=43800h "$PKI_MOUNT" >/dev/null
vault write -format=json "${PKI_MOUNT}/intermediate/generate/internal" \
  common_name="EST Review Intermediate CA" issuer_name="est-review-intermediate" \
  key_type=rsa key_bits=2048 \
  | "$JQ_BIN" -r '.data.csr' > "$WORKDIR/intermediate.csr"
vault write -format=json "${ROOT_MOUNT}/root/sign-intermediate" \
  issuer_ref="est-review-root" csr=@"$WORKDIR/intermediate.csr" \
  format=pem_bundle ttl=43800h \
  | "$JQ_BIN" -r '.data.certificate' > "$WORKDIR/intermediate.pem"
vault write "${PKI_MOUNT}/intermediate/set-signed" certificate=@"$WORKDIR/intermediate.pem" >/dev/null
vault read -field=certificate "${PKI_MOUNT}/cert/ca" > "$WORKDIR/intermediate-ca.pem"
printf '\n' >> "$WORKDIR/intermediate-ca.pem"
cp "$WORKDIR/intermediate-ca.pem" "$WORKDIR/ca.pem"
vault read -field=certificate "${ROOT_MOUNT}/cert/ca" >> "$WORKDIR/ca.pem"
printf '\n' >> "$WORKDIR/ca.pem"

ISSUER_REF=$(vault read -field=default "${PKI_MOUNT}/config/issuers")
vault write "${PKI_MOUNT}/roles/${ROLE}" \
  issuer_ref="$ISSUER_REF" allowed_domains="est-review.example.test" \
  allow_subdomains=true allow_bare_domains=false allow_ip_sans=false \
  client_flag=true server_flag=false key_type=rsa key_bits=2048 \
  ttl=1h max_ttl=2h not_before_duration=0s require_cn=true \
  use_csr_common_name=true use_csr_sans=true no_store=false \
  ext_key_usage="Client Auth" >/dev/null

vault policy write "$POLICY" - <<EOF >/dev/null
path "${PKI_MOUNT}/roles/${ROLE}/est/simpleenroll" {
  capabilities = ["create", "update"]
}
path "${PKI_MOUNT}/roles/${ROLE}/est/simplereenroll" {
  capabilities = ["create", "update"]
}
EOF

vault auth enable -path="$USERPASS_MOUNT" userpass >/dev/null
vault auth tune -token-type=batch "$USERPASS_MOUNT" >/dev/null
openssl rand -base64 32 | tr -d '\n' > "$WORKDIR/password"
vault write "auth/${USERPASS_MOUNT}/users/device-a" \
  password=@"$WORKDIR/password" token_policies="$POLICY" \
  token_type=batch token_ttl=5m >/dev/null

vault auth enable -path="$CERT_MOUNT" cert >/dev/null
vault auth tune -token-type=batch "$CERT_MOUNT" >/dev/null
vault write "auth/${CERT_MOUNT}/certs/${ROLE}" \
  display_name="est-review-cert" token_policies="$POLICY" \
  certificate=@"$WORKDIR/intermediate-ca.pem" \
  allowed_common_names="*.est-review.example.test" \
  token_type=batch token_ttl=5m >/dev/null

USERPASS_ACCESSOR=$(vault read -field=accessor "sys/auth/${USERPASS_MOUNT}")
CERT_ACCESSOR=$(vault read -field=accessor "sys/auth/${CERT_MOUNT}")
vault secrets tune \
  -allowed-response-headers=Content-Transfer-Encoding \
  -allowed-response-headers=Content-Length \
  -allowed-response-headers=WWW-Authenticate \
  -delegated-auth-accessors="$USERPASS_ACCESSOR" \
  -delegated-auth-accessors="$CERT_ACCESSOR" \
  -audit-non-hmac-response-keys=serial_number \
  "$PKI_MOUNT" >/dev/null

"$JQ_BIN" -n \
  --arg up "$USERPASS_ACCESSOR" --arg cert "$CERT_ACCESSOR" --arg role "$ROLE" \
  '{enabled:true,default_mount:true,default_path_policy:("role:"+$role),label_to_path_policy:{},authenticators:{userpass:{accessor:$up},cert:{accessor:$cert,cert_role:$role}},enable_sentinel_parsing:true,audit_fields:["common_name","alt_names","ip_sans","uri_sans","key_type","key_bits"]}' \
  | vault write -format=json "${PKI_MOUNT}/config/est" - > "$EVIDENCE_DIR/est-config-write.json"
vault read -format=json "${PKI_MOUNT}/config/est" | tee "$EVIDENCE_DIR/est-config.json" >/dev/null
vault read -format=json "${PKI_MOUNT}/roles/${ROLE}" | tee "$EVIDENCE_DIR/est-role.json" >/dev/null
vault read -format=json "sys/mounts/${PKI_MOUNT}" | tee "$EVIDENCE_DIR/est-mount.json" >/dev/null

EST_BASE="${VAULT_ADDR}/.well-known/est"
wrap_p7() {
  { printf '%s\n' '-----BEGIN PKCS7-----'; tr -d '\r' < "$1"; printf '%s\n' '-----END PKCS7-----'; } \
    | "$OPENSSL_BIN" pkcs7 -inform PEM -print_certs -out "$2"
}
http_code() { awk 'BEGIN{c=""} /^HTTP\//{c=$2} END{print c}' "$1"; }

curl -sS --cacert "$VAULT_CACERT" -D "$WORKDIR/cacerts.hdr" -o "$WORKDIR/cacerts.p7" \
  "${EST_BASE}/cacerts"
[[ "$(http_code "$WORKDIR/cacerts.hdr")" == "200" ]]
wrap_p7 "$WORKDIR/cacerts.p7" "$WORKDIR/cacerts.pem"
"$OPENSSL_BIN" x509 -in "$WORKDIR/cacerts.pem" -noout -subject -issuer -serial \
  | tee "$EVIDENCE_DIR/cacerts.txt"

CN="device-a.est-review.example.test"
cat > "$WORKDIR/enroll.cnf" <<EOF
[req]
distinguished_name = dn
req_extensions = ext
string_mask = nombstr
prompt = no
utf8 = no
[dn]
CN = ${CN}
[ext]
subjectAltName = DNS:${CN}
EOF
"$OPENSSL_BIN" req -new -newkey rsa:2048 -nodes -keyout "$WORKDIR/device.key" \
  -out "$WORKDIR/device.csr" -config "$WORKDIR/enroll.cnf" -reqexts ext >/dev/null 2>&1
"$OPENSSL_BIN" req -in "$WORKDIR/device.csr" -outform DER | "$OPENSSL_BIN" base64 -A > "$WORKDIR/device.p10"

PASS=$(<"$WORKDIR/password")
curl -sS --cacert "$VAULT_CACERT" -D "$WORKDIR/enroll.hdr" -o "$WORKDIR/enroll.p7" \
  --user "device-a:${PASS}" -H 'Content-Type: application/pkcs10' \
  -H 'Content-Transfer-Encoding: base64' --data-binary @"$WORKDIR/device.p10" \
  "${EST_BASE}/simpleenroll"
[[ "$(http_code "$WORKDIR/enroll.hdr")" == "200" ]]
wrap_p7 "$WORKDIR/enroll.p7" "$WORKDIR/enroll.pem"
"$OPENSSL_BIN" x509 -in "$WORKDIR/enroll.pem" -out "$WORKDIR/device.pem"
"$OPENSSL_BIN" x509 -in "$WORKDIR/device.pem" -noout -subject -issuer -serial -dates \
  | tee "$EVIDENCE_DIR/simpleenroll-certificate.txt"
"$OPENSSL_BIN" x509 -in "$WORKDIR/device.pem" -noout -text | grep -A2 'Subject Alternative Name' \
  | tee -a "$EVIDENCE_DIR/simpleenroll-certificate.txt"
"$OPENSSL_BIN" verify -CAfile "$WORKDIR/ca.pem" "$WORKDIR/device.pem" | tee -a "$EVIDENCE_DIR/simpleenroll-certificate.txt"

NOAUTH_CODE=$(curl -sS --cacert "$VAULT_CACERT" -o "$WORKDIR/noauth.body" -w '%{http_code}' \
  -H 'Content-Type: application/pkcs10' -H 'Content-Transfer-Encoding: base64' \
  --data-binary @"$WORKDIR/device.p10" "${EST_BASE}/simpleenroll")
BADPASS_CODE=$(curl -sS --cacert "$VAULT_CACERT" -o "$WORKDIR/badpass.body" -w '%{http_code}' \
  --user 'device-a:not-the-password' -H 'Content-Type: application/pkcs10' \
  -H 'Content-Transfer-Encoding: base64' --data-binary @"$WORKDIR/device.p10" \
  "${EST_BASE}/simpleenroll")
[[ "$NOAUTH_CODE" == "401" ]]
[[ "$BADPASS_CODE" =~ ^4[0-9][0-9]$ ]]
printf 'no_auth_http=%s\nbad_password_http=%s\n' "$NOAUTH_CODE" "$BADPASS_CODE" \
  | tee "$EVIDENCE_DIR/negative-tests.txt"

cat > "$WORKDIR/reenroll.cnf" <<EOF
[req]
distinguished_name = dn
req_extensions = ext
string_mask = nombstr
prompt = no
utf8 = no
[dn]
CN = ${CN}
[ext]
subjectAltName = DNS:${CN}
EOF
"$OPENSSL_BIN" req -new -newkey rsa:2048 -nodes -keyout "$WORKDIR/device-re.key" \
  -out "$WORKDIR/device-re.csr" -config "$WORKDIR/reenroll.cnf" -reqexts ext >/dev/null 2>&1
"$OPENSSL_BIN" req -in "$WORKDIR/device-re.csr" -outform DER | "$OPENSSL_BIN" base64 -A > "$WORKDIR/device-re.p10"

BASIC_ONLY_CODE=$(curl -sS --cacert "$VAULT_CACERT" -o "$WORKDIR/basic-only.body" -w '%{http_code}' \
  --user "device-a:${PASS}" -H 'Content-Type: application/pkcs10' \
  -H 'Content-Transfer-Encoding: base64' --data-binary @"$WORKDIR/device-re.p10" \
  "${EST_BASE}/simplereenroll")
[[ "$BASIC_ONLY_CODE" == "400" ]]
grep -q 'no certificate found in TLS state' "$WORKDIR/basic-only.body"

curl -sS --cacert "$VAULT_CACERT" -D "$WORKDIR/reenroll.hdr" -o "$WORKDIR/reenroll.p7" \
  --user "device-a:${PASS}" --cert "$WORKDIR/device.pem" --key "$WORKDIR/device.key" \
  -H 'Content-Type: application/pkcs10' -H 'Content-Transfer-Encoding: base64' \
  --data-binary @"$WORKDIR/device-re.p10" "${EST_BASE}/simplereenroll"
[[ "$(http_code "$WORKDIR/reenroll.hdr")" == "200" ]]
wrap_p7 "$WORKDIR/reenroll.p7" "$WORKDIR/reenroll.pem"
"$OPENSSL_BIN" x509 -in "$WORKDIR/reenroll.pem" -out "$WORKDIR/device-re.pem"
OLD_SERIAL=$("$OPENSSL_BIN" x509 -in "$WORKDIR/device.pem" -noout -serial)
NEW_SERIAL=$("$OPENSSL_BIN" x509 -in "$WORKDIR/device-re.pem" -noout -serial)
[[ "$OLD_SERIAL" != "$NEW_SERIAL" ]]
"$OPENSSL_BIN" verify -CAfile "$WORKDIR/ca.pem" "$WORKDIR/device-re.pem" >/dev/null
printf 'basic_only_http=%s\nold_%s\nnew_%s\n' "$BASIC_ONLY_CODE" "$OLD_SERIAL" "$NEW_SERIAL" \
  | tee "$EVIDENCE_DIR/simplereenroll.txt"

# Cert-auth simpleenroll proves the second delegated authenticator and batch token path.
CN2="device-b.est-review.example.test"
sed "s/${CN}/${CN2}/g" "$WORKDIR/enroll.cnf" > "$WORKDIR/enroll-cert.cnf"
"$OPENSSL_BIN" req -new -newkey rsa:2048 -nodes -keyout "$WORKDIR/device-b.key" \
  -out "$WORKDIR/device-b.csr" -config "$WORKDIR/enroll-cert.cnf" -reqexts ext >/dev/null 2>&1
"$OPENSSL_BIN" req -in "$WORKDIR/device-b.csr" -outform DER | "$OPENSSL_BIN" base64 -A > "$WORKDIR/device-b.p10"
curl -sS --cacert "$VAULT_CACERT" -D "$WORKDIR/cert-enroll.hdr" -o "$WORKDIR/cert-enroll.p7" \
  --cert "$WORKDIR/device.pem" --key "$WORKDIR/device.key" \
  -H 'Content-Type: application/pkcs10' -H 'Content-Transfer-Encoding: base64' \
  --data-binary @"$WORKDIR/device-b.p10" "${EST_BASE}/simpleenroll"
[[ "$(http_code "$WORKDIR/cert-enroll.hdr")" == "200" ]]
wrap_p7 "$WORKDIR/cert-enroll.p7" "$WORKDIR/cert-enroll.pem"
"$OPENSSL_BIN" x509 -in "$WORKDIR/cert-enroll.pem" -out "$WORKDIR/device-b.pem"
"$OPENSSL_BIN" x509 -in "$WORKDIR/device-b.pem" -noout -subject -issuer -serial -dates \
  | tee "$EVIDENCE_DIR/cert-auth-certificate.txt"
"$OPENSSL_BIN" x509 -in "$WORKDIR/device-b.pem" -noout -text | grep -A2 'Subject Alternative Name' \
  | tee -a "$EVIDENCE_DIR/cert-auth-certificate.txt"

vault list -format=json "${PKI_MOUNT}/certs" | tee "$EVIDENCE_DIR/issued-serials.json" >/dev/null

for pod in $(kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NAMESPACE" get pod -l app.kubernetes.io/name=vault -o name 2>/dev/null); do
  kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NAMESPACE" exec "${pod#pod/}" -- \
    sh -c "test -f '$AUDIT_FILE' && cat '$AUDIT_FILE'" 2>/dev/null || true
done | "$JQ_BIN" -c --arg pki "$PKI_MOUNT" --arg up "$USERPASS_ACCESSOR" --arg cert "$CERT_ACCESSOR" '
  select((.request.path // "" | contains($pki)) or (.auth.accessor // "" == $up) or (.auth.accessor // "" == $cert))
  | {time,type,request_id:(.request.id // null),path:(.request.path // null),operation:(.request.operation // null),namespace:(.request.namespace.path // ""),auth:{client_id:(.auth.client_id // null),entity_id:(.auth.entity_id // null),accessor:(.auth.accessor // null),policies:(.auth.policies // []),token_type:(.auth.token_type // null)},error:(.error // null),serial_number:(.response.data.serial_number // null)}' \
  > "$EVIDENCE_DIR/audit-redacted.jsonl"

vault read -format=json sys/internal/counters/activity | tee "$EVIDENCE_DIR/activity-after.json" >/dev/null

BEFORE_COUNT=$("$JQ_BIN" '[.data.months[]?.counts.issued_certificates // 0] | add // 0' "$EVIDENCE_DIR/certificates-before.json")
for attempt in $(seq 1 18); do
  vault read -format=json sys/billing/certificates > "$EVIDENCE_DIR/certificates-after.json"
  AFTER_COUNT=$("$JQ_BIN" '[.data.months[]?.counts.issued_certificates // 0] | add // 0' "$EVIDENCE_DIR/certificates-after.json")
  echo "certificate-counter poll ${attempt}: before=${BEFORE_COUNT} after=${AFTER_COUNT}"
  (( AFTER_COUNT >= BEFORE_COUNT + 3 )) && break
  sleep 10
done

"$JQ_BIN" -n \
  --arg original_sha256 "$(shasum -a 256 2_PKI_API_EST.ipynb | awk '{print $1}')" \
  --arg namespace "root" --arg pki_mount "$PKI_MOUNT" --arg role "$ROLE" \
  --arg up_accessor "$USERPASS_ACCESSOR" --arg cert_accessor "$CERT_ACCESSOR" \
  --argjson no_auth "$NOAUTH_CODE" --argjson bad_password "$BADPASS_CODE" \
  --argjson basic_only "$BASIC_ONLY_CODE" --arg old_serial "$OLD_SERIAL" \
  --arg new_serial "$NEW_SERIAL" --argjson certificate_count_before "$BEFORE_COUNT" \
  --argjson certificate_count_after "$AFTER_COUNT" \
  '{status:"PASS",original_notebook_sha256:$original_sha256,namespace:$namespace,pki_mount:$pki_mount,role:$role,auth_accessors:{userpass:$up_accessor,cert:$cert_accessor},http:{cacerts:200,simpleenroll:200,no_auth:$no_auth,bad_password:$bad_password,simplereenroll_basic_only:$basic_only,simplereenroll:200,cert_auth_simpleenroll:200},serials:{before:$old_serial,after:$new_serial},certificate_counter:{before:$certificate_count_before,after:$certificate_count_after,delta:($certificate_count_after-$certificate_count_before)}}' \
  | tee "$EVIDENCE_DIR/summary.json"

echo "EST_REVIEW_VALIDATION_PASS evidence=${EVIDENCE_DIR}"
