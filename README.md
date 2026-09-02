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

### 6) Auto-unseal con AWS KMS

17. `Auto_unseal_AWS_AssumeRole.ipynb`
- Laboratorio de compatibilidad para `seal "awskms"` con credenciales compartidas y `role_arn`.
- Crea un usuario bootstrap limitado a `sts:AssumeRole`, un role con acceso a KMS y monta el perfil AWS dentro de los pods.
- Documenta una limitación comprobada de Vault Enterprise 2.1.0: la configuración acepta `role_arn`, pero la cadena de credenciales selecciona antes el perfil compartido y KMS recibe la identidad del usuario bootstrap.

18. `Auto_unseal_AWS_WebIdentity_OIDC.ipynb`
- Implementación funcional mediante Kubernetes Service Account, OIDC y `AssumeRoleWithWebIdentity`.
- Utiliza un token proyectado y renovable; Vault obtiene credenciales STS temporales sin almacenar access keys de AWS en Kubernetes.
- Es la opción recomendada en Vault Enterprise 2.1.0 para auto-unseal con credenciales renovables desde un Kubernetes externo a AWS.

19. `Auto_unseal_AWS_WebIdentity_OIDC_Terraform.ipynb`
- Variante equivalente que gestiona con Terraform el proveedor OIDC, IAM role, policies y clave KMS.
- Mantiene en Kubernetes/Helm la configuración de Minikube, token proyectado y Vault.

## Compatibilidad de AWS KMS AssumeRole

Que una clave sea aceptada dentro de `seal "awskms"` significa que el parser y el wrapper pueden leerla; no garantiza que cualquier combinación de providers produzca la identidad final esperada.

Vault Enterprise 2.1.0 incorpora estas dependencias para el seal AWS KMS:

```text
github.com/hashicorp/go-kms-wrapping/wrappers/awskms/v2 v2.0.11
github.com/hashicorp/go-secure-stdlib/awsutil v0.3.0
```

Con esta combinación, el uso conjunto de:

```hcl
shared_creds_filename = "/vault/userconfig/aws/credentials"
shared_creds_profile  = "vault-bootstrap"
role_arn              = "arn:aws:iam::<account>:role/vault-kms-unseal"
```

construye una cadena en la que el shared credentials provider aparece antes que el provider AssumeRole. Como las credenciales bootstrap son válidas, AWS selecciona ese primer provider y la llamada KMS se firma como el usuario:

```text
shared credentials ──▶ usuario bootstrap ──▶ KMS ──▶ AccessDenied
                          │
                          └── AssumeRole posterior no seleccionado
```

La policy del laboratorio niega deliberadamente KMS al usuario bootstrap. Concedérselo haría arrancar Vault, pero dejaría de probar AssumeRole y rompería la separación de privilegios.

La nueva generación del wrapper, `awskms/v3` y `awskms/v4`, utiliza `awsutil/v2` y AWS SDK for Go v2 para componer correctamente el role sobre las credenciales fuente. La rama principal de Vault ya usa esta generación, pero Vault 2.1.0 es todavía la última release publicada y conserva el wrapper anterior. Debe comprobarse el `go.mod` o el binario de cada nueva release antes de asumir que incluye la corrección.

Consecuencias prácticas:

- `access_key + secret_key + session_token` permite usar una sesión STS pre-generada, pero Vault no puede renovarla automáticamente.
- `role_arn + web_identity_token_file` evita que una credencial AWS base gane la precedencia y permite renovación automática mediante OIDC.
- Para este webinar, usa el notebook AssumeRole como prueba de compatibilidad y los notebooks Web Identity/OIDC como implementación funcional.

Referencias de implementación:

- [Cadena antigua de credenciales en awsutil v0.3.0](https://github.com/hashicorp/go-secure-stdlib/blob/awsutil/v0.3.0/awsutil/generate_credentials.go)
- [Migración del wrapper AWS KMS al AWS SDK for Go v2](https://github.com/hashicorp/go-kms-wrapping/commit/b50482337401006ca30a211370c57ee4e1ee2540)
- [Opciones actuales del wrapper AWS KMS](https://github.com/hashicorp/go-kms-wrapping/blob/d4ca45ec7310b5efea9a72993046cf896ff69550/wrappers/awskms/options.go#L50)
- [Configuración oficial del seal AWS KMS](https://developer.hashicorp.com/vault/docs/configuration/seal/awskms)


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
