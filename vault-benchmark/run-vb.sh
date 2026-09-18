#!/usr/bin/env bash
# Run vault-benchmark, print the report, save it, and extrapolate to crypto items.
# Usage: run-vb.sh <hcl> <label>
set -euo pipefail

HCL="${1:?hcl path}"
LABEL="${2:?label}"

ROOT="$(cd "$(dirname "$0")" && pwd)"
WORKDIR="${WORKDIR:-/tmp/vault}"
VB="${WORKDIR}/vault-benchmark"
OUT="${ROOT}/results-${LABEL}.txt"

if [ ! -x "$VB" ]; then
  echo "Missing $VB — run the download cell first." >&2
  exit 1
fi
if [ ! -f "$HCL" ]; then
  echo "Missing $HCL" >&2
  exit 1
fi

ENC_ITEMS=$(grep -c 'plaintext =' "$HCL" || true)
[ "${ENC_ITEMS}" -gt 0 ] || ENC_ITEMS=1
DEC_ITEMS=1

echo "=== vault-benchmark ${LABEL}  (encrypt x${ENC_ITEMS} / decrypt x${DEC_ITEMS} per request) ==="
"$VB" run -config="$HCL" 2>&1 | tee "$OUT"

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
