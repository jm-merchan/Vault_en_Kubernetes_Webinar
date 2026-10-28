#!/usr/bin/env bash
set -euo pipefail

# Proves whether three distinct EST simpleenroll requests made with one shared
# userpass credential resolve to one Vault entity/client. All Vault resources
# are isolated and removed automatically; public certificates and redacted
# evidence are retained.

VAULT_BIN="${VAULT_BIN:-/opt/homebrew/bin/vault}"
JQ_BIN="${JQ_BIN:-/usr/bin/jq}"
KUBE_CONTEXT="${KUBE_CONTEXT:-workshop-k8s}"
KUBE_NAMESPACE="${KUBE_NAMESPACE:-vault}"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
WORKDIR="${EST_SHARED_WORKDIR:-/tmp/vault/est-shared-credential-${RUN_ID}}"
EVIDENCE_DIR="${EST_SHARED_EVIDENCE_DIR:-$(pwd)/evidence/est-shared-credential-${RUN_ID}}"
ROOT_MOUNT="pki_est_shared_root"
PKI_MOUNT="pki_est_shared"
USERPASS_MOUNT="est-shared-userpass"
ROLE="est-shared-devices"
POLICY="est-shared-enroll"
AUDIT_PATH="est-shared-credential"
AUDIT_FILE="/tmp/est-shared-credential-${RUN_ID}.json"
USERNAME="shared-fleet"

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

mkdir -p "$WORKDIR" "$EVIDENCE_DIR" "$EVIDENCE_DIR/certificates"
chmod 700 "$WORKDIR" "$EVIDENCE_DIR" "$EVIDENCE_DIR/certificates"
umask 077

vault() { "$VAULT_BIN" "$@"; }

cleanup_vault() {
  set +e
  vault write "${PKI_MOUNT}/config/est" enabled=false default_mount=false >/dev/null 2>&1
  vault auth disable "$USERPASS_MOUNT" >/dev/null 2>&1
  vault secrets disable "$PKI_MOUNT" >/dev/null 2>&1
  vault secrets disable "$ROOT_MOUNT" >/dev/null 2>&1
  vault policy delete "$POLICY" >/dev/null 2>&1
  vault audit disable "$AUDIT_PATH" >/dev/null 2>&1
}

cleanup_all() {
  cleanup_vault
  if [[ "$WORKDIR" == /tmp/vault/est-shared-credential-* && -d "$WORKDIR" ]]; then
    find "$WORKDIR" -type f -delete
    find "$WORKDIR" -depth -type d -empty -delete
  fi
}
trap cleanup_all EXIT

# Remove only stale resources with the exact isolated names before starting.
cleanup_vault
set -e

vault status -format=json | "$JQ_BIN" '{version,cluster_name,sealed}' \
  | tee "$EVIDENCE_DIR/vault-status.json"
vault read -format=json sys/internal/counters/activity \
  | tee "$EVIDENCE_DIR/activity-before.json" >/dev/null
vault read -format=json sys/billing/certificates \
  | tee "$EVIDENCE_DIR/certificates-before.json" >/dev/null

vault audit enable -path="$AUDIT_PATH" file file_path="$AUDIT_FILE" log_raw=false >/dev/null

vault secrets enable -path="$ROOT_MOUNT" pki >/dev/null
vault secrets tune -max-lease-ttl=87600h "$ROOT_MOUNT" >/dev/null
vault write -format=json "${ROOT_MOUNT}/root/generate/internal" \
  common_name="EST Shared Credential Root CA" issuer_name="est-shared-root" \
  key_type=rsa key_bits=2048 ttl=87600h > "$WORKDIR/root.json"

vault secrets enable -path="$PKI_MOUNT" pki >/dev/null
vault secrets tune -max-lease-ttl=43800h "$PKI_MOUNT" >/dev/null
vault write -format=json "${PKI_MOUNT}/intermediate/generate/internal" \
  common_name="EST Shared Credential Intermediate CA" \
  issuer_name="est-shared-intermediate" key_type=rsa key_bits=2048 \
  | "$JQ_BIN" -r '.data.csr' > "$WORKDIR/intermediate.csr"
vault write -format=json "${ROOT_MOUNT}/root/sign-intermediate" \
  issuer_ref="est-shared-root" csr=@"$WORKDIR/intermediate.csr" \
  format=pem_bundle ttl=43800h \
  | "$JQ_BIN" -r '.data.certificate' > "$WORKDIR/intermediate.pem"
vault write "${PKI_MOUNT}/intermediate/set-signed" \
  certificate=@"$WORKDIR/intermediate.pem" >/dev/null
vault read -field=certificate "${PKI_MOUNT}/cert/ca" > "$WORKDIR/intermediate-ca.pem"
printf '\n' >> "$WORKDIR/intermediate-ca.pem"
cp "$WORKDIR/intermediate-ca.pem" "$WORKDIR/ca-chain.pem"
vault read -field=certificate "${ROOT_MOUNT}/cert/ca" >> "$WORKDIR/ca-chain.pem"
printf '\n' >> "$WORKDIR/ca-chain.pem"
cp "$WORKDIR/ca-chain.pem" "$EVIDENCE_DIR/certificates/ca-chain.pem"

ISSUER_REF=$(vault read -field=default "${PKI_MOUNT}/config/issuers")
vault write "${PKI_MOUNT}/roles/${ROLE}" \
  issuer_ref="$ISSUER_REF" allowed_domains="est-shared.example.test" \
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
"$OPENSSL_BIN" rand -base64 32 | tr -d '\n' > "$WORKDIR/password"
vault write "auth/${USERPASS_MOUNT}/users/${USERNAME}" \
  password=@"$WORKDIR/password" token_policies="$POLICY" \
  token_type=batch token_ttl=5m >/dev/null

USERPASS_ACCESSOR=$(vault read -field=accessor "sys/auth/${USERPASS_MOUNT}")
vault secrets tune \
  -allowed-response-headers=Content-Transfer-Encoding \
  -allowed-response-headers=Content-Length \
  -allowed-response-headers=WWW-Authenticate \
  -delegated-auth-accessors="$USERPASS_ACCESSOR" \
  -audit-non-hmac-response-keys=serial_number \
  "$PKI_MOUNT" >/dev/null

"$JQ_BIN" -n --arg up "$USERPASS_ACCESSOR" --arg role "$ROLE" \
  '{enabled:true,default_mount:true,default_path_policy:("role:"+$role),label_to_path_policy:{},authenticators:{userpass:{accessor:$up}},enable_sentinel_parsing:true,audit_fields:["common_name","alt_names","key_type","key_bits"]}' \
  | vault write -format=json "${PKI_MOUNT}/config/est" - \
  > "$EVIDENCE_DIR/est-config-write.json"
vault read -format=json "${PKI_MOUNT}/config/est" \
  | tee "$EVIDENCE_DIR/est-config.json" >/dev/null

EST_BASE="${VAULT_ADDR}/.well-known/est"
PASS=$(<"$WORKDIR/password")

wrap_p7() {
  { printf '%s\n' '-----BEGIN PKCS7-----'; tr -d '\r' < "$1"; printf '%s\n' '-----END PKCS7-----'; } \
    | "$OPENSSL_BIN" pkcs7 -inform PEM -print_certs -out "$2"
}

http_code() {
  awk 'BEGIN{c=""} /^HTTP\//{c=$2} END{print c}' "$1"
}

require_eq() {
  local actual=$1
  local expected=$2
  local description=$3
  if [[ "$actual" != "$expected" ]]; then
    echo "ASSERTION FAILED: ${description}: expected=${expected} actual=${actual}" >&2
    exit 1
  fi
}

printf 'device,common_name,http_status,serial,sha256_fingerprint\n' \
  > "$EVIDENCE_DIR/certificate-results.csv"

for device_number in 01 02 03; do
  device="device-${device_number}"
  cn="${device}.est-shared.example.test"
  cat > "$WORKDIR/${device}.cnf" <<EOF
[req]
distinguished_name = dn
req_extensions = ext
string_mask = nombstr
prompt = no
utf8 = no
[dn]
CN = ${cn}
[ext]
subjectAltName = DNS:${cn}
EOF
  "$OPENSSL_BIN" req -new -newkey rsa:2048 -nodes \
    -keyout "$WORKDIR/${device}.key" -out "$WORKDIR/${device}.csr" \
    -config "$WORKDIR/${device}.cnf" -reqexts ext >/dev/null 2>&1
  "$OPENSSL_BIN" req -in "$WORKDIR/${device}.csr" -outform DER \
    | "$OPENSSL_BIN" base64 -A > "$WORKDIR/${device}.p10"

  curl -sS --cacert "$VAULT_CACERT" \
    -D "$WORKDIR/${device}.hdr" -o "$WORKDIR/${device}.p7" \
    --user "${USERNAME}:${PASS}" \
    -H 'Content-Type: application/pkcs10' \
    -H 'Content-Transfer-Encoding: base64' \
    --data-binary @"$WORKDIR/${device}.p10" "${EST_BASE}/simpleenroll"
  status=$(http_code "$WORKDIR/${device}.hdr")
  [[ "$status" == "200" ]]

  wrap_p7 "$WORKDIR/${device}.p7" "$WORKDIR/${device}-bundle.pem"
  "$OPENSSL_BIN" x509 -in "$WORKDIR/${device}-bundle.pem" \
    -out "$WORKDIR/${device}.pem"
  "$OPENSSL_BIN" verify -CAfile "$WORKDIR/ca-chain.pem" \
    "$WORKDIR/${device}.pem" >/dev/null

  cp "$WORKDIR/${device}.pem" "$EVIDENCE_DIR/certificates/${device}.pem"
  serial=$("$OPENSSL_BIN" x509 -in "$WORKDIR/${device}.pem" -noout -serial | cut -d= -f2)
  fingerprint=$("$OPENSSL_BIN" x509 -in "$WORKDIR/${device}.pem" -noout -fingerprint -sha256 | cut -d= -f2-)
  printf '%s,%s,%s,%s,%s\n' "$device" "$cn" "$status" "$serial" "$fingerprint" \
    | tee -a "$EVIDENCE_DIR/certificate-results.csv"
done

UNIQUE_SERIALS=$(tail -n +2 "$EVIDENCE_DIR/certificate-results.csv" | cut -d, -f4 | sort -u | wc -l | tr -d ' ')
UNIQUE_FINGERPRINTS=$(tail -n +2 "$EVIDENCE_DIR/certificate-results.csv" | cut -d, -f5 | sort -u | wc -l | tr -d ' ')
require_eq "$UNIQUE_SERIALS" 3 "unique certificate serials"
require_eq "$UNIQUE_FINGERPRINTS" 3 "unique certificate fingerprints"

# Re-enroll device-01 with the same shared Basic credential. EST also requires
# the current device certificate and its matching private key at the TLS layer.
"$OPENSSL_BIN" req -new -newkey rsa:2048 -nodes \
  -keyout "$WORKDIR/device-01-reenrolled.key" \
  -out "$WORKDIR/device-01-reenrolled.csr" \
  -config "$WORKDIR/device-01.cnf" -reqexts ext >/dev/null 2>&1
"$OPENSSL_BIN" req -in "$WORKDIR/device-01-reenrolled.csr" -outform DER \
  | "$OPENSSL_BIN" base64 -A > "$WORKDIR/device-01-reenrolled.p10"

curl -sS --cacert "$VAULT_CACERT" \
  -D "$WORKDIR/device-01-reenrolled.hdr" \
  -o "$WORKDIR/device-01-reenrolled.p7" \
  --user "${USERNAME}:${PASS}" \
  --cert "$WORKDIR/device-01.pem" --key "$WORKDIR/device-01.key" \
  -H 'Content-Type: application/pkcs10' \
  -H 'Content-Transfer-Encoding: base64' \
  --data-binary @"$WORKDIR/device-01-reenrolled.p10" \
  "${EST_BASE}/simplereenroll"
REENROLL_STATUS=$(http_code "$WORKDIR/device-01-reenrolled.hdr")
require_eq "$REENROLL_STATUS" 200 "device-01 simplereenroll HTTP status"

wrap_p7 "$WORKDIR/device-01-reenrolled.p7" \
  "$WORKDIR/device-01-reenrolled-bundle.pem"
"$OPENSSL_BIN" x509 -in "$WORKDIR/device-01-reenrolled-bundle.pem" \
  -out "$WORKDIR/device-01-reenrolled.pem"
"$OPENSSL_BIN" verify -CAfile "$WORKDIR/ca-chain.pem" \
  "$WORKDIR/device-01-reenrolled.pem" >/dev/null
cp "$WORKDIR/device-01-reenrolled.pem" \
  "$EVIDENCE_DIR/certificates/device-01-reenrolled.pem"

ORIGINAL_SERIAL=$("$OPENSSL_BIN" x509 -in "$WORKDIR/device-01.pem" \
  -noout -serial | cut -d= -f2)
REENROLLED_SERIAL=$("$OPENSSL_BIN" x509 -in "$WORKDIR/device-01-reenrolled.pem" \
  -noout -serial | cut -d= -f2)
REENROLLED_FINGERPRINT=$("$OPENSSL_BIN" x509 \
  -in "$WORKDIR/device-01-reenrolled.pem" -noout -fingerprint -sha256 \
  | cut -d= -f2-)
if [[ "$ORIGINAL_SERIAL" == "$REENROLLED_SERIAL" ]]; then
  echo "ASSERTION FAILED: simplereenroll retained the original serial" >&2
  exit 1
fi
if cut -d, -f4 "$EVIDENCE_DIR/certificate-results.csv" | grep -Fxq "$REENROLLED_SERIAL"; then
  echo "ASSERTION FAILED: simplereenroll serial is not unique" >&2
  exit 1
fi

"$JQ_BIN" -n \
  --arg device device-01 \
  --arg common_name device-01.est-shared.example.test \
  --argjson http_status "$REENROLL_STATUS" \
  --arg original_serial "$ORIGINAL_SERIAL" \
  --arg reenrolled_serial "$REENROLLED_SERIAL" \
  --arg sha256_fingerprint "$REENROLLED_FINGERPRINT" \
  '{device:$device,common_name:$common_name,http_status:$http_status,original_serial:$original_serial,reenrolled_serial:$reenrolled_serial,serial_changed:($original_serial != $reenrolled_serial),sha256_fingerprint:$sha256_fingerprint}' \
  | tee "$EVIDENCE_DIR/reenrollment-result.json"

# Allow audit writes to settle, then collect only the isolated requests from all pods.
sleep 2
for pod in $(kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NAMESPACE" \
  get pod -l app.kubernetes.io/name=vault -o name 2>/dev/null); do
  kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NAMESPACE" exec "${pod#pod/}" -- \
    sh -c "test -f '$AUDIT_FILE' && cat '$AUDIT_FILE'" 2>/dev/null || true
done | "$JQ_BIN" -c \
  --arg enroll_path "${PKI_MOUNT}/roles/${ROLE}/est/simpleenroll" \
  --arg reenroll_path "${PKI_MOUNT}/roles/${ROLE}/est/simplereenroll" '
  select(((.request.path // "") == $enroll_path or (.request.path // "") == $reenroll_path) and (.auth.entity_id // "") != "")
  | {time,type,request_id:(.request.id // null),path:(.request.path // null),operation:(.request.operation // null),request_client_id:(.request.client_id // null),auth:{entity_id:(.auth.entity_id // null),display_name:(.auth.display_name // null),policies:(.auth.policies // []),token_type:(.auth.token_type // null)},http_status:(.response.data.http_status_code // null),error:(.error // null)}' \
  | sort -u > "$EVIDENCE_DIR/audit-redacted.jsonl"

"$JQ_BIN" -s '
  [ .[] | select(.type == "response" and .http_status == 200 and .error == null) ] as $responses
  | {
      successful_est_responses: ($responses | length),
      successful_simpleenroll_responses: ($responses | map(select((.path // "") | endswith("/simpleenroll"))) | length),
      successful_simplereenroll_responses: ($responses | map(select((.path // "") | endswith("/simplereenroll"))) | length),
      request_ids: ($responses | map(.request_id) | unique),
      client_ids: ($responses | map(.request_client_id) | unique),
      entity_ids: ($responses | map(.auth.entity_id) | unique),
      display_names: ($responses | map(.auth.display_name) | unique),
      token_types: ($responses | map(.auth.token_type) | unique)
    }' "$EVIDENCE_DIR/audit-redacted.jsonl" \
  | tee "$EVIDENCE_DIR/identity-correlation.json"

SUCCESSFUL_EST_RESPONSES=$("$JQ_BIN" -r '.successful_est_responses' "$EVIDENCE_DIR/identity-correlation.json")
SUCCESSFUL_ENROLL_RESPONSES=$("$JQ_BIN" -r '.successful_simpleenroll_responses' "$EVIDENCE_DIR/identity-correlation.json")
SUCCESSFUL_REENROLL_RESPONSES=$("$JQ_BIN" -r '.successful_simplereenroll_responses' "$EVIDENCE_DIR/identity-correlation.json")
UNIQUE_CLIENT_IDS=$("$JQ_BIN" -r '.client_ids | length' "$EVIDENCE_DIR/identity-correlation.json")
UNIQUE_ENTITY_IDS=$("$JQ_BIN" -r '.entity_ids | length' "$EVIDENCE_DIR/identity-correlation.json")
UNIQUE_DISPLAY_NAMES=$("$JQ_BIN" -r '.display_names | length' "$EVIDENCE_DIR/identity-correlation.json")
require_eq "$SUCCESSFUL_EST_RESPONSES" 4 "successful authenticated EST responses"
require_eq "$SUCCESSFUL_ENROLL_RESPONSES" 3 "successful authenticated simpleenroll responses"
require_eq "$SUCCESSFUL_REENROLL_RESPONSES" 1 "successful authenticated simplereenroll responses"
require_eq "$UNIQUE_CLIENT_IDS" 1 "unique client IDs"
require_eq "$UNIQUE_ENTITY_IDS" 1 "unique entity IDs"
require_eq "$UNIQUE_DISPLAY_NAMES" 1 "unique authenticated display names"

vault list -format=json "${PKI_MOUNT}/certs" \
  | tee "$EVIDENCE_DIR/issued-leaf-serials.json" >/dev/null
BEFORE_CLIENT_COUNT=$("$JQ_BIN" -r '.data.total.clients' "$EVIDENCE_DIR/activity-before.json")
BEFORE_ENTITY_COUNT=$("$JQ_BIN" -r '.data.total.entity_clients' "$EVIDENCE_DIR/activity-before.json")
AFTER_CLIENT_COUNT="$BEFORE_CLIENT_COUNT"
AFTER_ENTITY_COUNT="$BEFORE_ENTITY_COUNT"
for attempt in $(seq 1 12); do
  vault read -format=json sys/internal/counters/activity \
    > "$EVIDENCE_DIR/activity-after.json"
  AFTER_CLIENT_COUNT=$("$JQ_BIN" -r '.data.total.clients' "$EVIDENCE_DIR/activity-after.json")
  AFTER_ENTITY_COUNT=$("$JQ_BIN" -r '.data.total.entity_clients' "$EVIDENCE_DIR/activity-after.json")
  echo "client-counter poll ${attempt}: before=${BEFORE_CLIENT_COUNT} after=${AFTER_CLIENT_COUNT}"
  (( AFTER_CLIENT_COUNT >= BEFORE_CLIENT_COUNT + 1 )) && break
  sleep 5
done
require_eq "$AFTER_CLIENT_COUNT" "$((BEFORE_CLIENT_COUNT + 1))" "total client counter delta"
require_eq "$AFTER_ENTITY_COUNT" "$((BEFORE_ENTITY_COUNT + 1))" "entity client counter delta"

BEFORE_CERT_COUNT=$("$JQ_BIN" '[.data.months[]?.counts.issued_certificates // 0] | add // 0' \
  "$EVIDENCE_DIR/certificates-before.json")
AFTER_CERT_COUNT="$BEFORE_CERT_COUNT"
for attempt in $(seq 1 18); do
  vault read -format=json sys/billing/certificates \
    > "$EVIDENCE_DIR/certificates-after.json"
  AFTER_CERT_COUNT=$("$JQ_BIN" '[.data.months[]?.counts.issued_certificates // 0] | add // 0' \
    "$EVIDENCE_DIR/certificates-after.json")
  echo "certificate-counter poll ${attempt}: before=${BEFORE_CERT_COUNT} after=${AFTER_CERT_COUNT}"
  (( AFTER_CERT_COUNT >= BEFORE_CERT_COUNT + 6 )) && break
  sleep 10
done

"$JQ_BIN" -n \
  --arg run_id "$RUN_ID" --arg namespace root \
  --arg username "$USERNAME" --arg auth_accessor "$USERPASS_ACCESSOR" \
  --argjson issued_certificates 3 --argjson unique_serials "$UNIQUE_SERIALS" \
  --argjson unique_fingerprints "$UNIQUE_FINGERPRINTS" \
  --arg original_serial "$ORIGINAL_SERIAL" \
  --arg reenrolled_serial "$REENROLLED_SERIAL" \
  --argjson successful_simpleenroll_responses "$SUCCESSFUL_ENROLL_RESPONSES" \
  --argjson successful_simplereenroll_responses "$SUCCESSFUL_REENROLL_RESPONSES" \
  --argjson unique_client_ids "$UNIQUE_CLIENT_IDS" \
  --argjson unique_entity_ids "$UNIQUE_ENTITY_IDS" \
  --argjson unique_display_names "$UNIQUE_DISPLAY_NAMES" \
  --argjson certificate_count_before "$BEFORE_CERT_COUNT" \
  --argjson certificate_count_after "$AFTER_CERT_COUNT" \
  --argjson client_count_before "$BEFORE_CLIENT_COUNT" \
  --argjson client_count_after "$AFTER_CLIENT_COUNT" \
  --argjson entity_count_before "$BEFORE_ENTITY_COUNT" \
  --argjson entity_count_after "$AFTER_ENTITY_COUNT" \
  '{status:"PASS",hypothesis:"three EST enrollments and one re-enrollment using one shared credential resolve to one Vault entity/client",run_id:$run_id,namespace:$namespace,shared_identity:{username:$username,auth_accessor:$auth_accessor},est:{simpleenroll:{issued_certificates:$issued_certificates,unique_serials:$unique_serials,unique_fingerprints:$unique_fingerprints,successful_responses:$successful_simpleenroll_responses},simplereenroll:{successful_responses:$successful_simplereenroll_responses,original_serial:$original_serial,reenrolled_serial:$reenrolled_serial,serial_changed:($original_serial != $reenrolled_serial)}},identity_correlation:{unique_client_ids:$unique_client_ids,unique_entity_ids:$unique_entity_ids,unique_display_names:$unique_display_names},activity_counter:{clients_before:$client_count_before,clients_after:$client_count_after,client_delta:($client_count_after-$client_count_before),entity_clients_before:$entity_count_before,entity_clients_after:$entity_count_after,entity_client_delta:($entity_count_after-$entity_count_before)},certificate_counter:{before:$certificate_count_before,after:$certificate_count_after,delta:($certificate_count_after-$certificate_count_before)}}' \
  | tee "$EVIDENCE_DIR/summary.json"

echo "EST_SHARED_CREDENTIAL_TEST_PASS evidence=${EVIDENCE_DIR}"
