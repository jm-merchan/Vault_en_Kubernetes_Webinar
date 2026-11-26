"""KV write probe against the DR primary: one put per interval on a default
mount (kv/, no seal wrap) and on a seal-wrapped mount (kv-sealwrap/)."""
import sys
import time

from probe_common import PRI_NS, PRI_POD, kexec, now, one_line, root_token, wal_positions

duration_s = int(sys.argv[1]) if len(sys.argv) > 1 else 2700
interval_s = int(sys.argv[2]) if len(sys.argv) > 2 else 60
MOUNTS = ("kv", "kv-sealwrap")
token = root_token()
stats = {m: [0, 0] for m in MOUNTS}
deadline = time.time() + duration_s
print(f"{now()} start kv probe duration={duration_s}s interval={interval_s}s mounts={MOUNTS}", flush=True)
while True:
    started = time.time()
    epoch = int(started)
    for mount in MOUNTS:
        ok, out = kexec(PRI_NS, PRI_POD, ["kv", "put", f"{mount}/dr-probe-{epoch}", f"created_epoch={epoch}"], token)
        stats[mount][0 if ok else 1] += 1
        print(f"{now()} {'OK  ' if ok else 'FAIL'} put {mount}/dr-probe-{epoch}" + ("" if ok else f" :: {one_line(out)}"), flush=True)
    print(f"{now()} WAL  {wal_positions(token)}", flush=True)
    if time.time() >= deadline:
        break
    time.sleep(max(0, interval_s - (time.time() - started)))
for mount, (ok, failed) in stats.items():
    print(f"{now()} done {mount}/: {ok} written, {failed} failed", flush=True)
