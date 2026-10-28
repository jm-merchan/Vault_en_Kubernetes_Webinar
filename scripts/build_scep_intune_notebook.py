#!/usr/bin/env python3
"""Build the standalone SCEP + Microsoft Intune validation notebook."""

from pathlib import Path
import json
import os


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(os.environ.get("SCEP_NOTEBOOK_OUTPUT", ROOT / "SCEP_Intune_Validation.ipynb"))

cells = []


def md(text: str) -> None:
    cells.append({"cell_type": "markdown", "id": f"cell-{len(cells):03d}", "metadata": {},
                  "source": (text.strip() + "\n").splitlines(keepends=True)})


def code(text: str) -> None:
    cells.append({"cell_type": "code", "id": f"cell-{len(cells):03d}", "execution_count": None, "metadata": {}, "outputs": [],
                  "source": (text.strip() + "\n").splitlines(keepends=True)})


md(r"""
# Vault PKI SCEP + Microsoft Intune: validación técnica y de licenciamiento

Notebook independiente para Vault Enterprise **1.20+** (validado estructuralmente contra Vault Enterprise 2.2.0). Crea recursos de prueba aislados, configura SCEP con `auth_type="intune"`, conserva evidencia de auditoría y compara los contadores de **Vault Clients** y **PKI Only**.

La afirmación «una integración Intune equivale a un Vault Client» es una **hipótesis**, no una premisa. Este notebook distingue:

- **OBSERVED**: resultado obtenido en el entorno y conservado en `evidence/scep-intune-validation/`.
- **DOCUMENTED**: comportamiento descrito oficialmente por HashiCorp o Microsoft.
- **INFERENCE**: conclusión derivada de evidencia, todavía no observada directamente.
- **NOT VALIDATED**: falta una credencial, perfil, dispositivo, espera de persistencia o acción externa.

Referencias oficiales: [Vault SCEP](https://developer.hashicorp.com/vault/docs/secrets/pki/scep), [SCEP API](https://developer.hashicorp.com/vault/api-docs/secret/pki/issuance#scep-certificate-issuance), [SCEP auth API](https://developer.hashicorp.com/vault/api-docs/auth/scep), [Vault client counting](https://developer.hashicorp.com/vault/docs/concepts/billing/clients), [certificate counting](https://developer.hashicorp.com/vault/docs/concepts/billing/certificate-counts), [Intune third-party CA](https://learn.microsoft.com/en-us/intune/fundamentals/certificates/third-party-ca-scep).
""")

md(r"""
## 0. Modelo de ejecución y seguridad

Antes de abrir el notebook, carga `VAULT_ADDR`, `VAULT_CACERT` y `VAULT_TOKEN` en el proceso de Jupyter. `VAULT_NAMESPACE` es opcional; vacío significa root. El notebook nunca imprime tokens, client secrets ni challenges.

Para aplicar recursos: `SCEP_APPLY_CHANGES=true`. Sin ese flag, las celdas muestran el plan y no mutan Vault. Para la credencial Intune se recomienda `INTUNE_CREDENTIAL_MODE=server-env`, que guarda referencias `env://AZURE_*`; esas variables deben existir **en el proceso servidor de Vault**, no solo en Jupyter. Alternativas: `direct` (valores runtime `INTUNE_*`, no quedan en el código) o `msi`.

La limpieza exige `SCEP_CONFIRM_CLEANUP=DELETE_SCEP_INTUNE_VALIDATION`. Nunca se ejecuta implícitamente.
""")

code(r"""
import json, os, re, shutil, ssl, subprocess, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from IPython.display import Markdown, display

def load_env_file(path="/tmp/vault/config.env"):
    p = Path(path)
    if not p.exists():
        return
    for raw in p.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.replace("export ", "").strip(), value)

load_env_file()

VAULT_BIN = os.getenv("VAULT_BIN", "/opt/homebrew/bin/vault")
OPENSSL_BIN = os.getenv("OPENSSL_BIN", "/opt/homebrew/opt/openssl@3/bin/openssl")
if not Path(OPENSSL_BIN).exists(): OPENSSL_BIN = shutil.which("openssl") or "openssl"
KUBECTL_BIN = os.getenv("KUBECTL_BIN", shutil.which("kubectl") or "kubectl")
JQ_BIN = os.getenv("JQ_BIN", "/usr/bin/jq")

APPLY = os.getenv("SCEP_APPLY_CHANGES", "false").lower() == "true"
REQUIRE_INTUNE = os.getenv("SCEP_REQUIRE_INTUNE", "false").lower() == "true"
CREDENTIAL_MODE = os.getenv("INTUNE_CREDENTIAL_MODE", "server-env").lower()
NAMESPACE = os.getenv("VAULT_NAMESPACE", "")
WORKDIR = Path(os.getenv("SCEP_WORKDIR", "/tmp/vault/scep-intune-validation"))
EVIDENCE = Path(os.getenv("SCEP_EVIDENCE_DIR", "evidence/scep-intune-validation")).resolve()
WORKDIR.mkdir(parents=True, exist_ok=True); EVIDENCE.mkdir(parents=True, exist_ok=True)
os.chmod(WORKDIR, 0o700); os.chmod(EVIDENCE, 0o700)

ROOT_MOUNT = "pki_scep_intune_root"
PKI_MOUNT = "pki_scep_intune"
SCEP_AUTH = "scep-intune"
SCEP_AUTH_ALT = "scep-intune-alt"
CERT_AUTH = "scep-intune-cert"
ROLE = "scep-intune-devices"
ROLE_ALT = "scep-intune-devices-alt"
AUTH_ROLE = "intune"
AUTH_ROLE_ALT = "intune-alt"
POLICY = "scep-intune-access"
POLICY_ALT = "scep-intune-access-alt"
AUDIT_PATH = "scep-intune-validation"
AUDIT_FILE = "/tmp/scep-intune-validation-audit.json"

SAFE_ENV = os.environ.copy()
if NAMESPACE: SAFE_ENV["VAULT_NAMESPACE"] = NAMESPACE
else: SAFE_ENV.pop("VAULT_NAMESPACE", None)

def run(cmd, *, input_text=None, check=True, sensitive=False):
    p = subprocess.run(cmd, input=input_text, text=True, capture_output=True, env=SAFE_ENV)
    if check and p.returncode:
        detail = "<redacted>" if sensitive else (p.stderr.strip() or p.stdout.strip())
        raise RuntimeError(f"command failed ({p.returncode}): {cmd[0]} {cmd[1] if len(cmd)>1 else ''}: {detail}")
    return p

def vault(*args, input_text=None, check=True, sensitive=False):
    return run([VAULT_BIN, *args], input_text=input_text, check=check, sensitive=sensitive)

def vault_json(*args, input_text=None, check=True, sensitive=False):
    p = vault(*args, input_text=input_text, check=check, sensitive=sensitive)
    return json.loads(p.stdout) if p.stdout.strip() else {}

def save_json(name, value):
    (EVIDENCE / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")

def redact_config(obj):
    clone = json.loads(json.dumps(obj))
    ext = clone.get("data", clone).get("external_validation", {}).get("intune", {})
    if "client_secret" in ext: ext["client_secret"] = "<redacted-reference-or-secret>"
    return clone

print(json.dumps({"apply_changes": APPLY, "namespace": NAMESPACE or "root", "credential_mode": CREDENTIAL_MODE,
                  "workdir": str(WORKDIR), "evidence": str(EVIDENCE)}, indent=2))
""")

md(r"""
## 1. Preflight: versión, edición, herramientas y variables

Este bloque falla antes de mutar nada si Vault, TLS, el token administrativo o las herramientas locales no están disponibles. La ausencia de Intune no bloquea la configuración local salvo que `SCEP_REQUIRE_INTUNE=true`.
""")

code(r"""
missing = [name for name in ("VAULT_ADDR", "VAULT_CACERT", "VAULT_TOKEN") if not os.getenv(name)]
if missing: raise RuntimeError("Missing required environment variables: " + ", ".join(missing))
for tool in (VAULT_BIN, OPENSSL_BIN):
    if not (Path(tool).exists() or shutil.which(tool)): raise RuntimeError(f"Required tool not found: {tool}")
if not Path(os.environ["VAULT_CACERT"]).is_file(): raise RuntimeError("VAULT_CACERT is not a readable file")

status = vault_json("status", "-format=json")
version = status.get("version", "")
if "+ent" not in version: raise RuntimeError(f"SCEP requires Vault Enterprise; observed {version}")
m = re.match(r"(\d+)\.(\d+)", version)
if not m or (int(m.group(1)), int(m.group(2))) < (1, 20):
    raise RuntimeError(f"SCEP requires Vault Enterprise 1.20+; observed {version}")

license_status = vault_json("read", "-format=json", "sys/license/status")
safe_license = {"version": version, "cluster_name": status.get("cluster_name"), "sealed": status.get("sealed"),
                "license_expiration": license_status.get("data", {}).get("autoloaded", {}).get("expiration_time")}
save_json("preflight.json", safe_license)
print(json.dumps(safe_license, indent=2))

direct_ready = all(os.getenv(x) for x in ("INTUNE_TENANT_ID", "INTUNE_CLIENT_ID", "INTUNE_CLIENT_SECRET"))
server_ready = os.getenv("INTUNE_SERVER_ENV_READY", "false").lower() == "true"
msi_ready = bool(os.getenv("INTUNE_TENANT_ID")) and os.getenv("INTUNE_MSI_READY", "false").lower() == "true"
INTUNE_READY = {"direct": direct_ready, "server-env": server_ready, "msi": msi_ready}.get(CREDENTIAL_MODE, False)
print("Intune readiness:", "READY" if INTUNE_READY else "NOT VALIDATED")
if REQUIRE_INTUNE and not INTUNE_READY:
    raise RuntimeError("Intune is required but its runtime credential/profile readiness has not been confirmed")
""")

md(r"""
## 2. Inventario y línea base de contadores

`sys/internal/counters/activity` mide clientes activos del período. `sys/billing/certificates` mide certificados PKI y puede tardar unos dos minutos en persistir. El activity export puede retrasarse hasta 20 minutos durante el mes actual.
""")

code(r"""
mounts = vault_json("secrets", "list", "-format=json")
auths = vault_json("auth", "list", "-format=json")
planned = {
    "secret_mounts": [ROOT_MOUNT + "/", PKI_MOUNT + "/"],
    "auth_mounts": [SCEP_AUTH + "/", SCEP_AUTH_ALT + "/", CERT_AUTH + "/"],
    "policies": [POLICY, POLICY_ALT],
    "roles": [ROLE, ROLE_ALT],
    "namespace": NAMESPACE or "root",
}
conflicts = []
for path in planned["secret_mounts"]:
    if path in mounts and mounts[path].get("type") != "pki": conflicts.append(path)
for path in planned["auth_mounts"]:
    wanted = "cert" if path == CERT_AUTH + "/" else "scep"
    if path in auths and auths[path].get("type") != wanted: conflicts.append(path)
if conflicts: raise RuntimeError("Refusing to reuse conflicting paths: " + ", ".join(conflicts))
save_json("planned-resources.json", planned)
print(json.dumps(planned, indent=2))

activity_before = vault_json("read", "-format=json", "sys/internal/counters/activity")
certs_before = vault_json("read", "-format=json", "sys/billing/certificates")
save_json("activity-before.json", activity_before); save_json("certificates-before.json", certs_before)
def cert_total(doc):
    return sum(m.get("counts", {}).get("issued_certificates", 0) for m in doc.get("data", {}).get("months", []))
print({"clients_before": activity_before.get("data", {}).get("total", {}), "certificates_before": cert_total(certs_before)})
""")

md(r"""
## 3. Root e issuer intermedio RSA aislados

SCEP solo admite issuers respaldados por claves RSA. Se crea una raíz de laboratorio en `pki_scep_intune_root/` y un issuer intermedio en `pki_scep_intune/`; ninguna CA existente se reutiliza.
""")

code(r"""
def ensure_secret_mount(path, description):
    current = vault_json("secrets", "list", "-format=json")
    if path + "/" not in current:
        vault("secrets", "enable", f"-path={path}", f"-description={description}", "pki")

def list_issuers(path):
    p = vault("list", "-format=json", f"{path}/issuers", check=False)
    return json.loads(p.stdout) if p.returncode == 0 and p.stdout.strip() else []

if not APPLY:
    print("PLAN ONLY: set SCEP_APPLY_CHANGES=true to create the two PKI mounts and issuers")
else:
    ensure_secret_mount(ROOT_MOUNT, "SCEP Intune validation root - safe to delete")
    vault("secrets", "tune", "-max-lease-ttl=87600h", ROOT_MOUNT)
    if not list_issuers(ROOT_MOUNT):
        vault_json("write", "-format=json", f"{ROOT_MOUNT}/root/generate/internal",
                   "common_name=SCEP Intune Validation Root", "issuer_name=scep-intune-root",
                   "key_type=rsa", "key_bits=2048", "ttl=87600h")
    ensure_secret_mount(PKI_MOUNT, "SCEP Intune validation issuer - safe to delete")
    vault("secrets", "tune", "-max-lease-ttl=43800h", PKI_MOUNT)
    if not list_issuers(PKI_MOUNT):
        csr = vault_json("write", "-format=json", f"{PKI_MOUNT}/intermediate/generate/internal",
                         "common_name=SCEP Intune Validation Intermediate", "issuer_name=scep-intune-intermediate",
                         "key_type=rsa", "key_bits=2048")["data"]["csr"]
        csr_file = WORKDIR / "intermediate.csr"; csr_file.write_text(csr)
        signed = vault_json("write", "-format=json", f"{ROOT_MOUNT}/root/sign-intermediate",
                            "issuer_ref=scep-intune-root", f"csr=@{csr_file}", "format=pem_bundle", "ttl=43800h")
        cert_file = WORKDIR / "intermediate.pem"; cert_file.write_text(signed["data"]["certificate"])
        vault("write", f"{PKI_MOUNT}/intermediate/set-signed", f"certificate=@{cert_file}")
    print("PKI mounts and RSA issuers: READY")
""")

md(r"""
## 4. Roles PKI y políticas mínimas

Se preparan un rol primario y uno alternativo. El alternativo permite comprobar si cambiar la combinación de políticas produce otro `client_id`; no debe confundirse con cambiar solo el PKI role manteniendo las mismas políticas.
""")

code(r"""
if not APPLY:
    print("PLAN ONLY: roles", ROLE, ROLE_ALT, "policies", POLICY, POLICY_ALT)
else:
    issuer = vault_json("read", "-format=json", f"{PKI_MOUNT}/config/issuers")["data"]["default"]
    common = [f"issuer_ref={issuer}", "allowed_domains=scep-intune.example.test", "allow_subdomains=true",
              "allow_bare_domains=false", "allow_ip_sans=true", "client_flag=true", "server_flag=false",
              "key_type=rsa", "key_bits=2048", "ttl=24h", "max_ttl=48h", "not_before_duration=0s",
              "require_cn=true", "use_csr_common_name=true", "use_csr_sans=true", "no_store=false",
              "ext_key_usage=Client Auth"]
    for role in (ROLE, ROLE_ALT): vault("write", f"{PKI_MOUNT}/roles/{role}", *common)
    for policy, role in ((POLICY, ROLE), (POLICY_ALT, ROLE_ALT)):
        hcl = f'''path "{PKI_MOUNT}/roles/{role}/scep" {{ capabilities = ["read", "create", "update"] }}
path "{PKI_MOUNT}/roles/{role}/scep/pkiclient.exe" {{ capabilities = ["read", "create", "update"] }}
'''
        vault("policy", "write", policy, "-", input_text=hcl)
    print("PKI roles and least-privilege policies: READY")
""")

md(r"""
## 5. Auth mounts SCEP/cert y batch tokens

El auth mount principal y el alternativo usan `auth_type="intune"` y `token_type="batch"`. El mount `cert` permite investigar renovaciones sin challenge. Batch no significa «gratis»: HashiCorp documenta que se cuenta igual que service y, si no hay entidad, Vault construye el cliente a partir de alias (si existe), políticas y namespace.
""")

code(r"""
def ensure_auth_mount(path, auth_type, description):
    current = vault_json("auth", "list", "-format=json")
    if path + "/" not in current:
        vault("auth", "enable", f"-path={path}", f"-description={description}", auth_type)

if not APPLY:
    print("PLAN ONLY: SCEP auth roles use batch tokens; cert auth is prepared for renewal")
else:
    for auth_path in (SCEP_AUTH, SCEP_AUTH_ALT):
        ensure_auth_mount(auth_path, "scep", "SCEP Intune validation - safe to delete")
        vault("auth", "tune", "-token-type=batch", auth_path)
    vault("write", f"auth/{SCEP_AUTH}/role/{AUTH_ROLE}", "auth_type=intune", f"token_policies={POLICY}",
          "token_no_default_policy=true", "token_type=batch", "token_ttl=5m")
    vault("write", f"auth/{SCEP_AUTH}/role/{AUTH_ROLE_ALT}", "auth_type=intune", f"token_policies={POLICY_ALT}",
          "token_no_default_policy=true", "token_type=batch", "token_ttl=5m")
    vault("write", f"auth/{SCEP_AUTH_ALT}/role/{AUTH_ROLE}", "auth_type=intune", f"token_policies={POLICY}",
          "token_no_default_policy=true", "token_type=batch", "token_ttl=5m")
    ensure_auth_mount(CERT_AUTH, "cert", "SCEP certificate renewal validation - safe to delete")
    vault("auth", "tune", "-token-type=batch", CERT_AUTH)
    ca = vault("read", "-field=certificate", f"{PKI_MOUNT}/cert/ca").stdout
    ca_file = WORKDIR / "issuer-ca.pem"; ca_file.write_text(ca + ("" if ca.endswith("\n") else "\n"))
    vault("write", f"auth/{CERT_AUTH}/certs/{ROLE}", "display_name=scep-intune-cert-renewal",
          f"token_policies={POLICY}", "token_no_default_policy=true", f"certificate=@{ca_file}",
          "allowed_common_names=*.scep-intune.example.test", "token_type=batch", "token_ttl=5m")
    role_docs = {name: vault_json("read", "-format=json", f"auth/{mount}/role/{name}")
                 for mount, name in ((SCEP_AUTH, AUTH_ROLE), (SCEP_AUTH, AUTH_ROLE_ALT))}
    save_json("scep-auth-roles.json", role_docs)
    assert all(x["data"]["token_type"] == "batch" for x in role_docs.values())
    print("SCEP auth roles confirmed token_type=batch")
""")

md(r"""
## 6. Delegated auth accessors y `external_validation.intune`

Para Intune se fija `restrict_ca_chain_to_issuer=true`, porque HashiCorp documenta que Intune puede fallar si GetCACerts devuelve la cadena completa. `server-env` usa referencias indirectas y requiere que `AZURE_TENANT_ID`, `AZURE_CLIENT_ID` y `AZURE_CLIENT_SECRET` estén en el entorno de **cada proceso Vault**.

La API SCEP documentada por Vault expone `tenant_id`, `client_id`, `client_secret` o el valor `MSI`; no documenta un campo de certificado de aplicación. Por ello este notebook soporta client secret y managed identity. Un credential de aplicación basado en certificado queda **NOT VALIDATED/unsupported by the documented SCEP configuration surface** hasta que HashiCorp confirme otro mecanismo.
""")

code(r"""
def intune_block():
    environment = os.getenv("INTUNE_AZURE_ENVIRONMENT", "AzurePublicCloud")
    if CREDENTIAL_MODE == "direct":
        required = ("INTUNE_TENANT_ID", "INTUNE_CLIENT_ID", "INTUNE_CLIENT_SECRET")
        if not all(os.getenv(x) for x in required):
            raise RuntimeError("direct mode requires runtime INTUNE_TENANT_ID, INTUNE_CLIENT_ID, INTUNE_CLIENT_SECRET")
        return {"tenant_id": os.environ[required[0]], "client_id": os.environ[required[1]],
                "client_secret": os.environ[required[2]], "environment": environment}
    if CREDENTIAL_MODE == "msi":
        return {"tenant_id": os.getenv("INTUNE_TENANT_ID", "env://AZURE_TENANT_ID"),
                "client_id": "MSI", "client_secret": "MSI", "environment": environment}
    return {"tenant_id": "env://AZURE_TENANT_ID", "client_id": "env://AZURE_CLIENT_ID",
            "client_secret": "env://AZURE_CLIENT_SECRET", "environment": "env://AZURE_ENVIRONMENT"}

if not APPLY:
    print("PLAN ONLY: tune delegated accessors and configure SCEP external_validation.intune")
else:
    scep_accessor = vault("read", "-field=accessor", f"sys/auth/{SCEP_AUTH}").stdout.strip()
    cert_accessor = vault("read", "-field=accessor", f"sys/auth/{CERT_AUTH}").stdout.strip()
    vault("secrets", "tune", "-allowed-response-headers=Content-Type",
          f"-delegated-auth-accessors={scep_accessor}", f"-delegated-auth-accessors={cert_accessor}", PKI_MOUNT)
    payload = {"enabled": True, "default_path_policy": f"role:{ROLE}",
               "restrict_ca_chain_to_issuer": True, "log_level": "INFO",
               "authenticators": {"scep": {"accessor": scep_accessor, "scep_role": AUTH_ROLE},
                                  "cert": {"accessor": cert_accessor, "cert_role": ROLE}},
               "external_validation": {"intune": intune_block()}}
    written = vault_json("write", "-format=json", f"{PKI_MOUNT}/config/scep", "-",
                         input_text=json.dumps(payload), sensitive=(CREDENTIAL_MODE == "direct"))
    save_json("scep-config-write-redacted.json", redact_config(written))
    config = vault_json("read", "-format=json", f"{PKI_MOUNT}/config/scep")
    save_json("scep-config-redacted.json", redact_config(config))
    print(json.dumps(redact_config(config).get("data", {}), indent=2))
""")

md(r"""
## 7. Verificación estructural y GetCACerts

La URL que debe usar el perfil Intune es la ruta role-qualified, para que el PKI role quede inequívoco:

`https://<vault>/v1/pki_scep_intune/roles/scep-intune-devices/scep`

GetCACerts no demuestra que las credenciales Intune funcionen; solo valida publicación SCEP, issuer, TLS y compatibilidad de CA.
""")

code(r"""
if not APPLY:
    print("NOT EXECUTED: resources were not applied")
else:
    config = vault_json("read", "-format=json", f"{PKI_MOUNT}/config/scep")["data"]
    role_data = vault_json("read", "-format=json", f"{PKI_MOUNT}/roles/{ROLE}")["data"]
    auth_data = vault_json("read", "-format=json", f"auth/{SCEP_AUTH}/role/{AUTH_ROLE}")["data"]
    mount_data = vault_json("read", "-format=json", f"sys/mounts/{PKI_MOUNT}")["data"]
    checks = {
        "enabled": config.get("enabled") is True,
        "default_path_policy": config.get("default_path_policy") == f"role:{ROLE}",
        "restrict_ca_chain_to_issuer": config.get("restrict_ca_chain_to_issuer") is True,
        "scep_role": config.get("authenticators", {}).get("scep", {}).get("scep_role") == AUTH_ROLE,
        "token_type_batch": auth_data.get("token_type") == "batch",
        "issuer_ref_present": bool(role_data.get("issuer_ref")),
        "delegated_accessors": len(mount_data.get("config", {}).get("delegated_auth_accessors", [])) == 2,
    }
    save_json("structural-checks.json", checks)
    if not all(checks.values()): raise AssertionError(checks)
    print(json.dumps(checks, indent=2))

    base = f"{os.environ['VAULT_ADDR'].rstrip('/')}/v1/{PKI_MOUNT}/roles/{ROLE}/scep/pkiclient.exe"
    url = base + "?" + urllib.parse.urlencode({"operation": "GetCACert", "message": "CAIdentifier"})
    hdr = WORKDIR / "getcacerts.headers"; body = WORKDIR / "getcacerts.der"
    p = run(["curl", "-sS", "--cacert", os.environ["VAULT_CACERT"], "-D", str(hdr), "-o", str(body),
             "-w", "%{http_code}", url])
    if p.stdout.strip() != "200": raise RuntimeError(f"GetCACerts HTTP {p.stdout.strip()}")
    content_type = next((x.split(":",1)[1].strip() for x in hdr.read_text().splitlines()
                         if x.lower().startswith("content-type:")), "")
    inspect = run([OPENSSL_BIN, "x509", "-inform", "DER", "-in", str(body), "-noout", "-subject", "-issuer", "-serial"], check=False)
    if inspect.returncode:
        inspect = run([OPENSSL_BIN, "pkcs7", "-inform", "DER", "-in", str(body), "-print_certs", "-noout"])
    observed = {"http": 200, "content_type": content_type, "certificate": inspect.stdout.strip(), "url": base}
    save_json("getcacerts.json", observed)
    print(json.dumps(observed, indent=2))
""")

md(r"""
## 8. Requisitos externos de Microsoft Intune

Antes de emitir:

1. App registration Entra multitenant con application permissions `Intune > scep_challenge_provider` y `Microsoft Graph > Application.Read.All`, con admin consent.
2. Credencial disponible para Vault (secret, certificado/identidad según soporte operativo, o MSI). No la pegues aquí.
3. URL Vault pública por HTTPS y alcanzable por los dispositivos.
4. Trusted certificate profile con la CA apropiada y SCEP profile asignado a dos dispositivos reales.
5. Subject/SAN del perfil compatibles con `scep-intune.example.test` y con el rol Vault. Verifica también el URI SAN SID que Microsoft añade cuando aplique strong mapping.
6. Para cada acción externa registra hora UTC, device ID no sensible, perfil Intune y resultado del dispositivo.

La integración de CA de terceros no requiere el Intune Certificate Connector; Vault realiza la validación externa contra Intune.
""")

code(r"""
scep_urls = {
    "primary": f"{os.environ['VAULT_ADDR'].rstrip('/')}/v1/{PKI_MOUNT}/roles/{ROLE}/scep",
    "alternate_role": f"{os.environ['VAULT_ADDR'].rstrip('/')}/v1/{PKI_MOUNT}/roles/{ROLE_ALT}/scep",
}
external_status = {
    "status": "READY_FOR_DEVICE_TEST" if INTUNE_READY and APPLY else "NOT VALIDATED",
    "missing": [] if INTUNE_READY else [
        "Entra app credential available to the Vault server",
        "Intune trusted-certificate and SCEP profiles",
        "two enrolled devices and a forced renewal action",
        "public HTTPS reachability from the devices",
    ],
    "scep_urls": scep_urls,
}
save_json("intune-readiness.json", external_status)
print(json.dumps(external_status, indent=2))
""")

md(r"""
## 9. Matriz de pruebas Intune

Ejecuta las acciones en este orden y espera a que cada una aparezca en auditoría antes de continuar. Dos solicitudes del mismo dispositivo deben ser realmente dos operaciones SCEP; una reinstalación del mismo certificado no cuenta como segunda emisión.

| ID | Acción | Configuración |
|---|---|---|
| T1 | Primera emisión dispositivo A | role primario, auth role `intune` |
| T2 | Segunda solicitud consecutiva dispositivo A | misma configuración exacta |
| T3 | Primera emisión dispositivo B | misma configuración exacta |
| T4 | Renovación dispositivo A | misma configuración; anotar challenge o cert auth |
| T5 | Emisión con otra policy/role | cambiar temporalmente a `intune-alt` y URL del role alternativo |
| T6 | Mismo policy set desde otro auth mount | cambiar temporalmente el accessor a `scep-intune-alt` |
| T7 | Renovación sin challenge, con certificado | solo si el cliente Intune lo permite |

No se usa `static-challenge` como sustituto de Intune.
""")

code(r"""
TESTS = [
    ("T1", "device-a", "first issuance", ROLE, AUTH_ROLE),
    ("T2", "device-a", "second consecutive request", ROLE, AUTH_ROLE),
    ("T3", "device-b", "first issuance", ROLE, AUTH_ROLE),
    ("T4", "device-a", "renewal", ROLE, AUTH_ROLE),
    ("T5", "device-a", "alternate role and policies", ROLE_ALT, AUTH_ROLE_ALT),
    ("T6", "device-a", "same policies through alternate auth mount", ROLE, AUTH_ROLE),
    ("T7", "device-a", "certificate-auth renewal", ROLE, "cert"),
]
matrix = [{"test": t, "device": d, "action": a, "pki_role": r, "auth_role": ar,
           "namespace": NAMESPACE or "root", "status": "NOT VALIDATED", "request_id": None,
           "client_id": None, "entity_id": None, "serial": None, "http": None,
           "client_delta": None, "certificate_delta": None} for t,d,a,r,ar in TESTS]
save_json("test-matrix.json", matrix)
display(Markdown("\n".join(["| Test | Device | Action | PKI role | Auth | Status |", "|---|---|---|---|---|---|"] +
    [f"| {x['test']} | {x['device']} | {x['action']} | {x['pki_role']} | {x['auth_role']} | {x['status']} |" for x in matrix])))
""")

md(r"""
### Cambios controlados para T5 y T6

Ejecuta una celda, realiza **una** emisión externa y restaura inmediatamente la configuración primaria. Los cambios de accessor/policy se conservan en `scep-config-redacted.json`; ningún secret se imprime.
""")

code(r"""
def select_scep_auth(mount, auth_role):
    if not APPLY: raise RuntimeError("SCEP_APPLY_CHANGES=true is required")
    accessor = vault("read", "-field=accessor", f"sys/auth/{mount}").stdout.strip()
    cert_accessor = vault("read", "-field=accessor", f"sys/auth/{CERT_AUTH}").stdout.strip()
    current = vault_json("read", "-format=json", f"{PKI_MOUNT}/config/scep")["data"]
    current.pop("last_updated", None)
    current["authenticators"] = {"scep": {"accessor": accessor, "scep_role": auth_role},
                                  "cert": {"accessor": cert_accessor, "cert_role": ROLE}}
    current["external_validation"] = {"intune": intune_block()}
    vault_json("write", "-format=json", f"{PKI_MOUNT}/config/scep", "-", input_text=json.dumps(current),
               sensitive=(CREDENTIAL_MODE == "direct"))
    print({"selected_mount": mount, "selected_role": auth_role, "accessor": accessor})

print("T5: select_scep_auth(SCEP_AUTH, AUTH_ROLE_ALT)")
print("T6: select_scep_auth(SCEP_AUTH_ALT, AUTH_ROLE)")
print("Restore: select_scep_auth(SCEP_AUTH, AUTH_ROLE)")
""")

md(r"""
## 10. Auditoría: request IDs, identidad, policies, namespace y auth accessor

Si no existe un audit device adecuado, habilita el dedicado con `SCEP_ENABLE_AUDIT=true` **antes** de las emisiones. El fichero se crea en `/tmp` de los pods Vault. El extractor conserva solo campos técnicos y evita token/challenge/CSR completo. En HA, recoge el fichero de todos los pods.
""")

code(r"""
ENABLE_AUDIT = os.getenv("SCEP_ENABLE_AUDIT", "false").lower() == "true"
if APPLY and ENABLE_AUDIT:
    audits = vault_json("audit", "list", "-format=json")
    if AUDIT_PATH + "/" not in audits:
        vault("audit", "enable", f"-path={AUDIT_PATH}", "file", f"file_path={AUDIT_FILE}", "log_raw=false")
    print("Dedicated audit device enabled:", AUDIT_PATH)
else:
    print("Audit device not changed. Set SCEP_ENABLE_AUDIT=true before device tests if needed.")
""")

code(r"""
def collect_audit():
    lines = []
    local = os.getenv("VAULT_AUDIT_LOG")
    if local and Path(local).is_file(): lines.extend(Path(local).read_text(errors="replace").splitlines())
    if shutil.which(KUBECTL_BIN) or Path(KUBECTL_BIN).exists():
        ctx = os.getenv("KUBE_CONTEXT", "workshop-k8s"); ns = os.getenv("KUBE_NAMESPACE", "vault")
        pods = run([KUBECTL_BIN, "--context", ctx, "-n", ns, "get", "pod", "-l", "app.kubernetes.io/name=vault",
                    "-o", "jsonpath={.items[*].metadata.name}"], check=False).stdout.split()
        for pod in pods:
            p = run([KUBECTL_BIN, "--context", ctx, "-n", ns, "exec", pod, "--", "sh", "-c",
                     f"test -f {AUDIT_FILE} && cat {AUDIT_FILE}"], check=False)
            lines.extend(p.stdout.splitlines())
    result = []
    for line in lines:
        try: e = json.loads(line)
        except Exception: continue
        req, auth, resp = e.get("request", {}), e.get("auth", {}), e.get("response", {})
        path = req.get("path", "")
        if PKI_MOUNT not in path and auth.get("accessor") not in {
            vault("read", "-field=accessor", f"sys/auth/{SCEP_AUTH}", check=False).stdout.strip(),
            vault("read", "-field=accessor", f"sys/auth/{SCEP_AUTH_ALT}", check=False).stdout.strip(),
            vault("read", "-field=accessor", f"sys/auth/{CERT_AUTH}", check=False).stdout.strip()}:
            continue
        result.append({"time": e.get("time"), "type": e.get("type"), "request_id": req.get("id"),
                       "path": path, "operation": req.get("operation"), "namespace": req.get("namespace", {}).get("path", ""),
                       "client_id": auth.get("client_id"), "entity_id": auth.get("entity_id"),
                       "auth_accessor": auth.get("accessor"), "policies": auth.get("policies", []),
                       "token_type": auth.get("token_type"), "error": e.get("error"),
                       "serial_number": resp.get("data", {}).get("serial_number")})
    out = EVIDENCE / "audit-redacted.jsonl"
    out.write_text("".join(json.dumps(x, separators=(",", ":")) + "\n" for x in result))
    return result

audit_events = collect_audit() if APPLY else []
print(f"audit events captured: {len(audit_events)}")
""")

md(r"""
## 11. Inventario de certificados emitidos

Vault PKI no conserva la private key de certificados SCEP. Esta celda lista seriales almacenados y extrae subject, issuer, SAN y validez. Para correlación exacta con Intune necesitas request ID/audit timestamp y la identidad del dispositivo anotada en la matriz.
""")

code(r"""
def cert_inventory():
    p = vault("list", "-format=json", f"{PKI_MOUNT}/certs", check=False)
    if p.returncode: return []
    rows = []
    for serial in json.loads(p.stdout):
        doc = vault_json("read", "-format=json", f"{PKI_MOUNT}/cert/{serial}")
        pem = doc.get("data", {}).get("certificate", "")
        if not pem: continue
        f = WORKDIR / "inventory.pem"; f.write_text(pem)
        text = run([OPENSSL_BIN, "x509", "-in", str(f), "-noout", "-subject", "-issuer", "-serial", "-dates", "-ext", "subjectAltName"], check=False)
        if text.returncode: text = run([OPENSSL_BIN, "x509", "-in", str(f), "-noout", "-subject", "-issuer", "-serial", "-dates"])
        rows.append({"serial_path": serial, "details": text.stdout.strip()})
    save_json("certificate-inventory.json", rows)
    return rows

inventory = cert_inventory() if APPLY else []
print(json.dumps(inventory, indent=2))
""")

md(r"""
## 12. Contadores después de las pruebas y polling limitado

Define `SCEP_EXPECTED_ISSUED_CERTS` con el número de certificados **leaf** esperados para activar polling. Recuerda que si este notebook creó la raíz e intermedia dentro de la ventana, el delta del contador será mayor: el endpoint cuenta cada certificado emitido, no solo leaf SCEP.
""")

code(r"""
expected_leaf = int(os.getenv("SCEP_EXPECTED_ISSUED_CERTS", "0"))
activity_after = vault_json("read", "-format=json", "sys/internal/counters/activity")
save_json("activity-after.json", activity_after)

certs_after = vault_json("read", "-format=json", "sys/billing/certificates")
if expected_leaf > 0:
    baseline = cert_total(certs_before)
    for attempt in range(1, 19):
        certs_after = vault_json("read", "-format=json", "sys/billing/certificates")
        print(f"poll {attempt}/18: before={baseline} after={cert_total(certs_after)}")
        if cert_total(certs_after) >= baseline + expected_leaf: break
        time.sleep(10)
save_json("certificates-after.json", certs_after)

before_clients = activity_before.get("data", {}).get("total", {})
after_clients = activity_after.get("data", {}).get("total", {})
deltas = {k: after_clients.get(k, 0) - before_clients.get(k, 0)
          for k in ("clients", "entity_clients", "non_entity_clients", "acme_clients")}
counter_diff = {"clients_before": before_clients, "clients_after": after_clients, "client_delta": deltas,
                "certificates_before": cert_total(certs_before), "certificates_after": cert_total(certs_after),
                "certificate_delta": cert_total(certs_after)-cert_total(certs_before)}
save_json("counter-diff.json", counter_diff)
print(json.dumps(counter_diff, indent=2))
""")

md(r"""
## 13. Activity export: clientes distintos

El export es la fuente para comparar `client_id`, alias, mount accessor, políticas y namespace. Durante el mes actual puede tardar hasta 20 minutos; un HTTP 204 o una lista sin las solicitudes recientes se marca `NOT VALIDATED`, no como «cero clientes».
""")

code(r"""
export_url = f"{os.environ['VAULT_ADDR'].rstrip('/')}/v1/sys/internal/counters/activity/export?format=json"
export_file = EVIDENCE / "activity-export.jsonl"
p = run(["curl", "-sS", "--cacert", os.environ["VAULT_CACERT"], "-H", f"X-Vault-Token: {os.environ['VAULT_TOKEN']}",
         "-o", str(export_file), "-w", "%{http_code}", export_url], sensitive=True)
export_http = int(p.stdout.strip())
clients = []
if export_http == 200:
    for line in export_file.read_text().splitlines():
        try: row = json.loads(line)
        except Exception: continue
        if row.get("mount_path") in {f"auth/{SCEP_AUTH}/", f"auth/{SCEP_AUTH_ALT}/", f"auth/{CERT_AUTH}/"}:
            clients.append({k: row.get(k) for k in ("client_id", "client_type", "entity_name", "entity_alias_name",
                                                    "namespace_id", "namespace_path", "mount_accessor", "mount_type",
                                                    "mount_path", "policies", "client_first_used_time")})
save_json("distinct-clients.json", clients)
print(json.dumps({"http": export_http, "status": "OBSERVED" if clients else "NOT VALIDATED",
                  "distinct_client_ids": sorted({x['client_id'] for x in clients}), "rows": clients}, indent=2))
""")

md(r"""
## 14. Expected vs Observed y conclusión técnica

| Pregunta | Expected/documented | Observed en esta ejecución |
|---|---|---|
| Dos dispositivos, mismo namespace y policy set | **INFERENCE**: mismo constructed client ID si SCEP no crea alias/entidad distinta | Requiere T1-T3 + export/audit |
| Repetición/renovación con mismo identity input | No debe sumar otro cliente dentro del período si conserva el mismo client ID | Requiere T2/T4 |
| Cada certificado emitido o renovado | **DOCUMENTED**: suma 1; no hay deduplicación CN/SAN; persistencia ~2 min | Comparar seriales + `counter-diff.json` |
| Otra policy set o namespace | **DOCUMENTED/INFERENCE**: otro constructed client ID | Requiere T5 y entorno multi-namespace |
| Otro auth mount, mismo namespace/policies sin alias | **INFERENCE**: puede mantener constructed ID; la atribución de mount cambia | Requiere T6 |
| Renovación por certificado | El auth `cert` usa CN como alias; puede producir identidad/client ID distinto | Requiere T7 |

La configuración mínima esperada para deduplicar un **non-entity client** es mantener igual el namespace, el conjunto exacto de políticas y el alias asignado si existe. Mantener solo el mismo PKI role o el mismo auth mount no es la regla documentada. Para entidades normales, mount accessor + alias sí forman la identidad.

**Conclusión provisional:** no es correcto dimensionar «una integración Intune = un Vault Client» como regla comercial universal. Puede ocurrir técnicamente que múltiples dispositivos compartan un constructed client ID cuando SCEP genera batch tokens sin entidad/alias por dispositivo y conserva namespace/policies, pero debe demostrarse con los `client_id` reales del activity export/audit en la versión y configuración objetivo. Aun si Clients deduplica, **PKI Only cuenta cada emisión y cada renovación**.
""")

code(r"""
observed_status = "OBSERVED" if clients and expected_leaf > 0 else "NOT VALIDATED"
final = {
    "classification": observed_status,
    "intune_integration_equals_one_vault_client": "NOT PROVEN",
    "documented": [
        "batch and service tokens are counted using the same client rules",
        "Vault 1.9+ deduplicates non-entity tokens with the same namespace and policy assignments",
        "PKI certificate counts are not deduplicated and persist approximately every two minutes",
    ],
    "inference_to_test": "SCEP Intune requests with no per-device entity/alias and identical namespace/policies may share one constructed client_id",
    "blocking_requirements": external_status["missing"],
    "artifacts": ["test-matrix.json", "audit-redacted.jsonl", "distinct-clients.json",
                  "certificate-inventory.json", "counter-diff.json"],
}
save_json("conclusion.json", final)
print(json.dumps(final, indent=2))
""")

md(r"""
## 15. Limpieza idempotente (no automática)

Se eliminarán exactamente:

- secret mounts `pki_scep_intune/`, `pki_scep_intune_root/`;
- auth mounts `scep-intune/`, `scep-intune-alt/`, `scep-intune-cert/`;
- policies `scep-intune-access`, `scep-intune-access-alt`;
- audit device `scep-intune-validation/`, solo si existe.

No se eliminan los ficheros de evidencia. Los contadores históricos tampoco se revierten. Confirma con `SCEP_CONFIRM_CLEANUP=DELETE_SCEP_INTUNE_VALIDATION`.
""")

code(r"""
confirm = os.getenv("SCEP_CONFIRM_CLEANUP", "")
targets = {"secret_mounts": [PKI_MOUNT, ROOT_MOUNT], "auth_mounts": [SCEP_AUTH, SCEP_AUTH_ALT, CERT_AUTH],
           "policies": [POLICY, POLICY_ALT], "audit_device": AUDIT_PATH}
print(json.dumps(targets, indent=2))
if confirm != "DELETE_SCEP_INTUNE_VALIDATION":
    print("CLEANUP SKIPPED: confirmation value not present")
else:
    vault("write", f"{PKI_MOUNT}/config/scep", "enabled=false", check=False)
    for path in targets["auth_mounts"]: vault("auth", "disable", path, check=False)
    for path in targets["secret_mounts"]: vault("secrets", "disable", path, check=False)
    for policy in targets["policies"]: vault("policy", "delete", policy, check=False)
    vault("audit", "disable", AUDIT_PATH, check=False)
    print("CLEANUP COMPLETE; evidence and historical counters preserved")
""")

nb = {"cells": cells, "metadata": {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python", "version": "3.10"},
}, "nbformat": 4, "nbformat_minor": 5}
OUTPUT.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n")
print(OUTPUT)
