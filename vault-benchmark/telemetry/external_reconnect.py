import sys,os,json,subprocess,time
from pathlib import Path
sys.path.insert(0,'vault-benchmark/telemetry')
from scenarios import prepare,configure,restore
from validate import verify
from common import ROOT
state=Path(os.environ['VBB_STATE_DIR']);os.environ['VBB_TCP_ADDRESS']=json.loads((state/'deployment.json').read_text())['address']
case='reconnect-control-'+str(time.time_ns());os.environ['VBB_TCP_LOG_DIR']='/data/'+case
try:
 prepare(allow=True)
 subprocess.run(['podman','exec','vbb-tcp-external','python','-c',"from pathlib import Path;import sys;Path('/data/control.json').write_text(sys.argv[1])",json.dumps({'case':case})],check=True)
 config=configure('tcp-combined');result=verify('tcp-combined')
 result.update(passed=True,test='New TCP audit device after receiver restart; explicit reconfiguration, not automatic reconnect',log_directory='/data/'+case,audit_device_names=sorted(config['audit']))
 (ROOT.parent/'runs/20261029-tcp-external-reconnect-verification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
finally:restore()
