"""Watches the probe logs and the Vault server logs for seal/KMS errors. When one
appears (and every BASELINE_S as a control) it checks, independently of Vault:

  1. from inside the affected Vault pod: how far the pod clock is behind the
     host clock, DNS resolution and a TCP connection to the KMS and STS
     endpoints (same network namespace as the failing process);
  2. from the kms-netcheck pod of that namespace (same node, same pod network,
     same bootstrap credentials Secret): a fresh sts:AssumeRole followed by
     kms:Encrypt and kms:Decrypt on the cluster's seal key, with the AWS CLI.

If both succeed while Vault is returning ExpiredTokenException, the network and
the AWS side are healthy and the fault is in how the Vault process refreshes
its seal credentials. The check uses the session name "kms-netcheck", so its
CloudTrail events are easy to tell apart from Vault's."""
import glob
import os
import re
import subprocess
import sys
import time

CTX = os.environ.get("CTX", "workshop-k8s")
WORKDIR = os.environ.get("DRTEST_WORKDIR", os.path.expanduser("~/.vault-dr-test"))
RUN = os.path.join(WORKDIR, "run")
PRI_NS = os.environ.get("PRI_NS", "vault23")
DR_NS = os.environ.get("DR_NS", "vault23dr")
duration_s = int(sys.argv[1]) if len(sys.argv) > 1 else 7 * 86400
BASELINE_S, COOLDOWN_S, POLL_S = 600, 60, 5


def kms_key(cluster):
    with open(os.path.join(WORKDIR, cluster, "aws.env")) as fh:
        return dict(line.strip().split("=", 1) for line in fh if "=" in line)["KMS_KEY_ID"]


CLUSTERS = {
    "primary": {"ns": PRI_NS, "key": kms_key("primary")},
    "dr": {"ns": DR_NS, "key": kms_key("dr")},
}
TRIGGER = re.compile(r"ExpiredToken|seal wrapp|failed to encrypt|failed to decrypt|encryption generated no results|"
                     r"unhealthy|AccessDenied|InvalidClientTokenId|RequestExpired|UnrecognizedClient", re.I)
ENDPOINTS = ("kms.eu-west-3.amazonaws.com", "sts.eu-west-3.amazonaws.com", "sts.amazonaws.com")

POD_SCRIPT = "; ".join(
    f"(nslookup {h} >/dev/null 2>&1 && echo dns:{h}=ok || echo dns:{h}=FAIL); "
    f"(nc -z -w 5 {h} 443 >/dev/null 2>&1 && echo tcp443:{h}=ok || echo tcp443:{h}=FAIL)" for h in ENDPOINTS)
AWS_SCRIPT = r'''
ROLE=$(awk -F= '/^role_arn/{print $2}' /creds/credentials)
t0=$(date +%s%3N)
CREDS=$(aws sts assume-role --profile default --role-arn "$ROLE" --role-session-name kms-netcheck \
  --duration-seconds 900 --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' --output text 2>&1) \
  || { echo "assume-role=FAIL $(echo "$CREDS" | tr '\n' ' ' | cut -c1-200)"; exit 0; }
set -- $CREDS
export AWS_ACCESS_KEY_ID=$1 AWS_SECRET_ACCESS_KEY=$2 AWS_SESSION_TOKEN=$3
t1=$(date +%s%3N); echo "assume-role=ok ${1} $((t1-t0))ms"
CT=$(aws kms encrypt --key-id "$KEY" --plaintext bmV0Y2hlY2s= --query CiphertextBlob --output text 2>&1) \
  || { echo "kms-encrypt=FAIL $(echo "$CT" | tr '\n' ' ' | cut -c1-200)"; exit 0; }
t2=$(date +%s%3N); echo "kms-encrypt=ok $((t2-t1))ms"
PT=$(aws kms decrypt --key-id "$KEY" --ciphertext-blob "$CT" --query Plaintext --output text 2>&1) \
  || { echo "kms-decrypt=FAIL $(echo "$PT" | tr '\n' ' ' | cut -c1-200)"; exit 0; }
t3=$(date +%s%3N); [ "$PT" = "bmV0Y2hlY2s=" ] && echo "kms-decrypt=ok $((t3-t2))ms" || echo "kms-decrypt=FAIL mismatch"
'''


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def log(msg):
    print(f"{now()} {msg}", flush=True)


def kexec(ns, target, script, env=()):
    cmd = ["kubectl", "--context", CTX, "--request-timeout=30s", "-n", ns, "exec", target, "--",
           "env", *env, "sh", "-c", script]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        return " ".join((res.stdout + (res.stderr if res.returncode else "")).split())
    except subprocess.TimeoutExpired:
        return "kubectl exec timed out"


def check(cluster, reason, pods=None):
    cfg = CLUSTERS[cluster]
    ns = cfg["ns"]
    for pod in pods or [f"{ns}-0", f"{ns}-1", f"{ns}-2"]:
        # The failures seen in this lab were all caused by the node clock falling
        # behind real time, so the pod clock is compared with the host clock first.
        pod_clock = kexec(ns, pod, "date -u +%s")
        skew = f"{int(time.time()) - int(pod_clock)}s" if pod_clock.isdigit() else "unknown"
        log(f"CHECK {cluster} reason={reason} from-vault-pod {pod}: clock_behind_host={skew} {kexec(ns, pod, POD_SCRIPT)}")
    out = kexec(ns, "deploy/kms-netcheck", AWS_SCRIPT, env=(f"KEY={cfg['key']}",))
    verdict = "KMS-REACHABLE" if out.count("=ok") == 3 else "KMS-CHECK-FAILED"
    log(f"CHECK {cluster} reason={reason} fresh-sts+kms: {out} => {verdict}")


def cluster_of(path):
    base = os.path.basename(path)
    if base.startswith(f"{DR_NS}-"):
        return "dr", base[:-4]
    if base.startswith(f"{PRI_NS}-"):
        return "primary", base[:-4]
    return None, None  # probe log: the probe talks to the primary; check both clusters


offsets = {}
last_check = {name: 0.0 for name in CLUSTERS}
last_baseline = 0.0
deadline = time.time() + duration_s
log(f"kms_watch started; trigger={TRIGGER.pattern}")
while time.time() < deadline:
    files = glob.glob(f"{RUN}/logs/*-?.log") + glob.glob(f"{RUN}/probe_*.log")
    for path in files:
        size = os.path.getsize(path)
        if path not in offsets:
            offsets[path] = size  # only lines written after the watcher started
            continue
        if size <= offsets[path]:
            continue
        with open(path, errors="replace") as fh:
            fh.seek(offsets[path])
            chunk = fh.read()
            offsets[path] = fh.tell()
        hits = [line for line in chunk.splitlines() if TRIGGER.search(line)]
        if not hits:
            continue
        cluster, pod = cluster_of(path)
        log(f"TRIGGER {os.path.basename(path)} ({len(hits)} lines): {hits[0][:300]}")
        for name in ([cluster] if cluster else list(CLUSTERS)):
            if time.time() - last_check[name] >= COOLDOWN_S:
                last_check[name] = time.time()
                check(name, f"error-in-{os.path.basename(path)}", [pod] if pod else None)
    if time.time() - last_baseline >= BASELINE_S:
        last_baseline = time.time()
        for name in CLUSTERS:
            check(name, "baseline", [f"{CLUSTERS[name]['ns']}-0"])
    time.sleep(POLL_S)
log("kms_watch finished")
