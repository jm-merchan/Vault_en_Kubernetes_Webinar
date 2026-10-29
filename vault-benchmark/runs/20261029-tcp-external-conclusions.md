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
