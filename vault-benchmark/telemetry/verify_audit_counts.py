"""Read retained audit files and compare response element counts with real benchmarks.
Only request IDs, counts and validation flags leave the receiver pod; no payloads.
Run after the suite has restored its original audit device.
"""
import sys,json,subprocess,uuid,threading,re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from common import ROOT,CTX,NS
from report import load_runs
suite=sys.argv[1] if len(sys.argv)>1 else '20261028-prometheus-final'
runs=[r for r in sorted(load_runs(suite).values(),key=lambda r:r['start']) if r['scenario']!='none']
if len(runs)!=48:
 raise RuntimeError(f'Expected 48 completed audit cases before scanning; found {len(runs)}')
# Log timestamps contain milliseconds; use the next millisecond at both boundaries.
# Preserve boundary events so setup/result timing can be reviewed instead of hidden.
manifest=[{'start':r['start'],'end':r['end'],'scenario':r['scenario'],'encrypt_items':r['encrypt_items']} for r in runs]
for r in runs:
 if r['encrypt_items']>1 and re.search(r'\breference\s*=',(r['folder']/'config.hcl').read_text()):
  raise RuntimeError('HMAC error classification requires the known empty reference in these fixtures')
remote=r'''
import json,sys,gzip,glob,os,bisect
from datetime import datetime
m=json.loads(sys.argv[1]);starts=[x['start'] for x in m];errors=[];files=[];opened=[]
# Pin inodes before reading: rename/rotation cannot make us reopen a different file.
for pattern in ['/vault/audit/benchmark-audit.json*','/vault/audit/benchmark-socket.json*']:
 for path in sorted(glob.glob(pattern)):
  if path.endswith('.gz') and os.path.exists(path[:-3]):continue
  try:opened.append((path,open(path,'rb')))
  except FileNotFoundError:pass
for path,raw in opened:
 lines=0
 try:
  f=gzip.GzipFile(fileobj=raw) if path.endswith('.gz') else raw
  for line in f:
   lines+=1
   try:d=json.loads(line)
   except (ValueError,UnicodeDecodeError):errors.append({'file':os.path.basename(path),'line':lines,'bytes':len(line)});continue
   if not isinstance(d,dict) or d.get('type')!='response':continue
   req=d.get('request') or {};p=req.get('path','')
   if p not in ['transit/encrypt/orders','transit/decrypt/orders']:continue
   ts=datetime.fromisoformat(d['time'].replace('Z','+00:00')).timestamp();i=bisect.bisect_right(starts,ts)-1
   if i<0 or ts>=m[i]['end']+.001:continue
   sc=m[i]['scenario'];is_socket='benchmark-socket' in path
   if is_socket!=sc.startswith('socket'):continue
   op='e' if '/encrypt/' in p else 'd';data=(d.get('response') or {}).get('data') or {}
   results=data.get('batch_results')
   is_batch=isinstance(results,list)
   ignored_seed=op=='e' and m[i]['encrypt_items']>1 and not is_batch
   before_window=ts<m[i]['start']+.001
   if before_window or ignored_seed or ts>m[i]['end']:
    print(json.dumps({'boundary_event':{'case':i,'id':req['id'],'time':d['time'],'offset_start_ms':(ts-m[i]['start'])*1000,'offset_end_ms':(ts-m[i]['end'])*1000,'batch':len(results) if is_batch else 1,'excluded_start_millisecond':before_window,'excluded_setup_encrypt':ignored_seed,'included_end_millisecond':not before_window and not ignored_seed and ts>m[i]['end']}}),flush=True)
   if before_window or ignored_seed:continue
   if not is_batch:results=[data]
   errors_items=0;bad=0
   excluded=sc.endswith('no-request') or sc.endswith('combined')
   if ('data' not in req)!=excluded:bad+=1
   prefix='vault:' if sc.endswith('combined') else 'hmac-sha256:'
   for v in results:
    field='ciphertext' if op=='e' else 'plaintext'
    err=v.get('error')
    # Vault HMACs even empty error/reference strings. These HCL fixtures omit reference.
    empty_error_hmac=isinstance(err,str) and err.startswith('hmac-sha256:') and err==v.get('reference') and v.get('ciphertext')!=err and v.get('key_version',0)>0
    if d.get('error') or (err and not empty_error_hmac) or field not in v:errors_items+=1;continue
    expected=prefix if op=='e' else 'hmac-sha256:'
    if not isinstance(v[field],str) or not v[field].startswith(expected):bad+=1
   print(json.dumps([i,req['id'],op,len(results)-errors_items,errors_items,bad],separators=(',',':')))
 except Exception as e:errors.append({'file':os.path.basename(path),'error':str(e)})
 finally:raw.close()
 files.append({'file':os.path.basename(path),'lines':lines})
 print(json.dumps({'progress_file':os.path.basename(path),'lines':lines}),flush=True)
print(json.dumps({'files':files,'parse_errors':errors},separators=(',',':')))
'''
seen=[set() for _ in runs]
counts=[{'encrypt_requests':0,'decrypt_requests':0,'encrypt_items':0,'decrypt_items':0,'error_items':0,'validation_errors':0,'duplicates':0} for _ in runs]
node_reports=[];procs=[];boundary_events=[]
for node in range(3):
 cmd=['kubectl','--context',CTX,'-n',NS,'exec','-i',f'deployment/vbb-socket-{node}','--','python','-',json.dumps(manifest,separators=(',',':'))]
 proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
 proc.stdin.write(remote);proc.stdin.close();procs.append(proc)
# Drain all exec streams concurrently so stdout backpressure cannot cause idle timeouts.
lock=threading.Lock()
def drain(node,proc):
 for line in proc.stdout:
  row=json.loads(line)
  if isinstance(row,dict):
   if 'boundary_event' in row:
    with lock:boundary_events.append({'pod':f'vault-{node}',**row['boundary_event']})
   elif 'progress_file' in row:
    print(f"vault-{node}: scanned {row['progress_file']}",flush=True)
   else:
    with lock:node_reports.append({'pod':f'vault-{node}',**row})
   continue
  i,rid,op,items,failed,bad=row
  ident=uuid.UUID(rid).bytes
  with lock:
   if ident in seen[i]:counts[i]['duplicates']+=1;continue
   seen[i].add(ident);c=counts[i];prefix='encrypt' if op=='e' else 'decrypt'
   c[prefix+'_requests']+=1;c[prefix+'_items']+=items;c['error_items']+=failed;c['validation_errors']+=bad
 stderr=proc.stderr.read();rc=proc.wait()
 if rc:raise RuntimeError(f'Scan vault-{node} failed: '+stderr)
 print(f'Scanned vault-{node}; returned counts only.',flush=True)
with ThreadPoolExecutor(max_workers=3) as pool:
 futures=[pool.submit(drain,node,proc) for node,proc in enumerate(procs)]
 for future in futures:future.result()
summary=[]
for r,c in zip(runs,counts):
 expected={}
 for row in r['rows']:
  op=row['operation'];expected[op+'_requests']=int(row['count']);expected[op+'_items']=int(row['count'])*(r['encrypt_items'] if op=='encrypt' else 1)
 match=all(c[k]==v for k,v in expected.items()) and not c['error_items'] and not c['validation_errors']
 summary.append({'run_id':r['run_id'],'scenario':r['scenario'],'label':r['label'],'expected':expected,'observed':c,'match':match})
report={'suite_id':suite,'scope':'Retained audit responses deduplicated by request.id. Benchmark timestamps have millisecond precision: effective window [start+1ms,end+1ms). Non-batch setup encrypt calls are excluded from batch cases. Empty HMAC error strings are recognized using the HMAC of the known empty reference in these HCL fixtures.','boundary_events':boundary_events,'cases':summary,'node_reports':node_reports,'all_counts_match':all(x['match'] for x in summary),'parse_error_count':sum(len(x['parse_errors']) for x in node_reports)}
out=ROOT.parent/'runs'/f'{suite}-audit-count-verification.json';out.write_text(json.dumps(report,indent=2))
print(str(out),flush=True)
# Reconcile identifiable batch boundary records; retain intervals for ambiguous unit events.
rc=subprocess.call([sys.executable,str(ROOT/'reconcile_audit_boundaries.py'),suite])
sys.exit(rc)
