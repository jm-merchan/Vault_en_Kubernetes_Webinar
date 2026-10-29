"""UNIX audit receiver for the lab: append every byte, follow external rotation."""
import os,socket,threading,time,http.server
from pathlib import Path
ROOT=Path(os.getenv('VBB_AUDIT_ROOT','/vault/audit')); SOCK=ROOT/'benchmark.sock'; FILE=ROOT/'benchmark-socket.json'
metrics={'bytes_written_total':0,'entries_written_total':0,'write_errors_total':0,'connections_total':0}
lock=threading.Lock()
def handle(conn):
 fd=None
 try:
  while True:
   chunk=conn.recv(1024*1024)
   if not chunk:break
   with lock:
    if fd is None or not FILE.exists() or os.fstat(fd).st_ino!=FILE.stat().st_ino:
     if fd is not None:os.close(fd)
     fd=os.open(FILE,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
    view=memoryview(chunk)
    while view:
     n=os.write(fd,view); view=view[n:]
    metrics['bytes_written_total']+=len(chunk)
    metrics['entries_written_total']+=chunk.count(b'\n')
 except Exception:
  metrics['write_errors_total']+=1
 finally:
  if fd is not None:os.close(fd)
  conn.close()
class Metrics(http.server.BaseHTTPRequestHandler):
 def do_GET(self):
  with lock: body=''.join(f'vbb_socket_{k} {v}\n' for k,v in metrics.items()).encode()
  self.send_response(200);self.send_header("Content-Type","text/plain; version=0.0.4");self.end_headers();self.wfile.write(body)
 def log_message(self,*args):pass
threading.Thread(target=http.server.ThreadingHTTPServer(('0.0.0.0',int(os.getenv('VBB_METRICS_PORT','9102'))),Metrics).serve_forever,daemon=True).start()
SOCK.unlink(missing_ok=True)
s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);s.bind(str(SOCK));os.chmod(SOCK,0o666);s.listen(32)
while True:
 conn,_=s.accept();metrics['connections_total']+=1
 threading.Thread(target=handle,args=(conn,),daemon=True).start()
