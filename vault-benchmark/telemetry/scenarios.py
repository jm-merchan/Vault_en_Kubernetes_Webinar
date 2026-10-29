import json,os,urllib.error
from common import *
STATE=Path(os.getenv('VBB_STATE_DIR','/tmp/vault/vbb-observability'));STATE.mkdir(mode=0o700,exist_ok=True)
SCENARIOS=['none','file-default','file-no-request','file-combined','socket-default','socket-no-request','socket-combined']
EXTERNAL_SCENARIOS=['tcp-default','tcp-combined','udp-default','udp-combined']
def audit():return vault('sys/audit').get('data',{})
def prepare(allow=False):
 if (STATE/'original.json').exists():
  if not allow:raise RuntimeError('Resuming requires --allow-suspend-audit for the saved session')
  resume();return
 devices=audit()
 if devices and not allow:raise RuntimeError('Other audit devices exist; explicit --allow-suspend-audit required')
 mounts=vault('sys/mounts')['data'];existed='transit/' in mounts
 state={'audit':devices,'transit_existed':existed,'tune':vault('sys/mounts/transit/tune')['data'] if existed else {},'restored':False}
 (STATE/'original.json').write_text(json.dumps(state,indent=2));os.chmod(STATE/'original.json',0o600)
 if not existed:vault('sys/mounts/transit',{'type':'transit'})
 try:vault('transit/keys/orders')
 except urllib.error.HTTPError as e:
  if e.code==404:vault('transit/keys/orders',{'type':'aes256-gcm96'})
  else:raise
 for name in devices:vault('sys/audit/'+name.rstrip('/'),method='DELETE')
 print('Original audit configuration saved. Transit/orders ready; suspended previous audit as authorized.')
def resume():
 state=json.loads((STATE/'original.json').read_text())
 devices=audit()
 foreign=set(devices)-set(state['audit'])-{'vbb/'}
 if foreign:raise RuntimeError('Unexpected audit devices: '+','.join(foreign))
 for name,dev in state['audit'].items():
  if name in devices:
   current=devices[name]
   if any(current.get(k)!=dev.get(k) for k in ['type','local','options']):raise RuntimeError('Original audit configuration changed; refusing to suspend it')
   vault('sys/audit/'+name.rstrip('/'),method='DELETE')
 state['restored']=False;(STATE/'original.json').write_text(json.dumps(state,indent=2))
 print('Resumed authorized benchmark session; original audit saved for restoration.')
def configure(name):
 assert name in SCENARIOS+EXTERNAL_SCENARIOS
 devices=audit();foreign=[k for k in devices if k!='vbb/']
 if foreign:raise RuntimeError('Unrelated audit device is active: '+','.join(foreign)+'. Refusing to mix scenarios.')
 options={'log_raw':'false'}
 if name.startswith('tcp'):options.update(socket_type='tcp',address=os.environ['VBB_TCP_ADDRESS'],write_timeout='2s')
 elif name.startswith('udp'):options.update(socket_type='udp',address=os.environ['VBB_UDP_ADDRESS'],write_timeout='2s')
 elif name.startswith('socket'):options.update(socket_type='unix',address='/vault/audit/benchmark.sock',write_timeout='2s')
 else:options['file_path']=os.getenv('VBB_FILE_PATH','/vault/audit/benchmark-audit.json')
 if name.endswith('no-request') or name.endswith('combined'):options['exclude']=json.dumps([{'condition':'"/request/mount_type" == transit','fields':['/request/data']}],separators=(',',':'))
 kind='socket' if name.startswith(('socket','tcp','udp')) else 'file'
 desired=None if name=='none' else {'type':kind,'options':options,'local':True}
 active=devices.get('vbb/')
 if active and (not desired or active['type']!=kind or active['options']!=options):vault('sys/audit/vbb',method='DELETE');active=None
 vault('sys/mounts/transit/tune',{'audit_non_hmac_response_keys':['ciphertext','batch_results'] if name.endswith('combined') else []})
 if desired and active is None:vault('sys/audit/vbb',desired)
 current=audit()
 assert (not current) if name=='none' else (set(current)=={'vbb/'} and current['vbb/']['options']==options)
 return {'scenario':name,'audit':current,'transit_tune':vault('sys/mounts/transit/tune')['data']}
def restore():
 state=json.loads((STATE/'original.json').read_text())
 if state.get('restored'):return
 # Restore original sink before removing the experiment sink.
 for name,dev in state['audit'].items():
  if name not in audit():vault('sys/audit/'+name.rstrip('/'),{k:dev[k] for k in ['type','description','local','options'] if k in dev})
 if 'vbb/' in audit():vault('sys/audit/vbb',method='DELETE')
 vault('sys/mounts/transit/tune',{'audit_non_hmac_response_keys':state['tune'].get('audit_non_hmac_response_keys',[])})
 current=audit()
 for name,dev in state['audit'].items():
  assert name in current and all(current[name].get(k)==dev.get(k) for k in ['type','local','options']),'Audit restoration verification failed'
 assert vault('sys/mounts/transit/tune')['data'].get('audit_non_hmac_response_keys',[])==state['tune'].get('audit_non_hmac_response_keys',[])
 state['restored']=True;(STATE/'original.json').write_text(json.dumps(state,indent=2))
 print('Original audit and Transit HMAC tuning restored; test mount retained for reproducibility.')
if __name__=='__main__':
 import sys
 if sys.argv[1]=='prepare':prepare('--allow-suspend-audit' in sys.argv)
 elif sys.argv[1]=='restore':restore()
 elif sys.argv[1]=='resume':resume()
 else:print(json.dumps(configure(sys.argv[1]),indent=2))
