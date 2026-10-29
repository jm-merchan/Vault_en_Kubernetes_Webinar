<!-- VBB-EXTERNAL-TCP-START -->
# Audit TCP con receptor fuera de Minikube

Serie `20261029-tcp-external`: **50/50 casos completados**. Fecha: 29/10/2026. Esta serie tiene una línea base propia; no mezcla porcentajes con las pruebas históricas.

El receptor TCP se ejecuta como contenedor hermano de Minikube en la VM de Podman: VM de 8 CPU, Minikube con cuota de 2 CPU y receptor con cuota de 2 CPU/512 MiB. El receptor tiene volumen propio, pero ambos comparten la misma VM y el disco físico. No equivale a otra máquina. Red privada `workshop-k8s`, sin puertos publicados en el Mac.

Cinco escenarios, ocho tamaños; batch 500 tiene tres repeticiones con orden alternado, los demás una. Calentamiento inicial de 30 s, duración de 60 s, 50 workers en unitario y 10 en batch, mezcla 95/5 de peticiones encrypt/decrypt; decrypt siempre unitario. Batch 9000 contiene 8.982 elementos. Combinado significa excluir request.data y evitar HMAC en ciphertext/batch_results; log_raw=false, plaintext de decrypt unitario protegido. Eximir batch_results también afectaría al plaintext de un decrypt por lotes, que no forma parte de esta matriz.

Comparación controlada: logs nuevos en directorios por caso, fuera de los patrones de rotación histórica; no se comprimen durante la carga. El receptor escribe bytes sin parsear JSON durante la carga; el conteo y la compresión se realizan después de cada ejecución, antes de la siguiente. Esta medición no incluye analítica del audit en tiempo real. La telemetría del rotador histórico permanece activa. Se conservan los logs y resultados anteriores.

Prometheus: 11 targets, scrape cada 5 s; resumen de recursos desde inicio + 20 s hasta fin, tasas con ventana de 20 s. El receptor exporta CPU/cuota/throttle, memoria, PSI, IO por cgroup, bytes, entradas y errores. La memoria del cgroup incluye caché de ficheros. TCP y su buffer no constituyen confirmación durable por evento; se espera el cierre/drenaje y fsync del receptor al terminar cada caso.

## Rendimiento de encrypt

Elementos cifrados/s = throughput de peticiones encrypt × elementos por petición. Porcentajes frente a sin audit del mismo tamaño. Para batch 500 se muestra la mediana de las tres ejecuciones.

| Prueba | Sin audit | Fichero default | TCP externo default | Fichero combinado | TCP externo combinado |
| --- | ---: | ---: | ---: | ---: | ---: |
| Unitario | 2.286 | 1.859 (-18,7 %) | 1.879 (-17,8 %) | 1.560 (-31,8 %) | 1.574 (-31,1 %) |
| Batch 50 | 156.717 | 63.494 (-59,5 %) | 60.866 (-61,2 %) | 65.927 (-57,9 %) | 62.836 (-59,9 %) |
| Batch 100 | 239.832 | 82.374 (-65,7 %) | 79.080 (-67,0 %) | 92.979 (-61,2 %) | 87.290 (-63,6 %) |
| Batch 250 | 324.682 | 91.246 (-71,9 %) | 90.187 (-72,2 %) | 124.657 (-61,6 %) | 113.368 (-65,1 %) |
| Batch 500 | 384.933 | 101.019 (-73,8 %) | 102.993 (-73,2 %) | 135.030 (-64,9 %) | 123.301 (-68,0 %) |
| Batch 750 | 392.698 | 101.196 (-74,2 %) | 103.966 (-73,5 %) | 124.501 (-68,3 %) | 129.552 (-67,0 %) |
| Batch 1000 | 385.839 | 100.753 (-73,9 %) | 110.429 (-71,4 %) | 122.345 (-68,3 %) | 126.370 (-67,2 %) |
| Batch 9000 | 497.000 | 108.300 (-78,2 %) | 116.618 (-76,5 %) | 141.467 (-71,5 %) | 154.560 (-68,9 %) |

## Latencia p95 de encrypt

Milisegundos por petición completa. Batch 500: mediana de los p95, no p95 de una distribución agregada.

| Prueba | Sin audit | Fichero default | TCP externo default | Fichero combinado | TCP externo combinado |
| --- | ---: | ---: | ---: | ---: | ---: |
| Unitario | 85,5 | 90,6 | 79,0 | 95,0 | 93,0 |
| Batch 50 | 25,8 | 40,4 | 45,7 | 38,0 | 37,9 |
| Batch 100 | 30,9 | 64,2 | 50,6 | 52,1 | 45,9 |
| Batch 250 | 52,8 | 74,1 | 86,2 | 59,2 | 78,7 |
| Batch 500 | 55,4 | 102,2 | 103,6 | 92,5 | 95,2 |
| Batch 750 | 76,0 | 159,8 | 153,5 | 128,8 | 110,5 |
| Batch 1000 | 88,3 | 200,3 | 186,0 | 190,8 | 165,7 |
| Batch 9000 | 325,8 | 1.244,5 | 1.159,7 | 1.003,4 | 889,7 |

## Repetibilidad y recursos de batch 500

Medianas de las tres ejecuciones; rango de throughput observado, sin intervalo de confianza. CPU en cores; throttle expresa periodos con cuota agotada.

| Escenario | Encrypt/s mediana [mín–máx] | p95 ms | CPU Minikube | CPU Vault | CPU receptor externo | CPU rotador | Throttle Minikube % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Sin audit | 384.933 [378.249–421.648] | 55,4 | 1,98 | 1,58 | 0,00 | 0,00 | 100,00 |
| Fichero default | 101.019 [98.356–103.718] | 102,2 | 1,99 | 1,72 | 0,00 | 0,00 | 100,00 |
| TCP externo default | 102.993 [102.205–104.350] | 103,6 | 1,99 | 1,72 | 0,08 | 0,00 | 100,00 |
| Fichero combinado | 135.030 [126.296–135.576] | 92,5 | 1,99 | 1,72 | 0,00 | 0,00 | 100,00 |
| TCP externo combinado | 123.301 [117.883–136.142] | 95,2 | 1,99 | 1,68 | 0,04 | 0,00 | 100,00 |

### Memoria e IO de batch 500

Medianas de las medias por ejecución, salvo RAM del receptor, que resume los picos. PSI mide tiempo con tareas esperando recursos. El await corresponde al disco de la VM, compartido por todos los contenedores. La RAM del receptor incluye caché de ficheros; su uso residual en escenarios sin TCP no representa trabajo del audit de ese caso.

| Escenario | PSI CPU/IO Minikube % | PSI memoria Minikube % | RAM receptor pico MiB | PSI IO receptor % | Await VM ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| Sin audit | 66,17 / 0,13 | 0,00 | 237,8 | 0,00 | 0,27 |
| Fichero default | 74,12 / 0,22 | 0,00 | 171,2 | 0,00 | 2,70 |
| TCP externo default | 73,93 / 0,22 | 0,00 | 512,0 | 13,48 | 0,81 |
| Fichero combinado | 71,81 / 0,16 | 0,00 | 141,9 | 0,00 | 1,01 |
| TCP externo combinado | 72,38 / 0,21 | 0,00 | 512,0 | 0,00 | 1,13 |

Cada prueba conserva su tabla completa de CPU, throttling, RAM, GC, IOPS, latencia de disco, latencia del audit y métricas del receptor en `10_Transit.ipynb`; las series y consultas PromQL están en su `telemetry.json`.

## Integridad y alcance

Según el benchmark: **2.109.813 peticiones**, **422.382.145 elementos cifrados** y **105.635 descifrados** en los casos completados.

36 casos auditados con conteo exacto; 4 con intervalo por precisión temporal; 10 sin auditoría. Se comparan tanto peticiones como elementos, deduplicando por request.id. Errores de petición, parseo y validación deben ser cero para dar por válida una ejecución.

Cada conexión TCP tiene un fichero separado para impedir que fragmentos de nodos distintos se intercalen. Se conservan respuestas completas y batch_results; no se usa UDP ni se descartan logs. La pérdida de conexión y la persistencia deben evaluarse aparte del rendimiento.

Incidencia de preparación conservada: al habilitar el dispositivo de fichero para batch 750, `vault-1` registró un fallo de audit de request y otro de response para `sys/metrics` (`failed to persist salt: cannot write to readonly storage`), 1,843 s antes de iniciar la carga. La métrica original con ventana de 60 s arrastra esos incrementos; la consulta de 20 s dentro de la medición da cero, y las 8.107 peticiones encrypt / 434 decrypt del benchmark tienen audit exacto. Se conservan el log operativo, ambas series y la revisión en el directorio del caso.

| Escenario unitario | Encrypt audit intervalo | Encrypt benchmark | Decrypt audit intervalo | Decrypt benchmark |
| --- | ---: | ---: | ---: | ---: |
| file-default | 111.732–111.733 | 111.732 | 5.969 | 5.969 |
| tcp-default | 112.780–112.781 | 112.780 | 5.939 | 5.939 |
| file-combined | 93.640–93.641 | 93.640 | 4.925 | 4.925 |
| tcp-combined | 94.466–94.467 | 94.466 | 4.938 | 4.938 |

Restauración de audit y tune: **verificada**.

## Diagnóstico de compresión durante la carga

Dos ejecuciones adicionales de 60 s, batch 500 combinado. En fichero se aplica logrotate cada 2 s, umbral de 64 MiB, gzip y delaycompress; en TCP se rota al completar una línea y se comprime en el receptor externo. Son políticas distintas y una sola ejecución por variante; permiten observar dónde consume CPU la compresión, no establecer una ventaja universal de un colector.

| Escenario combinado | Encrypt/s | Variación vs. sin audit | p95 ms | CPU rotador en Minikube | CPU receptor externo |
| --- | ---: | ---: | ---: | ---: | ---: |
| Fichero, sin compresión durante carga — mediana de 3 | 135.030 | -64,9 % | 92,5 | 0,00 | 0,00 |
| Fichero, con compresión — 1 ejecución | 114.523 | -70,2 % | 102,1 | 0,15 | 0,00 |
| TCP, sin compresión durante carga — mediana de 3 | 123.301 | -68,0 % | 95,2 | 0,00 | 0,04 |
| TCP, con compresión — 1 ejecución | 126.699 | -67,1 % | 95,6 | 0,00 | 0,21 |

La referencia es la mediana de batch 500 sin audit de esta serie: 384.933 elementos/s. Ambos casos adicionales tienen 100 % de éxito y conteo exacto tras leer también los ficheros comprimidos. El rotador del caso fichero alcanza 0,30 cores de pico y compite con Vault por la cuota de Minikube. En TCP, el trabajo de compresión queda fuera de esa cuota. El resultado de TCP con compresión está dentro del rango observado en sus tres ejecuciones sin compresión.

## Interrupción y recuperación del receptor

Se hicieron dos diagnósticos: una parada/arranque breve y una repetición esperando 15 s con el receptor parado y otros 15 s después de arrancarlo antes de enviar las peticiones de recuperación. Cada petición cifra dos elementos. El segundo diagnóstico usa el receptor entregado y confirma que sólo estaba habilitado el dispositivo TCP de prueba y que el contenedor estaba parado durante la fase de indisponibilidad.

| Diagnóstico | Fase | Peticiones | HTTP 200 | Respuestas localizadas en audit |
| --- | --- | ---: | ---: | ---: |
| Breve | Antes de parar | 10 | 10 | 10 |
| Breve | Receptor parado | 3 | 3 | 0 |
| Breve | Tras arrancar | 10 | 10 | 0 |
| Con espera de 15 s | Antes de parar | 10 | 10 | 10 |
| Con espera de 15 s | Receptor parado | 3 | 3 | 0 |
| Con espera de 15 s | Tras arrancar | 10 | 10 | 0 |

**La recuperación de la API no acreditó recuperación de la entrega del audit.** En esta topología y versión de Vault no se observó reconexión efectiva dentro de la ventana ensayada. Al recrear expresamente el dispositivo TCP, un control positivo volvió a registrar ambas respuestas de encrypt/decrypt, con batch_results y HMAC de plaintext correctos. No se simularon cortes de alimentación ni se midió recuperación tras esperas más largas. HashiCorp documenta la posibilidad de omitir entradas TCP tras perder la conexión aunque la petición tenga éxito: [audit socket](https://developer.hashicorp.com/vault/docs/audit/socket).

Los IDs, fases y tiempos se conservan en los artefactos `resilience`, `resilience-extended` y `reconnect-verification`. El receptor entregado incluye nombres de fichero únicos entre reinicios, con conservación verificada del contenido anterior; las imágenes medida y entregada quedan identificadas en `delivery-verification`. Esta corrección de nombres no cambia la lógica de recepción/escritura medida ni resuelve por sí sola la reconexión del emisor.

## Interpretación de los resultados

**El límite más claro en este laboratorio es la cuota compartida de CPU de Minikube.** En batch 500 se consumen 1,98–1,99 de sus 2 cores y aparece throttling en el 100 % de los periodos; esto no significa estar detenido el 100 % del tiempo. Vault consume aproximadamente 1,6–1,7 cores. La VM utiliza alrededor de 2,8–3,0 de sus 8 CPU y dispone de unos 8 GiB de RAM. No aparecen OOM ni presión de memoria en Minikube. El receptor alcanza su límite de memoria principalmente con caché de ficheros; esa cifra no equivale a heap/RSS.

El disco compartido tiene actividad y latencia, pero las medianas de batch 500 no muestran saturación global: aproximadamente 2–5 % de ocupación y 0,27–2,70 ms de await. Sí hay espera de IO en el receptor TCP default (PSI de alrededor del 13,5 %). La evidencia permite priorizar CPU en este laboratorio, sin atribuir toda la penalización a HMAC ni descartar otros límites en máquinas distintas; no se ha hecho un perfil de CPU por función.

**Sacar el receptor de Minikube no elimina el coste principal de auditoría.** En batch 500, las medianas default son 101.019 con fichero y 102.993 con TCP; en combinado, 135.030 y 123.301. Los rangos se solapan y no hay una mejora uniforme en toda la matriz. TCP combinado llega a 154.560 elementos/s en batch 9000, pero con p95 de 890 ms, frente a 126.370 y 166 ms en batch 1000. El máximo de throughput no determina por sí solo el batch adecuado.

El siguiente experimento de capacidad con más fundamento sería aumentar la cuota CPU de Minikube y separar el generador de carga, conservando payload, mezcla, audit y telemetría. La compresión fuera de la cuota de Vault sí evita competencia local por CPU. Para auditoría que deba contabilizar todas las operaciones, este receptor TCP aislado no queda validado como único destino: la entrega ante fallos necesita un diseño adicional y una nueva prueba. La batería no representa tres máquinas independientes ni demuestra capacidad productiva de una arquitectura de Performance Replication.

Estado final: auditoría original `scep-intune-validation/` y ajuste HMAC de Transit restaurados y verificados; tres pods de Vault listos, sin reinicios durante las pruebas. Prometheus y el receptor externo permanecen disponibles para inspección, con 11 targets activos y sin puertos publicados en el Mac. El receptor TCP ya no está conectado al audit de Vault.


Reproducción: `vault-benchmark/telemetry/EXTERNAL_TCP.md`. Artefactos: `vault-benchmark/runs/<run_id>/`; manifiesto `20261029-tcp-external-plan.json`. Fuentes: [audit socket](https://developer.hashicorp.com/vault/docs/audit/socket) y [audit devices](https://developer.hashicorp.com/vault/docs/audit).
<!-- VBB-EXTERNAL-TCP-END -->
