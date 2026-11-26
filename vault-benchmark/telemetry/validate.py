"""Probe response visibility and HMAC without storing plaintexts or tokens."""
import json,base64,time,os,subprocess
from common import vault,kub

def verify(scenario):
 if scenario=='none':return {'audit_disabled':True}
 path='/vault/audit/benchmark-socket.json' if scenario.startswith('socket') else os.getenv('VBB_FILE_PATH','/vault/audit/benchmark-audit.json')
 # The local forward reaches vault-<VBB_FORWARD_POD_INDEX> (default 0). Read its PVC through the receiver pod.
 probe=base64.b64encode(b'vbb-observability-validation').decode()
 encrypted=vault('transit/encrypt/orders',{'batch_input':[{'plaintext':probe},{'plaintext':probe}]})
 values=encrypted['data']['batch_results']
 assert len(values)==2 and all('ciphertext' in v and not v.get('error') for v in values)
 decrypted=vault('transit/decrypt/orders',{'ciphertext':values[0]['ciphertext']})
 assert decrypted['data']['plaintext']==probe
 ids=[encrypted['request_id'],decrypted['request_id']]
 code='''import json,sys,os
p=sys.argv[1];ids=set(sys.argv[2:]);out=[]
for p in [p,p+'.1']:
 try:
  with open(p,'rb') as f:
   f.seek(max(0,os.fstat(f.fileno()).st_size-4*1024*1024))
   for line in f:
    try:d=json.loads(line)
    except (ValueError,UnicodeDecodeError):continue
    if isinstance(d,dict) and isinstance(d.get('request'),dict) and d['request'].get('id') in ids:out.append(d)
 except FileNotFoundError:pass
print(json.dumps(out))'''
 if scenario.endswith('filter-transit'):
  # Transit must be absent; an unrelated request made afterwards must be present.
  control=vault('sys/mounts/transit/tune')['request_id'];found=[]
  for _ in range(25):
   found=json.loads(kub('exec','deployment/vbb-socket-'+os.getenv('VBB_FORWARD_POD_INDEX','0'),'--','python','-c',code,path,control,*ids))
   if sum(e.get('type')=='response' and e['request']['id']==control for e in found)>=1:break
   time.sleep(.2)
  assert any(e['request']['id']==control for e in found),'Control audit entry missing'
  assert not any(e['request']['id'] in ids for e in found),'Transit entry reached the filtered device'
  return {'transit_entries':0,'control_entries':len(found),'filter':'mount_point != "transit/"','round_trip_ok':True}
 entries=[]
 for _ in range(10):
  if scenario.startswith(('tcp','udp')):
   tcp_code=code.replace("for p in [p,p+'.1']:","import glob\nfor p in glob.glob(p+'/*.json'):")
   prefix='UDP' if scenario.startswith('udp') else 'TCP'
   entries=json.loads(subprocess.check_output(['podman','exec',os.getenv('VBB_'+prefix+'_CONTAINER','vbb-'+prefix.lower()+'-external'),'python','-c',tcp_code,os.environ['VBB_'+prefix+'_LOG_DIR'],*ids]))
  else:entries=json.loads(kub('exec','deployment/vbb-socket-'+os.getenv('VBB_FORWARD_POD_INDEX','0'),'--','python','-c',code,path,*ids))
  if sum(e.get('type')=='response' for e in entries)>=2:break
  time.sleep(.2)
 response={e['request']['id']:e for e in entries if e.get('type')=='response'}
 assert set(response)==set(ids),'Probe audit response missing'
 if scenario.endswith('no-data'):
  assert all('data' not in e['request'] for e in entries),'request.data not excluded'
  assert all('data' not in e['response'] for e in response.values()),'response.data not excluded'
  assert all(e['request'].get('path','').startswith('transit/') for e in entries),'Transit metadata missing'
  return {'probe_response_entries':len(response),'request_data_excluded':True,'response_data_excluded':True,'round_trip_ok':True}
 enc=response[ids[0]];dec=response[ids[1]]
 results=enc['response']['data']['batch_results']
 assert len(results)==2,'batch_results not retained'
 expected='vault:' if scenario.endswith('combined') else 'hmac-sha256:'
 assert all(v['ciphertext'].startswith(expected) for v in results),'Unexpected ciphertext HMAC state'
 assert dec['response']['data']['plaintext'].startswith('hmac-sha256:'),'Plaintext must remain protected'
 excluded=scenario.endswith('no-request') or scenario.endswith('combined')
 assert all(('data' not in e['request'])==excluded for e in entries),'Unexpected request.data exclusion'
 return {'probe_response_entries':len(response),'encrypt_batch_items':len(results),'ciphertext_hmac':not scenario.endswith('combined'),'decrypt_plaintext_hmac':True,'request_data_excluded':excluded,'round_trip_ok':True}
if __name__=='__main__':
 import sys
 print(json.dumps(verify(sys.argv[1]),indent=2))
