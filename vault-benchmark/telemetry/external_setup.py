"""Deploy a sibling Podman receiver and append its scrape to existing Prometheus."""
import json,os,subprocess,tempfile,time
from common import ROOT,kub
from collect import api
STATE=__import__('pathlib').Path('/tmp/vault/vbb-tcp-external');STATE.mkdir(mode=0o700,exist_ok=True)
def podman(*args):return subprocess.check_output(['podman',*args],stderr=subprocess.PIPE).decode()
assert not podman('ps','-a','--filter','name=^vbb-tcp-external$','--format','{{.Names}}').strip(),'Receiver already exists; inspect before changing it'
with tempfile.TemporaryDirectory() as d:
 p=__import__('pathlib').Path(d)
 (p/'external_receiver.py').write_bytes((ROOT/'external_receiver.py').read_bytes())
 (p/'Containerfile').write_text('FROM docker.io/library/python:3.12-slim\nCOPY external_receiver.py /app/receiver.py\nENTRYPOINT ["python", "-u", "/app/receiver.py"]\n')
 subprocess.run(['podman','build','-t','localhost/vbb-tcp-external:20261029',d],check=True)
if subprocess.run(['podman','volume','exists','vbb-tcp-external-data']).returncode:
 podman('volume','create','vbb-tcp-external-data')
podman('run','-d','--name','vbb-tcp-external','--network','workshop-k8s','--cpus','2','--memory','512m','--cap-drop','ALL','--security-opt','no-new-privileges','--read-only','--tmpfs','/tmp','-v','vbb-tcp-external-data:/data','localhost/vbb-tcp-external:20261029')
info=json.loads(podman('inspect','vbb-tcp-external'))[0]
ip=info['NetworkSettings']['Networks']['workshop-k8s']['IPAddress']
(STATE/'deployment.json').write_text(json.dumps({'ip':ip,'address':ip+':9090','metrics':ip+':9102','image':info['Image'],'container_id':info['Id'],'cpu_quota':info['HostConfig']['CpuQuota'],'cpu_period':info['HostConfig']['CpuPeriod'],'network':'workshop-k8s','published_ports':info['NetworkSettings']['Ports'],'volume':'vbb-tcp-external-data'},indent=2))
for i in range(3):
 for attempt in range(30):
  try:
   kub('exec',f'vault-{i}','-c','vault','--','nc','-z','-w','3',ip,'9090');break
  except subprocess.CalledProcessError:time.sleep(1)
 else:raise RuntimeError(f'vault-{i}: TCP unreachable')
 print(f'vault-{i}: TCP reachable')
cm=json.loads(kub('get','cm','vbb-prometheus-config','-o','json'))
(STATE/'prometheus-config-before.json').write_text(json.dumps(cm))
config=json.loads(cm['data']['prometheus.yml'])
assert not any(s['job_name']=='tcp-external' for s in config['scrape_configs'])
config['scrape_configs'].append({'job_name':'tcp-external','static_configs':[{'targets':[ip+':9102'],'labels':{'location':'outside-minikube'}}]})
kub('patch','cm','vbb-prometheus-config','--type=merge','-p',json.dumps({'data':{'prometheus.yml':json.dumps(config)}}))
for _ in range(90):
 if 'tcp-external' in kub('exec','deployment/vbb-prometheus','--','cat','/etc/prometheus/prometheus.yml'):break
 time.sleep(1)
else:raise RuntimeError('Projected Prometheus config not updated')
kub('exec','deployment/vbb-prometheus','--','sh','-c','kill -HUP 1')
for _ in range(30):
 targets=api('targets')['activeTargets']
 if len(targets)==11 and all(t['health']=='up' for t in targets):break
 time.sleep(2)
else:raise RuntimeError('Metrics targets not healthy')
print('External TCP receiver ready at '+ip+'; 11 Prometheus targets healthy; no published host ports.')
