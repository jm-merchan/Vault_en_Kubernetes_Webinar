"""Helpers shared by the DR probes. They run `vault` inside the pods with kubectl exec.

Settings come from the environment (replicate.sh exports them):
  DRTEST_WORKDIR  work directory with primary/vault-init.json
  CTX             kubectl context
  PRI_NS, DR_NS   namespaces (the Helm release has the same name as the namespace)
"""
import json
import os
import subprocess
import time

WORKDIR = os.environ.get("DRTEST_WORKDIR", os.path.expanduser("~/.vault-dr-test"))
CTX = os.environ.get("CTX", "workshop-k8s")
PRI_NS = os.environ.get("PRI_NS", "vault23")
DR_NS = os.environ.get("DR_NS", "vault23dr")
DEPS_NS = os.environ.get("DEPS_NS", "vault23-deps")
PRI_POD = f"{PRI_NS}-0"   # a standby forwards requests to the active node
DR_PODS = [f"{DR_NS}-{i}" for i in range(3)]


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def root_token():
    raw = open(os.path.join(WORKDIR, "primary", "vault-init.json")).read()
    return json.loads(raw[raw.find("{"):])["root_token"]


def kexec(ns, pod, args, token=None, stdin=None, timeout=40):
    env = ["env", "VAULT_SKIP_VERIFY=true"] + ([f"VAULT_TOKEN={token}"] if token else [])
    cmd = ["kubectl", "--context", CTX, "--request-timeout=20s", "exec"]
    if stdin is not None:
        cmd.append("-i")
    cmd += ["-n", ns, pod, "--", *env, "vault", *args]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, input=stdin, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "kubectl exec timed out"
    out = (res.stdout if res.returncode == 0 else (res.stderr or res.stdout)).strip()
    return res.returncode == 0, out


def one_line(text, limit=400):
    return " | ".join(part.strip() for part in text.splitlines() if part.strip())[:limit]


def wal_positions(token):
    """Primary last_dr_wal against the secondary's last_remote_wal. The DR state
    can read stream-wals while the WAL is not advancing, so compare the numbers."""
    ok_p, pri = kexec(PRI_NS, PRI_POD, ["read", "-field=last_dr_wal", "sys/replication/dr/status"], token)
    state = remote = "?"
    for pod in DR_PODS:  # a sealed node cannot answer; try the next one
        ok_s, sec = kexec(DR_NS, pod, ["read", "-format=json", "sys/replication/dr/status"])
        if ok_s:
            data = json.loads(sec)["data"]
            state, remote = data.get("state"), data.get("last_remote_wal")
            break
    return f"primary_last_dr_wal={pri if ok_p else '?'} dr_last_remote_wal={remote} dr_state={state}"
