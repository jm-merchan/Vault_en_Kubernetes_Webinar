#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
python3 "$ROOT/setup.py"
for deployment in vbb-prometheus vbb-node-exporter vbb-host-probe vbb-socket-0 vbb-socket-1 vbb-socket-2; do
  kubectl --context "${KUBE_CONTEXT:-workshop-k8s}" -n "${VB_NAMESPACE:-vault}" rollout status "deployment/$deployment" --timeout=180s
done
# Only start our local forward if Prometheus is not reachable already.
if ! curl -fsS http://127.0.0.1:19090/-/ready >/dev/null; then
  mkdir -p /tmp/vault/vbb-observability
  nohup kubectl --context "${KUBE_CONTEXT:-workshop-k8s}" -n "${VB_NAMESPACE:-vault}" port-forward service/vbb-prometheus 19090:9090 > /tmp/vault/vbb-observability/prometheus-forward.log 2>&1 &
  echo "$!" > /tmp/vault/vbb-observability/prometheus-forward.pid
fi

for attempt in {1..30}; do
  if curl -fsS http://127.0.0.1:19090/-/ready >/dev/null 2>&1; then exit 0; fi
  sleep 1
done
echo "Prometheus port-forward did not become ready" >&2
exit 1
