"""Run the measured matrix sequentially and restore the saved audit configuration."""
import os,sys,subprocess,signal
from common import ROOT,kub
from scenarios import SCENARIOS,restore,resume
from report import update,load_runs,LABELS
suite=os.getenv('VBB_SUITE_ID','20261028-prometheus-final')
active=None
if sys.platform=='darwin' and not os.getenv('VBB_AWAKE_MANAGED'):
 subprocess.Popen(['caffeinate','-is','-w',str(os.getpid())],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 os.environ['VBB_AWAKE_MANAGED']='1'

active_label=None

def stop(signum,frame):
 raise KeyboardInterrupt(f'Signal {signum}')

signal.signal(signal.SIGTERM,stop)
try:
 resume()
 for sc in SCENARIOS:
  for label in LABELS:
   previous=load_runs(suite).get((sc,label))
   if previous and len(previous['rows'])==2 and all(float(x['success_pct'])==100 for x in previous['rows']):continue
   name='unit' if label=='unit' else label.removeprefix('batch-')
   active_label=sc+'-'+label
   print(f'\nRUN {sc}/{label}',flush=True)
   active=subprocess.Popen(['bash',str(ROOT.parent/'run-observed.sh'),sc,str(ROOT.parent/f'vb-transit-{name}.hcl'),label])
   rc=active.wait();active=None
   if rc:raise subprocess.CalledProcessError(rc,active_label)
   update(suite)
   print(f'PROGRESS {len(load_runs(suite))}/56',flush=True)
except KeyboardInterrupt:
 # Stop only the current suite Job before changing its audit configuration.
 if active is not None:
  active.terminate()
  kub('delete','job','vb-'+active_label,'--ignore-not-found','--wait=true')
  try:active.wait(timeout=10)
  except subprocess.TimeoutExpired:active.kill();active.wait()
 raise
finally:
 restore()
 update(suite)
