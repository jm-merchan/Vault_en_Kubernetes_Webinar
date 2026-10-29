# Transit: Prometheus y comparación file/socket

Instrumentación para el laboratorio `workshop-k8s`, namespace `vault`, y el notebook `10_Transit.ipynb`. La matriz contiene ocho tamaños (1, 50, 100, 250, 500, 750, 1000 y **8982**, aunque el fichero se llame 9000) y siete escenarios: sin audit; file default, sin request.data y combinado; socket con las mismas tres configuraciones. Combinado excluye request.data y desactiva HMAC únicamente para las claves de respuesta `ciphertext` y `batch_results`. `log_raw=false` en todos los escenarios con audit. Decrypt es unitario y se verifica que su plaintext siga con HMAC. El tune se aplica por clave de respuesta en todo el mount: la excepción `batch_results` también afectaría al contenido de una respuesta de decrypt por lotes, que no forma parte de esta matriz.

En macOS, la suite y el runner individual inhiben temporalmente el reposo con `caffeinate -is -w <PID>` mientras trabajan. Las series preliminares se conservan como diagnóstico; no se mezclan con la serie final. Antes de la serie final se corrige postrotate a `pkill -HUP -x vault` para evitar que el rotador se termine a sí mismo y deje el pod en CrashLoopBackOff. La compresión continúa habilitada.

Cada test dura 60 s con los HCL del proyecto: 50 workers unitario, 10 en batches, mezcla de **peticiones** encrypt/decrypt 95/5, decrypt unitario y HTTP/1.1. Encrypt/s = throughput de peticiones exitosas × elementos del batch; no equivale a peticiones/s ni a una mezcla 95/5 de elementos.

## Ejecutar desde la raíz del proyecto

Requiere Python 3.9+, kubectl, CA/credenciales ya configuradas en `/tmp/vault/config.env`, el clúster de laboratorio y la imagen local `vault-benchmark:demo`. No ejecutar en producción. La preparación suspende temporalmente los dispositivos de auditoría existentes y guarda su configuración; recrearlos cambia sus claves HMAC. Para esta sesión el operador autorizó explícitamente ese cambio.

```bash
set -a
source /tmp/vault/config.env
set +a
```

```bash
bash ./vault-benchmark/telemetry/start.sh
```

```bash
python3 ./vault-benchmark/telemetry/scenarios.py prepare --allow-suspend-audit
```

```bash
VBB_SUITE_ID=20261028-prometheus-final python3 -u ./vault-benchmark/telemetry/suite.py
```

La matriz recorre escenarios y tamaños en orden, con una ejecución de 60 s por caso. La compresión puede procesar archivos de casos anteriores: las tablas marcan su consumo y los resultados no incluyen intervalos de confianza. La suite reanuda únicamente los casos pendientes de ese identificador. Para una nueva serie usar otro `VBB_SUITE_ID`; guardar previamente cualquier estado de restauración de la sesión anterior. La configuración original se guarda fuera del repositorio, en `/tmp/vault/vbb-observability/original.json`, con permisos 0600. No borrarla hasta verificar la restauración.

Un caso individual (después de preparar la sesión):

```bash
bash ./vault-benchmark/run-observed.sh socket-default ./vault-benchmark/vb-transit-100.hcl batch-100
```

Restaurar después de ejecutar casos individuales o de una interrupción, cuando el Job haya terminado o se haya detenido:

```bash
python3 ./vault-benchmark/telemetry/scenarios.py restore
```

```bash
python3 ./vault-benchmark/telemetry/report.py 20261028-prometheus-final
```

`report.py` actualiza las celdas identificadas por metadata en el notebook y genera `vault-benchmark/runs/<suite>-summary.md`. Si macOS permite acceder al vault de Obsidian, actualiza únicamente su bloque delimitado `VBB-PROMETHEUS`; si ese acceso está denegado, conserva el informe exportado y deja pendiente la sincronización en la aplicación. No interpreta ese fallo como un fallo del benchmark.

## Auditoría utilizada

El controlador de escenarios verifica que no haya otro dispositivo activo durante la medición. Los equivalentes CLI son:

```bash
vault audit enable \
  -local \
  -path=vbb \
  file \
  file_path=/vault/audit/benchmark-audit.json \
  log_raw=false
```

```bash
vault audit enable \
  -local \
  -path=vbb \
  socket \
  socket_type=unix \
  address=/vault/audit/benchmark.sock \
  write_timeout=2s \
  log_raw=false
```

A los escenarios sin request.data se añade:

```text
exclude='[{"condition":"\"/request/mount_type\" == transit","fields":["/request/data"]}]'
```

El controlador escribe la lista completa de claves non-HMAC mediante la API de tune, evitando ambigüedad entre flags repetidos. `-local` limita la replicación de la configuración del dispositivo entre clústeres; cada nodo que procesa peticiones necesita su destino local disponible.

## Qué se mide

Prometheus scrapea cada 5 s los tres nodos Vault, kubelet `/metrics/resource` (CPU y memoria por contenedor), cAdvisor, node_exporter, el cgroup padre de Minikube y los receptores de socket. El token de Prometheus solo tiene read/list en `sys/metrics`, TTL de 24 h; se guarda en un Secret. La instrumentación no cambia listeners ni reinicia Vault. Tras vencer el token hay que renovarlo o volver a ejecutar la preparación de observabilidad.

Las tasas usan ventanas de 20 s. Las tablas resumen las muestras desde inicio+20 s hasta fin para excluir preparación y transición; se conservan las muestras desde inicio−20 s hasta fin+5 s. `N/D` significa ausencia de datos, nunca cero. Los tiempos internos de auditoría de Vault se expresan en milisegundos.

| Recurso | Métricas y criterio |
| --- | --- |
| CPU | Cores de Vault, generador, receptor, logrotate y Prometheus; cuota real del cgroup padre; periodos con throttling y presión CPU. 100% de periodos con throttling no significa perder el 100% del tiempo de CPU. |
| RAM | Working set de Vault por contenedor y agregado; heap asignado y memoria del runtime (working set incluye más que heap), actividad de GC; memoria y límite del cgroup padre, presión de memoria y OOM. Memoria alta sin presión/OOM no basta para atribuir el cuello de botella a RAM. |
| Disco | IOPS, bytes/s, ocupación, await y cola de `/dev/vda`; presión IO y fechas de rotación. Son métricas compartidas de la VM, no IOPS físicos exclusivos de audit. |
| Auditoría | Duración request/response global y del dispositivo, fallos, volumen de socket, errores del receptor y ficheros/rotaciones. |
| Distribución | Peticiones por pod para contrastar el reparto real del Service entre activo y performance standbys. |

En este laboratorio los tres pods, generador, observabilidad y rotadores comparten **2 CPU efectivas**, aunque Kubernetes anuncie 8 CPU. Raft, audit y Prometheus comparten el disco de la VM. El resultado no representa tres máquinas independientes. Los receptores permanecen activos en todos los escenarios para mantener la misma instrumentación.

El receptor usa el mismo UID/GID que Vault (100/1000), de modo que el rotador puede leer y comprimir sus ficheros 0600. El socket UNIX termina en un receptor por PVC que escribe todos los bytes a `benchmark-socket.json`, incluido en el logrotate existente. Se evita UDP y no se descartan registros. El receptor sigue renombrados/reaperturas. La confirmación de envío al socket **no confirma fsync ni entrega duradera**; este receptor de laboratorio no es un colector con garantías de entrega de producción. `test_receiver.py` verifica conservación byte a byte y reapertura tras rotación sin reiniciar la conexión.

`validate.py` realiza un round-trip sintético antes de cada caso y verifica en el destino: request.data según escenario, dos elementos contables de batch_results, estado HMAC del ciphertext y plaintext de decrypt protegido. No guarda datos de prueba ni secretos en el informe de validación.

## Evidencia por ejecución

En `vault-benchmark/runs/<UTC-scenario-label>/`:

- `configuration.json`, `config.hcl`: audit/tune efectivos, workers y hash del HCL.
- `benchmark.txt`, `result.json`: salida original, operaciones, latencias y ventana exacta.
- `audit-validation.json`: comprobación funcional del audit.
- `resources.json`: recursos de contenedores Vault, sin variables de credenciales.
- `telemetry.json`: PromQL, muestras crudas y resúmenes; errores de consulta explícitos.
- `rotator-logs.json`: logs de los tres rotadores en la ventana.

Conservar el estado y los resultados antes de limpiar el laboratorio. Prometheus y receptores se mantienen para inspección. **No retirar un receptor mientras un dispositivo socket dependa de él.** El estado original se restaura antes de retirar el audit de benchmark.

Fuentes: [telemetría de Vault](https://developer.hashicorp.com/vault/docs/configuration/telemetry), [referencia de métricas](https://developer.hashicorp.com/vault/docs/internals/telemetry), [audit socket](https://developer.hashicorp.com/vault/docs/audit/socket), [node_exporter](https://github.com/prometheus/node_exporter).

## Validación final

```bash
python3 ./vault-benchmark/telemetry/verify_suite.py 20261028-prometheus-final
```

Con las credenciales del laboratorio cargadas, verificar también la restauración del audit original, el tune de Transit y la salud de los tres pods:

```bash
python3 ./vault-benchmark/telemetry/verify_restoration.py 20261028-prometheus-final
```

Después de restaurar el audit original, contrastar los registros conservados con los contadores del benchmark:

```bash
python3 ./vault-benchmark/telemetry/verify_audit_counts.py 20261028-prometheus-final
```

Este escáner lee los ficheros actuales y rotados de los tres PVC, fija sus inodos antes de leer, cuenta únicamente respuestas Transit dentro de cada ventana y deduplica por request.id. Solo salen del pod IDs, contadores y flags de validación; no payloads. Comprueba elementos, errores y HMAC/exclusiones. Si la retención ya eliminó historia, informa de la discrepancia: no la presenta como entrega completa.

El contador trata dos particularidades de esta batería: las marcas del benchmark tienen precisión de milisegundos (ventana efectiva `[inicio+1ms, fin+1ms)`; se guardan los eventos de frontera), y los encrypt unitarios de preparación no pertenecen a los casos de batch. Además, un `error` vacío puede quedar como una cadena HMAC no vacía. Para estos HCL, donde `reference` está vacío, el verificador reconoce el HMAC del error vacío comparándolo con el de `reference`, y exige ciphertext y versión de clave válidos; no interpreta cualquier cadena HMAC en `error` como un fallo real. Esta regla depende de los fixtures y se debe revisar si se añade `reference`.

`verify_audit_counts.py` llama a `reconcile_audit_boundaries.py`: las respuestas batch del primer milisegundo se identifican por su cardinalidad; las unitarias ambiguas se conservan como intervalo inferior/superior. Preparación y carga pueden reutilizar la misma conexión TCP, por lo que ese dato por sí solo no permite clasificarlas. El resultado diferencia coincidencia exacta, coherencia dentro del margen temporal y discrepancia. Se conservan los contadores anteriores a la conciliación.
