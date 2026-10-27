#!/usr/bin/env bash
# Run patched vault-benchmark as a Job against Service vault (all HA nodes).
# Usage: run-vb-job.sh <hcl> <label>
set -euo pipefail

HCL="${1:?hcl path}"
LABEL="${2:?label}"

ROOT="$(cd "$(dirname "$0")" && pwd)"
WORKDIR="${WORKDIR:-/tmp/vault}"
OUT="${ROOT}/results-${LABEL}.txt"
NS="${VB_NAMESPACE:-vault}"
JOB="vb-${LABEL}"
CM="vb-hcl-${LABEL}"
SECRET="${VB_SECRET:-vault-benchmark-creds}"
IMAGE="${VB_IMAGE:-vault-benchmark:demo}"
PROFILE="${MINIKUBE_PROFILE:-workshop-k8s}"
KCTX="${KUBE_CONTEXT:-$PROFILE}"
VAULT_SVC_ADDR="${VAULT_SVC_ADDR:-https://vault.vault.svc.cluster.local:8200}"

if [ ! -f "$HCL" ]; then
  echo "Missing $HCL" >&2
  exit 1
fi
if [ -z "${VAULT_TOKEN:-}" ]; then
  echo "VAULT_TOKEN is required (source config.env first)." >&2
  exit 1
fi
CACERT="${VAULT_CACERT:-$WORKDIR/vault.ca}"
if [ ! -f "$CACERT" ]; then
  echo "Missing CA cert: $CACERT" >&2
  exit 1
fi

ENC_ITEMS=$(awk '/test "transit_encrypt"/ {p=1} /test "transit_decrypt"/ {p=0} p && /plaintext =/ {c++} END {print c+0}' "$HCL")
[ "${ENC_ITEMS}" -gt 0 ] || ENC_ITEMS=1
DEC_ITEMS=1

echo "=== vault-benchmark ${LABEL} as Job/${JOB}  (encrypt x${ENC_ITEMS} / decrypt x${DEC_ITEMS} per request) ==="
echo "Target: ${VAULT_SVC_ADDR}  (Service vault → active + performance standbys)"

kubectl --context "$KCTX" -n "$NS" create secret generic "$SECRET" \
  --from-literal=token="$VAULT_TOKEN" \
  --from-file=ca.pem="$CACERT" \
  --dry-run=client -o yaml | kubectl --context "$KCTX" apply -f - >/dev/null

# Avoid `kubectl apply`: last-applied-configuration annotation caps at 256KiB
# and the batch-9000 HCL (~500KiB) exceeds that.
kubectl --context "$KCTX" -n "$NS" delete configmap "$CM" --ignore-not-found --wait=true >/dev/null
kubectl --context "$KCTX" -n "$NS" create configmap "$CM" \
  --from-file=vb.hcl="$HCL" >/dev/null
kubectl --context "$KCTX" -n "$NS" label configmap "$CM" \
  app=vault-benchmark "benchmark=${LABEL}" --overwrite >/dev/null

kubectl --context "$KCTX" -n "$NS" delete job "$JOB" --ignore-not-found --wait=true >/dev/null

kubectl --context "$KCTX" -n "$NS" apply -f - >/dev/null <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: ${JOB}
  labels:
    app: vault-benchmark
    benchmark: ${LABEL}
spec:
  backoffLimit: 0
  ttlSecondsAfterFinished: 900
  template:
    metadata:
      labels:
        app: vault-benchmark
        benchmark: ${LABEL}
    spec:
      restartPolicy: Never
      containers:
        - name: vault-benchmark
          image: ${IMAGE}
          imagePullPolicy: Never
          env:
            - name: VAULT_ADDR
              value: ${VAULT_SVC_ADDR}
            - name: VAULT_TOKEN
              valueFrom:
                secretKeyRef:
                  name: ${SECRET}
                  key: token
            - name: VAULT_CACERT
              value: /creds/ca.pem
          args: ["run", "-config=/config/vb.hcl"]
          volumeMounts:
            - name: config
              mountPath: /config
              readOnly: true
            - name: creds
              mountPath: /creds
              readOnly: true
          resources:
            requests:
              cpu: "250m"
              memory: 256Mi
            limits:
              cpu: "2"
              memory: 1Gi
      volumes:
        - name: config
          configMap:
            name: ${CM}
        - name: creds
          secret:
            secretName: ${SECRET}
EOF

# Stream logs as soon as the pod exists; then wait for Job completion.
POD=""
for _ in $(seq 1 60); do
  POD=$(kubectl --context "$KCTX" -n "$NS" get pods -l job-name="$JOB" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
  [ -n "$POD" ] && break
  sleep 1
done
if [ -z "$POD" ]; then
  echo "Job pod did not appear." >&2
  kubectl --context "$KCTX" -n "$NS" describe job "$JOB" >&2 || true
  exit 1
fi

kubectl --context "$KCTX" -n "$NS" wait --for=condition=Ready "pod/$POD" --timeout=120s >/dev/null 2>&1 || true
kubectl --context "$KCTX" -n "$NS" logs -f "$POD" 2>&1 | tee "$OUT" &
LOG_PID=$!

set +e
kubectl --context "$KCTX" -n "$NS" wait --for=condition=complete "job/$JOB" --timeout=300s
WAIT_RC=$?
if [ "$WAIT_RC" -ne 0 ]; then
  kubectl --context "$KCTX" -n "$NS" wait --for=condition=failed "job/$JOB" --timeout=10s >/dev/null 2>&1 || true
fi
set -e

wait "$LOG_PID" 2>/dev/null || true

if [ "$WAIT_RC" -ne 0 ]; then
  echo "Job ${JOB} did not complete successfully." >&2
  kubectl --context "$KCTX" -n "$NS" describe job "$JOB" >&2 || true
  kubectl --context "$KCTX" -n "$NS" logs "$POD" >&2 || true
  exit 1
fi

echo
echo "Saved ${OUT}"
echo
echo "=== Items (successful requests × items/request) ==="
awk -v ei="$ENC_ITEMS" -v di="$DEC_ITEMS" '
  $1 ~ /encrypt$/ && $2 ~ /^[0-9]+$/ {
    succ = $8; gsub(/%/, "", succ)
    items = $2 * ei * (succ / 100)
    ips = $4 * ei
    printf "  %-16s  req=%s  ok=%s  items=%.0f  items/s=%.0f  (x%d / request)\n", $1, $2, $8, items, ips, ei
  }
  $1 ~ /decrypt$/ && $2 ~ /^[0-9]+$/ {
    succ = $8; gsub(/%/, "", succ)
    items = $2 * di * (succ / 100)
    ips = $4 * di
    printf "  %-16s  req=%s  ok=%s  items=%.0f  items/s=%.0f  (x%d / request)\n", $1, $2, $8, items, ips, di
  }
' "$OUT"
