"""Export additional already-scraped runtime metrics for earlier runs of a suite."""
import json,sys
from datetime import datetime,timezone
from report import load_runs
from collect import collect
names=['vault_heap_alloc_bytes','vault_runtime_sys_bytes','vault_gc_pause_seconds_per_second','vault_gc_runs_per_second']
suite=sys.argv[1]
for r in load_runs(suite).values():
 p=r['folder']/'telemetry.json';t=json.loads(p.read_text());missing=[n for n in names if n not in t['queries']]
 if not missing:continue
 d=collect(r['start'],r['end'],'unused',names=missing)
 t['queries'].update(d['queries']);t['additional_runtime_export_utc']=datetime.now(timezone.utc).isoformat();p.write_text(json.dumps(t,indent=2))
 print(r['run_id'],', '.join(missing))
