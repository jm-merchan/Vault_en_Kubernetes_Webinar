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
- JDK 17+ y Maven (opcional; demo Java local del notebook Transit)

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
- Transit engine: cifrado/descifrado (CLI y curl), batch de 1000 operaciones, rotación de clave, rewrap y decrypt de ciphertexts `vault:vN:` de distintas versiones en un solo `batch_input`.
- Integridad AES-GCM: batch decrypt con ciphertext manipulado (versión inexistente y un carácter del payload); los ítems válidos siguen descifrando.
- Auth TLS (`cert`) con **batch token** (`hvb.…`, TTL 1m, `renewable=false`). El certificado de cliente lo emite `pki_int` del notebook 2.
- Cliente Python con [`hvac`](https://python-hvac.org/): guarda `auth.lease_duration` y se reautentica con el certificado antes de que expire el TTL.
- Cliente Java con [Spring Cloud Vault](https://docs.spring.io/spring-cloud-vault/reference/index.html) (`CERT`, `httpclient5`, keystore PKCS12). `LifecycleAwareSessionManager` solo hace `renew-self` si el token es renovable; con batch token esta demo re-loguea tras un **403**.
- Apps long-lived en Kubernetes (`transit-apps/`): imágenes `transit-python:demo` / `transit-java:demo` en el namespace `transit-apps`. En logs, un nuevo `LOGIN` / `NEW TOKEN` ~1 minuto después confirma la rotación.
- Celda de cleanup: namespace, imágenes, Transit, cert auth y policy. No toca el cluster de Vault ni el PKI.

15. `11_vault_pr.ipynb`
- Configuración de Performance Replication (PR).

16. `12_pr_tasks.ipynb`
- Tareas y validaciones sobre PR (primario/secundario, tokens y estado de replicación).

### 6) Auto-unseal con AWS KMS

17. `Auto_unseal_AWS_AssumeRole.ipynb`
- Auto-unseal on-prem (Minikube) con `seal "awskms"`, usuario bootstrap y `sts:AssumeRole`.
- Verificado en Vault Enterprise 2.1.0: CloudTrail muestra `kms:Encrypt` / `Decrypt` / `DescribeKey` como `AssumedRole` `vault-kms-unseal`, no como el usuario `vault-autounseal`.
- El token STS se obtiene al arrancar el proceso y dura 1 hora; no se refresca en caliente. Un `ASIA…` nuevo solo aparece tras reiniciar el Pod.
- Sigue habiendo access keys largas en un Secret de Kubernetes.

18. `Auto_unseal_AWS_WebIdentity_OIDC.ipynb`
- Auto-unseal con Service Account, OIDC y `AssumeRoleWithWebIdentity`.
- Token proyectado y renovable; no hay access keys de AWS en Kubernetes.
- Opción recomendada en 2.1.0 cuando se necesitan credenciales que se renueven solas desde un Kubernetes externo a AWS.

19. `Auto_unseal_AWS_WebIdentity_OIDC_Terraform.ipynb`
- Variante equivalente que gestiona con Terraform el proveedor OIDC, IAM role, policies y clave KMS.
- Mantiene en Kubernetes/Helm la configuración de Minikube, token proyectado y Vault.

## Auto-unseal AssumeRole en Vault Enterprise 2.1.0

Vault Enterprise 2.1.0 usa estas dependencias para el seal AWS KMS:

```text
github.com/hashicorp/go-kms-wrapping/wrappers/awskms/v2 v2.0.11
github.com/hashicorp/go-secure-stdlib/awsutil v0.3.0
```

El shared-credentials provider de `awsutil` v0.3.0 **solo** lee `aws_access_key_id` / `aws_secret_access_key`. Ignora `role_arn` y `source_profile` en el fichero INI. La cadena elige el **primer** provider válido:

1. Shared credentials del `shared_creds_profile`
2. AssumeRole, **solo si** el stanza define `role_arn`
3. Instance metadata (no existe on-prem)

### Patrón verificado (KMS como rol)

Fichero montado en `/vault/userconfig/aws/credentials`:

```ini
[default]
aws_access_key_id=...
aws_secret_access_key=...

[vault-bootstrap]
role_arn=arn:aws:iam::<account>:role/vault-kms-unseal
role_session_name=vault-auto-unseal
source_profile=default
```

```hcl
seal "awskms" {
  region                = "eu-west-3"
  kms_key_id            = "<kms-key-id>"
  shared_creds_filename = "/vault/userconfig/aws/credentials"
  shared_creds_profile  = "vault-bootstrap"
  role_arn              = "arn:aws:iam::<account>:role/vault-kms-unseal"
  role_session_name     = "vault-auto-unseal"
}
```

En el Pod: `AWS_SHARED_CREDENTIALS_FILE=/vault/userconfig/aws/credentials`. No definir `AWS_PROFILE`.

`[vault-bootstrap]` no tiene keys, así que el shared-credentials provider falla. `role_arn` en el stanza añade AssumeRole. La sesión interna lee `[default]` vía `AWS_SHARED_CREDENTIALS_FILE`.

El trust del role debe nombrar el ARN del usuario en `Principal`. Account-root más condición `aws:PrincipalArn` exige la policy de identidad del usuario y puede quedar denegado por un permissions boundary.

CloudTrail (Event history, región de KMS):

- `sts:AssumeRole` por `IAMUser` `vault-autounseal` sobre `role/vault-kms-unseal`
- `kms:Encrypt` / `Decrypt` / `DescribeKey` con `userIdentity.type = AssumedRole` y ARN `…/assumed-role/vault-kms-unseal/vault-auto-unseal`

### Patrones que fallan

```text
Keys estáticas en el mismo profile que selecciona Vault
  + role_arn en el stanza
  → shared credentials gana → KMS se firma como el usuario

role_arn / source_profile solo en el INI, sin role_arn en el stanza
  → NoCredentialProviders
```

No concedas KMS al usuario bootstrap para “hacer arrancar” Vault: dejarías de probar AssumeRole.

### Vida del token STS

`awsutil` v0.3.0 guarda las credenciales STS en un `StaticProvider` al arrancar. Un Pod en ejecución **no** vuelve a llamar a `AssumeRole`. La sesión dura 1 hora (`MaxSessionDuration=3600`). Una `sts_key` (`ASIA…`) distinta en CloudTrail solo aparece tras recrear el proceso. Esperar 1 hora sin reiniciar conserva la misma clave hasta que caduca; entonces KMS falla hasta el siguiente start.

`awskms/v3` y `awskms/v4` (`awsutil/v2`, AWS SDK for Go v2) componen el role sobre el profile fuente. La rama principal de Vault ya usa esa generación; 2.1.0 aún no. Comprueba el `go.mod` de cada release nueva.

Para credenciales que se renueven solas en 2.1.0, usa Web Identity/OIDC. Una sesión STS pre-generada (`AWS_SESSION_TOKEN`) tampoco se renueva.

Referencias:

- [Cadena de credenciales en awsutil v0.3.0](https://github.com/hashicorp/go-secure-stdlib/blob/awsutil/v0.3.0/awsutil/generate_credentials.go)
- [Migración del wrapper AWS KMS al AWS SDK for Go v2](https://github.com/hashicorp/go-kms-wrapping/commit/b50482337401006ca30a211370c57ee4e1ee2540)
- [Opciones del wrapper AWS KMS](https://github.com/hashicorp/go-kms-wrapping/blob/d4ca45ec7310b5efea9a72993046cf896ff69550/wrappers/awskms/options.go#L50)
- [Seal AWS KMS](https://developer.hashicorp.com/vault/docs/configuration/seal/awskms)


## Archivos auxiliares

- `postgres.yaml`, `mongodb_deploy.yaml`, `openldap_deployment.yml`: manifiestos de soporte.
- `local-pv.yaml`, `pv-claim.yaml`: almacenamiento persistente local.
- `transit-apps/`: apps Python (`hvac`) y Java (Spring Cloud Vault) más `k8s.yaml` del laboratorio Transit.
- `batch_*.json`, `tamper_*.json`, `ciphertext.txt`: se generan al ejecutar `10_Transit.ipynb` (están en `.gitignore`).

## Consejos de ejecución

- Ejecuta los notebooks en orden para evitar fallos por dependencias entre laboratorios.
- `10_Transit.ipynb` necesita `pki_int` del notebook 2 para emitir el certificado de cliente TLS.
- Si cambias de kernel y aparece error de ipykernel, reinstálalo en el intérprete activo.
- Evita guardar tokens reales en notebooks (GitHub Push Protection bloquea commits con secretos).

## Referencias

- Vault docs: https://developer.hashicorp.com/vault/docs
- Vault on Kubernetes: https://developer.hashicorp.com/vault/tutorials/kubernetes
- VSO: https://developer.hashicorp.com/vault/docs/platform/k8s/vso
- CSI Provider: https://developer.hashicorp.com/vault/docs/platform/k8s/csi
- Agent Injector: https://developer.hashicorp.com/vault/docs/platform/k8s/injector
- Transit: https://developer.hashicorp.com/vault/docs/secrets/transit
- Batch tokens: https://developer.hashicorp.com/vault/docs/concepts/tokens#batch-tokens
- cert-manager: https://cert-manager.io/docs/

## Licencia

Material educativo para el webinar de Vault en Kubernetes.
