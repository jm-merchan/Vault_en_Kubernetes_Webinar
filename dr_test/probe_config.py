"""Configuration probe against the DR primary. Each interval it creates a
namespace (and deletes the previous one), writes a policy, creates an entity
and an entity alias on the LDAP mount, rewrites the LDAP auth config, logs in
through LDAP, issues dynamic PostgreSQL credentials and rotates a static role."""
import json
import sys
import time

from probe_common import DEPS_NS, PRI_NS, PRI_POD, kexec, now, one_line, root_token

duration_s = int(sys.argv[1]) if len(sys.argv) > 1 else 2700
interval_s = int(sys.argv[2]) if len(sys.argv) > 2 else 60
token = root_token()


def vault(*args, stdin=None):
    return kexec(PRI_NS, PRI_POD, list(args), token, stdin=stdin)


ok, out = vault("auth", "list", "-format=json")
ldap_accessor = json.loads(out)["ldap/"]["accessor"]
LDAP_CONFIG = [
    "binddn=cn=admin,dc=learn,dc=example", "bindpass=2LearnVault",
    f"url=ldap://openldap.{DEPS_NS}.svc.cluster.local:389",
    "userdn=ou=users,dc=learn,dc=example", "userattr=cn",
    "userfilter=({{.UserAttr}}={{.Username}})", "groupdn=dc=learn,dc=example",
    "groupfilter=(&(objectClass=person)(cn={{.Username}}))", "groupattr=memberOf", "insecure_tls=true",
]
OPS = ("namespace-create", "namespace-delete", "policy-write", "entity-create", "entity-alias-create",
       "ldap-config-write", "ldap-login", "db-creds", "db-rotate-static-role")
stats = {op: [0, 0] for op in OPS}


def record(op, ok, detail=""):
    stats[op][0 if ok else 1] += 1
    print(f"{now()} {'OK  ' if ok else 'FAIL'} {op}" + ("" if ok else f" :: {one_line(detail)}"), flush=True)
    return ok


previous_ns = None
deadline = time.time() + duration_s
print(f"{now()} start config probe duration={duration_s}s interval={interval_s}s ldap_accessor={ldap_accessor}", flush=True)
while True:
    started = time.time()
    epoch = int(started)
    name = f"dr-probe-{epoch}"

    ok, out = vault("namespace", "create", name)
    created = record("namespace-create", ok, out)
    if previous_ns:
        ok, out = vault("namespace", "delete", previous_ns)
        record("namespace-delete", ok, out)
    if created:
        previous_ns = name

    policy = f'path "kv/{name}/*" {{\n  capabilities = ["read"]\n}}\n'
    ok, out = vault("policy", "write", name, "-", stdin=policy)
    record("policy-write", ok, out)

    ok, out = vault("write", "-field=id", "identity/entity", f"name={name}", f"policies={name}")
    record("entity-create", ok, out)
    if ok:
        ok, out = vault("write", "-field=id", "identity/entity-alias", f"name={name}",
                        f"canonical_id={out.strip()}", f"mount_accessor={ldap_accessor}")
        record("entity-alias-create", ok, out)

    ok, out = vault("write", "auth/ldap/config", *LDAP_CONFIG)
    record("ldap-config-write", ok, out)
    ok, out = vault("login", "-method=ldap", "-no-store", "-field=token_accessor", "username=alice", "password=alice")
    record("ldap-login", ok, out)

    ok, out = vault("read", "-field=username", "database/creds/readonly")
    record("db-creds", ok, out)
    ok, out = vault("write", "-f", "database/rotate-role/static-app")
    record("db-rotate-static-role", ok, out)

    if time.time() >= deadline:
        break
    time.sleep(max(0, interval_s - (time.time() - started)))
for op, (ok, failed) in stats.items():
    print(f"{now()} done {op}: {ok} ok, {failed} failed", flush=True)
