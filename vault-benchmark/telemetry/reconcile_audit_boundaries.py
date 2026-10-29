"""Resolve batch boundary events by shape; preserve ambiguous unit events as intervals.
No payloads leave the pod. Preserve the unadjusted verification alongside the result.
"""
import json,sys,subprocess
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from common import ROOT,CTX,NS
suite=sys.argv[1] if len(sys.argv)>1 else '20261028-prometheus-final'
path=ROOT.parent/'runs'/f'{suite}-audit-count-verification.json'
doc=json.loads(path.read_text())
if doc.get('boundary_reconciliation'):
 print('Boundary reconciliation already saved');sys.exit(not doc.get('all_counts_consistent',doc['all_counts_match']))
original=path.with_name(f'{suite}-audit-count-before-boundary-reconciliation.json')
original.write_text(json.dumps(doc,indent=2)+'\n')
by_node=defaultdict(list)
for b in doc['boundary_events']:
 if b['excluded_start_millisecond'] and not b['excluded_setup_encrypt']:
  case=doc['cases'][b['case']]
  by_node[b['pod']].append({**b,'scenario':case['scenario'],'label':case['label']})
remote=r'''
import json,sys,glob,gzip,os
from datetime import datetime
cases=json.loads(sys.argv[1]);out=[]
def stamp(d):return datetime.fromisoformat(d['time'].replace('Z','+00:00')).timestamp()
def opened(p):return gzip.open(p,'rt') if p.endswith('.gz') else open(p)
for c in cases:
 ts=datetime.fromisoformat(c['time'].replace('Z','+00:00')).timestamp()
 prefix='benchmark-socket' if c['scenario'].startswith('socket') else 'benchmark-audit'
 files=[]
 for p in glob.glob('/vault/audit/'+prefix+'.json*'):
  if p.endswith('.gz') and os.path.exists(p[:-3]):continue
  with opened(p) as f:
   first=f.readline()
   if first:files.append((stamp(json.loads(first)),p))
 files.sort()
 choices=[p for start,p in files if start<=ts]
 if not choices:raise RuntimeError('No retained file for boundary')
 p=choices[-1];candidate=None;peers={}
 with opened(p) as f:
  for line in f:
   d=json.loads(line);t=stamp(d)
   if t<ts-3:continue
   if t>ts+1:break
   if d.get('type')!='response':continue
   req=d.get('request') or {};peer=(req.get('remote_address'),req.get('remote_port'))
   peers.setdefault(peer,[]).append((req.get('id'),req.get('path')))
   if req.get('id')==c['id']:
    data=(d.get('response') or {}).get('data') or {};b=data.get('batch_results');is_batch=isinstance(b,list);values=b if is_batch else [data];errors=0
    op='encrypt' if req.get('path')=='transit/encrypt/orders' else 'decrypt'
    for v in values:
     field='ciphertext' if op=='encrypt' else 'plaintext';err=v.get('error')
     empty_hmac=isinstance(err,str) and err.startswith('hmac-sha256:') and err==v.get('reference') and v.get('ciphertext')!=err and v.get('key_version',0)>0
     prefix_value='vault:' if op=='encrypt' and c['scenario'].endswith('combined') else 'hmac-sha256:'
     if d.get('error') or (err and not empty_hmac) or not isinstance(v.get(field),str) or not v[field].startswith(prefix_value):errors+=1
    candidate={'peer':peer,'operation':op,'items':len(values),'batch':is_batch,'errors':errors}
 if candidate is None:raise RuntimeError('Boundary ID missing from selected file')
 peer_records=peers[candidate.pop('peer')]
 other_transit=[rid for rid,pth in peer_records if rid!=c['id'] and pth in ['transit/encrypt/orders','transit/decrypt/orders']]
 setup_paths=sorted({pth for rid,pth in peer_records if pth=='sys/mounts' or pth=='transit/keys/orders'})
 if c['label']!='unit':
  include=candidate['operation']=='encrypt' and candidate['batch'];method='Measured batch shape'
 else:
  include=None;method='Unit operation in the first logged millisecond: setup and measured clients may share the TCP peer'
 out.append({'case':c['case'],'id':c['id'],'file':os.path.basename(p),'include':include,'method':method,'other_transit_responses_same_peer':len(other_transit),'setup_paths_same_peer':setup_paths,**candidate})
print(json.dumps(out))
'''
def inspect(pair):
 pod,records=pair;node=pod.split('-')[-1]
 p=subprocess.run(['kubectl','--context',CTX,'-n',NS,'exec','-i','deployment/vbb-socket-'+node,'--','python','-',json.dumps(records)],input=remote,text=True,capture_output=True,check=True)
 return [{'pod':pod,**x} for x in json.loads(p.stdout)]
reconciliation=[]
with ThreadPoolExecutor(max_workers=3) as pool:
 for result in pool.map(inspect,by_node.items()):reconciliation.extend(result)
for item in reconciliation:
 if item['include'] is True:
  c=doc['cases'][item['case']]['observed'];op=item['operation']
  c[op+'_requests']+=1;c[op+'_items']+=item['items']-item['errors'];c['error_items']+=item['errors']
for i,c in enumerate(doc['cases']):
 c['match']=all(c['observed'][k]==v for k,v in c['expected'].items()) and c['observed']['error_items']==0 and c['observed']['validation_errors']==0
 ambiguous=[x for x in reconciliation if x['case']==i and x['include'] is None]
 lower={k:c['observed'][k] for k in c['expected']};upper=lower.copy()
 for x in ambiguous:
  upper[x['operation']+'_requests']+=1;upper[x['operation']+'_items']+=x['items']-x['errors']
 c['audit_count_interval']={'lower':lower,'upper':upper}
 c['consistent']=all(lower[k]<=v<=upper[k] for k,v in c['expected'].items()) and c['observed']['error_items']==0 and c['observed']['validation_errors']==0 and not any(x['errors'] for x in ambiguous)
 c['verification_status']='consistent_with_millisecond_boundary' if ambiguous and c['consistent'] else 'exact' if c['match'] and not ambiguous else 'discrepancy'
doc['boundary_reconciliation']=reconciliation
doc['scope']+=' Batch events in the initial millisecond are identified by their measured batch shape. Unit events there remain ambiguous because setup and workload can share a TCP peer; an explicit count interval is reported. Original counters are retained separately.'
doc['all_counts_match']=all(c['match'] for c in doc['cases'])
doc['all_counts_consistent']=all(c['consistent'] for c in doc['cases'])
doc['verification_complete']=True
path.write_text(json.dumps(doc,indent=2)+'\n')
print(json.dumps(reconciliation,indent=2));print('Exact:',sum(c['verification_status']=='exact' for c in doc['cases']),'Consistent with boundary precision:',sum(c['verification_status']=='consistent_with_millisecond_boundary' for c in doc['cases']))
sys.exit(not doc['all_counts_consistent'] or bool(doc['parse_error_count']))
