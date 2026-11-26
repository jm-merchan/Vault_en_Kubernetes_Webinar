#!/usr/bin/env python3
"""Live view of the DR test: every probe result and every notable server log line,
each stamped with the real (host) time at which it was seen.

    watch.py            follow from now
    watch.py --all      replay the whole run first, then follow
    watch.py --errors   only failures, errors, warnings and clock lines

Columns:  REAL TIME (host, UTC) | SOURCE | LINE

* Probe lines (kv, transit, transit-sw, config) carry the host time at which the
  operation ran, so their own timestamp is real time.
* Server lines (vault23-0, vault23dr-1 ...) carry the POD clock in their own
  timestamp. When the pod clock is behind, that timestamp is earlier than the
  REAL TIME column: the difference is the clock skew that makes KMS reject the
  STS token.
* A CLOCK line every 30 s shows how far each cluster's pod clock is behind the
  host. It turns red above 60 s.

Failures are red, warnings yellow, successful operations dim.
"""
import glob
import os
import re
import subprocess
import sys
import time

WORKDIR = os.environ.get("DRTEST_WORKDIR", os.path.expanduser("~/.vault-dr-test"))
RUN = os.path.join(WORKDIR, "run")
CTX = os.environ.get("CTX", "workshop-k8s")
PRI_NS = os.environ.get("PRI_NS", "vault23")
DR_NS = os.environ.get("DR_NS", "vault23dr")
REPLAY = "--all" in sys.argv
ERRORS_ONLY = "--errors" in sys.argv
TTY = sys.stdout.isatty()
RED, YELLOW, GREEN, DIM, BOLD, RESET = (
    ("\033[31m", "\033[33m", "\033[32m", "\033[2m", "\033[1m", "\033[0m") if TTY else ("",) * 6)

SOURCES = {
    "probe_kv.log": "kv",
    "probe_transit.log": "transit",
    "probe_transit_sealwrap.log": "transit-sw",
    "probe_config.log": "config",
    "kms_watch.log": "kms-check",
}
SERVER_NOTABLE = re.compile(
    r"\[ERROR\]|\[WARN\]|ExpiredToken|seal wrap|autoseal|healthy|marked as sealed|vault is sealed|"
    r"leadership|entering leader state|acquired lock|stepping down|merkle|stream started", re.I)
SERVER_NOISE = re.compile(r"certificate count|guard mis-match|requesting WAL stream|stream started|wal receive", re.I)
BAD = re.compile(r" FAIL |\[ERROR\]|ExpiredToken|KMS-CHECK-FAILED|=FAIL|marked as sealed|vault is sealed|unhealthy", re.I)
WARN = re.compile(r"\[WARN\]| TRIGGER |merkle-sync|merkle-diff|stepping down|leadership lost", re.I)


def real_now():
    return time.strftime("%H:%M:%S", time.gmtime())


def emit(source, line, when=None):
    bad, warn = BAD.search(line), WARN.search(line)
    if ERRORS_ONLY and not (bad or warn or source == "CLOCK"):
        return
    colour = RED if bad else YELLOW if warn else DIM if " OK " in line else ""
    print(f"{BOLD}{when or real_now()}Z{RESET} | {source:<12} | {colour}{line.rstrip()[:260]}{RESET}", flush=True)


def shorten(source, line):
    if source in ("kv", "transit", "transit-sw", "config"):
        line = line[11:]                       # drop the date; keep HH:MM:SSZ of the operation
        line = re.sub(r"Error making API request\. \| URL: \S+ \S+ \| ", "", line)
    elif source == "kms-check":
        line = line[21:]
    else:                                      # server log: drop the kubelet stamp, keep Vault's own
        line = line[31:]
    return line


def pod_clock_skew(ns):
    try:
        out = subprocess.run(["kubectl", "--context", CTX, "--request-timeout=10s", "-n", ns, "exec", f"{ns}-0",
                              "--", "date", "-u", "+%s"], capture_output=True, text=True, timeout=20).stdout.strip()
        return int(time.time()) - int(out)
    except (subprocess.TimeoutExpired, ValueError):
        return None


def clock_line():
    parts, worst = [], 0
    for label, ns in (("primary", PRI_NS), ("DR", DR_NS)):
        skew = pod_clock_skew(ns)
        parts.append(f"{label} pod clock {'unreachable' if skew is None else f'{skew}s behind host'}")
        worst = max(worst, abs(skew) if skew is not None else 0)
    line = "; ".join(parts)
    if worst > 60:
        line += "  => KMS rejects the STS token while this lasts [ERROR]"
    return line


def files():
    found = {}
    for name, source in SOURCES.items():
        path = os.path.join(RUN, name)
        if os.path.exists(path):
            found[path] = source
    for path in glob.glob(os.path.join(RUN, "logs", "*.log")):
        found[path] = os.path.basename(path)[:-4]
    return found


print(f"{BOLD}REAL TIME | SOURCE       | LINE{RESET}   (server lines show the pod clock; compare it with REAL TIME)")
offsets = {}
last_clock = 0.0
first_pass = True
while True:
    for path, source in files().items():
        size = os.path.getsize(path)
        if path not in offsets:
            offsets[path] = 0 if (REPLAY or not first_pass) else size
        if size <= offsets[path]:
            continue
        with open(path, errors="replace") as fh:
            fh.seek(offsets[path])
            chunk = fh.read()
            offsets[path] = fh.tell()
        replaying = REPLAY and first_pass
        for line in chunk.splitlines():
            if not line.strip() or line.startswith("  |"):
                continue
            is_server = source not in SOURCES.values()
            if is_server and (not SERVER_NOTABLE.search(line) or SERVER_NOISE.search(line)):
                continue
            if source == "kms-check" and " CHECK " in line and "reason=baseline" in line and "FAIL" not in line:
                continue
            if source == "kms-check" and "kms_watch started" in line:
                continue
            if source == "kv" and " WAL " in line and "stream-wals" in line and ERRORS_ONLY:
                continue
            emit(source, shorten(source, line), when="replay  " if replaying else None)
    first_pass = False
    if time.time() - last_clock >= 30:
        last_clock = time.time()
        emit("CLOCK", clock_line())
    time.sleep(1)
