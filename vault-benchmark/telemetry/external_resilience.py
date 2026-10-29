"""Controlled receiver outage after the performance series; retain all evidence."""
import base64,json,os,ssl,subprocess,time,urllib.request,urllib.error
from pathlib import Path
from datetime import datetime,timezone
from common import ROOT,vault
from scenarios import prepare,configure,restore
STATE=Path(os.environ['VBB_STATE_DIR']);deployment=json.loads((STATE/'deployment.json').read_text())
os.environ['VBB_TCP_ADDRESS']=deployment['address']
prefix='resilience-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
hold=float(os.getenv('VBB_RESILIENCE_HOLD_SECONDS','0'))
report={'scenario':'tcp-combined','test':'receiver process stop/start; same VM and persistent volume','hold_seconds_before_unavailable_and_recovered_requests':hold,'requests':[],'log_directories':[]}
def podman(*args):return subprocess.check_output(['podman',*args],stderr=subprocess.PIPE).decode()
def select(phase):
 case=prefix+'-'+phase;report['log_directories'].append('/data/'+case)
 podman('exec','vbb-tcp-external','python','-c',"from pathlib import Path;import sys;Path('/data/control.json').write_text(sys.argv[1])",json.dumps({'case':case,'rotate_bytes':0,'compress':False}))
def request(phase):
 payload=base64.b64encode(b'vbb-tcp-resilience-fixture').decode();body={'batch_input':[{'plaintext':payload},{'plaintext':payload}]}
 req=urllib.request.Request(os.environ['VAULT_ADDR']+'/v1/transit/encrypt/orders',data=json.dumps(body).encode(),headers={'X-Vault-Token':os.environ['VAULT_TOKEN'],'Content-Type':'application/json'})
 start=time.monotonic();result={'phase':phase}
 try:
  with urllib.request.urlopen(req,context=ssl.create_default_context(cafile=os.environ['VAULT_CACERT']),timeout=8) as response:
   d=json.load(response);result.update(status=response.status,request_id=d['request_id'],items=len(d['data']['batch_results']))
 except urllib.error.HTTPError as e:result.update(status=e.code,error='HTTPError')
 except Exception as e:result.update(status=None,error=type(e).__name__)
 result['seconds']=time.monotonic()-start;report['requests'].append(result)
 print(phase,result.get('status'),result.get('error',''),round(result['seconds'],3),flush=True)
try:
 prepare(allow=True);select('before');report['configuration']=configure('tcp-combined')
 report['receiver_image']=json.loads(podman('inspect','vbb-tcp-external'))[0]['Image']
 for _ in range(10):request('before')
 podman('stop','--time','0','vbb-tcp-external')
 report['receiver_running_while_unavailable']=json.loads(podman('inspect','vbb-tcp-external'))[0]['State']['Running']
 time.sleep(hold)
 try:
  for _ in range(3):request('unavailable');time.sleep(.5 if hold else 0)
 finally:podman('start','vbb-tcp-external')
 for _ in range(40):
  try:podman('exec','vbb-tcp-external','python','-c',"import urllib.request;urllib.request.urlopen('http://127.0.0.1:9102/metrics').read()");break
  except subprocess.CalledProcessError:time.sleep(.25)
 # New case directory after restart avoids reusing a previous connection filename.
 select('recovered')
 time.sleep(hold)
 for _ in range(10):request('recovered');time.sleep(.25 if hold else 0)
finally:
 if podman('inspect','--format','{{.State.Running}}','vbb-tcp-external').strip()!='true':podman('start','vbb-tcp-external')
 restore()
scan="""import glob,json,sys
ids=set(json.loads(sys.argv[1]));found=set();errors=0
for directory in json.loads(sys.argv[2]):
 for path in glob.glob(directory+'/*.json'):
  for line in open(path,'rb'):
   try:d=json.loads(line)
   except (ValueError,UnicodeDecodeError):errors+=1;continue
   if d.get('type')=='response' and d.get('request',{}).get('id') in ids:found.add(d['request']['id'])
print(json.dumps({'observed_response_ids':sorted(found),'parse_errors':errors}))
"""
ids=[r['request_id'] for r in report['requests'] if r.get('status')==200]
time.sleep(2)
report.update(json.loads(podman('exec','vbb-tcp-external','python','-c',scan,json.dumps(ids),json.dumps(report['log_directories']))))
report['missing_successful_response_ids']=sorted(set(ids)-set(report['observed_response_ids']))
report['api_recovery_succeeded']=all(r.get('status')==200 for r in report['requests'] if r['phase']=='recovered')
report['audit_recovery_succeeded']=all(r.get('request_id') in report['observed_response_ids'] for r in report['requests'] if r['phase']=='recovered' and r.get('status')==200)
report['note']='This is a receiver process outage, not a host/power-loss durability test. TCP can omit events on connection loss. Client success and retained audit evidence are reported separately.'
p=ROOT.parent/('runs/20261029-tcp-external-resilience'+('-extended' if hold else '')+'.json');p.write_text(json.dumps(report,indent=2)+'\n');print(str(p))
