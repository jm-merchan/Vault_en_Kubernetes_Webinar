"""Audit evidence and configuration checks for the independent external series."""
import json,hashlib,sys
from pathlib import Path
from common import ROOT
BASE=ROOT.parent/'runs';SUITE=sys.argv[1] if len(sys.argv)>1 else '20261029-tcp-external'
plan=json.loads((BASE/(SUITE+'-plan.json')).read_text());errors=[];warnings=[];checked=[]
for c in plan:
 if c.get('status')!='passed':errors.append('Missing '+str(c));continue
 f=BASE/c['run_id'];r=json.loads((f/'result.json').read_text());q=json.loads((f/'quality.json').read_text());t=json.loads((f/'telemetry.json').read_text());cfg=json.loads((f/'configuration.json').read_text());external=json.loads((f/'external.json').read_text())
 bad=[]
 if r['status']!='passed' or len(r['rows'])!=2 or any(float(x['success_pct'])!=100 for x in r['rows']):bad.append('request errors')
 if q['scrape_gaps'] or q['query_errors'] or abs(q['clock_offset_change_seconds'])>.1:bad.append('telemetry quality')
 if hashlib.sha256((f/'config.hcl').read_bytes()).hexdigest()!=cfg['hcl_sha256']:bad.append('HCL hash')
 if len(t['queries']['target_up']['summary'])!=11:bad.append('target coverage')
 for name in ['host_cpu_quota_cores','external_cpu_quota_cores']:
  vals=t['queries'][name]['summary']
  if len(vals)!=1 or vals[0]['min']!=2 or vals[0]['max']!=2:bad.append('quota '+name)
 for name in ['external_write_errors','external_oom_kills','host_oom_events']:
  vals=t['queries'][name]['summary']
  if not vals or any(x['max']!=0 for x in vals):bad.append('failure metric '+name)
 audit60=t['queries']['audit_failures']['summary']
 audit20=t['queries'].get('audit_failures_during_measurement',{}).get('summary',[])
 if not audit60 or not audit20 or any(x['max']!=0 for x in audit20):bad.append('audit failure during measurement or missing capture')
 if any(x['max']!=0 for x in audit60):
  review=f/'audit-failure-review.json'
  evidence=json.loads(review.read_text()) if review.exists() else {}
  if not audit20 or not evidence.get('all_failures_before_benchmark') or evidence.get('run_id')!=c['run_id'] or any(ts>=r['start'] for ts in evidence.get('failure_epoch_times',[r['start']])):bad.append('unresolved audit failure counter')
  else:warnings.append(c['run_id']+': documented sys/metrics audit failures during device enable, before benchmark; retained 60s counter overlaps setup')
 for name in ['external_cpu_cores','external_memory_bytes','external_io_pressure_pct','disk_iops','disk_await_ms']:
  if not t['queries'][name]['summary']:bad.append('missing metric '+name)
 before=json.loads((f/'resources.json').read_text());after=json.loads((f/'pods-after.json').read_text());b={p['name']:{x['name']:x['restartCount'] for x in p['statuses']} for p in before};a={p['name']:{x['name']:x['restartCount'] for x in p['statuses']} for p in after}
 if a!=b or any(not s['ready'] for p in after for s in p['statuses']):bad.append('Vault pod readiness/restarts')
 if {p['name']:p['pod_uid'] for p in before}!={p['name']:p['uid'] for p in after}:bad.append('Vault pod replacement')
 if r['scenario']=='none':
  if cfg['audit']:bad.append('baseline has audit')
 else:
  counts=json.loads((f/'audit-counts.json').read_text())
  if not counts['passed']:bad.append('audit count')
  if set(cfg['audit'])!={'vbb/'}:bad.append('more than experiment audit device')
  if cfg['audit']['vbb/']['options']['log_raw']!='false':bad.append('log_raw')
  validation=json.loads((f/'audit-validation.json').read_text())
  if not validation.get('decrypt_plaintext_hmac'):bad.append('plaintext HMAC')
  if not validation.get('round_trip_ok') or validation.get('encrypt_batch_items')!=2:bad.append('probe round trip/count')
  if validation.get('ciphertext_hmac')==r['scenario'].endswith('combined'):bad.append('ciphertext HMAC setting')
  if validation.get('request_data_excluded')!=r['scenario'].endswith('combined'):bad.append('request exclusion setting')
  if c.get('phase')=='compression':
   if not any(entry['file'].endswith('.gz') for reader in counts['readers'] for entry in reader['files']):bad.append('compression did not produce archived logs during the case')
   if r['scenario'].startswith('tcp'):
    before_cpu=float(external['external_metrics_before']['vbb_external_compression_cpu_seconds_total'])
    after_cpu=float(external['external_metrics_after']['vbb_external_compression_cpu_seconds_total'])
    if after_cpu<=before_cpu:bad.append('receiver compression CPU did not advance')
 if r['scenario'].startswith('tcp') and cfg['audit']['vbb/']['options'].get('address')!=external['external_deployment']['address']:bad.append('wrong TCP endpoint')
 expected=['ciphertext','batch_results'] if r['scenario'].endswith('combined') else []
 if cfg['transit_tune'].get('audit_non_hmac_response_keys',[])!=expected:bad.append('HMAC tune')
 rot=t['queries']['rotator_cpu_cores']['summary']
 if rot and rot[0]['mean']>.05 and c.get('phase')!='compression':warnings.append(c['run_id']+': historical rotation CPU >0.05')
 errors.extend(c['run_id']+': '+x for x in bad)
 checked.append({'run_id':c['run_id'],'passed':not bad,'sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [f/'result.json',f/'telemetry.json',f/'configuration.json',f/'external.json']}})
restore=BASE/(SUITE+'-restoration-verification.json')
if not restore.exists() or not json.loads(restore.read_text())['passed']:errors.append('Restoration not verified')
result={'suite_id':SUITE,'checked':len(checked),'expected':len(plan),'passed':not errors,'errors':errors,'warnings':warnings,'manifest':checked}
(BASE/(SUITE+'-verification.json')).write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='manifest'},indent=2));sys.exit(bool(errors))
