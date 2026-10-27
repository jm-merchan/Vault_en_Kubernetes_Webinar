#!/usr/bin/env bash
# Re-run the Transit vault-benchmark matrix with the audit device and
# Transit tune each scenario is meant to measure.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
set -a
# shellcheck disable=SC1091
source /tmp/vault/config.env
set +a
unset VAULT_NAMESPACE || true

RUNS="$ROOT/vault-benchmark/runs"
mkdir -p "$RUNS"

echo "=== suite start $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

clear_non_hmac() {
  printf '%s\n' '{"audit_non_hmac_response_keys":[]}' | vault write sys/mounts/transit/tune -
}

tune_json() {
  vault read -format=json sys/mounts/transit/tune
}

assert_no_non_hmac() {
  tune_json | jq -e '
    ((.data.audit_non_hmac_response_keys // []) | length == 0)
    and ((.data.audit_non_hmac_request_keys // []) | length == 0)
  ' >/dev/null
}

assert_hmac_keys() {
  tune_json | jq -e '
    (.data.audit_non_hmac_response_keys | sort) == ["batch_results", "ciphertext"]
  ' >/dev/null
}

apply_none() {
  vault audit disable file 2>/dev/null || true
  clear_non_hmac
}

apply_full() {
  clear_non_hmac
  vault audit disable file 2>/dev/null || true
  vault audit enable file file_path=/vault/audit/benchmark-audit.json log_raw=false
}

apply_noreq() {
  clear_non_hmac
  vault audit disable file 2>/dev/null || true
  vault audit enable \
    file \
    file_path=/vault/audit/benchmark-no-request-data.json \
    log_raw=false \
    exclude='[{"condition":"\"/request/mount_type\" == transit","fields":["/request/data"]}]'
}

apply_nohmac() {
  vault audit disable file 2>/dev/null || true
  vault audit enable \
    file \
    file_path=/vault/audit/benchmark-no-request-data.json \
    log_raw=false \
    exclude='[{"condition":"\"/request/mount_type\" == transit","fields":["/request/data"]}]'
  vault secrets tune \
    -audit-non-hmac-response-keys=ciphertext \
    -audit-non-hmac-response-keys=batch_results \
    transit/
}

assert_none() {
  local audit
  audit="$(vault audit list -detailed 2>&1 || true)"
  grep -q "No audit devices are enabled" <<<"$audit"
  assert_no_non_hmac
}

assert_full() {
  local audit
  audit="$(vault audit list -detailed)"
  grep -q "benchmark-audit.json" <<<"$audit"
  grep -q "log_raw=false" <<<"$audit"
  if grep -q "exclude=" <<<"$audit"; then
    echo "full audit unexpectedly has exclude" >&2
    return 1
  fi
  assert_no_non_hmac
}

assert_noreq() {
  local audit
  audit="$(vault audit list -detailed)"
  grep -q "benchmark-no-request-data.json" <<<"$audit"
  grep -q "log_raw=false" <<<"$audit"
  grep -q '/request/data' <<<"$audit"
  assert_no_non_hmac
}

assert_nohmac() {
  local audit
  audit="$(vault audit list -detailed)"
  grep -q "benchmark-no-request-data.json" <<<"$audit"
  grep -q "log_raw=false" <<<"$audit"
  grep -q '/request/data' <<<"$audit"
  assert_hmac_keys
}

save_setup() {
  local scenario="$1"
  {
    echo "--- audit ---"
    vault audit list -detailed 2>&1 || true
    echo "--- transit tune ---"
    vault read sys/mounts/transit/tune
  } | tee "$RUNS/$scenario/setup.txt"
}

TESTS=(
  "vb-transit-unit.hcl unit"
  "vb-transit-50.hcl batch-50"
  "vb-transit-100.hcl batch-100"
  "vb-transit-250.hcl batch-250"
  "vb-transit-500.hcl batch-500"
  "vb-transit-750.hcl batch-750"
  "vb-transit-1000.hcl batch-1000"
  "vb-transit-9000.hcl batch-9000"
)

failed=0

run_scenario() {
  local scenario="$1"
  local apply="$2"
  local assert="$3"
  mkdir -p "$RUNS/$scenario"
  echo
  echo "======== $scenario $(date -u +%H:%M:%SZ) ========"
  "$apply"
  "$assert"
  save_setup "$scenario"
  local spec hcl label workers
  for spec in "${TESTS[@]}"; do
    hcl="${spec%% *}"
    label="${spec##* }"
    workers="$(awk '/^workers/{print $3; exit}' "vault-benchmark/$hcl")"
    echo "---- $scenario $label workers=$workers ----"
    if [[ "$label" == "unit" && "$workers" != "50" ]]; then
      echo "unit workers must be 50, got $workers" >&2
      failed=1
      continue
    fi
    if [[ "$label" != "unit" && "$workers" != "10" ]]; then
      echo "$label workers must be 10, got $workers" >&2
      failed=1
      continue
    fi
    set +e
    bash ./vault-benchmark/run-vb-job.sh "vault-benchmark/$hcl" "$label" \
      | tee "$RUNS/$scenario/${label}.txt"
    local rc=${PIPESTATUS[0]}
    set -e
    if [[ "$rc" -ne 0 ]]; then
      echo "FAILED $scenario $label rc=$rc" >&2
      failed=1
    fi
    cp -f "vault-benchmark/results-${label}.txt" "$RUNS/$scenario/results-${label}.txt" 2>/dev/null || true
  done
}

run_scenario none apply_none assert_none
run_scenario full apply_full assert_full
run_scenario noreq apply_noreq assert_noreq
run_scenario nohmac apply_nohmac assert_nohmac

# Standalone reads that the notebook shows after the no-audit and no-HMAC setup.
{
  vault read sys/mounts/transit/tune
} | tee "$RUNS/none/tune-only.txt" >/dev/null || true

# none tune was cleared at the start; nohmac is the live state now.
# Re-read none from the saved setup is not a live read. Capture none tune
# was already stored in setup.txt. The dedicated tune cell output is the
# "--- transit tune ---" section, rebuilt below from that snapshot only if
# we did not keep a live file. none/tune-only.txt above is the FINAL tune
# (nohmac). Rewrite none/tune-only from the none setup snapshot instead.
awk 'BEGIN{p=0} /^--- transit tune ---$/{p=1; next} p' "$RUNS/none/setup.txt" \
  | tee "$RUNS/none/tune-only.txt" >/dev/null
{
  echo "--- audit ---"
  vault audit list -detailed
  echo "--- transit tune ---"
  vault read sys/mounts/transit/tune
} | tee "$RUNS/nohmac/live.txt"

echo "=== suite end $(date -u +%Y-%m-%dT%H:%M:%SZ) failed=$failed ==="
exit "$failed"
