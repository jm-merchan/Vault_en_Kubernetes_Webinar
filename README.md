# Vault en Kubernetes - Webinar

Este repositorio contiene una colección completa de notebooks para el webinar sobre HashiCorp Vault en Kubernetes, demostrando diferentes patrones de integración y casos de uso.

## Prerequisitos

* **Minikube** o cluster de Kubernetes
* **Podman** (para imágenes de contenedor)
* **Python 3.9+**
  * `python-dotenv`
  * `jupyter`
* **Herramientas CLI:**
  * `vault` (HashiCorp Vault CLI)
  * `kubectl`
  * `helm`
  * `k9s` (opcional, para visualización)
  * `jq`

## Inicio Rápido

1. **Clona el repositorio:**
   ```bash
   git clone <repository-url>
   cd Vault_on_Kubernetes_Webinar
   ```

2. **Inicia Minikube y despliega Vault:**
   ```bash
   # Ejecuta el primer notebook
   jupyter notebook 1_Deploy_Vault_minikube.ipynb
   ```

3. **Verifica la instalación:**
   ```bash
   k9s
   :namespace vault
   :pods
   ```

## Notebooks del Webinar

### 1. Infraestructura Base

#### `1_Deploy_Vault_minikube.ipynb`
Despliega HashiCorp Vault en Minikube usando Helm con configuración de alta disponibilidad.

**Características:**
- Instalación de Vault usando Helm chart
- Configuración de Raft storage backend
- Inicialización y unsealing de Vault
- Configuración de variables de entorno
- Generación de archivo `config.env` con credenciales

**Validación:**
```bash
kubectl get pods -n vault
vault status
```

---

### 2. Secret Engines

#### `2_Database_Secret_Engine.ipynb`
Configura el Database Secret Engine para credenciales dinámicas de PostgreSQL.

**Características:**
- Despliegue de PostgreSQL en Kubernetes
- Configuración de roles para credenciales dinámicas
- TTL y rotación automática
- Integración con aplicaciones

**Validación:**
```bash
vault read database/creds/readonly
kubectl get secret -n database
```

#### `2_PKI.ipynb`
Implementa una PKI completa con CA raíz e intermedia.

**Características:**
- Creación de CA raíz y CA intermedia
- Configuración de roles para emisión de certificados
- Templates y políticas de certificados
- Revocación de certificados

**Validación:**
```bash
vault list pki_int/certs
vault read pki_int/cert/<serial>
```

#### `2b_LDAP_Authentication.ipynb`
Configura autenticación LDAP con OpenLDAP.

**Características:**
- Despliegue de OpenLDAP en Kubernetes
- Configuración de LDAP auth method
- Mapeo de grupos a políticas
- Validación de login LDAP

**Validación:**
```bash
vault login -method=ldap username=<user>
vault auth list
```

#### `2c_LDAP_Secret_Engine.ipynb`
Gestiona credenciales dinámicas de LDAP.

**Características:**
- Configuración de LDAP secrets engine
- Rotación de passwords LDAP
- Gestión de service accounts
- Políticas de acceso

**Validación:**
```bash
vault read ldap/creds/<role>
```

#### `2d_MongoDB_Secret_Engine.ipynb`
Credenciales dinámicas para MongoDB.

**Características:**
- Despliegue de MongoDB
- Database roles y permisos
- Generación de credenciales temporales
- Revocación automática

**Validación:**
```bash
vault read mongodb/creds/<role>
```

---

### 3. Integraciones con Kubernetes

#### `3_VSO.ipynb`
Vault Secrets Operator - Sincronización declarativa de secretos.

**Características:**
- Instalación de VSO usando Helm
- Custom Resource Definitions (CRDs):
  - `VaultConnection` - Conexión a Vault
  - `VaultAuth` - Autenticación Kubernetes
  - `VaultStaticSecret` - Secretos estáticos (KV)
  - `VaultDynamicSecret` - Credenciales dinámicas
  - `VaultPKISecret` - Certificados PKI
- Rollout restart automático
- Instant updates con eventos
- Transformaciones de secretos
- Renovación automática

**Validación:**
```bash
kubectl get vaultconnection -n vault-secrets-operator
kubectl get vaultstaticsecret -A
kubectl describe vaultdynamicsecret -n database
```

#### `4_Vault_Agent_injector.ipynb`
Inyección de secretos como sidecars usando annotations.

**Características:**
- Instalación del Agent Injector
- Annotations para inyección automática
- Templates de Agent
- Init containers vs sidecars
- Renderizado de templates

**Validación:**
```bash
kubectl get pods -n agent
kubectl logs <pod> -c vault-agent
```

#### `5_CSI_Provider.ipynb`
Montaje de secretos como volúmenes CSI.

**Características:**
- Instalación del CSI provider
- SecretProviderClass configuration
- Montaje de secretos en filesystem
- Rotación automática
- Sincronización con Kubernetes secrets

**Validación:**
```bash
kubectl get secretproviderclass
kubectl exec <pod> -- ls /mnt/secrets
```

#### `5b_VSO_Protected_Secrets.ipynb` / `6_VSO_Protected_Secrets.ipynb`
Secretos protegidos con CSI usando VSO.

**Características:**
- Habilitación de CSI en VSO
- CSISecrets CRD
- Access control patterns:
  - `serviceAccountPattern`
  - `namespacePatterns`
  - `containerState.namePattern`
- Match policies (all/any)
- RBAC para CSI driver
- Sincronización de secretos estáticos y AppRole
- Troubleshooting de permisos

**Validación:**
```bash
kubectl get csisecrets -n vault-secrets-operator
kubectl describe pod -n psecret
kubectl exec <pod> -- ls /var/run/csi-secrets/
```

---

### 4. Gestión de Certificados

#### `7_CertManager.ipynb`
Integración con cert-manager para automatización de certificados.

**Características:**
- Instalación de cert-manager
- Issuer y ClusterIssuer configuration
- Certificate resources
- Integración con Vault PKI
- Renovación automática

**Validación:**
```bash
kubectl get certificate -A
kubectl describe issuer vault-issuer
```

#### `8_ACME.ipynb`
Protocolo ACME para certificados estilo Let's Encrypt.

**Características:**
- Configuración de ACME en Vault PKI
- External Account Binding (EAB)
- ACME challenges (HTTP-01)
- Integración con cert-manager
- Troubleshooting de TTL y configuración

**Validación:**
```bash
vault list pki_int/acme/directory
kubectl get certificate -n test
```

---

### 5. Casos de Uso Avanzados

#### `9_Other_Use_Cases.ipynb`
Casos de uso específicos de producción.

**Casos cubiertos:**
1. **Certificados de cliente (JKS):**
   - Almacenamiento de Java KeyStore en base64
   - Password cifrada del JKS
   - Montaje en aplicaciones Java

2. **Truststores:**
   - Gestión de truststores JKS
   - Cadenas de certificados
   - Actualización automática

3. **Basic HTTP Authentication:**
   - Username/password para SOAP/REST
   - Rotación de credenciales
   - Templates para diferentes formatos

4. **API Keys:**
   - Gestión de API keys para clientes REST
   - Versionado de keys
   - Revocación

5. **Credenciales de bases de datos Oracle:**
   - Conexiones por entorno
   - Credenciales dinámicas
   - Rotación programada

6. **Conexiones a Host (mainframe):**
   - tpnName/user management
   - Secretos por entorno
   - Integración con aplicaciones legacy

7. **Secretos OAuth:**
   - Client secrets para OAuth flows
   - HMAC signing
   - Rotación de secretos

8. **Claves de cifrado:**
   - Gestión de claves privadas
   - Transit engine para operaciones criptográficas
   - Cifrado/descifrado de recursos
   - Key rotation

**Características de Transit Engine:**
- Cifrado y descifrado
- Signing y verificación
- HMAC operations
- Key derivation
- Rewrapping después de rotation

**Validación:**
```bash
vault write transit/encrypt/my-key plaintext=<base64>
vault write transit/decrypt/my-key ciphertext=<vault-encrypted>
```

---

## Arquitectura General

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Applications  │────│  Secret Clients │────│     Vault      │
│                 │    │                 │    │                 │
│ • Microservices │    │ • VSO          │    │ • Auth Methods  │
│ • Batch Jobs    │    │ • Agent Inject │    │ • Secret Engines│
│ • Web Apps      │    │ • CSI Provider │    │ • Policies      │
│ • Legacy Apps   │    │ • cert-manager │    │ • Transit       │
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
                       │ • Certificates │
                       └─────────────────┘
```

### Componentes de Integración

- **Vault Secrets Operator (VSO)**: Gestiona secretos como recursos nativos de Kubernetes con CRDs
- **Agent Injector**: Inyecta secretos en pods mediante sidecars o init containers
- **CSI Provider**: Monta secretos como volúmenes usando Container Storage Interface
- **cert-manager**: Automatiza la gestión y renovación de certificados TLS
- **PKI Engine**: Gestiona certificados X.509 y actúa como CA
- **Database Engines**: Credenciales dinámicas para PostgreSQL, MongoDB, Oracle
- **Transit Engine**: Operaciones criptográficas (cifrado, firma, HMAC)
- **LDAP**: Autenticación y secretos dinámicos para directorios LDAP
- **ACME**: Protocolo para obtención automática de certificados

---

## Patrones de Integración

### Comparación de métodos

| Método | Use Case | Ventajas | Consideraciones |
|--------|----------|----------|-----------------|
| **VSO** | Aplicaciones cloud-native | • CRDs nativos de K8s<br>• Renovación automática<br>• Transformaciones<br>• GitOps friendly | Requiere VSO deployment |
| **Agent Injector** | Aplicaciones con templates complejos | • Sin cambios en la app<br>• Templates avanzados<br>• Sidecar automático | Overhead de sidecar |
| **CSI Provider** | Secretos como archivos | • Montaje directo<br>• Rotación automática<br>• Sin sidecar | Requires CSI driver support |
| **Protected Secrets (CSI+VSO)** | Multi-tenant environments | • Access control granular<br>• Namespace isolation<br>• Container-level filtering | RBAC configuration required |

---

## Troubleshooting

### CSI Driver Issues

**Problema:** `PermissionDenied desc = not authorized for secret sync`

**Solución:**
```bash
# Verificar RBAC
kubectl get clusterrole vso-csi-secrets-reader
kubectl get clusterrolebinding vso-csi-secrets-reader-binding

# Si no existe, crear:
kubectl apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: vso-csi-secrets-reader
rules:
- apiGroups: ["secrets.hashicorp.com"]
  resources: ["csisecrets"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: vso-csi-secrets-reader-binding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: vso-csi-secrets-reader
subjects:
- kind: ServiceAccount
  name: vault-secrets-operator-csi-node
  namespace: vault-secrets-operator
EOF
```

**Problema:** Secretos no se montan en pods

**Diagnóstico:**
```bash
# Verificar CSISecrets resource
kubectl describe csisecrets -n vault-secrets-operator

# Verificar logs del CSI driver
kubectl logs -n vault-secrets-operator -l app.kubernetes.io/component=csi-provider

# Verificar accessControl patterns
kubectl get csisecrets <name> -o yaml | grep -A 10 accessControl
```

**Solución:** Ajustar `accessControl` patterns:
```yaml
accessControl:
  - serviceAccountPattern: "^webapp$"
    namespacePatterns: ["^app-.*$"]
    # containerState.namePattern puede causar problemas - usar solo si necesario
```

### Certificate TTL Issues

**Problema:** Certificados con TTL muy corto (ej. 5 minutos)

**Solución:**
```bash
# Aumentar max_ttl en role PKI
vault write pki_int/roles/cert-manager \
  allowed_domains=example.com \
  allow_subdomains=true \
  max_ttl=8760h \
  ttl=720h

# Actualizar Certificate resource
kubectl patch certificate my-cert -n test --type=merge -p '{"spec":{"duration":"720h","renewBefore":"360h"}}'
```

### ACME Configuration

**Problema:** ACME directory no permite durations largas

**Solución:** Configurar `default_directory_ttl`:
```bash
vault write pki_int/config/acme \
  enabled=true \
  default_directory_ttl=24h
```

### VaultDynamicSecret Template Errors

**Problema:** Error en transformación de secrets

**Diagnóstico:**
```bash
kubectl describe vaultdynamicsecret -n database
# Buscar eventos con errores de template
```

**Solución:** Usar sintaxis correcta de Go template:
```yaml
# ❌ Incorrecto - no se puede asignar variables en action blocks
{{- $host := get .Annotations "..." -}}

# ✅ Correcto - inline get directo
{{- printf "postgresql://%s:%s@%s/postgres" 
    (get .Secrets "username") 
    (get .Secrets "password") 
    (get .Annotations "myapp.config/postgres-host") -}}
```

---

## Recursos Adicionales

### Documentación Oficial

- [HashiCorp Vault Documentation](https://developer.hashicorp.com/vault)
- [Vault Secrets Operator](https://developer.hashicorp.com/vault/docs/platform/k8s/vso)
- [Vault CSI Provider](https://developer.hashicorp.com/vault/docs/platform/k8s/csi)
- [Vault Agent Injector](https://developer.hashicorp.com/vault/docs/platform/k8s/injector)
- [cert-manager](https://cert-manager.io/docs/)

### Tutoriales

- [Vault on Kubernetes Deployment Guide](https://developer.hashicorp.com/vault/tutorials/kubernetes/kubernetes-minikube)
- [Dynamic Database Credentials](https://developer.hashicorp.com/vault/tutorials/db-credentials)
- [Build Your Own CA](https://developer.hashicorp.com/vault/tutorials/secrets-management/pki-engine)
- [Transit Engine - Encryption as a Service](https://developer.hashicorp.com/vault/tutorials/encryption-as-a-service)

### Community

- [Vault GitHub](https://github.com/hashicorp/vault)
- [VSO GitHub](https://github.com/hashicorp/vault-secrets-operator)
- [HashiCorp Discuss](https://discuss.hashicorp.com/c/vault)

---

## Licencia

Este proyecto es proporcionado como material educativo para el webinar de Vault en Kubernetes.

## Contacto

Para preguntas o soporte adicional sobre este webinar, consulta los canales oficiales de HashiCorp.

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
