"""Transit probe against the DR primary. Each interval it encrypts and decrypts
with a long-lived key (use of a key already in memory), rotates that key
(a write of the key policy) and creates a new key (a new storage entry).
Usage: probe_transit.py [duration_s] [interval_s] [mount] [sealwrap]
With "sealwrap" the mount is enabled with -seal-wrap, so every key write calls KMS."""
import base64
import json
import sys
import time

from probe_common import PRI_NS, PRI_POD, kexec, now, one_line, root_token

duration_s = int(sys.argv[1]) if len(sys.argv) > 1 else 2700
interval_s = int(sys.argv[2]) if len(sys.argv) > 2 else 60
MOUNT = sys.argv[3] if len(sys.argv) > 3 else "transit-dr"
SEAL_WRAP = len(sys.argv) > 4 and sys.argv[4] == "sealwrap"
KEY = "dr-probe"
token = root_token()


def vault(*args, stdin=None):
    return kexec(PRI_NS, PRI_POD, list(args), token, stdin=stdin)


ok, out = vault("secrets", "list", "-detailed", "-format=json")
mounts = json.loads(out) if ok else {}
if f"{MOUNT}/" not in mounts:
    flags = ["-seal-wrap"] if SEAL_WRAP else []
    ok, out = vault("secrets", "enable", f"-path={MOUNT}", *flags, "transit")
    print(f"{now()} {'OK  ' if ok else 'FAIL'} enable {MOUNT}/ flags={flags} {'' if ok else one_line(out)}", flush=True)
    ok, out = vault("secrets", "list", "-detailed", "-format=json")
    mounts = json.loads(out) if ok else {}
seal_wrap = mounts.get(f"{MOUNT}/", {}).get("seal_wrap")
print(f"{now()} mount {MOUNT}/ seal_wrap={seal_wrap}", flush=True)
if bool(seal_wrap) != SEAL_WRAP:
    raise SystemExit(f"{MOUNT}/ has seal_wrap={seal_wrap}; the flag is fixed at enable time, use another mount")
ok, out = vault("write", "-f", f"{MOUNT}/keys/{KEY}")
print(f"{now()} {'OK  ' if ok else 'FAIL'} create key {KEY} {'' if ok else one_line(out)}", flush=True)

OPS = ("encrypt", "decrypt", "rotate", "create-key")
stats = {op: [0, 0] for op in OPS}


def record(op, ok, detail=""):
    stats[op][0 if ok else 1] += 1
    print(f"{now()} {'OK  ' if ok else 'FAIL'} {op}" + (f" :: {one_line(detail)}" if detail else ""), flush=True)


deadline = time.time() + duration_s
print(f"{now()} start transit probe duration={duration_s}s interval={interval_s}s", flush=True)
while True:
    started = time.time()
    epoch = int(started)
    plaintext = base64.b64encode(f"dr-probe-{epoch}".encode()).decode()
    ok, out = vault("write", "-field=ciphertext", f"{MOUNT}/encrypt/{KEY}", f"plaintext={plaintext}")
    record("encrypt", ok, "" if ok else out)
    if ok:
        ciphertext = out.strip()
        ok, out = vault("write", "-field=plaintext", f"{MOUNT}/decrypt/{KEY}", f"ciphertext={ciphertext}")
        if ok and out.strip() != plaintext:
            ok, out = False, "decrypted value does not match"
        record("decrypt", ok, "" if ok else out)
    ok, out = vault("write", "-f", f"{MOUNT}/keys/{KEY}/rotate")
    record("rotate", ok, "" if ok else out)
    ok, out = vault("write", "-f", f"{MOUNT}/keys/dr-probe-{epoch}")
    record("create-key", ok, "" if ok else out)
    if time.time() >= deadline:
        break
    time.sleep(max(0, interval_s - (time.time() - started)))
for op, (ok, failed) in stats.items():
    print(f"{now()} done {op}: {ok} ok, {failed} failed", flush=True)
