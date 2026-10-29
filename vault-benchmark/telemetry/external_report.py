"""Report the sibling-container series without replacing historical results."""
import json,statistics,hashlib
from pathlib import Path
from datetime import datetime,timezone
from common import ROOT
from report import summary_table
SUITE='20261029-tcp-external';BASE=ROOT.parent/'runs';PLAN=BASE/(SUITE+'-plan.json')
SCENARIOS=['none','file-default','tcp-default','file-combined','tcp-combined']
NAMES=['Sin audit','Fichero default','TCP externo default','Fichero combinado','TCP externo combinado']
LABELS=['unit','batch-50','batch-100','batch-250','batch-500','batch-750','batch-1000','batch-9000']
def label_name(label):return 'Unitario' if label=='unit' else 'Batch '+label.split('-')[1]
def fmt(v,n=0):
 return f'{v:,.{n}f}'.replace(',','X').replace('.',',').replace('X','.') if v is not None else 'N/D'
def metric(r,key,field='mean'):
 a=r['telemetry']['queries'].get(key,{}).get('summary',[])
 return a[0].get(field) if len(a)==1 else None
def median(v):
 v=[x for x in v if x is not None];return statistics.median(v) if v else None
def duration_ms(s):
 for unit,m in [('ms',1),('µs',.001),('us',.001),('ns',.000001),('s',1000)]:
  if s.endswith(unit):return float(s[:-len(unit)])*m
 raise ValueError(s)
def external_table(telemetry):
 rows=[('CPU receptor (cores)','external_cpu_cores',1),('Throttle receptor (%)','external_throttled_periods_pct',1),('RAM cgroup receptor (MiB, incluye caché)','external_memory_bytes',1/1024**2),('PSI memoria receptor (%)','external_memory_pressure_pct',1),('PSI IO receptor (%)','external_io_pressure_pct',1),('IOPS escritura receptor','external_write_iops',1),('IO escritura receptor (MiB/s)','external_write_bytes_per_second',1/1024**2),('Audit recibido (MiB/s)','external_received_bytes_per_second',1/1024**2),('Entradas audit/s','external_entries_per_second',1),('Errores escritura (ventanas de 60 s)','external_write_errors',1),('CPU VM completa (cores)','vm_cpu_cores',1),('RAM disponible VM (MiB)','vm_memory_available_bytes',1/1024**2)]
 rows.insert(0,('Fallos audit durante medición (ventanas de 20 s)','audit_failures_during_measurement',1))
 lines=['| Recurso externo / verificación | Media | Pico |','| --- | ---: | ---: |']
 for name,key,factor in rows:
  summaries=telemetry['queries'].get(key,{}).get('summary',[])
  means=summaries[0].get('mean') if len(summaries)==1 else None
  maximum=summaries[0].get('max') if len(summaries)==1 else None
  lines.append('| '+name+' | '+fmt(means*factor if means is not None else None,2)+' | '+fmt(maximum*factor if maximum is not None else None,2)+' |')
 return '\n'.join(lines)+'\n'

def report():
 plan=json.loads(PLAN.read_text());runs=[]
 for case in plan:
  if case.get('status')!='passed':continue
  folder=BASE/case['run_id'];r=json.loads((folder/'result.json').read_text());r.update(case)
  r['folder']=folder;r['telemetry']=json.loads((folder/'telemetry.json').read_text());r['external']=json.loads((folder/'external.json').read_text())
  r['quality']=json.loads((folder/'quality.json').read_text());r['counts']=json.loads((folder/'audit-counts.json').read_text()) if (folder/'audit-counts.json').exists() else {'status':'not_applicable','passed':True}
  enc=next(x for x in r['rows'] if x['operation']=='encrypt');r['encrypt_s']=float(enc['throughput'])*r['encrypt_items'];r['p95']=duration_ms(enc['p95']);runs.append(r)
 groups={(label,sc):[r for r in runs if r['label']==label and r['scenario']==sc] for label in LABELS for sc in SCENARIOS}
 text=['<!-- VBB-EXTERNAL-TCP-START -->','# Audit TCP con receptor fuera de Minikube','',f'Serie `{SUITE}`: **{len(runs)}/{len(plan)} casos completados**. Fecha: 29/10/2026. Esta serie tiene una línea base propia; no mezcla porcentajes con las pruebas históricas.','',
 'El receptor TCP se ejecuta como contenedor hermano de Minikube en la VM de Podman: VM de 8 CPU, Minikube con cuota de 2 CPU y receptor con cuota de 2 CPU/512 MiB. El receptor tiene volumen propio, pero ambos comparten la misma VM y el disco físico. No equivale a otra máquina. Red privada `workshop-k8s`, sin puertos publicados en el Mac.','',
 'Cinco escenarios, ocho tamaños; batch 500 tiene tres repeticiones con orden alternado, los demás una. Calentamiento inicial de 30 s, duración de 60 s, 50 workers en unitario y 10 en batch, mezcla 95/5 de peticiones encrypt/decrypt; decrypt siempre unitario. Batch 9000 contiene 8.982 elementos. Combinado significa excluir request.data y evitar HMAC en ciphertext/batch_results; log_raw=false, plaintext de decrypt unitario protegido. Eximir batch_results también afectaría al plaintext de un decrypt por lotes, que no forma parte de esta matriz.','',
 'Comparación controlada: logs nuevos en directorios por caso, fuera de los patrones de rotación histórica; no se comprimen durante la carga. El receptor escribe bytes sin parsear JSON durante la carga; el conteo y la compresión se realizan después de cada ejecución, antes de la siguiente. Esta medición no incluye analítica del audit en tiempo real. La telemetría del rotador histórico permanece activa. Se conservan los logs y resultados anteriores.','',
 'Prometheus: 11 targets, scrape cada 5 s; resumen de recursos desde inicio + 20 s hasta fin, tasas con ventana de 20 s. El receptor exporta CPU/cuota/throttle, memoria, PSI, IO por cgroup, bytes, entradas y errores. La memoria del cgroup incluye caché de ficheros. TCP y su buffer no constituyen confirmación durable por evento; se espera el cierre/drenaje y fsync del receptor al terminar cada caso.','',
 '## Rendimiento de encrypt','',
 'Elementos cifrados/s = throughput de peticiones encrypt × elementos por petición. Porcentajes frente a sin audit del mismo tamaño. Para batch 500 se muestra la mediana de las tres ejecuciones.','',
 '| Prueba | Sin audit | Fichero default | TCP externo default | Fichero combinado | TCP externo combinado |','| --- | ---: | ---: | ---: | ---: | ---: |']
 for label in LABELS:
  baseline=median([r['encrypt_s'] for r in groups[label,'none']]);cells=[label_name(label)]
  for sc in SCENARIOS:
   value=median([r['encrypt_s'] for r in groups[label,sc]])
   cells.append(fmt(value)+(f' ({fmt((value/baseline-1)*100,1)} %)' if sc!='none' and value is not None and baseline else ''))
  text.append('| '+' | '.join(cells)+' |')
 text+=['','## Latencia p95 de encrypt','','Milisegundos por petición completa. Batch 500: mediana de los p95, no p95 de una distribución agregada.','','| Prueba | Sin audit | Fichero default | TCP externo default | Fichero combinado | TCP externo combinado |','| --- | ---: | ---: | ---: | ---: | ---: |']
 for label in LABELS:text.append('| '+' | '.join([label_name(label)]+[fmt(median([r['p95'] for r in groups[label,sc]]),1) for sc in SCENARIOS])+' |')
 text+=['','## Repetibilidad y recursos de batch 500','','Medianas de las tres ejecuciones; rango de throughput observado, sin intervalo de confianza. CPU en cores; throttle expresa periodos con cuota agotada.','','| Escenario | Encrypt/s mediana [mín–máx] | p95 ms | CPU Minikube | CPU Vault | CPU receptor externo | CPU rotador | Throttle Minikube % |','| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
 for sc,name in zip(SCENARIOS,NAMES):
  group=groups['batch-500',sc]
  if not group:continue
  vals=[r['encrypt_s'] for r in group]
  cells=[name,fmt(median(vals))+' ['+fmt(min(vals))+'–'+fmt(max(vals))+']',fmt(median([r['p95'] for r in group]),1)]
  cells += [fmt(median([metric(r,k) for r in group]),2) for k in ['host_cpu_cores','vault_cpu_cores','external_cpu_cores','rotator_cpu_cores','host_throttled_periods_pct']]
  text.append('| '+' | '.join(cells)+' |')
 text+=['','### Memoria e IO de batch 500','','Medianas de las medias por ejecución, salvo RAM del receptor, que resume los picos. PSI mide tiempo con tareas esperando recursos. El await corresponde al disco de la VM, compartido por todos los contenedores. La RAM del receptor incluye caché de ficheros; su uso residual en escenarios sin TCP no representa trabajo del audit de ese caso.','','| Escenario | PSI CPU/IO Minikube % | PSI memoria Minikube % | RAM receptor pico MiB | PSI IO receptor % | Await VM ms |','| --- | ---: | ---: | ---: | ---: | ---: |']
 for sc,name in zip(SCENARIOS,NAMES):
  group=groups['batch-500',sc]
  if not group:continue
  def medmetric(key,field='mean'):return median([metric(r,key,field) for r in group])
  ram=medmetric('external_memory_bytes','max')
  text.append('| '+' | '.join([name,fmt(medmetric('host_cpu_pressure_pct'),2)+' / '+fmt(medmetric('host_io_pressure_pct'),2),fmt(medmetric('host_memory_pressure_pct'),2),fmt(ram/1024**2 if ram is not None else None,1),fmt(medmetric('external_io_pressure_pct'),2),fmt(medmetric('disk_await_ms'),2)])+' |')
 text+=['','Cada prueba conserva su tabla completa de CPU, throttling, RAM, GC, IOPS, latencia de disco, latencia del audit y métricas del receptor en `10_Transit.ipynb`; las series y consultas PromQL están en su `telemetry.json`.']
 total_requests=sum(int(row['count']) for r in runs for row in r['rows'])
 total_encrypt=sum(int(next(row for row in r['rows'] if row['operation']=='encrypt')['count'])*r['encrypt_items'] for r in runs)
 total_decrypt=sum(int(next(row for row in r['rows'] if row['operation']=='decrypt')['count']) for r in runs)
 text+=['','## Integridad y alcance','',f'Según el benchmark: **{fmt(total_requests)} peticiones**, **{fmt(total_encrypt)} elementos cifrados** y **{fmt(total_decrypt)} descifrados** en los casos completados.','',f"{sum(r['counts']['status']=='exact' for r in runs)} casos auditados con conteo exacto; {sum(r['counts']['status']=='millisecond_boundary' for r in runs)} con intervalo por precisión temporal; {sum(r['scenario']=='none' for r in runs)} sin auditoría. Se comparan tanto peticiones como elementos, deduplicando por request.id. Errores de petición, parseo y validación deben ser cero para dar por válida una ejecución.",'',
 'Cada conexión TCP tiene un fichero separado para impedir que fragmentos de nodos distintos se intercalen. Se conservan respuestas completas y batch_results; no se usa UDP ni se descartan logs. La pérdida de conexión y la persistencia deben evaluarse aparte del rendimiento.','']
 boundaries=[r for r in runs if r['counts']['status']=='millisecond_boundary']
 reviews=[r for r in runs if (r['folder']/'audit-failure-review.json').exists()]
 if reviews:
  text += ['Incidencia de preparación conservada: al habilitar el dispositivo de fichero para batch 750, `vault-1` registró un fallo de audit de request y otro de response para `sys/metrics` (`failed to persist salt: cannot write to readonly storage`), 1,843 s antes de iniciar la carga. La métrica original con ventana de 60 s arrastra esos incrementos; la consulta de 20 s dentro de la medición da cero, y las 8.107 peticiones encrypt / 434 decrypt del benchmark tienen audit exacto. Se conservan el log operativo, ambas series y la revisión en el directorio del caso.','']
 if boundaries:
  text += ['| Escenario unitario | Encrypt audit intervalo | Encrypt benchmark | Decrypt audit intervalo | Decrypt benchmark |','| --- | ---: | ---: | ---: | ---: |']
  for r in boundaries:
   cells=[r['scenario']]
   for op in ['encrypt','decrypt']:
    c=r['counts']['counts'][op];lo=c['requests']-c['boundary_requests'];hi=c['requests']
    cells += [fmt(lo)+('–'+fmt(hi) if lo!=hi else ''),fmt(c['expected_requests'])]
   text.append('| '+' | '.join(cells)+' |')
  text += ['']
 restore_path=BASE/(SUITE+'-restoration-verification.json')
 if restore_path.exists():
  restored=json.loads(restore_path.read_text());text += ['Restauración de audit y tune: **'+('verificada' if restored['passed'] else 'pendiente')+'**.','']
 conclusions=BASE/(SUITE+'-conclusions.md')
 if conclusions.exists():text += [conclusions.read_text(),'']
 text+=['Reproducción: `vault-benchmark/telemetry/EXTERNAL_TCP.md`. Artefactos: `vault-benchmark/runs/<run_id>/`; manifiesto `20261029-tcp-external-plan.json`. Fuentes: [audit socket](https://developer.hashicorp.com/vault/docs/audit/socket) y [audit devices](https://developer.hashicorp.com/vault/docs/audit).','<!-- VBB-EXTERNAL-TCP-END -->','']
 summary='\n'.join(text);(BASE/(SUITE+'-summary.md')).write_text(summary)
 nbpath=ROOT.parent.parent/'10_Transit.ipynb';nb=json.loads(nbpath.read_text())
 nb['cells']=[c for c in nb['cells'] if not c.get('metadata',{}).get('vbb_external')]
 def md(source,id):return {'cell_type':'markdown','id':id,'metadata':{'vbb_external':True},'source':source.splitlines(True)}
 nb['cells'].append(md('# Audit TCP externo — receptor fuera de Minikube\n\nEsta sección conserva los resultados de la serie independiente del 29/10. Reproducción y topología: `vault-benchmark/telemetry/EXTERNAL_TCP.md`.\n','vbb-external-intro'))
 nb['cells'].append({'cell_type':'code','id':'vbb-external-run','metadata':{'vbb_external':True},'execution_count':None,'source':['# Ejecutar desde Bash tras cargar /tmp/vault/config.env (no imprimir credenciales).\n','# VBB_STATE_DIR=/tmp/vault/vbb-tcp-external VBB_SUITE_ID=20261029-tcp-external python3 vault-benchmark/telemetry/external_suite.py\n'],'outputs':[]})
 notebook_runs=list(runs)
 compression_plan=BASE/'20261029-tcp-compression-plan.json'
 if compression_plan.exists():
  for case in json.loads(compression_plan.read_text()):
   if case.get('status')!='passed':continue
   folder=BASE/case['run_id'];r=json.loads((folder/'result.json').read_text());r.update(case)
   r.update(folder=folder,telemetry=json.loads((folder/'telemetry.json').read_text()),counts=json.loads((folder/'audit-counts.json').read_text()))
   notebook_runs.append(r)
 for i,r in enumerate(notebook_runs):
  phase='Diagnóstico con compresión: ' if r.get('phase')=='compression' else ''
  note='\nIncidencia anterior a la carga: dos fallos de audit de sys/metrics durante la habilitación del dispositivo, 1,843 s antes del inicio. La ventana de 60 s los arrastra; la ventana de 20 s durante la medición da cero. Evidencia: audit-failure-review.json y audit-failure-operational.log.\n' if (r['folder']/'audit-failure-review.json').exists() else ''
  nb['cells'].append(md(f"## {phase}{r['scenario']} / {r['label']} / repetición {r['repeat']}\n\nRun: `{r['run_id']}`. Conteo audit: **{r['counts']['status']}**.\n"+note,'vbb-ext-title-'+str(i)))
  output=(r['folder']/'benchmark.txt').read_text()+'\n'+summary_table({'telemetry':r['telemetry']}).replace('Socket MiB/s / errores de escritura','Socket UNIX previo (inactivo) MiB/s / errores de escritura')+'\n'+external_table(r['telemetry'])
  source=("from pathlib import Path\nimport json, sys\nsys.path.insert(0, 'vault-benchmark/telemetry')\nfrom report import summary_table\nfrom external_report import external_table\n"
          +"folder = Path('vault-benchmark/runs/"+r['run_id']+"')\n"
          +"telemetry = json.loads((folder / 'telemetry.json').read_text())\n"
          +"print((folder / 'benchmark.txt').read_text() + '\\n' + summary_table({'telemetry': telemetry}).replace('Socket MiB/s / errores de escritura', 'Socket UNIX previo (inactivo) MiB/s / errores de escritura') + '\\n' + external_table(telemetry), end='')\n")
  nb['cells'].append({'cell_type':'code','id':'vbb-ext-case-'+str(i),'metadata':{'vbb_external':True,'vbb_external_run_id':r['run_id']},'execution_count':i+1,'source':source.splitlines(True),'outputs':[{'output_type':'stream','name':'stdout','text':output.splitlines(True)}]})
 for name,title in [('resilience','Interrupción breve del receptor: API y audit por separado'),('resilience-extended','Interrupción prolongada: espera de 15 s antes de cada fase'),('reconnect-verification','Control positivo al recrear el dispositivo TCP'),('delivery-verification','Verificación del receptor entregado')]:
  artifact=BASE/(SUITE+'-'+name+'.json')
  if not artifact.exists():continue
  nb['cells'].append(md('## '+title+'\n','vbb-ext-'+name+'-title'))
  source="from pathlib import Path\nprint(Path('vault-benchmark/runs/"+artifact.name+"').read_text(), end='')\n"
  nb['cells'].append({'cell_type':'code','id':'vbb-ext-'+name,'metadata':{'vbb_external':True},'execution_count':len(notebook_runs)+1,'source':source.splitlines(True),'outputs':[{'output_type':'stream','name':'stdout','text':artifact.read_text().splitlines(True)}]})
 nb['cells'].append(md(summary,'vbb-external-summary'))
 nbpath.write_text(json.dumps(nb,ensure_ascii=False,indent=2)+'\n')
 print(f'Reported {len(runs)}/{len(plan)} cases')
if __name__=='__main__':report()
