# Transit: UDP y audit file con 8 CPU / 12 GiB

Fecha: 2026-10-29. Laboratorio: `workshop-k8s`, namespace `vault`, tres pods Vault sobre una única VM Minikube/Podman. Carga: 60 s, 95 % encrypt y 5 % decrypt, 50 workers en unitario y 10 en batch. `batch-9000` contiene realmente 8.982 elementos. `log_raw=false` en todos los casos auditados.

## Conclusión

UDP no es un destino adecuado cuando se necesita un registro completo. Tiene dos límites independientes: una entrada debe caber en un único datagrama y, aun cabiendo, el receptor puede perder datagramas por presión de buffer sin que la petición de Transit falle. El modo combinado reduce mucho el tamaño, pero no cambia las garantías del protocolo.

Con `audit file`, pasar de 2 a 8 CPU eliminó el throttling y multiplicó el throughput auditado entre 2,81 y 3,91 veces en los casos válidos. Aun así, el coste frente a la referencia sin audit de 8 CPU fue del 24 % al 75 %. Batch 8.982 no produjo una medición válida: llenó el disco compartido con unos 12,2 GiB nuevos de audit, dejó el Job bloqueado y solo alcanzó 99,45 % de éxito.

## UDP: límite por tamaño

La sonda envió una petición por tamaño y exigió HTTP 200 más request y response completas en el receptor.

| Configuración | Último batch válido | Request audit | Response audit | Primer batch fallido |
| --- | ---: | ---: | ---: | ---: |
| Default | 100 | 10.470 B | 39.471 B | 250, HTTP 500 |
| Combinado | 500 | 1.145 B | 62.345 B | 750, HTTP 500 |

Combinado excluye `request.data` de Transit y deja sin HMAC únicamente `ciphertext` y `batch_results`; mantiene `log_raw=false` y el plaintext de decrypt con HMAC. La respuesta de batch 500 queda muy cerca del máximo práctico de un datagrama UDP.

## UDP: carga sostenida

| Caso | Encrypt elementos/s | p95 | Audit encrypt recibido / esperado | Pérdida | RcvbufErrors |
| --- | ---: | ---: | ---: | ---: | ---: |
| Default unitario | 1.533 | 95,35 ms | 91.988 / 91.988 | 0,00 % | 0 |
| Default batch 50 | 57.552 | 39,00 ms | 53.540 / 69.105 | 22,52 % | 32.794 |
| Default batch 100 | 71.437 | 49,77 ms | 36.078 / 42.874 | 15,85 % | 14.234 |
| Combinado unitario | 1.411 | 97,33 ms | coherente en el límite de 1 ms | 0,00 % | 0 |
| Combinado batch 50 | 67.210 | 36,88 ms | 80.698 / 80.698 | 0,00 % | 0 |
| Combinado batch 100 | 81.172 | 44,18 ms | 48.747 / 48.747 | 0,00 % | 0 |
| Combinado batch 250 | 93.974 | 83,16 ms | 22.575 / 22.575 | 0,00 % | 0 |
| Combinado batch 500 | 110.065 | 98,28 ms | 13.211 / 13.211 | 0,00 % | 0 |

Las cargas default batch 50/100 mantuvieron 100 % de respuestas HTTP, pero el kernel del receptor registró desbordamientos del buffer UDP y el audit quedó incompleto. Los casos combinados válidos no demostraron pérdida en esta ejecución concreta; no prueban entrega duradera ni comportamiento ante caída del receptor.

## Audit file con toda la VM

Minikube se amplió temporalmente de 2 CPU / 9.646.899.200 B a 8 CPU / 12 GiB. Los pods Vault no tienen límites Kubernetes, por lo que pudieron usar la capacidad del nodo; generador, Raft, telemetría y audit siguieron compartiendo la misma VM y disco. Se ejecutó una referencia sin audit por cada tamaño.

| Batch | File 2 CPU elem/s | File 8 CPU elem/s | Mejora | Sin audit 8 CPU elem/s | Coste file vs sin audit | p95 file |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 1.859 | 7.264 | 3,91x | 9.540 | -23,9 % | 21,38 ms |
| 50 | 63.494 | 183.581 | 2,89x | 457.222 | -59,8 % | 6,88 ms |
| 100 | 82.374 | 231.540 | 2,81x | 682.086 | -66,1 % | 10,76 ms |
| 250 | 91.246 | 292.294 | 3,20x | 973.073 | -70,0 % | 19,03 ms |
| 500 | 101.019 | 316.502 | 3,13x | 1.097.356 | -71,2 % | 35,06 ms |
| 750 | 101.196 | 341.960 | 3,38x | 1.355.259 | -74,8 % | 43,74 ms |
| 1000 | 100.753 | 383.158 | 3,80x | 1.375.052 | -72,1 % | 47,89 ms |
| 8982 | no válido | no válido | — | no ejecutado en esta serie | disco lleno; 99,45 % éxito | 272,12 ms observado antes del bloqueo |

Los siete casos válidos tuvieron 100 % de éxito, audit reconciliado, cero fallos de audit, cero OOM y cero throttling. El audit escribió entre 16,3 MiB/s en unitario y 165,4 MiB/s en batch 1000. El working set de los contenedores Vault alcanzó aproximadamente 6,7 GiB en los batches grandes; incluye caché de fichero y no equivale al heap de Vault, que se mantuvo alrededor de 300–421 MiB.

### Batch 8.982

El caso creó aproximadamente 4,2 GiB, 4,3 GiB y 3,7 GiB en los tres PVC antes de agotar `/dev/vda4`. Se conservaron el output del benchmark y la evidencia de agotamiento; se truncaron solo esos tres `audit.json` experimentales para recuperar la VM. Al no haber 100 % de éxito ni audit reconciliable, el throughput observado no es un resultado válido de capacidad.

## Estado final

- Audit original `scep-intune-validation/`: restaurado y verificado.
- Tune de Transit: restaurado, sin claves response non-HMAC.
- Minikube: restaurado a 2 CPU y 9.646.899.200 B.
- Vault: tres pods listos, mismos UID, sin reinicios del contenedor Vault durante las pruebas.
- Disco: 13 GiB libres después de retirar únicamente los logs fallidos de batch 8.982.

Artefactos: `20261029-udp-external-probe.json`, `20261029-udp-external-plan.json`, `20261029-file-max-vm-plan.json` y directorios por `run_id`. Referencias: https://developer.hashicorp.com/vault/docs/audit/socket y https://developer.hashicorp.com/vault/docs/audit.
