"""After measurements, deploy and verify restart-safe log filenames.
The measured image and code snapshot remain recorded for reproducibility.
"""
import json,subprocess,tempfile,time,re
from pathlib import Path
from datetime import datetime
from common import ROOT,vault
from collect import api
STATE=Path('/tmp/vault/vbb-tcp-external')
assert 'vbb/' not in vault('sys/audit')['data'],'Cannot restart a receiver used by an active test audit device'
def p(*args):return subprocess.check_output(['podman',*args],stderr=subprocess.PIPE).decode()
old=json.loads((STATE/'deployment.json').read_text());ip=old['ip']
with tempfile.TemporaryDirectory() as d:
 root=Path(d);(root/'external_receiver.py').write_bytes((ROOT/'external_receiver.py').read_bytes())
 (root/'Containerfile').write_text('FROM docker.io/library/python:3.12-slim\nCOPY external_receiver.py /app/receiver.py\nENTRYPOINT ["python", "-u", "/app/receiver.py"]\n')
 subprocess.run(['podman','build','-t','localhost/vbb-tcp-external:20261029-restart-safe',d],check=True)
p('stop','vbb-tcp-external');p('rm','vbb-tcp-external')
p('run','-d','--name','vbb-tcp-external','--network','workshop-k8s','--ip',ip,'--cpus','2','--memory','512m','--cap-drop','ALL','--security-opt','no-new-privileges','--read-only','--tmpfs','/tmp','-v','vbb-tcp-external-data:/data','localhost/vbb-tcp-external:20261029-restart-safe')
case='delivery-restart-selftest-'+str(time.time_ns())
p('exec','vbb-tcp-external','python','-c',"from pathlib import Path;import sys;Path('/data/control.json').write_text(sys.argv[1])",json.dumps({'case':case}))
for i in range(2):
 for _ in range(30):
  try:
   p('exec','vbb-tcp-external','python','-c',"import socket,json,sys;s=socket.create_connection(('127.0.0.1',9090));s.sendall((json.dumps({'receiver_selftest':int(sys.argv[1])})+'\\n').encode());s.close()",str(i));break
  except subprocess.CalledProcessError:time.sleep(.2)
 else:raise RuntimeError('Receiver did not start')
 time.sleep(.3)
 if i==0:p('restart','vbb-tcp-external')
check=json.loads(p('exec','vbb-tcp-external','python','-c',"import json,glob,sys;print(json.dumps([json.loads(open(p).read()) for p in glob.glob('/data/'+sys.argv[1]+'/*.json')]))",case))
assert sorted(d['receiver_selftest'] for d in check)==[0,1]
scrape_after=time.time()
for _ in range(40):
 targets=api('targets')['activeTargets']
 external=[t for t in targets if t['labels'].get('job')=='tcp-external']
 fresh=len(external)==1 and datetime.fromisoformat(re.sub(r'(\.\d{6})\d+',r'\1',external[0]['lastScrape'].replace('Z','+00:00'))).timestamp()>scrape_after
 if len(targets)==11 and all(t['health']=='up' for t in targets) and fresh:break
 time.sleep(.5)
else:raise RuntimeError('Metrics did not recover')
new=json.loads(p('inspect','vbb-tcp-external'))[0]
result={'passed':True,'measured_image':old['image'],'delivered_image':new['Image'],'measured_code_snapshot':str(STATE/'receiver-measured.py'),'change':'Add process-unique prefix to per-connection log filenames to preserve data when a process restarts in the same case directory. No changes to receive/write/metrics logic.','restart_log_preservation_verified':True,'prometheus_targets_up':11,'ip':ip,'published_ports':new['NetworkSettings']['Ports'],'audit_device_names':sorted(vault('sys/audit')['data'])}
(ROOT.parent/'runs/20261029-tcp-external-delivery-verification.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
