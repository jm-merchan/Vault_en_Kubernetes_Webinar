"""Follow the logs of every DR server (and the primary leader) for a fixed time.
Raw logs go to <outdir>/<pod>.log; lines about the seal, replication, warnings
and errors are echoed to stdout with the pod name."""
import os
import re
import subprocess
import sys
import threading
import time

CTX = os.environ.get("CTX", "workshop-k8s")
PRI_NS = os.environ.get("PRI_NS", "vault23")
DR_NS = os.environ.get("DR_NS", "vault23dr")
duration_s = int(sys.argv[1]) if len(sys.argv) > 1 else 2700
outdir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.environ.get("DRTEST_WORKDIR", "."), "run", "logs")
os.makedirs(outdir, exist_ok=True)
TARGETS = [(DR_NS, f"{DR_NS}-{i}") for i in range(3)] + [(PRI_NS, f"{PRI_NS}-{i}") for i in range(3)]
INTERESTING = re.compile(r"\[ERROR\]|\[WARN\]|seal|ExpiredToken|AccessDenied|kms|replication", re.I)
NOISE = re.compile(r"\[TRACE\]|\[DEBUG\]")
lock = threading.Lock()
deadline = time.time() + duration_s


def follow(ns, pod):
    since = "1s"
    with open(f"{outdir}/{pod}.log", "a") as raw:
        while time.time() < deadline:
            proc = subprocess.Popen(
                ["kubectl", "--context", CTX, "-n", ns, "logs", "-f", "--timestamps", f"--since={since}", pod],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            timer = threading.Timer(max(1, deadline - time.time()), proc.terminate)
            timer.start()
            for line in proc.stdout:
                raw.write(line)
                raw.flush()
                if INTERESTING.search(line) and not NOISE.search(line):
                    with lock:
                        print(f"{pod} {line.rstrip()[:420]}", flush=True)
            timer.cancel()
            proc.wait()
            since = "5s"  # the stream ended early (pod restart or API hiccup): reattach
            time.sleep(2)


threads = [threading.Thread(target=follow, args=t, daemon=True) for t in TARGETS]
print(f"monitoring {[t[1] for t in TARGETS]} for {duration_s}s -> {outdir}", flush=True)
for t in threads:
    t.start()
for t in threads:
    t.join()
print("monitor finished", flush=True)
