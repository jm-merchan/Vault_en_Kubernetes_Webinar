"""Controlled sibling-container TCP/file comparison. Restore audit in finally."""
import json,os,sys,time,subprocess,re,signal
from pathlib import Path
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor
from common import ROOT,kub,vault
from collect import api
from scenarios import prepare,configure,restore
from external_verify import verify
STATE=Path(os.environ.get('VBB_STATE_DIR','/tmp/vault/vbb-tcp-external'))
SUITE=os.environ.get('VBB_SUITE_ID','20261029-tcp-external')
RUNS=ROOT.parent/'runs';MANIFEST=RUNS/(SUITE+'-plan.json')
SCENARIOS=['none','file-default','tcp-default','file-combined','tcp-combined']
# Batch500 first: balanced order across three repeats. Other sizes once each.
plan=[]
for rep in range(3):
 for sc in SCENARIOS[rep:]+SCENARIOS[:rep]:plan.append({'scenario':sc,'label':'batch-500','repeat':rep+1})
for i,label in enumerate(['unit','batch-50','batch-100','batch-250','batch-750','batch-1000','batch-9000']):
 for sc in SCENARIOS[i%5:]+SCENARIOS[:i%5]:plan.append({'scenario':sc,'label':label,'repeat':1})
if MANIFEST.exists():plan=json.loads(MANIFEST.read_text())
else:MANIFEST.write_text(json.dumps(plan,indent=2))
subprocess.Popen(['caffeinate','-is','-w',str(os.getpid())],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
os.environ.update(VBB_AWAKE_MANAGED='1',VBB_EXPECTED_TARGETS='11',VBB_SUITE_ID=SUITE)
deployment=json.loads((STATE/'deployment.json').read_text());os.environ['VBB_TCP_ADDRESS']=deployment['address']
for signum in [signal.SIGTERM,signal.SIGINT]:signal.signal(signum,lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
def podman(*args):return subprocess.check_output(['podman',*args],stderr=subprocess.PIPE).decode()
def tcp_metrics():
 return dict(line.split() for line in podman('exec','vbb-tcp-external','python','-c',"import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:9102/metrics').read().decode())").splitlines() if len(line.split())==2)
def quiesce():
 configure('none')
 for _ in range(120):
  m=tcp_metrics()
  if float(m['vbb_external_connections_active'])==0 and float(m['vbb_external_compression_active'])==0:return m
  time.sleep(.5)
 raise RuntimeError('TCP receiver did not drain')
def archive(sc,logdir):
 script="import glob,gzip,shutil,os,sys; paths=[p for p in glob.glob(sys.argv[1]+'/*.json*') if not p.endswith('.gz')];\nfor p in paths:\n with open(p,'rb') as src,gzip.open(p+'.gz','wb',compresslevel=1) as dst:shutil.copyfileobj(src,dst,1024*1024)\n os.unlink(p)"
 def run(i):
  if sc.startswith('tcp'):podman('exec','vbb-tcp-external','python','-c',script,logdir)
  else:kub('exec',f'deployment/vbb-socket-{i}','--','python','-c',script,logdir)
 with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(run,[0] if sc.startswith('tcp') else range(3)))
def run_case(case,index):
 sc=case['scenario'];label=case['label'];compression=case.get('phase')=='compression'
 runid=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+sc+'-'+label+'-r'+str(case['repeat'])
 logdir='/data/'+runid if sc.startswith('tcp') else '/vault/audit/vbb-external/'+runid
 os.environ['VBB_RUN_ID']=runid;os.environ['VBB_FILE_PATH']=logdir+'/audit.json';os.environ['VBB_TCP_LOG_DIR']='/data/'+runid
 quiesce()
 if sc.startswith('tcp'):
  control=json.dumps({'case':runid,'rotate_bytes':64*1024*1024 if compression else 0,'compress':compression})
  podman('exec','vbb-tcp-external','python','-c',"import pathlib,sys;pathlib.Path('/data/control.json').write_text(sys.argv[1])",control)
 elif sc!='none':
  for i in range(3):kub('exec',f'vault-{i}','-c','vault','--','mkdir','-p',logdir)
 free=json.loads(podman('exec','vbb-tcp-external','python','-c',"import shutil,json;print(json.dumps(shutil.disk_usage('/data')._asdict()))"))['free']
 if free<8*1024**3:raise RuntimeError('Less than8GiB free; stopped before generating logs')
 hcl=ROOT.parent/('vb-transit-'+('unit' if label=='unit' else label.split('-')[1])+'.hcl')
 before=tcp_metrics()
 print(f'CASE {index+1}/{len(plan)} {sc} {label} repeat={case["repeat"]}',flush=True)
 rotators=[]
 if compression and sc.startswith('file'):
  conf=logdir+'/audit.json {\n size 64M\n rotate 99\n missingok\n notifempty\n compress\n delaycompress\n postrotate\n  pkill -HUP -x vault || true\n endscript\n}\n'
  for i in range(3):
   kub('exec','-i',f'vault-{i}','-c','auditlog-rotator','--','sh','-c','cat > '+logdir+'/logrotate.conf',input=conf.encode())
   command='while [ ! -f '+logdir+'/stop ]; do logrotate -v -s '+logdir+'/state '+logdir+'/logrotate.conf; sleep 2; done'
   log=STATE/(runid+f'-compression-{i}.log');handle=log.open('w')
   process=subprocess.Popen(['kubectl','--context','workshop-k8s','-n','vault','exec',f'vault-{i}','-c','auditlog-rotator','--','sh','-c',command],stdout=handle,stderr=subprocess.STDOUT,text=True)
   rotators.append((process,handle,log))
 try:
  subprocess.run([sys.executable,str(ROOT/'run.py'),sc,str(hcl),label],check=True)
 finally:
  for i,(p,handle,log) in enumerate(rotators):
   kub('exec',f'vault-{i}','-c','auditlog-rotator','--','touch',logdir+'/stop')
   p.wait(timeout=180);handle.close()
   (RUNS/runid/f'compression-{i}.log').write_bytes(log.read_bytes())
 after=quiesce();folder=RUNS/runid
 meta={**case,'phase':'compression' if compression else 'controlled-no-compression','external_deployment':deployment,'external_metrics_before':before,'external_metrics_after':after,'log_directory':logdir}
 (folder/'external.json').write_text(json.dumps(meta,indent=2))
 result=verify(folder,logdir)
 if not result['passed']:raise RuntimeError('Audit count validation failed '+runid)
 telemetry=json.loads((folder/'telemetry.json').read_text());quality=json.loads((folder/'quality.json').read_text())
 if quality['scrape_gaps'] or quality['query_errors'] or abs(quality['clock_offset_change_seconds'])>.1:raise RuntimeError('Telemetry quality failure '+runid)
 ext_delta=float(after['vbb_external_write_errors_total'])-float(before['vbb_external_write_errors_total'])
 if ext_delta:raise RuntimeError('TCP receiver write errors')
 for query in ['external_cpu_cores','external_memory_bytes','external_cpu_quota_cores']:
  if not telemetry['queries'][query]['summary']:raise RuntimeError('External metrics absent: '+query)
 case.update(run_id=runid,status='passed',count_status=result['status'])
 MANIFEST.write_text(json.dumps(plan,indent=2))
 print('VERIFIED '+runid+' '+result['status'],flush=True)
 if sc!='none':archive(sc,logdir)
def main():
 try:
  prepare(allow=True)
  if not (STATE/'warmed-up').exists():
   configure('none')
   warm=STATE/'warmup.hcl';warm.write_text((ROOT.parent/'vb-transit-500.hcl').read_text().replace('\"60s\"','\"30s\"',1))
   subprocess.run(['bash',str(ROOT.parent/'run-vb-job.sh'),str(warm),'external-warmup'],check=True)
   (STATE/'warmed-up').write_text(datetime.now(timezone.utc).isoformat())
  for index,case in enumerate(plan):
   if case.get('status')=='passed':continue
   run_case(case,index)
 finally:
  restore()
  subprocess.run([sys.executable,str(ROOT/'verify_restoration.py'),SUITE],check=True)
 print('EXTERNAL SUITE COMPLETE',flush=True)

if __name__=='__main__':main()
