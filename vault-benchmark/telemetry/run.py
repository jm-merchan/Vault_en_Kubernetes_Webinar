import sys,json,re,subprocess,os,time,hashlib
from datetime import datetime,timezone
from common import *
from scenarios import configure
from collect import collect,api
scenario,hcl,label=sys.argv[1:4]
if sys.platform=='darwin' and not os.getenv('VBB_AWAKE_MANAGED'):
 subprocess.Popen(['caffeinate','-is','-w',str(os.getpid())],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 os.environ['VBB_AWAKE_MANAGED']='1'

runid=os.getenv('VBB_RUN_ID') or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+scenario+'-'+label
folder=ROOT.parent/'runs'/runid;folder.mkdir(parents=True)
if scenario.startswith('socket'):
 # Match Vault's UID so the existing non-root rotator can compress these files.
 changed=[]
 for i in range(3):
  name=f'vbb-socket-{i}'
  d=json.loads(kub('get','deployment',name,'-o','json'))
  if d['spec']['template']['spec'].get('securityContext',{}).get('runAsUser')!=100:
   patch={'spec':{'template':{'spec':{'securityContext':{'runAsUser':100,'runAsGroup':1000,'runAsNonRoot':True,'fsGroup':1000}}}}}
   kub('patch','deployment',name,'--type=merge','-p',json.dumps(patch));changed.append(name)
 for name in changed:kub('rollout','status','deployment/'+name,'--timeout=120s')
 if changed:time.sleep(10)
deadline=time.monotonic()+90
healthy_checks=0
while True:
 active=api('targets')['activeTargets']
 bad=[t['labels'] for t in active if t['health']!='up']
 pods_state=json.loads(kub('get','pods','-l','app.kubernetes.io/name=vault','-o','json'))['items']
 unready=[p['metadata']['name'] for p in pods_state if not all(c.get('ready') for c in p['status']['containerStatuses'])]
 target_count_ok=(len(active)==int(os.environ['VBB_EXPECTED_TARGETS'])) if 'VBB_EXPECTED_TARGETS' in os.environ else len(active)>=10
 if target_count_ok and not bad and len(pods_state)==3 and not unready:
  healthy_checks+=1
  if healthy_checks>=2:break
 else:healthy_checks=0
 if time.monotonic()>=deadline:raise RuntimeError('Unhealthy preflight: targets='+str(bad)+' pods='+str(unready))
 if not healthy_checks:print('Waiting for healthy metrics and all three Vault pods...',flush=True)
 time.sleep(5)
def clock_check():
 before=time.time();guest=float(api('query',{'query':'time()'})['result'][1]);after=time.time()
 return {'host_epoch':(before+after)/2,'prometheus_epoch':guest,'guest_minus_host_seconds':guest-(before+after)/2,'round_trip_seconds':after-before}
clock_before=clock_check()
config=configure(scenario)
rotation={}
for i in range(3):
 text_config=kub('exec',f'vault-{i}','-c','auditlog-rotator','--','cat','/etc/logrotate.conf')
 if 'pkill -HUP -x vault || true' not in text_config:raise RuntimeError('Rotator postrotate fix is not mounted on '+f'vault-{i}')
 rotation[f'vault-{i}']={'sha256':hashlib.sha256(text_config.encode()).hexdigest(),'configuration':text_config}
config['logrotate']=rotation
from validate import verify
(folder/'audit-validation.json').write_text(json.dumps(verify(scenario),indent=2))
h=Path(hcl).read_bytes();(folder/'config.hcl').write_bytes(h)
config.update(hcl_sha256=hashlib.sha256(h).hexdigest(),workers=int(re.search(rb'workers\s*=\s*(\d+)',h).group(1)),run_id=runid)
(folder/'configuration.json').write_text(json.dumps(config,indent=2))
config['pods']=json.loads(kub('get','pods','-l','app.kubernetes.io/name=vault','-o','json'))
# Save resources and roles without secret values from pod environments.
resources=[{'name':p['metadata']['name'],'pod_uid':p['metadata']['uid'],'statuses':[{k:c.get(k) for k in ['name','restartCount','ready','state']} for c in p['status'].get('containerStatuses',[])],'node':p['spec'].get('nodeName'),'containers':[{'name':c['name'],'resources':c.get('resources',{})} for c in p['spec']['containers']]} for p in config.pop('pods')['items']]
(folder/'resources.json').write_text(json.dumps(resources,indent=2))
full_label=scenario+'-'+label
cmd=['bash',str(ROOT.parent/'run-vb-job.sh'),hcl,full_label]
proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
text=''
for line in proc.stdout:
 print(line,end='',flush=True);text+=line
rc=proc.wait();(folder/'benchmark.txt').write_text(text)
if rc:raise RuntimeError(f'Benchmark failed ({rc}); artifacts: {folder}')
start=re.search(r'(\d{4}-\d\d-\d\dT[\d:.]+Z).*starting benchmarks',text).group(1)
end=re.search(r'(\d{4}-\d\d-\d\dT[\d:.]+Z).*benchmark complete',text).group(1)
start=datetime.fromisoformat(start.replace('Z','+00:00')).timestamp();end=datetime.fromisoformat(end.replace('Z','+00:00')).timestamp()
pods=json.loads(kub('get','pods','-l','job-name=vb-'+full_label,'-o','json'))['items'];pod=pods[0]['metadata']['name']
time.sleep(7)
telemetry=collect(start,end,pod);(folder/'telemetry.json').write_text(json.dumps(telemetry,indent=2))
rotations={}
for i in range(3):
 rotations[f'vault-{i}']=kub('logs',f'vault-{i}','-c','auditlog-rotator','--since-time='+datetime.fromtimestamp(start,timezone.utc).isoformat().replace('+00:00','Z'),'--timestamps=true')
(folder/'rotator-logs.json').write_text(json.dumps(rotations,indent=2))
after_pods=json.loads(kub('get','pods','-l','app.kubernetes.io/name=vault','-o','json'))['items']
(folder/'pods-after.json').write_text(json.dumps([{'name':p['metadata']['name'],'uid':p['metadata']['uid'],'statuses':[{k:c.get(k) for k in ['name','restartCount','ready','state']} for c in p['status'].get('containerStatuses',[])]} for p in after_pods],indent=2))
rows=[]
for m in re.finditer(r'^(unit|batch)_(encrypt|decrypt)\s+(\d+)\s+([\d.]+)\s+([\d.]+)\s+(\S+)\s+(\S+)\s+(\S+)\s+([\d.]+)%',text,re.M):
 rows.append(dict(zip(['mode','operation','count','rate','throughput','mean','p95','p99','success_pct'],m.groups())))
items=int(re.search(r'encrypt x(\d+)',text).group(1))
clock_after=clock_check()
quality={'clock_before':clock_before,'clock_after':clock_after,'clock_offset_change_seconds':clock_after['guest_minus_host_seconds']-clock_before['guest_minus_host_seconds'],'scrape_gaps':[x['labels'] for x in telemetry['queries']['target_up']['summary'] if x['min']!=1], 'benchmark_elapsed_wall_seconds':end-start,'query_errors':{k:v['error'] for k,v in telemetry['queries'].items() if 'error' in v}}
(folder/'quality.json').write_text(json.dumps(quality,indent=2))
summary={'status':'passed' if len(rows)==2 and all(float(x['success_pct'])==100 for x in rows) else 'failed','run_id':runid,'suite_id':os.getenv('VBB_SUITE_ID','20261028-prometheus-final'),'scenario':scenario,'label':label,'workers':config['workers'],'encrypt_items':items,'decrypt_items':1,'start':start,'end':end,'rows':rows,'telemetry_file':'telemetry.json'}
(folder/'result.json').write_text(json.dumps(summary,indent=2))
for key in ['host_cpu_cores','host_cpu_quota_cores','host_throttled_periods_pct','vault_memory_bytes','disk_iops','disk_busy_pct','disk_await_ms','audit_request_ms','audit_response_ms']:
 a=telemetry['queries'][key]['summary'];print(key,[(round(x['mean'],3) if x['mean'] is not None else None,round(x['max'],3) if x['max'] is not None else None) for x in a])
from report import summary_table
print(summary_table({'telemetry':telemetry}))
print('OBSERVED_RESULT='+str(folder),flush=True)
if len(rows)!=2 or any(float(x['success_pct'])!=100 for x in rows):raise RuntimeError('Incomplete results or requests failed')
