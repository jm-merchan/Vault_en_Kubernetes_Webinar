#!/usr/bin/env bash
# Vault Enterprise DR replication with AWS KMS auto-unseal (AssumeRole): rebuild
# the lab and rerun the tests of 20-22 Nov 2026.
#
#   ./replicate.sh up                 Minikube profile, AWS resources, primary and DR
#                                     clusters, DR replication, LDAP, PostgreSQL
#   ./replicate.sh test-start [secs]  start the probes, log monitor and KMS watcher
#                                     in the background (default 28800 s = 8 h)
#   ./replicate.sh watch [--errors|--all]
#                                     live view: every probe result and notable server
#                                     log line with the real (host) time, failures in red
#   ./replicate.sh status             probe counts, replication, clock skew, sealed nodes
#   ./replicate.sh heal               restart Vault pods that sealed themselves
#   ./replicate.sh test-stop          stop the probes and watchers
#   ./replicate.sh down [--delete-profile]
#                                     remove both clusters, the helper namespace and
#                                     the AWS resources; optionally the Minikube profile
#
# What the original run found, and why some steps exist:
#   * Every seal failure (ExpiredTokenException on KMS Encrypt) happened while the
#     node clock was behind real time. On a laptop that is what happens when the
#     Mac sleeps: the Podman VM clock stops. `status` prints the clock skew, and
#     `test-start` warns about it. caffeinate does not prevent sleep on lid close.
#   * A leader election while the token is expired seals the new active node, and
#     it does not unseal by itself once KMS works again: `heal` restarts it.
#   * After a DR secondary is enabled, its followers seal ("encryption keys have
#     changed"); with awskms they are restarted instead of unsealed by hand.
#
# Settings (override with environment variables):
#   PROFILE (workshop-k8s)  REGION (eu-west-3)  VAULT_TAG (2.2.2-ent)
#   LICENSE_FILE (../vault.hclic)  AWS_ADMIN_CSV (../vault_test_accessKeys.csv)
#   DRTEST_WORKDIR (~/.vault-dr-test; holds root tokens and AWS keys, mode 700)
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO=$(dirname "${HERE}")
: "${PROFILE:=workshop-k8s}"
: "${REGION:=eu-west-3}"
: "${VAULT_TAG:=2.2.2-ent}"
: "${LICENSE_FILE:=${REPO}/vault.hclic}"
: "${AWS_ADMIN_CSV:=${REPO}/vault_test_accessKeys.csv}"
: "${DRTEST_WORKDIR:=${HOME}/.vault-dr-test}"
CTX=${PROFILE}
PRI_NS=vault23;    PRI_SUFFIX=23
DR_NS=vault23dr;   DR_SUFFIX=23-dr
DEPS_NS=vault23-deps
CLUSTER_DOMAIN=cluster.local
RUN=${DRTEST_WORKDIR}/run
PYTHON=${REPO}/.venv/bin/python
[ -x "${PYTHON}" ] || PYTHON=python3
export REGION CTX PRI_NS DR_NS DEPS_NS DRTEST_WORKDIR AWS_ADMIN_CSV

k()   { kubectl --context "${CTX}" "$@"; }
say() { printf '\n=== %s\n' "$*"; }
root_token() { "${PYTHON}" -c 'import json,sys;r=open(sys.argv[1]).read();print(json.loads(r[r.find("{"):])["root_token"])' "${DRTEST_WORKDIR}/$1/vault-init.json"; }
vault_in() {  # vault_in <role> <namespace> <pod> <vault args...>
  local role=$1 ns=$2 pod=$3; shift 3
  k -n "${ns}" exec -i "${pod}" -- env VAULT_TOKEN="$(root_token "${role}")" vault "$@"
}
pv() { vault_in primary "${PRI_NS}" "${PRI_NS}-0" "$@"; }
aws_value() { sed -n "s/^$2=//p" "${DRTEST_WORKDIR}/$1/aws.env"; }
clock_skew() { echo $(( $(date -u +%s) - $(k -n "$1" exec "$1-0" -- date -u +%s 2>/dev/null || echo 0) )); }

ensure_minikube() {
  say "Minikube profile ${PROFILE}"
  if ! minikube status -p "${PROFILE}" >/dev/null 2>&1; then
    minikube start -p "${PROFILE}" --driver=podman
  fi
  k get nodes
  helm repo add hashicorp https://helm.releases.hashicorp.com >/dev/null 2>&1 || true
  helm repo update hashicorp >/dev/null
  mkdir -p "${DRTEST_WORKDIR}"; chmod 700 "${DRTEST_WORKDIR}"
}

# deploy_cluster <role: primary|dr> <namespace> <aws suffix> <cluster name>
deploy_cluster() {
  local role=$1 ns=$2 suffix=$3 name=$4 dir=${DRTEST_WORKDIR}/$1 svc=$2-internal
  say "${role}: AWS resources (suffix ${suffix})"
  mkdir -p "${dir}/aws"; umask 077
  "${PYTHON}" "${HERE}/aws_env.py" create "${suffix}" "${dir}/aws/credentials" "${dir}/aws.env"
  local kms_key_id; kms_key_id=$(aws_value "${role}" KMS_KEY_ID)

  say "${role}: namespace ${ns} and Secrets"
  k create namespace "${ns}" --dry-run=client -o yaml | k apply -f -
  k -n "${ns}" delete secret vault-aws-creds vault-ha-tls vault-ent-license --ignore-not-found
  k -n "${ns}" create secret generic vault-aws-creds --from-file=credentials="${dir}/aws/credentials"

  openssl genrsa -out "${dir}/vault.key" 2048 2>/dev/null
  cat > "${dir}/vault-csr.conf" <<CONF
[req]
default_bits = 2048
prompt = no
encrypt_key = yes
default_md = sha256
distinguished_name = kubelet_serving
req_extensions = v3_req
[ kubelet_serving ]
O = system:nodes
CN = system:node:*.${ns}.svc.${CLUSTER_DOMAIN}
[ v3_req ]
basicConstraints = CA:FALSE
keyUsage = nonRepudiation, digitalSignature, keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth, clientAuth
subjectAltName = @alt_names
[alt_names]
DNS.1 = *.${svc}
DNS.2 = *.${svc}.${ns}.svc.${CLUSTER_DOMAIN}
DNS.3 = *.${ns}
DNS.4 = *.${ns}.svc.${CLUSTER_DOMAIN}
IP.1 = 127.0.0.1
CONF
  openssl req -new -key "${dir}/vault.key" -out "${dir}/vault.csr" -config "${dir}/vault-csr.conf"
  k delete csr "${ns}.svc" --ignore-not-found
  k apply -f - <<YAML
apiVersion: certificates.k8s.io/v1
kind: CertificateSigningRequest
metadata:
  name: ${ns}.svc
spec:
  signerName: kubernetes.io/kubelet-serving
  expirationSeconds: 8640000
  request: $(base64 < "${dir}/vault.csr" | tr -d '\n')
  usages: ["digital signature", "key encipherment", "server auth"]
YAML
  k certificate approve "${ns}.svc"
  local cert=""
  for _ in $(seq 1 30); do
    cert=$(k get csr "${ns}.svc" -o jsonpath='{.status.certificate}')
    [ -n "${cert}" ] && break; sleep 1
  done
  [ -n "${cert}" ] || { echo "CSR ${ns}.svc approved but not issued" >&2; exit 1; }
  printf '%s' "${cert}" | openssl base64 -d -A -out "${dir}/vault.crt"
  [ "$(openssl x509 -in "${dir}/vault.crt" -noout -modulus)" = "$(openssl rsa -in "${dir}/vault.key" -noout -modulus)" ] \
    || { echo "certificate does not match key" >&2; exit 1; }
  k config view --raw --minify --flatten -o jsonpath='{.clusters[].cluster.certificate-authority-data}' \
    | base64 -d > "${dir}/vault.ca"
  k -n "${ns}" create secret generic vault-ha-tls \
    --from-file=vault.key="${dir}/vault.key" --from-file=vault.crt="${dir}/vault.crt" --from-file=vault.ca="${dir}/vault.ca"
  k -n "${ns}" create secret generic vault-ent-license --from-literal="license=$(cat "${LICENSE_FILE}")"

  say "${role}: Helm release ${ns} (vault-enterprise:${VAULT_TAG})"
  cat > "${dir}/overrides.yaml" <<YAML
global:
  enabled: true
  tlsDisable: false
csi:
  enabled: false
injector:
  enabled: false
server:
  image:
    repository: docker.io/hashicorp/vault-enterprise
    tag: ${VAULT_TAG}
  enterpriseLicense:
    secretName: vault-ent-license
  extraEnvironmentVars:
    VAULT_CACERT: /vault/userconfig/vault-ha-tls/vault.ca
    VAULT_TLSCERT: /vault/userconfig/vault-ha-tls/vault.crt
    VAULT_TLSKEY: /vault/userconfig/vault-ha-tls/vault.key
    AWS_SHARED_CREDENTIALS_FILE: /vault/userconfig/aws/credentials
  volumes:
    - name: userconfig-vault-ha-tls
      secret: {defaultMode: 420, secretName: vault-ha-tls}
    - name: aws-shared-credentials
      secret: {defaultMode: 256, secretName: vault-aws-creds}
  volumeMounts:
    - {mountPath: /vault/userconfig/vault-ha-tls, name: userconfig-vault-ha-tls, readOnly: true}
    - {mountPath: /vault/userconfig/aws, name: aws-shared-credentials, readOnly: true}
  standalone:
    enabled: false
  affinity: ""
  ha:
    enabled: true
    replicas: 3
    raft:
      enabled: true
      setNodeId: true
      config: |
        ui = true
        cluster_name = "${name}"
        listener "tcp" {
          tls_disable = 0
          address = "[::]:8200"
          cluster_address = "[::]:8201"
          tls_cert_file = "/vault/userconfig/vault-ha-tls/vault.crt"
          tls_key_file  = "/vault/userconfig/vault-ha-tls/vault.key"
          tls_client_ca_file = "/vault/userconfig/vault-ha-tls/vault.ca"
        }
        storage "raft" {
          path = "/vault/data"
          retry_join {
            auto_join             = "provider=k8s namespace=${ns} label_selector=\"component=server,app.kubernetes.io/name=vault\""
            auto_join_scheme      = "https"
            leader_ca_cert_file   = "/vault/userconfig/vault-ha-tls/vault.ca"
            leader_tls_servername = "${ns}-0.${svc}"
          }
        }
        # AssumeRole is driven by [vault-bootstrap] in the credentials file. On
        # 2.2.2 (awsutil v2.1.2) role_arn in this stanza sends an empty ExternalID
        # and STS rejects it, so the stanza only names the profile and the key.
        seal "awskms" {
          region                = "${REGION}"
          kms_key_id            = "${kms_key_id}"
          shared_creds_filename = "/vault/userconfig/aws/credentials"
          shared_creds_profile  = "vault-bootstrap"
        }
        disable_mlock = true
        service_registration "kubernetes" {}
YAML
  helm --kube-context "${CTX}" upgrade --install "${ns}" hashicorp/vault -n "${ns}" --values "${dir}/overrides.yaml" >/dev/null
  k -n "${ns}" wait pod "${ns}-0" --for=jsonpath='{.status.phase}'=Running --timeout=300s
  for _ in $(seq 1 60); do
    k -n "${ns}" exec "${ns}-0" -- vault status -format=json 2>/dev/null | grep -q '"initialized"' && break; sleep 3
  done

  say "${role}: initialise (recovery keys) and wait for the Raft cluster"
  if ! k -n "${ns}" exec "${ns}-0" -- vault status -format=json 2>/dev/null | grep -q '"initialized": true'; then
    k -n "${ns}" exec "${ns}-0" -- vault operator init -recovery-shares=1 -recovery-threshold=1 -format=json \
      > "${dir}/vault-init.json"
  fi
  [ -s "${dir}/vault-init.json" ] || { echo "no ${dir}/vault-init.json for an initialised cluster" >&2; exit 1; }
  k -n "${ns}" wait pod -l app.kubernetes.io/name=vault,component=server --for=condition=Ready --timeout=300s
  k -n "${ns}" exec "${ns}-0" -- vault status | grep -E 'Seal Type|Sealed|Version|HA Mode'
}

setup_replication() {
  say "DR replication: ${PRI_NS} (primary) -> ${DR_NS} (secondary)"
  if [ "$(pv read -field=mode sys/replication/dr/status)" = "disabled" ]; then
    pv write -f sys/replication/dr/primary/enable \
      primary_cluster_addr="https://${PRI_NS}-active.${PRI_NS}.svc.${CLUSTER_DOMAIN}:8201"
    sleep 15
  fi
  for _ in $(seq 1 30); do
    [ "$(pv read -field=mode sys/replication/dr/status 2>/dev/null || true)" = "primary" ] && break; sleep 2
  done
  if [ "$(k -n "${DR_NS}" exec "${DR_NS}-0" -- vault read -field=mode sys/replication/dr/status 2>/dev/null || true)" != "secondary" ]; then
    pv write sys/replication/dr/primary/revoke-secondary id=dr23 >/dev/null 2>&1 || true
    local token; token=$(pv write -format=json sys/replication/dr/primary/secondary-token id=dr23 | jq -r .wrap_info.token)
    # Wipes the DR cluster's storage and replaces it with the primary's data.
    vault_in dr "${DR_NS}" "${DR_NS}-0" write sys/replication/dr/secondary/enable \
      primary_api_addr="https://${PRI_NS}-active.${PRI_NS}.svc.${CLUSTER_DOMAIN}:8200" \
      ca_file=/vault/userconfig/vault-ha-tls/vault.ca token="${token}"
    sleep 30
    # The followers seal ("encryption keys have changed"); a restart auto-unseals them.
    k -n "${DR_NS}" delete pod "${DR_NS}-1" "${DR_NS}-2"
    sleep 5
  fi
  k -n "${DR_NS}" wait pod -l app.kubernetes.io/name=vault,component=server --for=condition=Ready --timeout=300s
  for _ in $(seq 1 40); do
    [ "$(k -n "${DR_NS}" exec "${DR_NS}-0" -- vault read -field=state sys/replication/dr/status 2>/dev/null || true)" = "stream-wals" ] && break
    sleep 5
  done
  k -n "${DR_NS}" exec "${DR_NS}-0" -- vault read sys/replication/dr/status | grep -E 'mode|state|last_remote_wal'
}

setup_workload() {
  say "Workload: KV mounts, OpenLDAP, PostgreSQL, kms-netcheck"
  pv secrets list -format=json | jq -e '."kv/"' >/dev/null || pv secrets enable kv
  pv secrets list -format=json | jq -e '."kv-sealwrap/"' >/dev/null || pv secrets enable -path=kv-sealwrap -seal-wrap kv

  k create namespace "${DEPS_NS}" --dry-run=client -o yaml | k apply -f -
  k -n "${DEPS_NS}" apply -f - <<'YAML'
apiVersion: v1
kind: Service
metadata: {name: openldap, labels: {app.kubernetes.io/name: openldap}}
spec:
  ports: [{name: tcp-ldap, port: 389, targetPort: tcp-ldap}]
  selector: {app.kubernetes.io/name: openldap}
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: openldap, labels: {app.kubernetes.io/name: openldap}}
spec:
  replicas: 1
  selector: {matchLabels: {app.kubernetes.io/name: openldap}}
  template:
    metadata: {labels: {app.kubernetes.io/name: openldap}}
    spec:
      containers:
        - name: openldap
          image: osixia/openldap:1.4.0
          env:
            - {name: LDAP_ORGANISATION, value: learn}
            - {name: LDAP_DOMAIN, value: learn.example}
            - {name: LDAP_ADMIN_PASSWORD, value: 2LearnVault}
          ports: [{name: tcp-ldap, containerPort: 389}]
---
apiVersion: v1
kind: Service
metadata: {name: postgresql-dev, labels: {app.kubernetes.io/name: postgresql-dev}}
spec:
  ports: [{name: tcp-postgres, port: 5432, targetPort: 5432}]
  selector: {app.kubernetes.io/name: postgresql-dev}
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: postgresql-dev, labels: {app.kubernetes.io/name: postgresql-dev}}
spec:
  replicas: 1
  selector: {matchLabels: {app.kubernetes.io/name: postgresql-dev}}
  template:
    metadata: {labels: {app.kubernetes.io/name: postgresql-dev}}
    spec:
      containers:
        - name: postgres
          image: postgres:16
          env:
            - {name: POSTGRES_PASSWORD, value: StrongPassword}
            - {name: POSTGRES_DB, value: app_db}
          ports: [{containerPort: 5432}]
YAML
  k -n "${DEPS_NS}" wait --for=condition=Available deployment/openldap deployment/postgresql-dev --timeout=300s
  sleep 10
  local ldap_pod pg_pod out rc
  ldap_pod=$(k -n "${DEPS_NS}" get pods -l app.kubernetes.io/name=openldap -o jsonpath='{.items[0].metadata.name}')
  set +e
  out=$(k -n "${DEPS_NS}" exec -i "${ldap_pod}" -- ldapadd -h 127.0.0.1 -p 389 -w 2LearnVault -cxD "cn=admin,dc=learn,dc=example" 2>&1 <<'LDIF'
dn: ou=groups,dc=learn,dc=example
objectClass: organizationalunit
objectClass: top
ou: groups

dn: ou=users,dc=learn,dc=example
objectClass: organizationalunit
objectClass: top
ou: users

dn: cn=dev,ou=groups,dc=learn,dc=example
objectClass: groupofnames
objectClass: top
cn: dev
member: cn=alice,ou=users,dc=learn,dc=example

dn: cn=alice,ou=users,dc=learn,dc=example
objectClass: person
objectClass: top
sn: alice
memberOf: cn=dev,ou=groups,dc=learn,dc=example
userPassword: alice
LDIF
)
  rc=$?
  set -e
  if [ "${rc}" -ne 0 ] && ! echo "${out}" | grep -qi 'Already exists'; then echo "${out}" >&2; exit "${rc}"; fi
  pg_pod=$(k -n "${DEPS_NS}" get pods -l app.kubernetes.io/name=postgresql-dev -o jsonpath='{.items[0].metadata.name}')
  for _ in $(seq 1 30); do k -n "${DEPS_NS}" exec "${pg_pod}" -- pg_isready -U postgres >/dev/null 2>&1 && break; sleep 2; done
  k -n "${DEPS_NS}" exec "${pg_pod}" -- psql -U postgres -c 'CREATE ROLE "ro" NOINHERIT;' 2>&1 | grep -v 'already exists' || true
  k -n "${DEPS_NS}" exec "${pg_pod}" -- psql -U postgres -c 'GRANT SELECT ON ALL TABLES IN SCHEMA public TO "ro";' >/dev/null
  k -n "${DEPS_NS}" exec "${pg_pod}" -- psql -U postgres \
    -c "CREATE ROLE \"static-app\" WITH LOGIN PASSWORD 'initial-password';" 2>&1 | grep -v 'already exists' || true

  pv auth list -format=json | jq -e '."ldap/"' >/dev/null || pv auth enable ldap
  pv write auth/ldap/config \
    binddn="cn=admin,dc=learn,dc=example" bindpass="2LearnVault" \
    url="ldap://openldap.${DEPS_NS}.svc.${CLUSTER_DOMAIN}:389" \
    userdn="ou=users,dc=learn,dc=example" userattr="cn" userfilter="({{.UserAttr}}={{.Username}})" \
    groupdn="dc=learn,dc=example" groupfilter="(&(objectClass=person)(cn={{.Username}}))" groupattr="memberOf" \
    insecure_tls=true
  printf 'path "kv/*" {\n  capabilities = ["read", "list"]\n}\n' | pv policy write dev -
  pv write auth/ldap/groups/dev policies=dev
  pv secrets list -format=json | jq -e '."database/"' >/dev/null || pv secrets enable database
  pv write database/config/postgresql plugin_name=postgresql-database-plugin \
    connection_url="postgresql://{{username}}:{{password}}@postgresql-dev.${DEPS_NS}.svc.${CLUSTER_DOMAIN}:5432/postgres?sslmode=disable" \
    allowed_roles="*" username="postgres" password="StrongPassword"
  pv write database/roles/readonly db_name=postgresql default_ttl=60s max_ttl=200s \
    creation_statements="CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}' INHERIT; GRANT ro TO \"{{name}}\";"
  pv write database/static-roles/static-app db_name=postgresql username=static-app rotation_period=24h

  # AWS CLI pod per Vault namespace, with the same bootstrap credentials, for the
  # independent AssumeRole + KMS checks made by kms_watch.py.
  local ns
  for ns in "${PRI_NS}" "${DR_NS}"; do
    k -n "${ns}" apply -f - <<'YAML'
apiVersion: apps/v1
kind: Deployment
metadata: {name: kms-netcheck, labels: {app.kubernetes.io/name: kms-netcheck}}
spec:
  replicas: 1
  selector: {matchLabels: {app.kubernetes.io/name: kms-netcheck}}
  template:
    metadata: {labels: {app.kubernetes.io/name: kms-netcheck}}
    spec:
      containers:
        - name: awscli
          image: public.ecr.aws/aws-cli/aws-cli:2.22.35
          command: ["sleep", "infinity"]
          env:
            - {name: AWS_SHARED_CREDENTIALS_FILE, value: /creds/credentials}
            - {name: AWS_DEFAULT_REGION, value: eu-west-3}
          volumeMounts: [{name: creds, mountPath: /creds, readOnly: true}]
      volumes:
        - name: creds
          secret: {secretName: vault-aws-creds, defaultMode: 256}
YAML
    k -n "${ns}" rollout status deployment/kms-netcheck --timeout=300s
  done
}

cmd_up() {
  for f in "${LICENSE_FILE}" "${AWS_ADMIN_CSV}"; do [ -r "$f" ] || { echo "missing $f" >&2; exit 1; }; done
  ensure_minikube
  deploy_cluster primary "${PRI_NS}" "${PRI_SUFFIX}" "vault23-primary"
  deploy_cluster dr "${DR_NS}" "${DR_SUFFIX}" "vault23-dr-secondary"
  setup_replication
  setup_workload
  say "Ready. Start the tests with: $0 test-start"
}

PROBES="probe_kv probe_transit probe_transit_sealwrap probe_config monitor_logs kms_watch"

cmd_test_start() {
  local duration=${1:-28800}
  mkdir -p "${RUN}/logs"
  cd "${HERE}"
  for p in ${PROBES}; do
    if [ -f "${RUN}/${p}.pid" ] && kill -0 "$(cat "${RUN}/${p}.pid")" 2>/dev/null; then
      echo "${p} is already running; run '$0 test-stop' first" >&2; exit 1
    fi
  done
  launch() { local name=$1; shift; nohup caffeinate -i "${PYTHON}" -u "$@" >> "${RUN}/${name}.log" 2>&1 & echo $! > "${RUN}/${name}.pid"; }
  launch monitor_logs monitor_logs.py "$((duration + 120))" "${RUN}/logs"
  launch kms_watch kms_watch.py "$((duration + 120))"
  launch probe_kv probe_kv.py "${duration}" 60
  launch probe_transit probe_transit.py "${duration}" 60
  launch probe_transit_sealwrap probe_transit.py "${duration}" 60 transit-dr-sealwrap sealwrap
  launch probe_config probe_config.py "${duration}" 60
  sleep 6
  echo "started for ${duration}s; logs in ${RUN}"
  echo "clock behind host: primary $(clock_skew "${PRI_NS}")s, DR $(clock_skew "${DR_NS}")s"
  echo "Keep the Mac awake: plugged in, lid open (or an external display). If it sleeps, the VM"
  echo "clock stops, the STS token expires unrenewed and seal-wrapped writes fail until it resyncs."
}

cmd_test_stop() {
  for p in ${PROBES}; do
    [ -f "${RUN}/${p}.pid" ] && kill "$(cat "${RUN}/${p}.pid")" 2>/dev/null && echo "stopped ${p}"
    rm -f "${RUN}/${p}.pid"
  done
  pkill -f "kubectl --context ${CTX} -n ${PRI_NS}.* logs -f" 2>/dev/null || true
  pkill -f "kubectl --context ${CTX} -n ${DR_NS}.* logs -f" 2>/dev/null || true
}

cmd_status() {
  echo "now: $(date -u +%FT%TZ)   clock behind host: primary $(clock_skew "${PRI_NS}")s, DR $(clock_skew "${DR_NS}")s"
  local p alive
  for p in probe_kv probe_transit probe_transit_sealwrap probe_config; do
    [ -f "${RUN}/${p}.log" ] || continue
    alive=no; kill -0 "$(cat "${RUN}/${p}.pid" 2>/dev/null)" 2>/dev/null && alive=yes
    echo "${p}: alive=${alive} OK=$(grep -c ' OK ' "${RUN}/${p}.log") FAIL=$(grep -c ' FAIL ' "${RUN}/${p}.log") last=$(tail -1 "${RUN}/${p}.log" | cut -c1-20)"
  done
  if ls "${RUN}"/probe_*.log >/dev/null 2>&1; then
    echo "failures by cause: seal/KMS=$(cat "${RUN}"/probe_*.log | grep ' FAIL ' | grep -ciE 'seal wrap|kms|ExpiredToken') raft/leader=$(cat "${RUN}"/probe_*.log | grep ' FAIL ' | grep -ciE 'leadership lost|not active')"
    { grep -h ' FAIL ' "${RUN}"/probe_*.log || true; } | tail -2 | cut -c1-300
    echo "replication: $(grep ' WAL ' "${RUN}/probe_kv.log" | tail -1 | cut -c22-140)"
    echo "samples not in stream-wals: $(grep ' WAL ' "${RUN}/probe_kv.log" | grep -vc stream-wals)"
  fi
  [ ! -f "${RUN}/kms_watch.log" ] || echo "kms_watch: triggers=$(grep -c ' TRIGGER ' "${RUN}/kms_watch.log") reachable=$(grep -c KMS-REACHABLE "${RUN}/kms_watch.log") failed=$(grep -c KMS-CHECK-FAILED "${RUN}/kms_watch.log")"
  local ns i
  for ns in "${PRI_NS}" "${DR_NS}"; do for i in 0 1 2; do
    echo "${ns}-${i}: $(k -n "${ns}" exec "${ns}-${i}" -- vault status 2>&1 | grep -E '^Sealed|HA Mode' | awk '{print $1,$2,$3}' | tr '\n' ' ')"
  done; done
  for f in "${RUN}"/logs/*.log; do
    [ ! -f "$f" ] || echo "$(basename "$f" .log): ERROR=$(grep -c '\[ERROR\]' "$f") WARN=$(grep -c '\[WARN\]' "$f") ExpiredToken=$(grep -c ExpiredToken "$f") merkle-restarts=$(grep -c 'guard mis-match' "$f")"
  done
}

cmd_heal() {
  local ns i skew
  for ns in "${PRI_NS}" "${DR_NS}"; do
    skew=$(clock_skew "${ns}")
    if [ "${skew#-}" -gt 60 ]; then
      echo "${ns}: clock is ${skew}s behind the host; a restarted node could not reach KMS. Wait for the VM clock to resync."
      continue
    fi
    for i in 0 1 2; do
      if k -n "${ns}" exec "${ns}-${i}" -- vault status 2>&1 | grep -qE '^Sealed +true'; then
        echo "restarting sealed node ${ns}-${i}"
        k -n "${ns}" delete pod "${ns}-${i}"
      fi
    done
    k -n "${ns}" wait pod -l app.kubernetes.io/name=vault,component=server --for=condition=Ready --timeout=300s
  done
}

cmd_down() {
  cmd_test_stop || true
  if [ -d "${RUN}" ] && ls "${RUN}"/*.log >/dev/null 2>&1; then
    mkdir -p "${HERE}/results"
    tar czf "${HERE}/results/run-$(date -u +%Y%m%dT%H%MZ).tar.gz" -C "${DRTEST_WORKDIR}" run
    echo "run logs archived in ${HERE}/results"
  fi
  if minikube status -p "${PROFILE}" >/dev/null 2>&1; then
    say "Kubernetes"
    [ -s "${DRTEST_WORKDIR}/primary/vault-init.json" ] && pv write -f sys/replication/dr/primary/disable >/dev/null 2>&1 || true
    local ns
    for ns in "${DR_NS}" "${PRI_NS}"; do
      helm --kube-context "${CTX}" uninstall "${ns}" -n "${ns}" 2>/dev/null || true
      k delete namespace "${ns}" --ignore-not-found --wait=true --timeout=240s || true
      k delete csr "${ns}.svc" --ignore-not-found || true
    done
    k delete namespace "${DEPS_NS}" --ignore-not-found --wait=true --timeout=240s || true
    if [ "${1:-}" = "--delete-profile" ]; then minikube delete -p "${PROFILE}"; fi
  fi
  say "AWS"
  "${PYTHON}" "${HERE}/aws_env.py" delete "${DR_SUFFIX}"
  "${PYTHON}" "${HERE}/aws_env.py" delete "${PRI_SUFFIX}"
  rm -rf "${DRTEST_WORKDIR}"
  echo "removed ${DRTEST_WORKDIR} (root tokens, recovery keys and AWS keys of the deleted clusters)"
}

case "${1:-help}" in
  up)          cmd_up ;;
  test-start)  cmd_test_start "${2:-}" ;;
  test-stop)   cmd_test_stop ;;
  status)      cmd_status ;;
  watch)       shift; exec "${PYTHON}" "${HERE}/watch.py" "$@" ;;
  heal)        cmd_heal ;;
  down)        cmd_down "${2:-}" ;;
  *)           sed -n '2,34p' "$0" | sed 's/^# \{0,1\}//' ;;
esac
