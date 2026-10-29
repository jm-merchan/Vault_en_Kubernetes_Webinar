<!-- VBB-PROMETHEUS-START -->
# Pruebas con Prometheus y audit por socket

Serie `20261028-prometheus`: **32/56 pruebas completas**. Actualizado 28/10/2026 21:08 CET. Los apartados anteriores corresponden a la serie histórica del 27/10 sin esta instrumentación.

Mismos HCL, 50 workers unitario y 10 en batches; 60 s, peticiones encrypt/decrypt 95/5; encrypt por batch y decrypt unitario. Todos los escenarios de esta serie incluyen la misma observabilidad. Vault Enterprise 2.2.0, tres pods en un único nodo Minikube, **cuota agregada de 2 CPU**; Raft, audit y Prometheus comparten el dispositivo `/dev/vda` de la VM. Estas métricas no equivalen a IOPS físicos exclusivos del audit ni a tres máquinas de producción.

Prometheus scrapea cada 5 s: Vault por nodo autenticado con token de solo métricas, kubelet resource, cAdvisor, node_exporter, cuota/pressure del cgroup padre y receptores. Tasas con ventanas de 20 s; resumen desde inicio+20 s hasta fin para excluir preparación y transición. Se conservan PromQL y series crudas por ejecución; N/D significa dato ausente, nunca cero.

Socket: `socket_type=unix`, `/vault/audit/benchmark.sock`, receptor local por PVC que escribe todos los bytes en `benchmark-socket.json` y sigue la rotación. No se descartan logs ni se usa UDP. La escritura de Vault al socket y la persistencia final son fases distintas: el retorno de socket no acredita fsync del receptor. Se mantienen receptor y Prometheus también durante file y sin audit para comparar con igual instrumentación.

Todos los porcentajes son frente a **sin audit del mismo tamaño de esta serie**; combinado significa exclusión de request.data más ciphertext/batch_results sin HMAC.

| Prueba | Sin audit ops/s | File default | File sin request.data | File combinado | Socket default | Socket sin request.data | Socket combinado |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| unit | 2.444 | 1.833 (-25,0 %) | 1.913 (-21,8 %) | 1.826 (-25,3 %) | Pendiente | Pendiente | Pendiente |
| batch-50 | 200.614 | 52.046 (-74,1 %) | 48.971 (-75,6 %) | 47.574 (-76,3 %) | Pendiente | Pendiente | Pendiente |
| batch-100 | 270.658 | 77.422 (-71,4 %) | 90.650 (-66,5 %) | 109.032 (-59,7 %) | Pendiente | Pendiente | Pendiente |
| batch-250 | 361.581 | 89.793 (-75,2 %) | 112.816 (-68,8 %) | 129.040 (-64,3 %) | Pendiente | Pendiente | Pendiente |
| batch-500 | 420.975 | 113.407 (-73,1 %) | 105.023 (-75,1 %) | 17.240 (-95,9 %) | Pendiente | Pendiente | Pendiente |
| batch-750 | 448.592 | 96.254 (-78,5 %) | 69.155 (-84,6 %) | 66.424 (-85,2 %) | Pendiente | Pendiente | Pendiente |
| batch-1000 | 469.258 | 55.729 (-88,1 %) | 123.072 (-73,8 %) | 34.716 (-92,6 %) | Pendiente | Pendiente | Pendiente |
| batch-9000 | 552.789 | 121.699 (-78,0 %) | 130.590 (-76,4 %) | 179.117 (-67,6 %) | Pendiente | Pendiente | Pendiente |

Valores en elementos cifrados/s. La mezcla 95/5 corresponde a peticiones, no a elementos: el peso de encrypt crece con el batch. Cada celda proviene de una ejecución de 60 s, sin intervalo de confianza.

## Sin audit — recursos por prueba

| Prueba | CPU host media cores | Throttle periodos % | RAM Vault pico MiB | IOPS media/pico | Disco ocupado media % | Await ms | Audit req/resp ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| unit | 1,99 | 100,0 | 576,5 | 359,2/382,7 | 2,2 | 0,21 | 0,00/0,00 |
| batch-50 | 1,98 | 100,0 | 540,3 | 371,0/381,6 | 2,8 | 0,33 | 0,00/0,00 |
| batch-100 | 1,98 | 100,0 | 563,3 | 366,4/377,8 | 2,4 | 0,22 | 0,00/0,00 |
| batch-250 | 1,99 | 100,0 | 641,6 | 407,2/499,2 | 2,7 | 0,28 | 0,00/0,00 |
| batch-500 | 1,98 | 100,0 | 632,2 | 369,5/381,2 | 2,5 | 0,22 | 0,00/0,00 |
| batch-750 | 1,99 | 100,0 | 662,5 | 365,5/379,7 | 2,3 | 0,18 | 0,00/0,00 |
| batch-1000 | 1,99 | 100,0 | 678,6 | 374,8/392,0 | 2,5 | 0,23 | 0,00/0,00 |
| batch-9000 | 1,99 | 100,0 | 873,6 | 378,9/416,1 | 2,4 | 0,24 | 0,00/0,00 |

## File default — recursos por prueba

| Prueba | CPU host media cores | Throttle periodos % | RAM Vault pico MiB | IOPS media/pico | Disco ocupado media % | Await ms | Audit req/resp ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| unit | 1,99 | 100,0 | 884,2 | 375,3/410,4 | 2,7 | 0,49 | 5,43/3,30 |
| batch-50 | 1,93 | 92,2 | 2.074,2 | 549,9/744,0 | 9,7 | 3,24 | 1,81/3,59 |
| batch-100 | 1,99 | 99,7 | 3.191,2 | 435,8/499,5 | 6,4 | 2,96 | 1,47/3,60 |
| batch-250 | 1,96 | 99,3 | 3.857,9 | 417,7/526,1 | 6,7 | 1,96 | 4,41/11,89 |
| batch-500 | 1,99 | 99,7 | 4.059,9 | 399,6/419,2 | 5,3 | 2,04 | 7,14/19,62 |
| batch-750 | 2,01 | 98,9 | 4.126,8 | 379,5/400,7 | 6,5 | 2,05 | 10,27/31,71 |
| batch-1000 | 1,96 | 99,2 | 1.573,8 | 697,8/1.007,2 | 8,8 | 2,09 | 34,88/98,29 |
| batch-9000 | 2,00 | 100,0 | 5.059,3 | 393,1/413,0 | 4,9 | 1,73 | 130,87/387,61 |

## File sin request.data — recursos por prueba

| Prueba | CPU host media cores | Throttle periodos % | RAM Vault pico MiB | IOPS media/pico | Disco ocupado media % | Await ms | Audit req/resp ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| unit | 1,99 | 100,0 | 4.920,4 | 386,0/410,5 | 2,7 | 0,60 | 5,49/3,96 |
| batch-50 | 1,98 | 98,9 | 5.452,3 | 375,8/402,7 | 7,2 | 1,45 | 2,63/4,60 |
| batch-100 | 1,99 | 100,0 | 2.154,8 | 421,1/521,0 | 3,7 | 0,89 | 1,33/3,03 |
| batch-250 | 1,99 | 100,0 | 4.080,8 | 438,1/644,8 | 4,3 | 1,08 | 2,90/8,37 |
| batch-500 | 1,97 | 99,4 | 5.940,1 | 403,2/661,6 | 4,2 | 1,01 | 7,34/20,93 |
| batch-750 | 1,96 | 98,9 | 3.588,2 | 452,2/544,5 | 6,5 | 2,66 | 17,44/53,12 |
| batch-1000 | 1,99 | 100,0 | 5.301,8 | 395,5/421,9 | 3,9 | 1,36 | 12,64/39,65 |
| batch-9000 | 1,98 | 100,0 | 6.247,6 | 418,3/520,4 | 4,2 | 1,89 | 106,62/356,61 |

## File combinado — recursos por prueba

| Prueba | CPU host media cores | Throttle periodos % | RAM Vault pico MiB | IOPS media/pico | Disco ocupado media % | Await ms | Audit req/resp ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| unit | 1,99 | 100,0 | 6.194,6 | 374,5/378,3 | 3,2 | 0,69 | 5,38/3,63 |
| batch-50 | 1,99 | 100,0 | 1.161,2 | 513,7/583,9 | 6,2 | 1,41 | 1,50/2,20 |
| batch-100 | 1,98 | 100,0 | 2.026,0 | 410,1/521,6 | 3,1 | 0,50 | 1,05/1,87 |
| batch-250 | 1,69 | 100,0 | 2.895,0 | 319,2/389,1 | 2,3 | 0,40 | 2,93/5,66 |
| batch-500 | 1,97 | 98,1 | 3.262,2 | 261,6/361,6 | 11,1 | 2,40 | 290,96/575,73 |
| batch-750 | 2,00 | 100,0 | 3.048,9 | 392,2/401,7 | 6,0 | 1,23 | 22,18/47,65 |
| batch-1000 | 1,99 | 97,6 | 2.490,4 | 306,5/405,7 | 11,3 | 1,73 | 276,00/1.059,46 |
| batch-9000 | 2,00 | 100,0 | 3.936,5 | 372,7/390,1 | 2,9 | 0,57 | 100,07/215,89 |

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

Estos tests terminaron, pero tuvieron fallos de scrape durante la ventana resumida. Sus métricas pueden tener huecos y no deben interpretarse como una captura continua:

| Escenario | Prueba | Targets con huecos |
| --- | --- | --- |
| file-default | batch-100 | vault/vault-0 |
| file-default | batch-750 | kubelet-cadvisor, kubelet-resource, vault/vault-0, vault/vault-1, vault/vault-2 |
| file-no-request | batch-50 | kubelet-cadvisor, kubelet-resource, vault/vault-0 |
| file-combined | batch-500 | kubelet-cadvisor, kubelet-resource, vault/vault-0, vault/vault-1, vault/vault-2 |
| file-combined | batch-1000 | kubelet-cadvisor, kubelet-resource, vault/vault-0, vault/vault-1, vault/vault-2 |

Las ventanas se correlacionan con los timestamps del Job y de Prometheus dentro de la VM. El reloj del Mac presentó desfase y hubo un salto del reloj de la VM; los nombres de directorio son identificadores, no la referencia temporal de las consultas. La suite se detuvo al detectar targets no saludables y reanudó tras recuperar los tres pods.

## Coincidencias con rotación y compresión

El mtime de un fichero rotado es una señal de actividad, no la hora exacta de ejecución de logrotate. Se contrasta con CPU del contenedor rotador. Filas con consumo medio del rotador mayor de 0,05 cores durante la ventana de resumen:

| Escenario | Prueba | CPU rotador media/pico | CPU Vault media | CPU host media |
| --- | --- | ---: | ---: | ---: |
| file-default | batch-1000 | 0,62 / 0,69 | 0,99 | 1,96 |
| file-no-request | batch-500 | 0,10 / 0,51 | 1,61 | 1,97 |
| file-no-request | batch-750 | 0,48 / 0,51 | 1,22 | 1,96 |
| file-combined | batch-50 | 0,61 / 0,79 | 1,07 | 1,99 |
| file-combined | batch-750 | 0,72 / 0,73 | 1,03 | 2,00 |

Se observaron reinicios del contenedor `auditlog-rotator` con salida 129. El comando configurado `pkill -HUP vault` coincide con `vault` y `vault-logrotate` (verificado con pgrep); `pkill -HUP -x vault` limitaría la señal al proceso de Vault. Esta configuración se mantuvo durante la matriz para conservar las condiciones.


Estas coincidencias pueden explicar parte de la variación; una sola ejecución no permite atribuir todo el descenso al dispositivo audit.

Interpretación: CPU próxima a la cuota junto con throttling y presión CPU indica contención; RAM alta por sí sola no prueba escasez (consultar presión/OOM); IOPS por sí solos no prueban saturación de disco (contrastar await, cola, presión IO y rotaciones). La carga del generador, receptores, logrotate y Prometheus se conserva por contenedor para distinguirla de Vault.

Fuentes técnicas: [telemetría](https://developer.hashicorp.com/vault/docs/configuration/telemetry) y [audit socket](https://developer.hashicorp.com/vault/docs/audit/socket).

Artefactos: `vault-benchmark/runs/<run_id>/` contiene validación de HMAC/exclusiones y round-trip sintético, HCL y hash, configuración audit/tune, recursos, salida completa, timestamps, PromQL, series y logs del rotador.
<!-- VBB-PROMETHEUS-END -->
