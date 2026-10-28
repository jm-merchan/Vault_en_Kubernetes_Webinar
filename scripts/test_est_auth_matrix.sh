#!/usr/bin/env bash
# Isolated EST enrollment/re-enrollment authentication matrix. No Python.
if [[ -f /tmp/vault/config.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source /tmp/vault/config.env
  set +a
fi
set -euo pipefail
umask 077
unset VAULT_NAMESPACE
: "${VAULT_ADDR:?}" "${VAULT_TOKEN:?}" "${VAULT_CACERT:?}"
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(dirname "$SCRIPT_DIR")
RUN_ID=$(date -u +%Y%m%dT%H%M%SZ)
EVIDENCE="$REPO_DIR/evidence/est-auth-matrix-$RUN_ID"
WORKDIR=""
REPLAY=false
MODE=matrix
PKI="pki_est_matrix_$RUN_ID"
UP="est-matrix-up-$RUN_ID"
CERT="est-matrix-cert-$RUN_ID"
POLICY="est-matrix-$(printf '%s' "$RUN_ID" | tr '[:upper:]' '[:lower:]')"
AUDIT="est-matrix-$RUN_ID"
AUDIT_FILE="/tmp/$AUDIT.json"
DOMAIN=est-matrix.example.test
KUBE_CONTEXT=${KUBE_CONTEXT:-workshop-k8s}
KUBE_NAMESPACE=${KUBE_NAMESPACE:-vault}
OPENSSL_BIN=${OPENSSL_BIN:-/opt/homebrew/opt/openssl@3/bin/openssl}
[[ -x "$OPENSSL_BIN" ]] || OPENSSL_BIN=openssl
CREATED_PKI=false CREATED_UP=false CREATED_CERT=false CREATED_POLICY=false CREATED_AUDIT=false
if [[ "${1:-}" == --analyze ]]; then
  EVIDENCE=${2:?Usage: --analyze evidence-directory}
  [[ -f "$EVIDENCE/resources.json" && -f "$EVIDENCE/requests.jsonl" && -f "$EVIDENCE/audit-redacted.jsonl" ]] || exit 1
  EVIDENCE=$(cd "$EVIDENCE" && pwd)
  RUN_ID=${EVIDENCE##*/est-auth-matrix-}
  [[ "$RUN_ID" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || exit 1
  PKI=$(jq -r .pki_mount "$EVIDENCE/resources.json")
  UP=$(jq -r .userpass_mount "$EVIDENCE/resources.json")
  CERT=$(jq -r .cert_mount "$EVIDENCE/resources.json")
  UP_ACCESSOR=$(jq -r .userpass_accessor "$EVIDENCE/resources.json")
  CERT_ACCESSOR=$(jq -r .cert_accessor "$EVIDENCE/resources.json")
  MODE=$(jq -r '.mode // "matrix"' "$EVIDENCE/resources.json")
  REPLAY=true
elif [[ "${1:-}" == --cert-lifecycle && $# == 1 ]]; then
  MODE=cert-lifecycle
  WORKDIR=$(mktemp -d /tmp/vault-est-matrix.XXXXXX)
elif [[ $# != 0 ]]; then
  printf 'Usage: %s [--cert-lifecycle | --analyze evidence-directory]\n' "$0" >&2
  exit 1
else
  WORKDIR=$(mktemp -d /tmp/vault-est-matrix.XXXXXX)
fi
mkdir -p "$EVIDENCE/certificates"
vault() { command vault "$@"; }
log() { printf '%s\n' "$*"; }
assert() { if ! "$@"; then log "FAILED: $*" >&2; exit 1; fi; }

collect_audit() {
  local pod
  for pod in $(kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NAMESPACE" get pods -l app.kubernetes.io/name=vault -o name); do
    kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NAMESPACE" exec "${pod#pod/}" -c vault -- \
      sh -c "test ! -f '$AUDIT_FILE' || cat '$AUDIT_FILE'" 2>/dev/null
  done | jq -c --arg base "$PKI/roles/devices/est/" --arg up "auth/$UP/login/" --arg cert "auth/$CERT/login" '
    select((.request.path|startswith($base)) or (.request.path|startswith($up)) or .request.path==$cert)
    | {time,type,request_id:.request.id,path:.request.path,operation:.request.operation,
       client_id:(.request.client_id // .auth.client_id // null),entity_id:(.auth.entity_id // null),
       display_name:(.auth.display_name // null),token_type:(.auth.token_type // null),
       http_status:(.response.data.http_status_code // null),error:(.error // null)}' > "$EVIDENCE/audit-redacted.jsonl"
}

cleanup() (
  set +e
  [[ "$CREATED_CERT" == false ]] || vault auth disable "$CERT" >/dev/null
  [[ "$CREATED_UP" == false ]] || vault auth disable "$UP" >/dev/null
  [[ "$CREATED_PKI" == false ]] || vault secrets disable "$PKI" >/dev/null
  [[ "$CREATED_POLICY" == false ]] || vault policy delete "$POLICY" >/dev/null
  [[ "$CREATED_AUDIT" == false ]] || vault audit disable "$AUDIT" >/dev/null
  # Only the exact mktemp directory owned by this invocation.
  if [[ "$WORKDIR" == /tmp/vault-est-matrix.* && -d "$WORKDIR" ]]; then
    find "$WORKDIR" -type f -delete
    rmdir "$WORKDIR"
  fi
)
on_exit() {
  local rc=$?
  trap - EXIT
  if [[ "$CREATED_AUDIT" == true ]]; then collect_audit || true; fi
  cleanup
  exit "$rc"
}
trap on_exit EXIT

checkpoint() {
  vault read -format=json sys/internal/counters/activity > "$EVIDENCE/activity-$1.json"
  jq -n --arg phase "$1" --slurpfile activity "$EVIDENCE/activity-$1.json" \
    '{phase:$phase,clients:$activity[0].data.total}' >> "$EVIDENCE/phases.jsonl"
}

make_csr() {
  local name=$1 cn=$2 san=${3:-$2}
  printf '[req]\nprompt=no\ndistinguished_name=dn\nreq_extensions=ext\nstring_mask=nombstr\nutf8=no\n[dn]\nCN=%s\n[ext]\nsubjectAltName=DNS:%s\n' \
    "$cn" "$san" > "$WORKDIR/$name.cnf"
  "$OPENSSL_BIN" req -new -newkey rsa:2048 -nodes -sha256 -keyout "$WORKDIR/$name.key" \
    -out "$WORKDIR/$name.csr" -config "$WORKDIR/$name.cnf" >/dev/null 2>&1
  "$OPENSSL_BIN" req -in "$WORKDIR/$name.csr" -outform DER | "$OPENSSL_BIN" base64 -A > "$WORKDIR/$name.p10"
}

# auth user: none, shared, device-01/02/03, or bad (shared user, wrong password).
# auth cert: none, shared-auth, or a previous issued certificate's step name.
send_est() {
  local name=$1 operation=$2 csr=$3 user=$4 cert=$5 expected=$6 http cn auth_cn="" serial="" fingerprint="" pubkey csrkey
  local tls_serial="" tls_fingerprint="" tls_pubkey="" tls_keypub="" tls_san="" csr_san="" renewal_preflight=false
  local -a auth_args=(--cacert "$VAULT_CACERT")
  if [[ "$user" != none ]]; then
    if [[ "$user" == bad ]]; then
      auth_args+=(--user "shared:wrong-$RUN_ID")
    else
      auth_args+=(--user "$user:$(<"$WORKDIR/password-$user")")
    fi
  fi
  if [[ "$cert" != none ]]; then
    auth_args+=(--cert "$EVIDENCE/certificates/$cert.pem" --key "$WORKDIR/$cert.key")
    auth_cn=$("$OPENSSL_BIN" x509 -in "$EVIDENCE/certificates/$cert.pem" -noout -subject -nameopt RFC2253)
    tls_serial=$("$OPENSSL_BIN" x509 -in "$EVIDENCE/certificates/$cert.pem" -noout -serial | cut -d= -f2)
    tls_fingerprint=$("$OPENSSL_BIN" x509 -in "$EVIDENCE/certificates/$cert.pem" -noout -fingerprint -sha256 | cut -d= -f2)
    tls_pubkey=$("$OPENSSL_BIN" x509 -in "$EVIDENCE/certificates/$cert.pem" -noout -pubkey | "$OPENSSL_BIN" sha256)
    tls_keypub=$("$OPENSSL_BIN" pkey -in "$WORKDIR/$cert.key" -pubout | "$OPENSSL_BIN" sha256)
    assert test "$tls_pubkey" = "$tls_keypub"
  fi
  cn=$("$OPENSSL_BIN" req -in "$WORKDIR/$csr.csr" -noout -subject -nameopt RFC2253)
  csrkey=$("$OPENSSL_BIN" req -in "$WORKDIR/$csr.csr" -noout -pubkey | "$OPENSSL_BIN" sha256)
  if [[ "$MODE" == cert-lifecycle && "$operation" == simplereenroll ]]; then
    # Correct lifecycle: the current issued leaf/key authenticates TLS; the CSR
    # retains its Subject/SAN and requests a NEW key. Never use bootstrap here.
    assert test "$cert" != shared-auth
    assert test "$cert" != none
    assert test "$user" = none
    assert test "$cn" = "$auth_cn"
    tls_san=$("$OPENSSL_BIN" x509 -in "$EVIDENCE/certificates/$cert.pem" -noout -ext subjectAltName | tail -n 1 | sed 's/^[[:space:]]*//')
    csr_san=$("$OPENSSL_BIN" req -in "$WORKDIR/$csr.csr" -noout -text | sed -n '/X509v3 Subject Alternative Name:/{n;s/^[[:space:]]*//;p;}')
    assert test "$tls_san" = "$csr_san"
    assert test "$tls_pubkey" != "$csrkey"
    "$OPENSSL_BIN" verify -purpose sslclient -CAfile "$CA" "$EVIDENCE/certificates/$cert.pem" >/dev/null
    renewal_preflight=true
  fi
  cp "$WORKDIR/$csr.csr" "$EVIDENCE/$name.csr.pem"
  # No Vault token is sent to EST. Curl verifies the server's TLS certificate.
  http=$(curl --silent --show-error --connect-timeout 10 --max-time 60 --cacert "$VAULT_CACERT" \
    "${auth_args[@]}" -H 'Content-Type: application/pkcs10' -H 'Content-Transfer-Encoding: base64' \
    --data-binary @"$WORKDIR/$csr.p10" -D "$EVIDENCE/$name.headers" \
    -o "$EVIDENCE/$name.body" -w '%{http_code}' "$BASE/$operation")
  if [[ "$http" == 200 ]]; then
    tr -d '\r\n' < "$EVIDENCE/$name.body" | "$OPENSSL_BIN" base64 -d -A -out "$WORKDIR/$name.p7.der"
    "$OPENSSL_BIN" pkcs7 -inform DER -in "$WORKDIR/$name.p7.der" -print_certs -out "$WORKDIR/$name.bundle.pem"
    "$OPENSSL_BIN" x509 -in "$WORKDIR/$name.bundle.pem" -out "$EVIDENCE/certificates/$name.pem"
    "$OPENSSL_BIN" verify -CAfile "$CA" "$EVIDENCE/certificates/$name.pem" >/dev/null
    assert test "$("$OPENSSL_BIN" x509 -in "$EVIDENCE/certificates/$name.pem" -noout -subject -nameopt RFC2253)" = "$cn"
    pubkey=$("$OPENSSL_BIN" x509 -in "$EVIDENCE/certificates/$name.pem" -noout -pubkey | "$OPENSSL_BIN" sha256)
    csrkey=$("$OPENSSL_BIN" req -in "$WORKDIR/$csr.csr" -noout -pubkey | "$OPENSSL_BIN" sha256)
    assert test "$pubkey" = "$csrkey"
    "$OPENSSL_BIN" x509 -in "$EVIDENCE/certificates/$name.pem" -noout -subject -issuer -serial -dates -ext subjectAltName \
      > "$EVIDENCE/$name-certificate.txt"
    serial=$("$OPENSSL_BIN" x509 -in "$EVIDENCE/certificates/$name.pem" -noout -serial | cut -d= -f2)
    fingerprint=$("$OPENSSL_BIN" x509 -in "$EVIDENCE/certificates/$name.pem" -noout -fingerprint -sha256 | cut -d= -f2)
    if [[ "$csr" != "$name" ]]; then cp "$WORKDIR/$csr.key" "$WORKDIR/$name.key"; fi
  fi
  jq -n --arg step "$name" --arg op "$operation" --arg user "$user" --arg cert "$cert" \
    --arg cn "$cn" --arg auth_cn "$auth_cn" --arg expected "$expected" --argjson http "$http" \
    --arg serial "$serial" --arg fingerprint "$fingerprint" --arg tls_serial "$tls_serial" \
    --arg tls_fingerprint "$tls_fingerprint" --arg tls_pubkey "$tls_pubkey" --arg csr_pubkey "$csrkey" \
    --argjson renewal_preflight "$renewal_preflight" \
    '{step:$step,operation:$op,basic_user:$user,tls_certificate:$cert,csr_subject:$cn,tls_subject:$auth_cn,
      expected:$expected,http:$http,serial:$serial,sha256:$fingerprint,
      tls_serial:$tls_serial,tls_sha256:$tls_fingerprint,tls_public_key_sha256:$tls_pubkey,
      csr_public_key_sha256:$csr_pubkey,renewal_preflight:$renewal_preflight,
      expectation_met:(if $expected=="success" then $http==200 elif $expected=="reject" then ($http>=400 and $http<500) else true end)}' \
    >> "$EVIDENCE/requests.jsonl"
  log "$name: HTTP=$http EST=$operation Basic=$user TLS=$cert"
  if [[ "$expected" == success ]]; then assert test "$http" = 200; fi
}

if [[ "$REPLAY" == false ]]; then
log "EST matrix evidence: $EVIDENCE"
vault status -format=json | jq '{version,sealed,cluster_name}' > "$EVIDENCE/vault-status.json"
checkpoint before
vault read -format=json sys/billing/certificates > "$EVIDENCE/certificates-before.json"
assert jq -e --arg p "$PKI/" 'has($p)|not' < <(vault secrets list -format=json)
assert jq -e --arg up "$UP/" --arg cert "$CERT/" '(has($up)|not) and (has($cert)|not)' < <(vault auth list -format=json)
vault audit enable -path="$AUDIT" file file_path="$AUDIT_FILE" log_raw=false >/dev/null
CREATED_AUDIT=true
vault secrets enable -path="$PKI" pki >/dev/null
CREATED_PKI=true
vault secrets tune -max-lease-ttl=24h "$PKI" >/dev/null
vault write -format=json "$PKI/root/generate/internal" common_name="EST Matrix CA $RUN_ID" key_type=rsa key_bits=2048 ttl=24h \
  | jq -r .data.certificate > "$EVIDENCE/certificates/ca.pem"
CA="$EVIDENCE/certificates/ca.pem"
vault write "$PKI/roles/devices" allowed_domains="$DOMAIN" allow_subdomains=true allow_bare_domains=false \
  allow_ip_sans=false allow_wildcard_certificates=false key_type=rsa key_bits=2048 \
  client_flag=true server_flag=false ttl=1h max_ttl=2h not_before_duration=0s \
  use_csr_common_name=true use_csr_sans=true no_store=false >/dev/null
make_csr shared-auth "shared-auth.$DOMAIN"
vault write -format=json "$PKI/sign/devices" csr=@"$WORKDIR/shared-auth.csr" ttl=1h \
  | jq -r .data.certificate > "$EVIDENCE/certificates/shared-auth.pem"
printf 'path "%s/roles/devices/est/simpleenroll" { capabilities = ["create", "update"] }\npath "%s/roles/devices/est/simplereenroll" { capabilities = ["create", "update"] }\n' "$PKI" "$PKI" \
  | vault policy write "$POLICY" - >/dev/null
CREATED_POLICY=true
UP_ACCESSOR=""
if [[ "$MODE" == matrix ]]; then
vault auth enable -path="$UP" userpass >/dev/null
CREATED_UP=true
vault auth tune -token-type=batch "$UP" >/dev/null
for user in shared device-01 device-02 device-03; do
  "$OPENSSL_BIN" rand -hex 32 | tr -d '\n' > "$WORKDIR/password-$user"
  vault write "auth/$UP/users/$user" password=@"$WORKDIR/password-$user" token_type=batch token_ttl=5m \
    token_no_default_policy=true token_policies="$POLICY" >/dev/null
done
UP_ACCESSOR=$(vault read -field=accessor "sys/auth/$UP")
fi
vault auth enable -path="$CERT" cert >/dev/null
CREATED_CERT=true
vault auth tune -token-type=batch "$CERT" >/dev/null
vault write "auth/$CERT/certs/devices" certificate=@"$CA" allowed_common_names="*.$DOMAIN" \
  allowed_dns_sans="*.$DOMAIN" token_type=batch token_ttl=5m token_no_default_policy=true token_policies="$POLICY" >/dev/null
CERT_ACCESSOR=$(vault read -field=accessor "sys/auth/$CERT")
DELEGATED_ARGS=(-delegated-auth-accessors="$CERT_ACCESSOR")
if [[ -n "$UP_ACCESSOR" ]]; then DELEGATED_ARGS+=(-delegated-auth-accessors="$UP_ACCESSOR"); fi
vault secrets tune -allowed-response-headers=Content-Transfer-Encoding -allowed-response-headers=Content-Length \
  -allowed-response-headers=WWW-Authenticate "${DELEGATED_ARGS[@]}" "$PKI" >/dev/null
jq -n --arg up "$UP_ACCESSOR" --arg cert "$CERT_ACCESSOR" \
  '{enabled:true,default_mount:false,default_path_policy:"role:devices",label_to_path_policy:{},
    authenticators:({cert:{accessor:$cert,cert_role:"devices"}} +
      if $up=="" then {} else {userpass:{accessor:$up}} end),
    enable_sentinel_parsing:true,audit_fields:["common_name","alt_names"]}' \
  | vault write -format=json "$PKI/config/est" - > "$EVIDENCE/est-config.json"
BASE="$VAULT_ADDR/v1/$PKI/roles/devices/est"
jq -n --arg pki "$PKI" --arg up "$UP" --arg cert "$CERT" --arg up_accessor "$UP_ACCESSOR" \
  --arg cert_accessor "$CERT_ACCESSOR" --arg policy "$POLICY" --arg audit "$AUDIT" --arg url "$BASE" --arg mode "$MODE" \
  '{pki_mount:$pki,userpass_mount:$up,cert_mount:$cert,userpass_accessor:$up_accessor,cert_accessor:$cert_accessor,
    policy:$policy,audit:$audit,url:$url,namespace:"root",default_mount:false,mode:$mode}' > "$EVIDENCE/resources.json"
assert test "$(curl --silent --show-error --cacert "$VAULT_CACERT" -o "$EVIDENCE/cacerts.body" -w '%{http_code}' "$BASE/cacerts")" = 200

if [[ "$MODE" == cert-lifecycle ]]; then
  for i in 01 02 03; do
    make_csr "lifecycle-enroll-$i" "device-$i.$DOMAIN"
    send_est "lifecycle-enroll-$i" simpleenroll "lifecycle-enroll-$i" none shared-auth success
    checkpoint "lifecycle-enroll-$i"
  done
  for i in 01 02 03; do
    make_csr "lifecycle-renew1-$i" "device-$i.$DOMAIN"
    send_est "lifecycle-renew1-$i" simplereenroll "lifecycle-renew1-$i" none "lifecycle-enroll-$i" success
    checkpoint "lifecycle-renew1-$i"
  done
  for i in 01 02 03; do
    make_csr "lifecycle-renew2-$i" "device-$i.$DOMAIN"
    send_est "lifecycle-renew2-$i" simplereenroll "lifecycle-renew2-$i" none "lifecycle-renew1-$i" success
    checkpoint "lifecycle-renew2-$i"
  done
else
for i in 01 02 03; do
  make_csr "up-shared-$i" "device-$i.$DOMAIN"
  send_est "up-shared-$i" simpleenroll "up-shared-$i" shared none success
done
checkpoint shared-user-enroll
for i in 01 02 03; do
  make_csr "up-shared-renew-$i" "device-$i.$DOMAIN"
  send_est "up-shared-renew-$i" simplereenroll "up-shared-renew-$i" shared "up-shared-$i" success
done
checkpoint shared-user-renew
for i in 01 02 03; do
  make_csr "up-unique-$i" "device-$i.$DOMAIN"
  send_est "up-unique-$i" simpleenroll "up-unique-$i" "device-$i" none success
done
checkpoint unique-user-enroll
for i in 01 02 03; do
  make_csr "up-unique-renew-$i" "device-$i.$DOMAIN"
  send_est "up-unique-renew-$i" simplereenroll "up-unique-renew-$i" "device-$i" "up-unique-$i" success
done
checkpoint unique-user-renew
for i in 01 02 03; do
  make_csr "cert-shared-$i" "device-$i.$DOMAIN"
  send_est "cert-shared-$i" simpleenroll "cert-shared-$i" none shared-auth success
done
checkpoint shared-cert-enroll
make_csr shared-cert-device-renew "device-01.$DOMAIN"
send_est shared-cert-device-renew simplereenroll shared-cert-device-renew none shared-auth observe
checkpoint shared-cert-device-renew
for i in 01 02 03; do
  make_csr "cert-own-transition-$i" "device-$i.$DOMAIN"
  send_est "cert-own-transition-$i" simplereenroll "cert-own-transition-$i" none "cert-shared-$i" success
done
checkpoint own-cert-transition
for i in 01 02 03; do
  make_csr "cert-own-enroll-$i" "device-$i.$DOMAIN"
  send_est "cert-own-enroll-$i" simpleenroll "cert-own-enroll-$i" none "cert-own-transition-$i" success
done
checkpoint own-cert-enroll
for i in 01 02 03; do
  make_csr "cert-own-renew-$i" "device-$i.$DOMAIN"
  send_est "cert-own-renew-$i" simplereenroll "cert-own-renew-$i" none "cert-own-enroll-$i" success
done
checkpoint own-cert-renew
make_csr shared-auth-renew "shared-auth.$DOMAIN"
send_est shared-auth-renew simplereenroll shared-auth-renew none shared-auth success
make_csr renewed-shared-auth-enroll "device-01.$DOMAIN"
send_est renewed-shared-auth-enroll simpleenroll renewed-shared-auth-enroll none shared-auth-renew success
checkpoint shared-auth-rotation

# Explicitly measure precedence when HTTP Basic and a TLS certificate coexist.
make_csr both-enroll "device-01.$DOMAIN"
send_est both-enroll simpleenroll both-enroll shared shared-auth success
make_csr both-renew "device-01.$DOMAIN"
send_est both-renew simplereenroll both-renew shared cert-own-renew-01 success
checkpoint combined-auth

# Negative/mismatch cases use fresh CSR keys but never change validation settings.
make_csr negative "device-01.$DOMAIN"
send_est no-auth-enroll simpleenroll negative none none reject
send_est no-auth-renew simplereenroll negative none none reject
send_est wrong-password-enroll simpleenroll negative bad none reject
send_est basic-only-renew simplereenroll negative shared none reject
send_est bad-basic-valid-cert-enroll simpleenroll negative bad shared-auth observe
send_est bad-basic-valid-cert-renew simplereenroll negative bad cert-own-renew-01 observe
make_csr untrusted "device-01.$DOMAIN"
"$OPENSSL_BIN" x509 -req -in "$WORKDIR/untrusted.csr" -signkey "$WORKDIR/untrusted.key" -sha256 -days 1 \
  -out "$EVIDENCE/certificates/untrusted.pem" >/dev/null 2>&1
send_est untrusted-enroll simpleenroll negative none untrusted reject
send_est untrusted-renew simplereenroll negative none untrusted reject
send_est valid-basic-untrusted-cert simpleenroll negative shared untrusted observe
send_est basic-shared-cert-renew simplereenroll negative shared shared-auth observe
make_csr changed-cn "changed.$DOMAIN" "device-01.$DOMAIN"
send_est changed-cn-renew simplereenroll changed-cn none cert-own-renew-01 observe
make_csr changed-san "device-01.$DOMAIN" "changed.$DOMAIN"
send_est changed-san-renew simplereenroll changed-san none cert-own-renew-01 observe
checkpoint after-controls
fi
collect_audit
fi

# Requests are sequential on isolated paths; join their ordered HTTP outcomes to
# ordered audit request IDs, then prove the delegated login path for each ID.
jq -n --slurpfile requests "$EVIDENCE/requests.jsonl" --slurpfile audit "$EVIDENCE/audit-redacted.jsonl" \
  --arg base "$PKI/roles/devices/est/" '
  [$audit[]|select(.operation=="update" and (.path|startswith($base)))]
  | group_by(.request_id) | map(sort_by(.time)) | sort_by(.[0].time) as $groups
  | if ($groups|length)!=($requests|length) then error("request/audit count mismatch") else
    [$requests|to_entries[]|.key as $i|.value as $r|$groups[$i] as $g
     | [$audit[]|select(.request_id==$g[0].request_id and .type=="response" and (.path|startswith("auth/")))] as $login
     | if $r.operation != ($g[0].path|split("/")|last) then error("request/audit operation mismatch") else
       $r+{request_id:$g[0].request_id,
           entity_id:([$g[]|.entity_id|select(.!=null)]|unique|first//null),
           client_id:([$g[]|.client_id|select(.!=null)]|unique|first//null),
           auth_paths:($login|map(.path)|unique),auth_errors:($login|map(.error)|map(select(.!=null)))} end] end' \
  > "$EVIDENCE/operations.json"
assert jq -e 'all(.expectation_met)' "$EVIDENCE/operations.json"
assert jq -e 'all(.[]|select(.http==200); .entity_id!=null and (.auth_paths|length==1))' "$EVIDENCE/operations.json"
if [[ "$MODE" == cert-lifecycle ]]; then
  jq -e -f "$SCRIPT_DIR/verify_est_cert_lifecycle.jq" "$EVIDENCE/operations.json" > "$EVIDENCE/assertions.json"
else
  jq -e -f "$SCRIPT_DIR/verify_est_auth_matrix.jq" "$EVIDENCE/operations.json" > "$EVIDENCE/assertions.json"
fi
for id in $(jq -r '[.[].entity_id|select(.!=null)]|unique[]' "$EVIDENCE/operations.json"); do
  vault read -format=json "identity/entity/id/$id" \
    | jq '.data|{id,name,aliases:[.aliases[]|{name,mount_accessor,mount_path,mount_type,canonical_id}]}'
done | jq -s . > "$EVIDENCE/entity-aliases.json"
jq -s '. as $p|to_entries|map(.key as $i|{phase:.value.phase,clients:.value.clients,
  delta:(if $i==0 then 0 else .value.clients.clients-$p[$i-1].clients.clients end)})' \
  "$EVIDENCE/phases.jsonl" > "$EVIDENCE/phase-deltas.json"
SUCCESS_COUNT=$(jq '[.[]|select(.http==200)]|length' "$EVIDENCE/operations.json")
EXPECTED_CERTIFICATES=$((SUCCESS_COUNT + 2))
BEFORE_CERTS=$(jq '[.data.months[]?.counts.issued_certificates // 0]|add//0' "$EVIDENCE/certificates-before.json")
for attempt in $(seq 1 24); do
  vault read -format=json sys/billing/certificates > "$EVIDENCE/certificates-after.json"
  AFTER_CERTS=$(jq '[.data.months[]?.counts.issued_certificates // 0]|add//0' "$EVIDENCE/certificates-after.json")
  log "certificate counter: $BEFORE_CERTS -> $AFTER_CERTS; expected delta=$EXPECTED_CERTIFICATES (poll $attempt)"
  (( AFTER_CERTS >= BEFORE_CERTS + EXPECTED_CERTIFICATES )) && break
  sleep 5
done
curl --silent --show-error --fail --cacert "$VAULT_CACERT" -H "X-Vault-Token: $VAULT_TOKEN" \
  "$VAULT_ADDR/v1/sys/internal/counters/activity/export?format=json" \
  | jq -c --arg up "$UP_ACCESSOR" --arg cert "$CERT_ACCESSOR" 'select(.mount_accessor==$up or .mount_accessor==$cert)' \
  > "$EVIDENCE/activity-export-focused.jsonl"
jq -s '{rows:length,status:(if length>0 then "AVAILABLE" else "PENDING_PROPAGATION" end)}' \
  "$EVIDENCE/activity-export-focused.jsonl" > "$EVIDENCE/activity-export-status.json"
jq -n --arg run "$RUN_ID" --arg mode "$MODE" --argjson replay "$REPLAY" --slurpfile ops "$EVIDENCE/operations.json" --slurpfile phases "$EVIDENCE/phase-deltas.json" \
  --argjson before "$BEFORE_CERTS" --argjson after "$AFTER_CERTS" --argjson expected "$EXPECTED_CERTIFICATES" '
  {status:"PASS",run_id:$run,mode:$mode,analyzed_from_saved_requests:$replay,requests:($ops[0]|length),successful_issuances:([$ops[0][]|select(.http==200)]|length),
    rejected_requests:([$ops[0][]|select(.http>=400)]|length),
    unique_serials:([$ops[0][]|select(.http==200)|.serial]|unique|length),
    unique_fingerprints:([$ops[0][]|select(.http==200)|.sha256]|unique|length),
    unique_client_ids:([$ops[0][].client_id|select(.!=null)]|unique),phases:$phases[0],
    certificates:{before:$before,after:$after,delta:($after-$before),expected_delta:$expected,
      counter_observed:($after-$before >= $expected),note:"One CA and one bootstrap cert plus successful EST requests; aggregate may include concurrent workloads"}}' \
  | tee "$EVIDENCE/summary.json"
assert jq -e '.successful_issuances==.unique_serials' "$EVIDENCE/summary.json"
log "EST_AUTH_MATRIX_PASS evidence=$EVIDENCE"
