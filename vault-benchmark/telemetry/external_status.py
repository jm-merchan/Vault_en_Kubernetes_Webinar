import json
from pathlib import Path
p=Path(__file__).resolve().parent.parent/'runs/20261029-tcp-external-plan.json'
a=json.loads(p.read_text());done=[c for c in a if c.get('status')=='passed'];print(f'{len(done)}/{len(a)} verified')
for c in done[-5:]:
 d=p.parent/c['run_id'];r=json.loads((d/'result.json').read_text());e=next(x for x in r['rows'] if x['operation']=='encrypt');t=json.loads((d/'telemetry.json').read_text())
 def m(k):
  s=t['queries'][k]['summary'];return round(s[0]['mean'],3) if len(s)==1 else None
 print(c['scenario'],c['label'],'r'+str(c['repeat']),round(float(e['throughput'])*r['encrypt_items']),e['p95'],'CPU mini/ext/rot',m('host_cpu_cores'),m('external_cpu_cores'),m('rotator_cpu_cores'),c['count_status'])
