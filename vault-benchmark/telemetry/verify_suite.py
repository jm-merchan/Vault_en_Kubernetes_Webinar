"""Validate the actual end-to-end evidence, not mocked benchmark results."""
import json,sys
from pathlib import Path
from report import load_runs,LABELS,SCENARIOS,metric
suite=sys.argv[1] if len(sys.argv)>1 else '20261028-prometheus-final'
runs=load_runs(suite);errors=[];warnings=[]
expected={(s,l) for s in SCENARIOS for l in LABELS}
if set(runs)!=expected:errors.append('Missing cases: '+str(sorted(expected-set(runs))))
required=['host_cpu_cores','host_cpu_quota_cores','host_throttled_periods_pct','vault_cpu_cores','benchmark_cpu_cores','vault_memory_bytes','vault_heap_alloc_bytes','rotator_cpu_cores','monitoring_cpu_cores','host_cpu_pressure_pct','host_io_pressure_pct','host_memory_pressure_pct','host_oom_events','disk_iops','disk_busy_pct','disk_await_ms','audit_request_ms','audit_response_ms']
for key,r in runs.items():
 tag='/'.join(key);f=r['folder'];t=r['telemetry'];c=json.loads((f/'configuration.json').read_text())
 if len(r['rows'])!=2 or {x['operation'] for x in r['rows']}!={'encrypt','decrypt'}:errors.append(tag+': operation rows')
 if any(float(x['success_pct'])!=100 for x in r['rows']):errors.append(tag+': request errors')
 expected_items=1 if r['label']=='unit' else 8982 if r['label']=='batch-9000' else int(r['label'].split('-')[1])
 if r['encrypt_items']!=expected_items or r['decrypt_items']!=1:errors.append(tag+': batch size')
 if r['workers']!=(50 if r['label']=='unit' else 10):errors.append(tag+': workers')
 for k in required:
  if not t['queries'][k]['summary'] or metric(t,k) is None:errors.append(tag+': missing '+k)
 for k,v in t['queries'].items():
  if 'error' in v:errors.append(tag+': PromQL error '+k)
 if any(x['min']!=1 for x in t['queries']['target_up']['summary']):warnings.append(tag+': scrape gaps')
 if metric(t,'host_oom_events','max')!=0:errors.append(tag+': OOM observed or missing')
 v=json.loads((f/'audit-validation.json').read_text())
 if len(c.get('logrotate',{}))!=3 or any('pkill -HUP -x vault || true' not in v['configuration'] for v in c.get('logrotate',{}).values()):errors.append(tag+': mounted logrotate config')
 before=json.loads((f/'resources.json').read_text());after=json.loads((f/'pods-after.json').read_text())
 before_counts={(p['name'],x['name']):x['restartCount'] for p in before for x in p['statuses']}
 after_counts={(p['name'],x['name']):x['restartCount'] for p in after for x in p['statuses']}
 if {p['name']:p['pod_uid'] for p in before}!={p['name']:p['uid'] for p in after}:errors.append(tag+': Vault pod replaced')
 if before_counts!=after_counts:errors.append(tag+': container restarted during test')
 if any(not x['ready'] for p in after for x in p['statuses']):errors.append(tag+': pod unready after test')
 if r['scenario']=='none':
  if c['audit'] or not v['audit_disabled']:errors.append(tag+': baseline audit enabled')
 else:
  if set(c['audit'])!={'vbb/'}:errors.append(tag+': unexpected audit devices')
  if not v['round_trip_ok'] or not v['decrypt_plaintext_hmac'] or v['encrypt_batch_items']!=2:errors.append(tag+': audit probe')
  if v['ciphertext_hmac']!= (not r['scenario'].endswith('combined')):errors.append(tag+': ciphertext HMAC')
  if v['request_data_excluded']!=(r['scenario'].endswith('combined') or r['scenario'].endswith('no-request')):errors.append(tag+': exclusion')
 if r['scenario'].startswith('socket'):
  if metric(t,'socket_write_errors','max')!=0:errors.append(tag+': socket write errors or missing metric')
  if not metric(t,'socket_bytes_per_second') or metric(t,'socket_bytes_per_second')<=0:errors.append(tag+': no socket bytes written')
 q=json.loads((f/'quality.json').read_text())
 if 'clock_offset_change_seconds' in q:
  if abs(q['clock_offset_change_seconds'])>1:errors.append(tag+': clock discontinuity')
 else:warnings.append(tag+': explicit clock offset probe not captured')
 if not 59<=r['end']-r['start']<=90:errors.append(tag+': unexpected measured duration')
result={'suite_id':suite,'cases':len(runs),'expected_cases':56,'errors':errors,'warnings':warnings,'passed':not errors}
print(json.dumps(result,indent=2))
sys.exit(bool(errors))
