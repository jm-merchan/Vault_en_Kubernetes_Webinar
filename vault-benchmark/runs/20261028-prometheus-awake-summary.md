<!-- VBB-PROMETHEUS-START -->
# Pruebas con Prometheus y audit por socket

Serie `20261028-prometheus-awake`: **29/56 pruebas completas**. Actualizado 28/10/2026 21:52 CET. Los apartados anteriores corresponden a la serie histórica del 27/10 sin esta instrumentación.

Serie ejecutada con `caffeinate` para impedir reposo del Mac. La serie preliminar `20261028-prometheus` se conserva como diagnóstico y no se usa para calcular estos porcentajes: macOS registró reposos repetidos que coincidieron con desfases/saltos del reloj de la VM, scrapes fallidos y errores de benchmark.

Mismos HCL, 50 workers unitario y 10 en batches; 60 s, peticiones encrypt/decrypt 95/5; encrypt por batch y decrypt unitario. Todos los escenarios de esta serie incluyen la misma observabilidad. Vault Enterprise 2.2.0, tres pods en un único nodo Minikube, **cuota agregada de 2 CPU**; Raft, audit y Prometheus comparten el dispositivo `/dev/vda` de la VM. Estas métricas no equivalen a IOPS físicos exclusivos del audit ni a tres máquinas de producción.

Prometheus scrapea cada 5 s: Vault por nodo autenticado con token de solo métricas, kubelet resource, cAdvisor, node_exporter, cuota/pressure del cgroup padre y receptores. Tasas con ventanas de 20 s; resumen desde inicio+20 s hasta fin para excluir preparación y transición. Se conservan PromQL y series crudas por ejecución; N/D significa dato ausente, nunca cero.

Socket: `socket_type=unix`, `/vault/audit/benchmark.sock`, receptor local por PVC que escribe todos los bytes en `benchmark-socket.json` y sigue la rotación. No se descartan logs ni se usa UDP. La escritura de Vault al socket y la persistencia final son fases distintas: el retorno de socket no acredita fsync del receptor. Se mantienen receptor y Prometheus también durante file y sin audit para comparar con igual instrumentación.

Todos los porcentajes son frente a **sin audit del mismo tamaño de esta serie**; combinado significa exclusión de request.data más ciphertext/batch_results sin HMAC.

| Prueba | Sin audit ops/s | File default | File sin request.data | File combinado | Socket default | Socket sin request.data | Socket combinado |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| unit | 2.437 | 2.104 (-13,7 %) | 1.828 (-25,0 %) | 1.985 (-18,6 %) | Pendiente | Pendiente | Pendiente |
| batch-50 | 206.266 | 78.917 (-61,7 %) | 76.203 (-63,1 %) | 55.477 (-73,1 %) | Pendiente | Pendiente | Pendiente |
| batch-100 | 280.076 | 94.374 (-66,3 %) | 81.856 (-70,8 %) | 111.956 (-60,0 %) | Pendiente | Pendiente | Pendiente |
| batch-250 | 388.727 | 104.784 (-73,0 %) | 58.005 (-85,1 %) | 137.689 (-64,6 %) | Pendiente | Pendiente | Pendiente |
| batch-500 | 448.368 | 119.394 (-73,4 %) | 72.971 (-83,7 %) | 105.421 (-76,5 %) | Pendiente | Pendiente | Pendiente |
| batch-750 | 455.990 | 123.485 (-72,9 %) | 129.515 (-71,6 %) | Pendiente | Pendiente | Pendiente | Pendiente |
| batch-1000 | 488.457 | 120.005 (-75,4 %) | 72.074 (-85,2 %) | Pendiente | Pendiente | Pendiente | Pendiente |
| batch-9000 | 573.488 | 99.824 (-82,6 %) | 150.527 (-73,8 %) | Pendiente | Pendiente | Pendiente | Pendiente |

Valores en elementos cifrados/s. La mezcla 95/5 corresponde a peticiones, no a elementos: el peso de encrypt crece con el batch. Cada celda proviene de una ejecución de 60 s, sin intervalo de confianza.

## Sin audit — recursos por prueba

| Prueba | CPU host media cores | Throttle periodos % | RAM Vault pico MiB | IOPS media/pico | Disco ocupado media % | Await ms | Audit req/resp ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| unit | 1,99 | 100,0 | 2.191,9 | 408,4/485,6 | 2,4 | 0,21 | 0,00/0,00 |
| batch-50 | 1,98 | 100,0 | 2.148,4 | 420,8/519,9 | 2,5 | 0,21 | 0,00/0,00 |
| batch-100 | 1,98 | 100,0 | 2.163,7 | 374,5/389,9 | 2,3 | 0,20 | 0,00/0,00 |
| batch-250 | 1,99 | 100,0 | 2.178,5 | 378,0/389,3 | 2,2 | 0,23 | 0,00/0,00 |
| batch-500 | 1,98 | 99,1 | 2.241,8 | 417,6/513,8 | 2,3 | 0,16 | 0,00/0,00 |
| batch-750 | 1,98 | 100,0 | 2.256,3 | 375,1/392,9 | 2,0 | 0,18 | 0,00/0,00 |
| batch-1000 | 1,98 | 100,0 | 2.292,0 | 372,8/390,6 | 2,1 | 0,16 | 0,00/0,00 |
| batch-9000 | 1,99 | 100,0 | 2.453,6 | 371,1/385,7 | 2,1 | 0,16 | 0,00/0,00 |

## File default — recursos por prueba

| Prueba | CPU host media cores | Throttle periodos % | RAM Vault pico MiB | IOPS media/pico | Disco ocupado media % | Await ms | Audit req/resp ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| unit | 1,99 | 100,0 | 2.579,1 | 422,9/537,3 | 2,9 | 0,39 | 4,68/2,99 |
| batch-50 | 1,98 | 100,0 | 4.919,3 | 411,2/445,1 | 4,8 | 1,73 | 0,64/1,17 |
| batch-100 | 1,98 | 100,0 | 6.318,6 | 403,1/435,2 | 4,9 | 1,89 | 1,28/2,99 |
| batch-250 | 1,99 | 100,0 | 3.808,7 | 401,4/443,2 | 4,6 | 1,30 | 3,09/8,56 |
| batch-500 | 1,99 | 100,0 | 5.979,9 | 385,9/395,5 | 5,3 | 1,77 | 6,62/18,56 |
| batch-750 | 1,99 | 100,0 | 6.353,1 | 388,2/410,9 | 4,7 | 1,91 | 9,72/29,12 |
| batch-1000 | 1,99 | 100,0 | 6.321,7 | 389,2/402,7 | 4,9 | 1,77 | 13,71/40,71 |
| batch-9000 | 2,00 | 100,0 | 3.466,6 | 593,5/797,3 | 7,0 | 3,36 | 161,03/479,75 |

## File sin request.data — recursos por prueba

| Prueba | CPU host media cores | Throttle periodos % | RAM Vault pico MiB | IOPS media/pico | Disco ocupado media % | Await ms | Audit req/resp ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| unit | 1,99 | 100,0 | 3.644,6 | 416,1/538,3 | 2,6 | 0,37 | 5,67/3,85 |
| batch-50 | 1,98 | 100,0 | 5.035,2 | 396,1/423,6 | 3,6 | 1,06 | 0,70/1,26 |
| batch-100 | 1,98 | 100,0 | 6.436,0 | 455,0/650,5 | 4,5 | 1,38 | 1,44/3,13 |
| batch-250 | 1,99 | 100,0 | 2.667,3 | 518,2/707,0 | 6,3 | 2,21 | 5,51/16,28 |
| batch-500 | 2,00 | 100,0 | 2.664,4 | 419,8/436,0 | 5,2 | 1,24 | 9,89/31,66 |
| batch-750 | 1,99 | 100,0 | 4.200,0 | 456,8/647,6 | 3,9 | 0,80 | 9,15/27,56 |
| batch-1000 | 2,00 | 100,0 | 4.412,7 | 820,9/1.253,7 | 6,4 | 2,35 | 23,38/71,82 |
| batch-9000 | 1,99 | 100,0 | 3.679,5 | 500,4/660,3 | 4,2 | 0,77 | 100,02/315,02 |

## File combinado — recursos por prueba

| Prueba | CPU host media cores | Throttle periodos % | RAM Vault pico MiB | IOPS media/pico | Disco ocupado media % | Await ms | Audit req/resp ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| unit | 1,99 | 100,0 | 3.829,7 | 371,0/394,6 | 2,5 | 0,44 | 5,12/3,56 |
| batch-50 | 1,99 | 100,0 | 3.259,9 | 519,0/746,7 | 5,6 | 0,80 | 1,42/1,95 |
| batch-100 | 1,98 | 100,0 | 4.169,9 | 374,4/397,4 | 2,9 | 0,45 | 1,16/1,98 |
| batch-250 | 1,98 | 100,0 | 5.163,8 | 376,3/389,4 | 2,7 | 0,49 | 2,75/5,43 |
| batch-500 | 1,99 | 100,0 | 5.494,1 | 429,3/478,3 | 4,7 | 0,72 | 8,16/19,02 |
| batch-750 | Pendiente | — | — | — | — | — | — |
| batch-1000 | Pendiente | — | — | — | — | — | — |
| batch-9000 | Pendiente | — | — | — | — | — | — |

## Socket default — recursos por prueba

| Prueba | CPU host media cores | Throttle periodos % | RAM Vault pico MiB | IOPS media/pico | Disco ocupado media % | Await ms | Audit req/resp ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| unit | Pendiente | — | — | — | — | — | — |
| batch-50 | Pendiente | — | — | — | — | — | — |
| batch-100 | Pendiente | — | — | — | — | — | — |
| batch-250 | Pendiente | — | — | — | — | — | — |
| batch-500 | Pendiente | — | — | — | — | — | — |
| batch-750 | Pendiente | — | — | — | — | — | — |
| batch-1000 | Pendiente | — | — | — | — | — | — |
| batch-9000 | Pendiente | — | — | — | — | — | — |

## Socket sin request.data — recursos por prueba

| Prueba | CPU host media cores | Throttle periodos % | RAM Vault pico MiB | IOPS media/pico | Disco ocupado media % | Await ms | Audit req/resp ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| unit | Pendiente | — | — | — | — | — | — |
| batch-50 | Pendiente | — | — | — | — | — | — |
| batch-100 | Pendiente | — | — | — | — | — | — |
| batch-250 | Pendiente | — | — | — | — | — | — |
| batch-500 | Pendiente | — | — | — | — | — | — |
| batch-750 | Pendiente | — | — | — | — | — | — |
| batch-1000 | Pendiente | — | — | — | — | — | — |
| batch-9000 | Pendiente | — | — | — | — | — | — |

## Socket combinado — recursos por prueba

| Prueba | CPU host media cores | Throttle periodos % | RAM Vault pico MiB | IOPS media/pico | Disco ocupado media % | Await ms | Audit req/resp ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| unit | Pendiente | — | — | — | — | — | — |
| batch-50 | Pendiente | — | — | — | — | — | — |
| batch-100 | Pendiente | — | — | — | — | — | — |
| batch-250 | Pendiente | — | — | — | — | — | — |
| batch-500 | Pendiente | — | — | — | — | — | — |
| batch-750 | Pendiente | — | — | — | — | — | — |
| batch-1000 | Pendiente | — | — | — | — | — | — |
| batch-9000 | Pendiente | — | — | — | — | — | — |

## Calidad de la captura

Los targets permanecieron disponibles en todas las muestras de las ventanas resumidas.

Las ventanas se correlacionan con los timestamps del Job y de Prometheus dentro de la VM. Los nombres de directorio usan el reloj del Mac; la referencia temporal de las consultas procede del clúster. Los desfases y saltos observados en la serie preliminar motivaron repetir la matriz completa evitando reposo.

## Coincidencias con rotación y compresión

El mtime de un fichero rotado es una señal de actividad, no la hora exacta de ejecución de logrotate. Se contrasta con CPU del contenedor rotador. Filas con consumo medio del rotador mayor de 0,05 cores durante la ventana de resumen:

| Escenario | Prueba | CPU rotador media/pico | CPU Vault media | CPU host media |
| --- | --- | ---: | ---: | ---: |
| file-default | batch-9000 | 0,37 / 0,70 | 1,41 | 2,00 |
| file-no-request | batch-100 | 0,14 / 0,62 | 1,54 | 1,98 |
| file-no-request | batch-250 | 0,75 / 0,76 | 1,02 | 1,99 |
| file-no-request | batch-500 | 0,60 / 0,70 | 1,15 | 2,00 |
| file-no-request | batch-1000 | 0,68 / 0,71 | 1,11 | 2,00 |
| file-combined | batch-50 | 0,66 / 0,84 | 1,16 | 1,99 |
| file-combined | batch-500 | 0,48 / 0,50 | 1,25 | 1,99 |

Se observaron reinicios del contenedor `auditlog-rotator` con salida 129. El comando configurado `pkill -HUP vault` coincide con `vault` y `vault-logrotate` (verificado con pgrep); `pkill -HUP -x vault` limitaría la señal al proceso de Vault. Esta configuración se mantuvo durante la matriz para conservar las condiciones.


Estas coincidencias pueden explicar parte de la variación; una sola ejecución no permite atribuir todo el descenso al dispositivo audit.

Interpretación: CPU próxima a la cuota junto con throttling y presión CPU indica contención; RAM alta por sí sola no prueba escasez (consultar presión/OOM); IOPS por sí solos no prueban saturación de disco (contrastar await, cola, presión IO y rotaciones). La carga del generador, receptores, logrotate y Prometheus se conserva por contenedor para distinguirla de Vault.

Fuentes técnicas: [telemetría](https://developer.hashicorp.com/vault/docs/configuration/telemetry) y [audit socket](https://developer.hashicorp.com/vault/docs/audit/socket).

Artefactos: `vault-benchmark/runs/<run_id>/` contiene validación de HMAC/exclusiones y round-trip sintético, HCL y hash, configuración audit/tune, recursos, salida completa, timestamps, PromQL, series y logs del rotador.
<!-- VBB-PROMETHEUS-END -->
