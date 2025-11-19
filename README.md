# Vault en Kubernetes - Webinar

## Prerequisitos

* Podman
* Python 3.9
  * dotenv
* Jupyter Notebook
* k9s

## Inicio Rápido

1. **Clona el repositorio y configura el entorno:**
   ```bash
   git clone <repository-url>
   cd Vault_en_Kubernetes_Webinar
   cp /tmp/vault/config.env .  # Si tienes configuración previa
   ```

2. **Ejecuta los notebooks en orden:**
   - `1_Deploy_Vault_minikube.ipynb` - Despliegue base de Vault
   - `2_Database_Secret_Engine.ipynb` - Configuración de base de datos
   - `2_PKI.ipynb` - Configuración de PKI
   - `3_VSO.ipynb` - Vault Secrets Operator
   - `4_Vault_Agent_injector.ipynb` - Agent Injector
   - `5_CSI_Provider.ipynb` - CSI Provider
   - `6_Use_Cases.ipynb` - Casos de uso avanzados
   - `7_CertManager.ipynb` - cert-manager integration
   - `8_ACME.ipynb` - ACME certificates

3. **Verifica con k9s:**
   ```bash
   k9s
   :namespace test
   :secrets
   ```

## Arquitectura General

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Applications  │────│  Secret Clients │────│     Vault      │
│                 │    │                 │    │                 │
│ • Microservices │    │ • VSO          │    │ • Auth Methods  │
│ • Batch Jobs    │    │ • Agent Inject │    │ • Secret Engines│
│ • Web Apps      │    │ • CSI Provider │    │ • Policies      │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                │
                                ▼
                       ┌─────────────────┐
                       │   Kubernetes   │
                       │   Resources    │
                       │                 │
                       │ • Secrets      │
                       │ • ConfigMaps   │
                       │ • Volumes      │
                       └─────────────────┘
```

### Componentes de Integración

- **Vault Secrets Operator (VSO)**: Gestiona secretos como recursos nativos de Kubernetes
- **Agent Injector**: Inyecta secretos en pods al momento del despliegue
- **CSI Provider**: Monta secretos como volúmenes en contenedores
- **PKI Engine**: Gestiona certificados X.509
- **Database Engine**: Credenciales dinámicas para bases de datos
- **ACME**: Certificados automáticos estilo Let's Encrypt


## Introducción

Este repo contiene una serie de Jupyter notebooks muestran los pasos para desplegar:

1. Un clúster de Vault en minikube (sobre Podman). El despliegue usando Helm, también incluye los componentes necesarios para hacer las integraciones usando el CSI Provider y Vault Agent Injector.
2. Desplegamos una base de datos postgres sobre minikube para mostrar la integración con secretos dinámicos.
3. Desplegue de VSO con secretos estáticos y dinámicos.
4. Vault agent con secretos dinámicos y templating.
5. CSI Provider con secretos dinámicos.
6. PKI Secrets Engine para gestión de certificados.
7. Cert-Manager integration con Vault.
8. ACME certificate provisioning con Vault.

## Notebooks Disponibles

### 1. 1_Deploy_Vault_minikube.ipynb
Despliegue completo de Vault en Minikube usando Helm charts. Incluye:
- Configuración del clúster de Vault Enterprise con alta disponibilidad
- Instalación del CSI Provider y Vault Agent Injector
- Inicialización y unseal del clúster de Vault
- Acceso mediante port-forward

### 2. 2_Database_Secret_Engine.ipynb
Configuración del motor de secretos de base de datos:
- Configuración de PostgreSQL como backend
- Creación de roles para credenciales dinámicas
- Políticas de acceso para bases de datos

### 3. 2_PKI.ipynb
Motor de secretos PKI para gestión de certificados:
- Configuración de Certificate Authorities
- Creación de roles PKI
- Emisión de certificados intermedios y finales
- Gestión de Certificate Revocation Lists (CRL)

### 4. 3_VSO.ipynb (Vault Secrets Operator)
Integración con Vault Secrets Operator:
- Despliegue de VSO en el clúster
- Configuración de VaultAuth y VaultStaticSecret, VaultDynamicSecret, VaultPKISecret
- Secretos estáticos y dinámicos
- Sincronización automática de secretos y reload de workload consumidor.

### 5. 4_Vault_Agent_injector.ipynb
Vault Agent Injector para inyección de secretos:
- Configuración de mutating webhooks
- Inyección de secretos en pods
- Templates para transformación de datos
- Manejo de certificados TLS

### 6. 5_CSI_Provider.ipynb
CSI Provider para montaje de secretos como volúmenes:
- Configuración del driver CSI
- SecretProviderClass para secretos estáticos
- Montaje de secretos en pods

### 7. 6_Use_Cases.ipynb
Casos de uso prácticos y escenarios avanzados:
- Gestión de secretos estáticos en la forma de binarios, archivos de configuración, claves de encriptación y otros

### 8. 7_CertManager.ipynb
Integración con cert-manager para gestión automática de certificados:
- Configuración de issuers Vault
- Solicitud automática de certificados
- Renovación automática de certificados

### 9. 8_ACME.ipynb
ACME protocol con Vault para certificados Let's Encrypt-style:
- Configuración de ACME en Vault
- Caddy web server con ACME
- cert-manager con ACME
- Validación HTTP-01 y DNS-01
- Renovación automática de certificados
- Integración con ingress controllers
