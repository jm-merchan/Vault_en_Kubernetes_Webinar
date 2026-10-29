"""Keep notebook outputs and a bounded Obsidian summary synchronized per run."""
import json,re,os
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from common import ROOT
SCENARIOS=['none','file-default','file-no-request','file-combined','socket-default','socket-no-request','socket-combined']
LABELS=['unit','batch-50','batch-100','batch-250','batch-500','batch-750','batch-1000','batch-9000']
NAMES=['Sin audit','File default','File sin request.data','File combinado','Socket default','Socket sin request.data','Socket combinado']
def metric(t,key,field='mean'):
 v=t['queries'].get(key,{}).get('summary',[])
 return v[0].get(field) if v else None
def fmt(n,d=1):return 'N/D' if n is None else f'{n:,.{d}f}'.replace(',','X').replace('.',',').replace('X','.')
def duration_ms(value):
 m=re.fullmatch(r'([\d.]+)(ns|us|µs|ms|s)',value)
 if not m:raise ValueError('Unsupported duration: '+value)
 return float(m[1])*{'ns':1e-6,'us':1e-3,'µs':1e-3,'ms':1,'s':1000}[m[2]]
def load_runs(suite):
 result={}
 for f in sorted((ROOT.parent/'runs').glob('*/result.json')):
  r=json.loads(f.read_text())
  if r.get('suite_id')!=suite:continue
  r['folder']=f.parent;r['telemetry']=json.loads((f.parent/'telemetry.json').read_text());result[(r['scenario'],r['label'])]=r
 return result
def summary_table(r):
 t=r['telemetry'];mean=lambda k:metric(t,k);peak=lambda k:metric(t,k,'max')
 gaps=[x['labels'].get('job','?')+('/'+x['labels']['pod'] if 'pod' in x['labels'] else '') for x in t['queries']['target_up']['summary'] if x['min']!=1]
 pairs=[('Calidad de captura', 'Scrapes intermitentes: '+', '.join(gaps) if gaps else 'Targets disponibles en las muestras'),('CPU Minikube (cores / cuota)',fmt(mean('host_cpu_cores'),2)+' / '+fmt(mean('host_cpu_quota_cores'),1)),('Periodos con throttling Minikube (%)',fmt(mean('host_throttled_periods_pct'))),('CPU Vault / generador / observabilidad (cores)', ' / '.join(fmt(mean(k),2) for k in ['vault_cpu_cores','benchmark_cpu_cores','monitoring_cpu_cores'])),('CPU rotador / receptor socket (cores)', ' / '.join(fmt(mean(k),2) for k in ['rotator_cpu_cores','receiver_cpu_cores'])),('Presión CPU / IO / memoria (%)', ' / '.join(fmt(mean(k),2) for k in ['host_cpu_pressure_pct','host_io_pressure_pct','host_memory_pressure_pct'])),('Memoria Vault pico (MiB)',fmt(peak('vault_memory_bytes')/2**20 if peak('vault_memory_bytes') is not None else None)),('Heap asignado Vault pico (MiB)',fmt(peak('vault_heap_alloc_bytes')/2**20 if peak('vault_heap_alloc_bytes') is not None else None)),('OOM observados en el cgroup (máximo)',fmt(peak('host_oom_events'),0)),('Disco IOPS media / pico',fmt(mean('disk_iops'))+' / '+fmt(peak('disk_iops'))),('Escritura disco media (MiB/s)',fmt(mean('disk_write_bytes_per_second')/2**20 if mean('disk_write_bytes_per_second') is not None else None,2)),('Disco ocupado media / pico (%)',fmt(mean('disk_busy_pct'))+' / '+fmt(peak('disk_busy_pct'))),('Disco await medio (ms)',fmt(mean('disk_await_ms'),2)),('Cola de disco media',fmt(mean('disk_queue_depth'),3)),('Audit request / response medio (ms)',fmt(mean('audit_request_ms'),2)+' / '+fmt(mean('audit_response_ms'),2)),('Fallos audit (máximo de ventanas 60 s)',fmt(peak('audit_failures'),0)),('Socket MiB/s / errores de escritura',fmt(mean('socket_bytes_per_second')/2**20 if mean('socket_bytes_per_second') is not None else None,2)+' / '+fmt(peak('socket_write_errors'),0))]
 return '| Métrica | Resultado |\n| --- | ---: |\n'+''.join('| '+a+' | '+b+' |\n' for a,b in pairs)
def update(suite):
 runs=load_runs(suite);nb=ROOT.parent.parent/'10_Transit.ipynb';raw=nb.read_text();n=json.loads(raw)
 for c in n['cells']:
  meta=c.get('metadata',{});key=(meta.get('vbb_scenario'),meta.get('vbb_label'))
  if meta.get('vbb_config_scenario'):
   candidates=[r for (sc,label),r in runs.items() if sc==meta['vbb_config_scenario']]
   if candidates:
    conf=json.loads((candidates[-1]['folder']/'configuration.json').read_text())
    value=conf[meta['vbb_config_field']] if meta.get('vbb_config_field') else {k:conf[k] for k in ['scenario','audit','transit_tune']}
    c['outputs']=[{'output_type':'stream','name':'stdout','text':(json.dumps(value,ensure_ascii=False,indent=2)+'\n').splitlines(keepends=True)}];c['execution_count']=None
  if key not in runs:continue
  r=runs[key];text=(r['folder']/'benchmark.txt').read_text()
  text+='\nPROMETHEUS: '+r['run_id']+'\n'+summary_table(r)+'\nArtifacts: '+str(r['folder'])+'\n'
  c['outputs']=[{'output_type':'stream','name':'stdout','text':text.splitlines(keepends=True)}];c['execution_count']=None
 if nb.read_text()!=raw:raise RuntimeError('Notebook changed while writing')
 nb.write_text(json.dumps(n,ensure_ascii=False,indent=2)+'\n')
 notes=Path('/Users/jose/Library/Mobile Documents/iCloud~md~obsidian/Documents/Vault/Customers')
 note=None
 try:
  note=next(notes.glob('*/Pruebas Audit Logging.md'),None)
  text=note.read_text() if note else None
 except OSError as e:
  print('Obsidian filesystem unavailable: '+str(e));text=None
 start='<!-- VBB-PROMETHEUS-START -->';end='<!-- VBB-PROMETHEUS-END -->'
 body=start+'\n# Pruebas con Prometheus y audit por socket\n\n'
 body+=f'Serie `{suite}`: **{len(runs)}/56 pruebas completas**. Actualizado {datetime.now(ZoneInfo("Europe/Madrid")).strftime("%d/%m/%Y %H:%M %Z")}. Los apartados anteriores corresponden a la serie histórica del 27/10 sin esta instrumentación.\n\n'
 body+='Serie ejecutada con `caffeinate` para impedir reposo del Mac. Las series preliminares `20261028-prometheus` (reposos de macOS) y `20261028-prometheus-awake` (reinicios del rotador) se conservan como diagnóstico y no se usan para calcular estos porcentajes. La matriz final se repite completa con reloj estable y el postrotate corregido a `pkill -HUP -x vault`.\n\n'
 body+='Mismos HCL, 50 workers unitario y 10 en batches; 60 s, peticiones encrypt/decrypt 95/5; encrypt por batch y decrypt unitario. **Batch 9000 contiene realmente 8.982 elementos**. Todos los escenarios de esta serie incluyen la misma observabilidad. Vault Enterprise 2.2.0, tres pods en un único nodo Minikube, **cuota agregada de 2 CPU**; Raft, audit y Prometheus comparten el dispositivo `/dev/vda` de la VM. Estas métricas no equivalen a IOPS físicos exclusivos del audit ni a tres máquinas de producción.\n\n'
 body+='Prometheus scrapea cada 5 s: Vault por nodo autenticado con token de solo métricas, kubelet resource, cAdvisor, node_exporter, cuota/pressure del cgroup padre y receptores. Tasas con ventanas de 20 s; resumen desde inicio+20 s hasta fin para excluir preparación y transición. Se conservan PromQL y series crudas por ejecución; N/D significa dato ausente, nunca cero.\n\n'
 body+='Socket: `socket_type=unix`, `/vault/audit/benchmark.sock`, receptor local por PVC que escribe todos los bytes en `benchmark-socket.json` y sigue la rotación. No se descartan logs ni se usa UDP. La escritura de Vault al socket y la persistencia final son fases distintas: el retorno de socket no acredita fsync del receptor. Se mantienen receptor y Prometheus también durante file y sin audit para comparar con igual instrumentación.\n\n'
 body+='Todos los porcentajes son frente a **sin audit del mismo tamaño de esta serie**; combinado significa exclusión de request.data más ciphertext/batch_results sin HMAC. Decrypt es unitario y su plaintext permanece con HMAC, verificado en cada caso. La excepción batch_results es de todo el mount y también afectaría a una respuesta decrypt por lotes, fuera de esta matriz ([tune del mount](https://developer.hashicorp.com/vault/api-docs/system/mounts#tune-mount-configuration)).\n\n'
 body+='| Prueba | Sin audit ops/s | File default | File sin request.data | File combinado | Socket default | Socket sin request.data | Socket combinado |\n| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |\n'
 for label in LABELS:
  base=runs.get(('none',label));basev=float(next(x for x in base['rows'] if x['operation']=='encrypt')['throughput'])*base['encrypt_items'] if base else None
  row=[label]
  for sc in SCENARIOS:
   r=runs.get((sc,label))
   if not r:row.append('Pendiente');continue
   v=float(next(x for x in r['rows'] if x['operation']=='encrypt')['throughput'])*r['encrypt_items']
   rotation=metric(r['telemetry'],'rotator_cpu_cores')
   mark=' †' if rotation is not None and rotation>0.05 else ''
   row.append(fmt(v,0)+((' ('+fmt((v/basev-1)*100)+' %)') if sc!='none' and basev else '')+mark)
  body+='| '+' | '.join(row)+' |\n'
 body+='\nValores en elementos cifrados/s. **†** coincide con consumo medio del rotador >0,05 cores: la variación incluye esa competencia por CPU. La mezcla 95/5 corresponde a peticiones, no a elementos: el peso de encrypt crece con el batch. Cada celda proviene de una ejecución de 60 s, sin intervalo de confianza.\n\n'
 body+='En las tablas de recursos, PSI (some) es el porcentaje de tiempo con alguna tarea esperando CPU, IO o memoria ([definición del kernel](https://docs.kernel.org/accounting/psi.html)). Throttle es el porcentaje de periodos con cuota CPU agotada; no expresa el porcentaje de tiempo de CPU perdido.\n\n'
 body+='## Latencia p95 de encrypt\n\n'
 body+='Milisegundos por petición completa; en batch incluye todos sus elementos.\n\n'
 body+='| Prueba | Sin audit | File default | File sin request.data | File combinado | Socket default | Socket sin request.data | Socket combinado |\n| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |\n'
 for label in LABELS:
  row=[label]
  for sc in SCENARIOS:
   r=runs.get((sc,label))
   row.append(fmt(duration_ms(next(x for x in r['rows'] if x['operation']=='encrypt')['p95'])) if r else 'Pendiente')
  body+='| '+' | '.join(row)+' |\n'
 body+='\nDecrypt procesa un elemento por petición y representa aproximadamente el 5 % de peticiones generadas. Sus tasas y latencias completas están en el notebook y los artefactos; esta mezcla no mide su capacidad máxima aislada.\n\n'
 for sc,name in zip(SCENARIOS,NAMES):
  body+='## '+name+' — recursos por prueba\n\n'
  body+='| Prueba | CPU host/Vault/rotador media cores | Throttle %; PSI CPU/IO/RAM % | RAM WS/heap pico MiB | IOPS media/pico | Disco ocupado media % | Await ms | Audit req/resp ms |\n| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |\n'
  for label in LABELS:
   r=runs.get((sc,label))
   if not r:body+='| '+label+' | Pendiente | — | — | — | — | — | — |\n';continue
   t=r['telemetry'];m=lambda k:metric(t,k);pk=lambda k:metric(t,k,'max')
   row=[label,'/'.join(fmt(m(k),2) for k in ['host_cpu_cores','vault_cpu_cores','rotator_cpu_cores']),fmt(m('host_throttled_periods_pct'))+'; '+'/'.join(fmt(m(k),2) for k in ['host_cpu_pressure_pct','host_io_pressure_pct','host_memory_pressure_pct']),' / '.join(fmt(pk(k)/2**20 if pk(k) is not None else None) for k in ['vault_memory_bytes','vault_heap_alloc_bytes']),fmt(m('disk_iops'))+'/'+fmt(pk('disk_iops')),fmt(m('disk_busy_pct')),fmt(m('disk_await_ms'),2),fmt(m('audit_request_ms'),2)+'/'+fmt(m('audit_response_ms'),2)]
   body+='| '+' | '.join(row)+' |\n'
  body+='\n'
 body+='## Calidad de la captura\n\n'
 gaps=[]
 for (sc,label),r in runs.items():
  bad=[x['labels'].get('job','?')+('/'+x['labels']['pod'] if 'pod' in x['labels'] else '') for x in r['telemetry']['queries']['target_up']['summary'] if x['min']!=1]
  if bad:gaps.append((sc,label,', '.join(bad)))
 if gaps:
  body+='Estos tests terminaron, pero tuvieron fallos de scrape durante la ventana resumida. Sus métricas pueden tener huecos y no deben interpretarse como una captura continua:\n\n| Escenario | Prueba | Targets con huecos |\n| --- | --- | --- |\n'
  for row in gaps:body+='| '+' | '.join(row)+' |\n'
 else:body+='Los targets permanecieron disponibles en todas las muestras de las ventanas resumidas.\n'
 clock_changes=[]
 for r in runs.values():
  f=r['folder']/'quality.json'
  if f.exists():
   q=json.loads(f.read_text())
   if 'clock_offset_change_seconds' in q:clock_changes.append(abs(q['clock_offset_change_seconds']))
 if clock_changes:body+='\nVariación máxima del desfase Mac/Prometheus antes y después de los tests instrumentados: '+fmt(max(clock_changes),3)+' s ('+str(len(clock_changes))+' comprobaciones).\n'
 body+='\nLas ventanas se correlacionan con los timestamps del Job y de Prometheus dentro de la VM. Los nombres de directorio usan el reloj del Mac; la referencia temporal de las consultas procede del clúster. Los desfases y saltos observados en la serie preliminar motivaron repetir la matriz completa evitando reposo.\n\n'
 body+='## Coincidencias con rotación y compresión\n\n'
 body+='El mtime de un fichero rotado es una señal de actividad, no la hora exacta de ejecución de logrotate. Se contrasta con CPU del contenedor rotador. Filas con consumo medio del rotador mayor de 0,05 cores durante la ventana de resumen:\n\n'
 body+='| Escenario | Prueba | CPU rotador media/pico | CPU Vault media | CPU host media |\n| --- | --- | ---: | ---: | ---: |\n'
 for (sc,label),r in runs.items():
  t=r['telemetry'];v=metric(t,'rotator_cpu_cores')
  if v is not None and v>0.05:
   body+='| '+' | '.join([sc,label,fmt(v,2)+' / '+fmt(metric(t,'rotator_cpu_cores','max'),2),fmt(metric(t,'vault_cpu_cores'),2),fmt(metric(t,'host_cpu_cores'),2)])+' |\n'
 body+='\nEn las series preliminares, `pkill -HUP vault` coincidía con `vault` y `vault-logrotate` (verificado con pgrep). El rotador terminaba con salida 129 y acumulaba CrashLoopBackOff, retirando pods del Service. Se corrigió a `pkill -HUP -x vault` antes de esta matriz y se verificó la configuración efectiva en los tres sidecars, sin reiniciar Vault. La compresión sigue habilitada: su coste de CPU permanece en la medición.\n\n'
 body+='\nLa compresión puede procesar archivos de escenarios anteriores. Estas coincidencias pueden explicar parte de la variación; una sola ejecución no permite atribuir todo el descenso al dispositivo audit.\n\n'
 body+='Interpretación: CPU próxima a la cuota junto con throttling y presión CPU indica contención; RAM alta por sí sola no prueba escasez (consultar presión/OOM); IOPS por sí solos no prueban saturación de disco (contrastar await, cola, presión IO y rotaciones). La carga del generador, receptores, logrotate y Prometheus se conserva por contenedor para distinguirla de Vault.\n\n'
 conclusions=ROOT.parent/'runs'/f'{suite}-conclusions.json'
 if conclusions.exists():
  extra=json.loads(conclusions.read_text())
  if sorted(extra.get('run_ids',[]))==sorted(r['run_id'] for r in runs.values()):body+=extra['markdown'].rstrip()+'\n\n'
 audit_check=ROOT.parent/'runs'/f'{suite}-audit-count-verification.json'
 if audit_check.exists():
  check=json.loads(audit_check.read_text())
  expected_ids=sorted(r['run_id'] for r in runs.values() if r['scenario']!='none')
  if sorted(x['run_id'] for x in check['cases'])!=expected_ids:
   raise RuntimeError('Audit count verification belongs to different run IDs; regenerate it')
  exact=sum(x.get('verification_status')=='exact' for x in check['cases'])
  ambiguous=[x for x in check['cases'] if x.get('verification_status')=='consistent_with_millisecond_boundary']
  body+='## Verificación del conteo en audit\n\n'
  batch_exact=sum(x.get('verification_status')=='exact' and x['label']!='unit' for x in check['cases'])
  body+=str(exact)+'/'+str(len(check['cases']))+' casos tienen conteo exacto, incluidos **'+str(batch_exact)+' casos batch**. En '+str(len(ambiguous))+' casos unitarios el contador del benchmark queda dentro de un intervalo de una petición por precisión temporal. Líneas con error de parseo: '+str(check['parse_error_count'])+'. Errores de elementos detectados: '+str(sum(x['observed']['error_items'] for x in check['cases']))+'; discrepancias HMAC/exclusiones: '+str(sum(x['observed']['validation_errors'] for x in check['cases']))+'.\n\n'
  body+='Se leen respuestas de los tres PVC y se deduplica por request.id. Las marcas del benchmark tienen precisión de milisegundos: se inspecciona `[inicio, fin+1ms)` y se conserva el primer milisegundo como frontera. Los encrypt unitarios de preparación se excluyen de casos batch; las respuestas batch en esa frontera se identifican por su cardinalidad. En unitarios, preparación y carga pueden compartir conexión y no se fuerza una clasificación. El HMAC de un error vacío se reconoce usando el reference vacío de estos HCL, además de ciphertext y key_version. Se conservan contadores originales y evidencia de frontera; el alcance son los ficheros retenidos.\n\n'
  if ambiguous:
   body+='| Escenario | Prueba | Encrypt: intervalo audit | Encrypt: benchmark | Decrypt: audit / benchmark |\n| --- | --- | ---: | ---: | ---: |\n'
   for x in ambiguous:
    interval=x['audit_count_interval'];o=x['observed'];e=x['expected']
    body+='| '+' | '.join([x['scenario'],x['label'],fmt(interval['lower']['encrypt_requests'],0)+'–'+fmt(interval['upper']['encrypt_requests'],0),fmt(e['encrypt_requests'],0),fmt(o['decrypt_requests'],0)+' / '+fmt(e['decrypt_requests'],0)])+' |\n'
   body+='\n'
  bad=[x for x in check['cases'] if x.get('verification_status')=='discrepancy']
  if bad:
   body+='Discrepancias fuera del margen temporal: '+', '.join(x['scenario']+'/'+x['label'] for x in bad)+'. Consultar el JSON antes de inferir entrega completa.\n\n'
 restoration=ROOT.parent/'runs'/f'{suite}-restoration-verification.json'
 if restoration.exists():
  restored=json.loads(restoration.read_text())
  body+='## Estado al finalizar\n\n'
  if restored['passed']:
   body+='Restauración verificada: '+', '.join('`'+x+'`' for x in restored['audit_device_names'])+'. El dispositivo vbb de la batería queda deshabilitado y el tune de HMAC de Transit vuelve a su valor anterior. Se mantienen Prometheus, receptores y Transit/orders para inspección y repetición.\n\n'
  else:body+='Restauración con incidencias: '+', '.join(restored['errors'])+'. Consultar el JSON de verificación.\n\n'
 body+='Fuentes técnicas: [telemetría](https://developer.hashicorp.com/vault/docs/configuration/telemetry) y [audit socket](https://developer.hashicorp.com/vault/docs/audit/socket).\n\n'
 body+='Artefactos: `vault-benchmark/runs/<run_id>/` contiene validación de HMAC/exclusiones y round-trip sintético, HCL y hash, configuración audit/tune, recursos, salida completa, timestamps, PromQL, series y logs del rotador.\n'+end
 export=ROOT.parent/'runs'/f'{suite}-summary.md'
 export.write_text(body+'\n')
 if text is None:
  print('Summary saved to '+str(export)+'; Obsidian sync pending.');return
 if start in text:text=text[:text.index(start)]+body+text[text.index(end)+len(end):]
 else:text=text.rstrip()+'\n\n'+body+'\n'
 note.write_text(text)
if __name__=='__main__':
 import sys
 update(sys.argv[1])
