# Vault on Kubernetes Webinar

Este repositorio contiene notebooks prácticos para desplegar HashiCorp Vault en Kubernetes y recorrer patrones de integración reales: motores de secretos, autenticación, VSO, Agent Injector, CSI, PKI, ACME, Transit, Performance Replication y auto-unseal con AWS KMS.

## Requisitos

- Kubernetes local (recomendado: Minikube)
- Helm
- kubectl
- Vault CLI
- jq
- Jupyter Notebook / VS Code Notebooks
- Python 3.10+ con ipykernel

## Inicio rápido

1. Clonar el repositorio:

```bash
git clone https://github.com/jm-merchan/Vault_en_Kubernetes_Webinar.git
cd Vault_on_Kubernetes_Webinar
```

2. Abrir los notebooks en VS Code o Jupyter.

3. Ejecutar en orden (se recomienda seguir la secuencia de abajo).

## Secuencia recomendada de notebooks

### 1) Base de plataforma

1. `1_Deploy_Vault_minikube.ipynb`
- Levanta entorno local y despliega Vault en Kubernetes.
- Inicialización/unseal y validaciones básicas.

### 2) Motores de secretos y autenticación

2. `2_Database_Secret_Engine.ipynb`
- Credenciales dinámicas para PostgreSQL.

3. `2_PKI.ipynb`
- PKI root/intermedia, roles y emisión de certificados.

4. `2b_LDAP_Authentication.ipynb`
- Autenticación LDAP.

5. `2c_LDAP_Secret_Engine.ipynb`
- Secret Engine de LDAP (credenciales/roles).

6. `2d_MongoDB_Secret_Engine.ipynb`
- Credenciales dinámicas para MongoDB.

### 3) Integraciones Kubernetes

7. `3_VSO.ipynb`
- Vault Secrets Operator (VaultConnection, VaultAuth, VaultStaticSecret, VaultDynamicSecret, VaultPKISecret).

8. `4_Vault_Agent_injector.ipynb`
- Inyección de secretos con Vault Agent Injector.

9. `5_CSI_Provider.ipynb`
- Consumo de secretos por CSI provider.

10. `6_VSO_Protected_Secrets.ipynb`
- Protected Secrets (VSO + CSI) y control de acceso.

### 4) Certificados y ACME

11. `7_CertManager.ipynb`
- Integración de Vault PKI con cert-manager.

12. `8_ACME.ipynb`
- Flujo ACME con Vault (incluye ejemplo con Caddy).

### 5) Casos avanzados

13. `9_Other_Use_Cases.ipynb`
- Casos empresariales: secretos estáticos complejos, credenciales, formatos específicos, etc.

14. `10_Transit.ipynb`
- Transit engine: cifrado/descifrado, curl y batch operations.

15. `11_vault_pr.ipynb`
- Configuración de Performance Replication (PR).

16. `12_pr_tasks.ipynb`
- Tareas y validaciones sobre PR (primario/secundario, tokens y estado de replicación).

17. `Auto_unseal_AWS_AssumeRole.ipynb`
- Auto-unseal con AWS KMS desde entorno on-prem.
- Notas sobre AssumeRole y limitaciones del parámetro `role_arn` en `seal "awskms"`.

## Archivos auxiliares

- `postgres.yaml`, `mongodb_deploy.yaml`, `openldap_deployment.yml`: manifiestos de soporte.
- `local-pv.yaml`, `pv-claim.yaml`: almacenamiento persistente local.
- `batch_input.json`, `batch_output.json`, `batch_decrypt_input.json`, `batch_decrypt_output.json`: pruebas para Transit batch.
- `ciphertext.txt`: ejemplo de salida de cifrado.

## Consejos de ejecución

- Ejecuta los notebooks en orden para evitar fallos por dependencias entre laboratorios.
- Si cambias de kernel y aparece error de ipykernel, reinstálalo en el intérprete activo.
- Evita guardar tokens reales en notebooks (GitHub Push Protection bloquea commits con secretos).

## Referencias

- Vault docs: https://developer.hashicorp.com/vault/docs
- Vault on Kubernetes: https://developer.hashicorp.com/vault/tutorials/kubernetes
- VSO: https://developer.hashicorp.com/vault/docs/platform/k8s/vso
- CSI Provider: https://developer.hashicorp.com/vault/docs/platform/k8s/csi
- Agent Injector: https://developer.hashicorp.com/vault/docs/platform/k8s/injector
- cert-manager: https://cert-manager.io/docs/

## Licencia

Material educativo para el webinar de Vault en Kubernetes.
