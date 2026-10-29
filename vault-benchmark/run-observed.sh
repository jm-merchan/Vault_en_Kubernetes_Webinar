#!/usr/bin/env bash
# Usage: run-observed.sh <scenario> <hcl> <label>
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$ROOT/telemetry/run.py" "$@"
