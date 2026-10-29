<!-- VBB-PROMETHEUS-START -->
# Pruebas con Prometheus y audit por socket

Serie `20261028-prometheus-final`: **56/56 pruebas completas**. Actualizado 28/10/2026 23:44 CET. Los apartados anteriores corresponden a la serie histórica del 27/10 sin esta instrumentación.

Serie ejecutada con `caffeinate` para impedir reposo del Mac. Las series preliminares `20261028-prometheus` (reposos de macOS) y `20261028-prometheus-awake` (reinicios del rotador) se conservan como diagnóstico y no se usan para calcular estos porcentajes. La matriz final se repite completa con reloj estable y el postrotate corregido a `pkill -HUP -x vault`.

Mismos HCL, 50 workers unitario y 10 en batches; 60 s, peticiones encrypt/decrypt 95/5; encrypt por batch y decrypt unitario. **Batch 9000 contiene realmente 8.982 elementos**. Todos los escenarios de esta serie incluyen la misma observabilidad. Vault Enterprise 2.2.0, tres pods en un único nodo Minikube, **cuota agregada de 2 CPU**; Raft, audit y Prometheus comparten el dispositivo `/dev/vda` de la VM. Estas métricas no equivalen a IOPS físicos exclusivos del audit ni a tres máquinas de producción.

Prometheus scrapea cada 5 s: Vault por nodo autenticado con token de solo métricas, kubelet resource, cAdvisor, node_exporter, cuota/pressure del cgroup padre y receptores. Tasas con ventanas de 20 s; resumen desde inicio+20 s hasta fin para excluir preparación y transición. Se conservan PromQL y series crudas por ejecución; N/D significa dato ausente, nunca cero.

Socket: `socket_type=unix`, `/vault/audit/benchmark.sock`, receptor local por PVC que escribe todos los bytes en `benchmark-socket.json` y sigue la rotación. No se descartan logs ni se usa UDP. La escritura de Vault al socket y la persistencia final son fases distintas: el retorno de socket no acredita fsync del receptor. Se mantienen receptor y Prometheus también durante file y sin audit para comparar con igual instrumentación.

Todos los porcentajes son frente a **sin audit del mismo tamaño de esta serie**; combinado significa exclusión de request.data más ciphertext/batch_results sin HMAC. Decrypt es unitario y su plaintext permanece con HMAC, verificado en cada caso. La excepción batch_results es de todo el mount y también afectaría a una respuesta decrypt por lotes, fuera de esta matriz ([tune del mount](https://developer.hashicorp.com/vault/api-docs/system/mounts#tune-mount-configuration)).

| Prueba | Sin audit ops/s | File default | File sin request.data | File combinado | Socket default | Socket sin request.data | Socket combinado |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| unit | 2.613 | 2.149 (-17,8 %) | 1.509 (-42,3 %) † | 1.873 (-28,4 %) | 1.946 (-25,5 %) | 1.843 (-29,5 %) | 1.893 (-27,6 %) |
| batch-50 | 209.833 | 75.712 (-63,9 %) | 75.743 (-63,9 %) | 88.035 (-58,0 %) | 68.578 (-67,3 %) | 69.314 (-67,0 %) | 79.966 (-61,9 %) |
| batch-100 | 288.546 | 93.499 (-67,6 %) | 91.470 (-68,3 %) | 108.790 (-62,3 %) | 63.118 (-78,1 %) † | 49.777 (-82,7 %) † | 62.751 (-78,3 %) † |
| batch-250 | 393.377 | 85.547 (-78,3 %) † | 64.610 (-83,6 %) † | 135.978 (-65,4 %) | 87.659 (-77,7 %) † | 56.725 (-85,6 %) † | 127.306 (-67,6 %) |
| batch-500 | 460.979 | 116.930 (-74,6 %) | 65.431 (-85,8 %) † | 143.885 (-68,8 %) | 113.102 (-75,5 %) | 120.365 (-73,9 %) | 143.405 (-68,9 %) |
| batch-750 | 468.636 | 119.029 (-74,6 %) | 84.361 (-82,0 %) † | 153.459 (-67,3 %) | 117.791 (-74,9 %) | 120.110 (-74,4 %) | 147.220 (-68,6 %) |
| batch-1000 | 499.927 | 121.232 (-75,8 %) | 129.049 (-74,2 %) | 133.401 (-73,3 %) † | 86.839 (-82,6 %) † | 67.619 (-86,5 %) † | 147.166 (-70,6 %) |
| batch-9000 | 578.249 | 90.968 (-84,3 %) † | 84.793 (-85,3 %) † | 170.295 (-70,5 %) | 127.229 (-78,0 %) | 129.395 (-77,6 %) † | 172.271 (-70,2 %) |

Valores en elementos cifrados/s. **†** coincide con consumo medio del rotador >0,05 cores: la variación incluye esa competencia por CPU. La mezcla 95/5 corresponde a peticiones, no a elementos: el peso de encrypt crece con el batch. Cada celda proviene de una ejecución de 60 s, sin intervalo de confianza.

En las tablas de recursos, PSI (some) es el porcentaje de tiempo con alguna tarea esperando CPU, IO o memoria ([definición del kernel](https://docs.kernel.org/accounting/psi.html)). Throttle es el porcentaje de periodos con cuota CPU agotada; no expresa el porcentaje de tiempo de CPU perdido.

## Latencia p95 de encrypt

Milisegundos por petición completa; en batch incluye todos sus elementos.

| Prueba | Sin audit | File default | File sin request.data | File combinado | Socket default | Socket sin request.data | Socket combinado |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| unit | 84,9 | 85,7 | 97,4 | 88,5 | 86,0 | 86,3 | 85,6 |
| batch-50 | 7,0 | 36,1 | 49,6 | 34,9 | 36,4 | 37,3 | 36,0 |
| batch-100 | 28,8 | 43,7 | 50,8 | 42,1 | 60,4 | 66,8 | 56,2 |
| batch-250 | 35,8 | 90,5 | 99,2 | 73,8 | 97,5 | 102,8 | 76,9 |
| batch-500 | 45,3 | 96,3 | 188,1 | 89,2 | 107,5 | 106,8 | 89,0 |
| batch-750 | 74,0 | 109,4 | 197,7 | 100,8 | 206,2 | 163,0 | 101,6 |
| batch-1000 | 75,8 | 165,3 | 146,6 | 179,7 | 318,7 | 313,4 | 152,4 |
| batch-9000 | 252,8 | 1.823,6 | 1.699,7 | 796,5 | 1.712,0 | 1.056,4 | 998,8 |

Decrypt procesa un elemento por petición y representa aproximadamente el 5 % de peticiones generadas. Sus tasas y latencias completas están en el notebook y los artefactos; esta mezcla no mide su capacidad máxima aislada.

## Sin audit — recursos por prueba

| Prueba | CPU host/Vault/rotador media cores | Throttle %; PSI CPU/IO/RAM % | RAM WS/heap pico MiB | IOPS media/pico | Disco ocupado media % | Await ms | Audit req/resp ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| unit | 1,99/1,37/0,00 | 100,0; 89,66/0,11/0,00 | 2.952,1 / 298,9 | 435,1/665,3 | 2,5 | 0,16 | 0,00/0,00 |
| batch-50 | 1,98/1,49/0,00 | 100,0; 52,31/0,12/0,00 | 2.914,5 / 286,7 | 375,6/388,5 | 2,0 | 0,19 | 0,00/0,00 |
| batch-100 | 1,98/1,53/0,00 | 100,0; 58,93/0,11/0,00 | 2.962,0 / 324,9 | 369,6/383,7 | 2,1 | 0,18 | 0,00/0,00 |
| batch-250 | 1,98/1,56/0,00 | 100,0; 57,23/0,12/0,00 | 2.974,7 / 346,8 | 372,9/388,8 | 2,2 | 0,23 | 0,00/0,00 |
| batch-500 | 1,98/1,61/0,00 | 100,0; 66,94/0,12/0,00 | 3.017,7 / 381,9 | 369,9/383,1 | 2,1 | 0,16 | 0,00/0,00 |
| batch-750 | 1,98/1,62/0,00 | 100,0; 68,69/0,12/0,00 | 3.045,2 / 424,3 | 412,9/513,6 | 2,3 | 0,17 | 0,00/0,00 |
| batch-1000 | 1,98/1,64/0,00 | 100,0; 64,88/0,10/0,00 | 3.019,1 / 411,9 | 364,2/382,1 | 2,1 | 0,20 | 0,00/0,00 |
| batch-9000 | 1,99/1,72/0,00 | 100,0; 78,09/0,10/0,00 | 3.315,3 / 540,3 | 371,3/384,5 | 1,9 | 0,22 | 0,00/0,00 |

## File default — recursos por prueba

| Prueba | CPU host/Vault/rotador media cores | Throttle %; PSI CPU/IO/RAM % | RAM WS/heap pico MiB | IOPS media/pico | Disco ocupado media % | Await ms | Audit req/resp ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| unit | 1,99/1,42/0,00 | 100,0; 82,83/0,15/0,00 | 3.325,4 / 332,9 | 388,8/495,1 | 2,6 | 0,45 | 4,30/2,75 |
| batch-50 | 1,98/1,66/0,00 | 100,0; 60,86/0,31/0,00 | 5.479,0 / 316,6 | 412,1/444,3 | 5,2 | 1,94 | 0,77/1,37 |
| batch-100 | 1,98/1,69/0,00 | 100,0; 66,95/0,18/0,00 | 6.368,1 / 320,1 | 407,0/422,3 | 5,9 | 2,40 | 1,30/3,00 |
| batch-250 | 1,99/1,43/0,31 | 100,0; 76,04/0,31/0,05 | 6.294,8 / 411,3 | 468,2/561,9 | 6,6 | 2,68 | 4,78/12,20 |
| batch-500 | 1,99/1,75/0,00 | 100,0; 72,45/0,24/0,00 | 5.497,2 / 359,1 | 393,6/412,7 | 4,6 | 1,75 | 6,56/19,00 |
| batch-750 | 1,99/1,76/0,00 | 100,0; 78,67/0,28/0,00 | 5.642,4 / 438,1 | 428,5/536,1 | 5,1 | 1,54 | 10,50/30,15 |
| batch-1000 | 1,99/1,77/0,00 | 100,0; 75,84/0,32/0,02 | 5.616,7 / 425,4 | 390,8/402,1 | 5,0 | 1,91 | 14,45/41,53 |
| batch-9000 | 2,00/1,36/0,46 | 100,0; 85,07/0,30/0,12 | 3.515,8 / 651,3 | 516,6/836,1 | 6,4 | 2,05 | 182,08/521,14 |

## File sin request.data — recursos por prueba

| Prueba | CPU host/Vault/rotador media cores | Throttle %; PSI CPU/IO/RAM % | RAM WS/heap pico MiB | IOPS media/pico | Disco ocupado media % | Await ms | Audit req/resp ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| unit | 1,99/1,21/0,29 | 100,0; 85,05/0,18/0,00 | 1.470,9 / 327,3 | 519,4/685,5 | 4,4 | 1,24 | 7,11/4,76 |
| batch-50 | 1,98/1,67/0,00 | 100,0; 54,98/0,17/0,00 | 2.908,6 / 302,0 | 403,2/436,1 | 3,4 | 0,90 | 0,74/1,28 |
| batch-100 | 1,98/1,70/0,00 | 100,0; 60,68/0,17/0,00 | 4.464,9 / 330,1 | 404,3/434,6 | 3,6 | 1,17 | 1,17/2,83 |
| batch-250 | 2,00/1,06/0,71 | 100,0; 77,86/0,24/0,03 | 5.127,6 / 357,7 | 429,7/466,7 | 5,6 | 1,44 | 5,61/15,79 |
| batch-500 | 2,00/1,08/0,69 | 100,0; 83,96/0,23/0,06 | 3.753,3 / 408,8 | 457,1/555,9 | 5,4 | 0,95 | 11,37/35,40 |
| batch-750 | 1,99/1,26/0,52 | 100,0; 79,57/0,30/0,02 | 4.330,6 / 393,3 | 432,6/552,8 | 4,9 | 1,13 | 14,97/47,69 |
| batch-1000 | 1,99/1,77/0,00 | 100,0; 75,96/0,12/0,00 | 6.210,0 / 418,6 | 378,6/399,8 | 3,4 | 1,01 | 11,53/38,22 |
| batch-9000 | 2,00/1,18/0,65 | 100,0; 85,51/0,23/0,14 | 5.994,1 / 623,5 | 494,3/675,4 | 5,1 | 0,69 | 168,78/566,44 |

## File combinado — recursos por prueba

| Prueba | CPU host/Vault/rotador media cores | Throttle %; PSI CPU/IO/RAM % | RAM WS/heap pico MiB | IOPS media/pico | Disco ocupado media % | Await ms | Audit req/resp ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| unit | 1,99/1,43/0,00 | 100,0; 82,35/0,14/0,00 | 3.153,2 / 352,2 | 394,3/515,5 | 2,9 | 0,52 | 5,43/3,67 |
| batch-50 | 1,98/1,66/0,00 | 100,0; 58,48/0,17/0,00 | 3.978,8 / 299,6 | 381,5/404,1 | 2,9 | 0,58 | 0,67/0,96 |
| batch-100 | 1,98/1,68/0,00 | 100,0; 60,46/0,12/0,00 | 5.003,7 / 317,4 | 403,7/628,7 | 2,9 | 0,47 | 1,15/1,94 |
| batch-250 | 1,99/1,71/0,00 | 100,0; 68,37/0,12/0,00 | 3.916,8 / 372,7 | 378,2/394,0 | 2,7 | 0,46 | 2,62/5,38 |
| batch-500 | 1,99/1,73/0,00 | 100,0; 72,30/0,15/0,00 | 5.016,1 / 333,4 | 415,9/522,6 | 2,8 | 0,45 | 5,91/12,46 |
| batch-750 | 1,99/1,75/0,00 | 100,0; 73,82/0,14/0,00 | 6.058,8 / 337,5 | 374,3/387,2 | 2,7 | 0,45 | 8,95/18,67 |
| batch-1000 | 1,99/1,58/0,17 | 100,0; 67,87/0,35/0,01 | 6.264,5 / 288,4 | 737,0/1.794,7 | 5,1 | 1,84 | 14,10/28,06 |
| batch-9000 | 1,99/1,80/0,00 | 100,0; 81,59/0,16/0,00 | 5.394,0 / 563,5 | 428,8/474,2 | 3,0 | 1,18 | 108,47/231,60 |

## Socket default — recursos por prueba

| Prueba | CPU host/Vault/rotador media cores | Throttle %; PSI CPU/IO/RAM % | RAM WS/heap pico MiB | IOPS media/pico | Disco ocupado media % | Await ms | Audit req/resp ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| unit | 1,99/1,34/0,00 | 100,0; 77,69/0,16/0,00 | 5.212,9 / 287,0 | 413,7/451,5 | 3,2 | 1,04 | 6,15/4,39 |
| batch-50 | 1,92/1,49/0,00 | 95,5; 50,62/6,66/0,09 | 5.178,3 / 275,1 | 501,6/518,6 | 4,6 | 1,02 | 1,62/1,65 |
| batch-100 | 1,91/1,22/0,36 | 92,7; 57,87/7,79/0,08 | 5.251,8 / 302,6 | 777,1/940,8 | 6,1 | 1,31 | 3,32/5,41 |
| batch-250 | 1,99/1,38/0,28 | 100,0; 60,83/8,66/0,08 | 2.901,8 / 333,9 | 617,7/791,2 | 6,0 | 0,85 | 6,59/12,34 |
| batch-500 | 1,88/1,58/0,00 | 91,8; 57,85/8,82/0,08 | 1.518,8 / 420,0 | 561,7/649,7 | 4,5 | 0,55 | 10,79/21,11 |
| batch-750 | 1,93/1,65/0,00 | 95,3; 58,52/9,16/0,08 | 1.505,7 / 368,6 | 559,2/835,4 | 5,2 | 0,73 | 15,67/33,68 |
| batch-1000 | 1,99/1,24/0,50 | 97,9; 71,52/4,89/0,14 | 1.524,6 / 373,5 | 516,5/554,8 | 5,9 | 1,00 | 28,69/66,79 |
| batch-9000 | 1,90/1,67/0,00 | 92,4; 61,05/10,19/0,07 | 999,0 / 580,8 | 578,4/711,2 | 4,3 | 0,60 | 154,56/392,46 |

## Socket sin request.data — recursos por prueba

| Prueba | CPU host/Vault/rotador media cores | Throttle %; PSI CPU/IO/RAM % | RAM WS/heap pico MiB | IOPS media/pico | Disco ocupado media % | Await ms | Audit req/resp ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| unit | 1,99/1,37/0,00 | 100,0; 77,88/0,15/0,01 | 577,8 / 305,9 | 407,1/457,0 | 2,9 | 1,07 | 6,92/5,28 |
| batch-50 | 1,98/1,57/0,00 | 99,9; 55,22/3,50/0,06 | 562,1 / 316,7 | 466,6/515,4 | 4,5 | 0,91 | 1,47/1,70 |
| batch-100 | 1,99/0,97/0,72 | 100,0; 71,27/2,19/0,05 | 611,6 / 339,0 | 426,2/457,6 | 5,3 | 0,76 | 4,52/6,71 |
| batch-250 | 1,99/0,99/0,73 | 100,0; 79,57/1,80/0,13 | 648,5 / 364,2 | 511,2/641,1 | 6,2 | 1,11 | 8,66/18,85 |
| batch-500 | 1,98/1,69/0,00 | 96,8; 60,76/6,41/0,06 | 695,6 / 357,3 | 539,9/629,8 | 4,6 | 0,42 | 9,00/19,55 |
| batch-750 | 1,86/1,60/0,00 | 87,9; 58,68/10,23/0,05 | 690,9 / 416,2 | 540,1/575,4 | 3,8 | 0,41 | 16,49/29,07 |
| batch-1000 | 2,00/1,00/0,76 | 100,0; 79,17/2,30/0,04 | 679,6 / 363,7 | 434,0/461,9 | 5,4 | 0,74 | 30,60/79,85 |
| batch-9000 | 1,99/1,67/0,11 | 100,0; 82,09/0,71/0,04 | 998,2 / 623,2 | 471,6/579,2 | 4,7 | 0,70 | 114,04/370,59 |

## Socket combinado — recursos por prueba

| Prueba | CPU host/Vault/rotador media cores | Throttle %; PSI CPU/IO/RAM % | RAM WS/heap pico MiB | IOPS media/pico | Disco ocupado media % | Await ms | Audit req/resp ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| unit | 1,99/1,38/0,00 | 100,0; 78,22/0,12/0,02 | 582,1 / 314,2 | 383,9/404,7 | 2,9 | 0,41 | 6,49/5,02 |
| batch-50 | 1,97/1,55/0,00 | 96,7; 50,74/2,20/0,04 | 564,2 / 292,4 | 418,7/439,2 | 3,7 | 0,98 | 1,23/1,24 |
| batch-100 | 1,99/1,10/0,58 | 100,0; 69,39/0,25/0,07 | 604,9 / 296,7 | 459,2/520,3 | 6,1 | 1,04 | 3,04/4,22 |
| batch-250 | 1,99/1,64/0,00 | 100,0; 70,38/1,21/0,05 | 622,5 / 335,1 | 455,4/543,1 | 3,8 | 0,59 | 3,99/6,21 |
| batch-500 | 1,99/1,68/0,00 | 100,0; 68,78/2,11/0,04 | 668,2 / 374,3 | 416,9/432,7 | 3,5 | 0,36 | 6,69/13,04 |
| batch-750 | 1,99/1,69/0,00 | 100,0; 73,18/1,47/0,04 | 656,4 / 339,1 | 413,0/434,8 | 3,5 | 0,45 | 10,20/20,82 |
| batch-1000 | 1,99/1,69/0,00 | 100,0; 71,30/2,49/0,04 | 698,6 / 417,9 | 423,5/468,6 | 3,6 | 0,68 | 14,41/29,03 |
| batch-9000 | 2,00/1,76/0,00 | 99,7; 74,15/3,99/0,03 | 880,7 / 542,3 | 429,2/453,6 | 3,2 | 0,31 | 111,08/244,14 |

## Calidad de la captura

Los targets permanecieron disponibles en todas las muestras de las ventanas resumidas.

Variación máxima del desfase Mac/Prometheus antes y después de los tests instrumentados: 0,018 s (56 comprobaciones).

Las ventanas se correlacionan con los timestamps del Job y de Prometheus dentro de la VM. Los nombres de directorio usan el reloj del Mac; la referencia temporal de las consultas procede del clúster. Los desfases y saltos observados en la serie preliminar motivaron repetir la matriz completa evitando reposo.

## Coincidencias con rotación y compresión

El mtime de un fichero rotado es una señal de actividad, no la hora exacta de ejecución de logrotate. Se contrasta con CPU del contenedor rotador. Filas con consumo medio del rotador mayor de 0,05 cores durante la ventana de resumen:

| Escenario | Prueba | CPU rotador media/pico | CPU Vault media | CPU host media |
| --- | --- | ---: | ---: | ---: |
| file-default | batch-250 | 0,31 / 0,70 | 1,43 | 1,99 |
| file-default | batch-9000 | 0,46 / 0,69 | 1,36 | 2,00 |
| file-no-request | unit | 0,29 / 0,45 | 1,21 | 1,99 |
| file-no-request | batch-250 | 0,71 / 0,76 | 1,06 | 2,00 |
| file-no-request | batch-500 | 0,69 / 0,70 | 1,08 | 2,00 |
| file-no-request | batch-750 | 0,52 / 0,75 | 1,26 | 1,99 |
| file-no-request | batch-9000 | 0,65 / 0,70 | 1,18 | 2,00 |
| file-combined | batch-1000 | 0,17 / 0,76 | 1,58 | 1,99 |
| socket-default | batch-100 | 0,36 / 0,81 | 1,22 | 1,91 |
| socket-default | batch-250 | 0,28 / 0,55 | 1,38 | 1,99 |
| socket-default | batch-1000 | 0,50 / 0,76 | 1,24 | 1,99 |
| socket-no-request | batch-100 | 0,72 / 0,82 | 0,97 | 1,99 |
| socket-no-request | batch-250 | 0,73 / 0,77 | 0,99 | 1,99 |
| socket-no-request | batch-1000 | 0,76 / 0,81 | 1,00 | 2,00 |
| socket-no-request | batch-9000 | 0,11 / 0,25 | 1,67 | 1,99 |
| socket-combined | batch-100 | 0,58 / 0,82 | 1,10 | 1,99 |

En las series preliminares, `pkill -HUP vault` coincidía con `vault` y `vault-logrotate` (verificado con pgrep). El rotador terminaba con salida 129 y acumulaba CrashLoopBackOff, retirando pods del Service. Se corrigió a `pkill -HUP -x vault` antes de esta matriz y se verificó la configuración efectiva en los tres sidecars, sin reiniciar Vault. La compresión sigue habilitada: su coste de CPU permanece en la medición.


La compresión puede procesar archivos de escenarios anteriores. Estas coincidencias pueden explicar parte de la variación; una sola ejecución no permite atribuir todo el descenso al dispositivo audit.

Interpretación: CPU próxima a la cuota junto con throttling y presión CPU indica contención; RAM alta por sí sola no prueba escasez (consultar presión/OOM); IOPS por sí solos no prueban saturación de disco (contrastar await, cola, presión IO y rotaciones). La carga del generador, receptores, logrotate y Prometheus se conserva por contenedor para distinguirla de Vault.

## Conclusiones de la serie medida

**La limitación más clara de este laboratorio es la CPU compartida.** Minikube consume 1,86–2,00 de sus 2 cores efectivos; hay throttling en 87,9–100,0 % de los periodos y PSI CPU medio de 50,6–89,7 %. El rotador llega a 0,76 cores de media en una prueba (38,1 % de la cuota). Separar o limitar la compresión y aumentar la cuota CPU efectiva son las primeras hipótesis a validar. Estos datos no separan el coste de HMAC, JSON y otras funciones internas de Vault.

**RAM:** no se registran OOM; PSI memoria medio entre 0,000–0,138 %. El pico agregado de working set de Vault es 6,22 GiB, frente a 651 MiB de heap asignado. Son máximos de la serie, no necesariamente simultáneos. El working set incluye memoria distinta del heap, incluida caché de archivos; no hay evidencia suficiente para atribuir el descenso principalmente a falta de RAM.

**IO:** el disco virtual muestra ocupación media de 1,9–6,6 % y await medio de 0,16–2,68 ms. Sin embargo, PSI IO alcanza 10,2 % de media y 14,0 % de pico, especialmente con socket. Hay esperas en la ruta de IO; la baja ocupación de vda no permite descartar el almacenamiento del host ni cuantificar las IOPS físicas del audit. CPU e IO deben interpretarse juntos.

**El socket UNIX local no aporta una mejora consistente frente a file en esta matriz.** El receptor comparte CPU, disco y rotador con Vault. En batch 500, sin compresión relevante en los cuatro casos comparados, default pasa de 116.930 a 113.102 cifrados/s al usar socket (−3,3 %); combinado pasa de 143.885 a 143.405 (−0,3 %). En batch 8.982 combinado, file da 170.295 cifrados/s con p95 796,5 ms y socket 172.271 con p95 998,8 ms. Las pequeñas diferencias de throughput no establecen una ventaja estadística con una ejecución por caso. Un colector remoto y otro almacenamiento requieren una prueba propia.

**Tamaño de batch:** 500–750 es un punto de partida razonable para la siguiente validación con auditoría. Con file default entrega 116.930–119.029 cifrados/s y p95 96,3–109,4 ms; con file combinado, 143.885–153.459 y p95 89,2–100,8 ms. El batch 8.982 combinado aumenta throughput, pero eleva mucho la latencia. El batch óptimo depende del SLA y de la ocupación real de los lotes. Las filas con compresión activa no deben usarse para adjudicar por sí solas una diferencia a la exclusión o al HMAC.

**Alcance:** 56/56 casos y 2.770.026 peticiones correctas; 438.869.946 elementos cifrados y 138.347 descifrados según el benchmark. Sin huecos de scrape, errores de consulta, fallos audit, errores de escritura del receptor ni reinicios durante la matriz. Se conserva el audit original y el tune de HMAC restaurados, verificados al terminar. Los resultados describen tres pods que comparten una VM: el dimensionamiento del PR de producción requiere recursos reales por máquina, reparto de tráfico, mezcla de elementos encrypt/decrypt y carga sostenida. Este diagnóstico no identifica por sí solo el recurso limitante del cliente.

## Verificación del conteo en audit

45/48 casos tienen conteo exacto, incluidos **42 casos batch**. En 3 casos unitarios el contador del benchmark queda dentro de un intervalo de una petición por precisión temporal. Líneas con error de parseo: 0. Errores de elementos detectados: 0; discrepancias HMAC/exclusiones: 0.

Se leen respuestas de los tres PVC y se deduplica por request.id. Las marcas del benchmark tienen precisión de milisegundos: se inspecciona `[inicio, fin+1ms)` y se conserva el primer milisegundo como frontera. Los encrypt unitarios de preparación se excluyen de casos batch; las respuestas batch en esa frontera se identifican por su cardinalidad. En unitarios, preparación y carga pueden compartir conexión y no se fuerza una clasificación. El HMAC de un error vacío se reconoce usando el reference vacío de estos HCL, además de ciphertext y key_version. Se conservan contadores originales y evidencia de frontera; el alcance son los ficheros retenidos.

| Escenario | Prueba | Encrypt: intervalo audit | Encrypt: benchmark | Decrypt: audit / benchmark |
| --- | --- | ---: | ---: | ---: |
| file-combined | unit | 112.496–112.497 | 112.496 | 5.847 / 5.847 |
| socket-no-request | unit | 110.615–110.616 | 110.616 | 5.689 / 5.689 |
| socket-combined | unit | 113.743–113.744 | 113.744 | 6.108 / 6.108 |

## Estado al finalizar

Restauración verificada: `scep-intune-validation/`. El dispositivo vbb de la batería queda deshabilitado y el tune de HMAC de Transit vuelve a su valor anterior. Se mantienen Prometheus, receptores y Transit/orders para inspección y repetición.

Fuentes técnicas: [telemetría](https://developer.hashicorp.com/vault/docs/configuration/telemetry) y [audit socket](https://developer.hashicorp.com/vault/docs/audit/socket).

Artefactos: `vault-benchmark/runs/<run_id>/` contiene validación de HMAC/exclusiones y round-trip sintético, HCL y hash, configuración audit/tune, recursos, salida completa, timestamps, PromQL, series y logs del rotador.
<!-- VBB-PROMETHEUS-END -->
