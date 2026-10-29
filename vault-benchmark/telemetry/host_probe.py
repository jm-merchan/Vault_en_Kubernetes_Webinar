"""Read the Minikube parent cgroup; node CPU count is not its CPU quota."""
from pathlib import Path
import http.server,os
C=Path('/host-cgroup')
def collect():
 lines=[]
 def emit(k,v,labels=''):lines.append(f'vbb_host_{k}{labels} {v}')
 for filename,prefix in [('cpu.stat','cpu'),('memory.events','memory_events')]:
  for l in (C/filename).read_text().splitlines():
   k,v=l.split();emit(prefix+'_'+k.replace('.','_')+('_total' if filename=='cpu.stat' or filename=='memory.events' else ''),v)
 quota,period=(C/'cpu.max').read_text().split();emit('cpu_quota_cores',float(quota)/float(period) if quota!='max' else -1)
 for f in ['memory.current','memory.max']:
  val=(C/f).read_text().strip();emit(f.replace('.','_')+'_bytes',val if val!='max' else -1)
 for kind in ['cpu','memory','io']:
  f=C/(kind+'.pressure')
  if f.exists():
   for l in f.read_text().splitlines():
    parts=l.split();v=dict(x.split('=') for x in parts[1:]);emit(kind+'_pressure_seconds_total',float(v['total'])/1e6,'{stall="'+parts[0]+'"}')
 for node in range(3):
  root=Path('/audit-'+str(node));files=[x for x in root.iterdir() if x.is_file()]
  labels='{pod="vault-'+str(node)+'"}'
  emit('audit_files_bytes',sum(x.stat().st_size for x in files),labels)
  rotated=[x for x in files if x.name.endswith('.gz') or any(x.name.endswith('.'+str(n)) for n in range(1,10))]
  emit('audit_last_rotation_mtime_seconds',max([x.stat().st_mtime for x in rotated] or [0]),labels)
 return '\n'.join(lines)+'\n'
class Handler(http.server.BaseHTTPRequestHandler):
 def do_GET(self):
  try:body=collect().encode();self.send_response(200)
  except Exception as e:body=str(e).encode();self.send_response(500)
  self.send_header("Content-Type","text/plain; version=0.0.4");self.end_headers();self.wfile.write(body)
 def log_message(self,*args):pass
http.server.ThreadingHTTPServer(('0.0.0.0',9103),Handler).serve_forever()
