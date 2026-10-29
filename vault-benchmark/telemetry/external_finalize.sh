#!/usr/bin/env bash
# Run only after the 50-case controlled matrix has exited and restored audit.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
export VBB_STATE_DIR=/tmp/vault/vbb-tcp-external
export VBB_SUITE_ID=20261029-tcp-external
python3 "$ROOT/external_backfill.py"
python3 "$ROOT/external_check.py"
python3 - "$ROOT" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1]).parent/'runs/20261029-tcp-compression-plan.json'
if not p.exists():
 p.write_text(json.dumps([{'scenario':s,'label':'batch-500','repeat':1,'phase':'compression'} for s in ['file-combined','tcp-combined']],indent=2))
PY
VBB_SUITE_ID=20261029-tcp-compression python3 -u "$ROOT/external_suite.py"
python3 "$ROOT/external_check.py" 20261029-tcp-compression
python3 -u "$ROOT/external_resilience.py"
python3 "$ROOT/external_upgrade.py"
VBB_RESILIENCE_HOLD_SECONDS=15 python3 -u "$ROOT/external_resilience.py"
python3 "$ROOT/external_reconnect.py"
python3 "$ROOT/verify_restoration.py" 20261029-tcp-external
python3 "$ROOT/external_check.py"
python3 "$ROOT/external_report.py"
