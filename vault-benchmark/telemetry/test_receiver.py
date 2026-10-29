import tempfile,subprocess,sys,os,socket,time,json,urllib.request
from pathlib import Path
with tempfile.TemporaryDirectory() as d:
 env=dict(os.environ,VBB_AUDIT_ROOT=d,VBB_METRICS_PORT='19102')
 proc=subprocess.Popen([sys.executable,str(Path(__file__).with_name('receiver.py'))],env=env)
 try:
  for i in range(50):
   if (Path(d)/'benchmark.sock').exists():break
   time.sleep(.1)
  message=(json.dumps({'test':'x'*2100000})+'\n').encode()
  c=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);c.connect(d+'/benchmark.sock');c.sendall(message)
  path=Path(d)/'benchmark-socket.json'
  for i in range(100):
   if path.exists() and path.stat().st_size==len(message):break
   time.sleep(.05)
  assert path.read_bytes()==message
  path.rename(Path(d)/'rotated.json');c.sendall(b'{"after_rotation":true}\n');c.close()
  for i in range(100):
   if path.exists() and path.stat().st_size==24:break
   time.sleep(.05)
  assert json.loads(path.read_text())=={'after_rotation':True}
  metrics=urllib.request.urlopen('http://127.0.0.1:19102').read().decode()
  assert 'vbb_socket_write_errors_total 0' in metrics
  assert 'vbb_socket_entries_written_total 2' in metrics
  print('Receiver verified: >2MB NDJSON entry preserved byte-for-byte; continued connection follows rotation; 2 entries, 0 errors.')
 finally:proc.terminate();proc.wait()
