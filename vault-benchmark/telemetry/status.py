"""Read-only progress and quality summary from saved artifacts."""
import os,sys,json
from report import load_runs,metric,fmt
suite=sys.argv[1] if len(sys.argv)>1 else os.getenv('VBB_SUITE_ID','20261028-prometheus-final')
runs=load_runs(suite)
passed=sum(len(r['rows'])==2 and all(float(x['success_pct'])==100 for x in r['rows']) for r in runs.values())
gaps=sum(any(x['min']!=1 for x in r['telemetry']['queries']['target_up']['summary']) for r in runs.values())
print(f'{suite}: {len(runs)}/56 casos; {passed} con 100% de peticiones exitosas; {gaps} con huecos de scrape.')
if runs:
 r=max(runs.values(),key=lambda x:x['start']);e=next(x for x in r['rows'] if x['operation']=='encrypt');t=r['telemetry']
 print(r['scenario'],r['label'],fmt(float(e['throughput'])*r['encrypt_items'],0)+' encrypt/s','p95='+e['p95'])
 baseline=runs.get(('none',r['label']))
 if baseline and r['scenario']!='none':
  b=next(x for x in baseline['rows'] if x['operation']=='encrypt')
  delta=(float(e['throughput'])*r['encrypt_items']/(float(b['throughput'])*baseline['encrypt_items'])-1)*100
  print('Frente a sin audit:',fmt(delta)+'%')
 print('CPU host='+fmt(metric(t,'host_cpu_cores'),2),'Vault='+fmt(metric(t,'vault_cpu_cores'),2),'rotador='+fmt(metric(t,'rotator_cpu_cores'),2),'disco ocupado='+fmt(metric(t,'disk_busy_pct'))+'%')
 q=r['folder']/'quality.json'
 if q.exists():
  d=json.loads(q.read_text());print('Cambio desfase reloj:',d.get('clock_offset_change_seconds','N/D'),'s; errores consulta:',len(d.get('query_errors',{})))

if runs and (r["folder"]/"pods-after.json").exists():
 before=json.loads((r["folder"]/"resources.json").read_text());after=json.loads((r["folder"]/"pods-after.json").read_text())
 b={(p["name"],c["name"]):c["restartCount"] for p in before for c in p["statuses"]}
 a={(p["name"],c["name"]):c["restartCount"] for p in after for c in p["statuses"]}
 print("Reinicios durante ultimo test:",sum(a[k]-b[k] for k in a),"; pods listos:",all(c["ready"] for p in after for c in p["statuses"]))
