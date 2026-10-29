"""Count complete audit responses from a single retained external-suite case."""
import json,subprocess,sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from common import kub
REMOTE=r'''
import glob,gzip,json,os,sys
from datetime import datetime
root,start,end,items,scenario=sys.argv[1:];start=float(start);end=float(end);items=int(items)
events=[];bad=0;parse=0;files=[];item_errors=0
for path in sorted(glob.glob(root+'/*.json*')):
 if path.endswith('.tmp'):continue
 if path.endswith('.gz') and os.path.exists(path[:-3]):continue
 lines=0
 with (gzip.open(path,'rb') if path.endswith('.gz') else open(path,'rb')) as f:
  for line in f:
   lines+=1
   try:d=json.loads(line)
   except (ValueError,UnicodeDecodeError):parse+=1;continue
   if not isinstance(d,dict) or d.get('type')!='response':continue
   req=d.get('request') or {};p=req.get('path','')
   if p not in ['transit/encrypt/orders','transit/decrypt/orders']:continue
   t=datetime.fromisoformat(d['time'].replace('Z','+00:00')).timestamp()
   if t<start or t>=end+.001:continue
   op='encrypt' if '/encrypt/' in p else 'decrypt'
   data=(d.get('response') or {}).get('data') or {};results=data.get('batch_results')
   batch=isinstance(results,list)
   if op=='encrypt' and items>1 and not batch:continue
   values=results if batch else [data]
   if ('data' not in req)!=scenario.endswith('combined'):bad+=1
   for v in values:
    field='ciphertext' if op=='encrypt' else 'plaintext';err=v.get('error')
    empty_hmac=isinstance(err,str) and err.startswith('hmac-sha256:') and err==v.get('reference') and v.get('key_version',0)>0 and v.get('ciphertext')!=err
    if d.get('error') or (err and not empty_hmac) or field not in v:item_errors+=1
    prefix='vault:' if op=='encrypt' and scenario.endswith('combined') else 'hmac-sha256:'
    if not isinstance(v.get(field),str) or not v[field].startswith(prefix):bad+=1
   if op=='encrypt' and len(values)!=items:bad+=1
   events.append([req['id'],op,len(values),t<start+.001])
 files.append({'file':os.path.basename(path),'lines':lines,'bytes':os.path.getsize(path)})
print(json.dumps({'events':events,'parse_errors':parse,'validation_errors':bad,'item_errors':item_errors,'files':files}))
'''
def verify(folder,logdir):
 r=json.loads((folder/'result.json').read_text())
 if r['scenario']=='none':return {'status':'not_applicable','passed':True}
 args=[logdir,str(r['start']),str(r['end']),str(r['encrypt_items']),r['scenario']]
 def scan(i):
  if r['scenario'].startswith(('tcp','udp')):
   container='vbb-udp-external' if r['scenario'].startswith('udp') else 'vbb-tcp-external'
   cmd=['podman','exec','-i',container,'python','-',*args]
  else:cmd=['kubectl','--context','workshop-k8s','-n','vault','exec','-i',f'deployment/vbb-socket-{i}','--','python','-',*args]
  p=subprocess.run(cmd,input=REMOTE.encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=240,check=True)
  return json.loads(p.stdout)
 with ThreadPoolExecutor(max_workers=3) as pool:reports=list(pool.map(scan,[0] if r['scenario'].startswith('tcp') else range(3)))
 seen=set();counts={o:{'requests':0,'items':0,'boundary_requests':0,'boundary_items':0} for o in ['encrypt','decrypt']};duplicates=0
 for report in reports:
  for rid,op,n,boundary in report.pop('events'):
   if rid in seen:duplicates+=1;continue
   seen.add(rid);c=counts[op];c['requests']+=1;c['items']+=n
   if boundary and r['encrypt_items']==1:c['boundary_requests']+=1;c['boundary_items']+=n
 for row in r['rows']:
  c=counts[row['operation']];c['expected_requests']=int(row['count']);c['expected_items']=int(row['count'])*(r['encrypt_items'] if row['operation']=='encrypt' else 1)
  c['exact']=c['requests']==c['expected_requests'] and c['items']==c['expected_items']
  c['consistent']=c['requests']-c['boundary_requests']<=c['expected_requests']<=c['requests'] and c['items']-c['boundary_items']<=c['expected_items']<=c['items']
 bad=sum(x[k] for x in reports for k in ['parse_errors','validation_errors','item_errors'])
 result={'passed':not bad and all(c['consistent'] for c in counts.values()),'status':'exact' if all(c['exact'] for c in counts.values()) else 'millisecond_boundary' if all(c['consistent'] for c in counts.values()) else 'mismatch','counts':counts,'duplicates':duplicates,'readers':reports}
 (folder/'audit-counts.json').write_text(json.dumps(result,indent=2)+'\n')
 return result
if __name__=='__main__':
 result=verify(Path(sys.argv[1]),sys.argv[2]);print(json.dumps(result,indent=2));sys.exit(not result['passed'])
