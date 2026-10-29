"""Probe UDP audit size limits, then benchmark only cases that preserve the probe.

The suite treats missing UDP audit records as a measured result, not as a
reason to discard the run. Original audit and Transit tuning are restored in
the outer finally block.
"""
import base64
from datetime import datetime, timezone
import gzip
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error

from common import ROOT, vault
from external_verify import verify
from scenarios import configure, prepare, restore

STATE = Path(os.environ.get("VBB_STATE_DIR", "/tmp/vault/vbb-udp-external"))
RUNS = ROOT.parent / "runs"
SUITE = os.environ.get("VBB_SUITE_ID", "20261029-udp-external")
MANIFEST = RUNS / (SUITE + "-plan.json")
PROBE = RUNS / (SUITE + "-probe.json")
DEPLOYMENT = json.loads((STATE / "deployment.json").read_text())
ADDRESS = DEPLOYMENT["address"]
os.environ.update(
    VBB_UDP_ADDRESS=ADDRESS,
    VBB_EXPECTED_TARGETS="12",
    VBB_SUITE_ID=SUITE,
    VBB_AWAKE_MANAGED="1",
)
subprocess.Popen(["caffeinate", "-is", "-w", str(os.getpid())], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for signum in [signal.SIGTERM, signal.SIGINT]:
    signal.signal(signum, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))


def podman(*args, input=None):
    return subprocess.check_output(["podman", *args], input=input, stderr=subprocess.PIPE).decode()


def receiver_metrics():
    text = podman("exec", "vbb-udp-external", "python", "-c",
        "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:9102/metrics').read().decode())")
    return {parts[0]: float(parts[1]) for line in text.splitlines() if len(parts := line.split()) == 2}


def set_case(name):
    control = json.dumps({"case": name})
    podman("exec", "-i", "vbb-udp-external", "python", "-c",
        "import pathlib,sys;pathlib.Path('/data/control.json').write_text(sys.stdin.read())", input=control.encode())


def flush_receiver():
    set_case("quiesce")
    subprocess.run(["podman", "exec", "workshop-k8s", "sh", "-c", f"printf quiesce | nc -u -w 1 {ADDRESS.split(':')[0]} 9090"], check=True)
    time.sleep(.2)


def request_batch(size):
    if size == 1:
        return [{"plaintext": base64.b64encode(b"4000 0000 0000 0001").decode()}]
    hcl = (ROOT.parent / f"vb-transit-{9000 if size == 8982 else size}.hcl").read_text()
    values = re.findall(r'plaintext\s*=\s*"([^"]+)"', hcl)
    if len(values) != size:
        raise RuntimeError(f"Expected {size} plaintexts, found {len(values)}")
    return [{"plaintext": value} for value in values]


def read_case(case):
    script = r'''import json,pathlib,sys
p=pathlib.Path('/data')/sys.argv[1]/'audit.json';events=[];bad=0;sizes=[]
if p.exists():
 for line in p.open('rb'):
  sizes.append(len(line))
  try:d=json.loads(line)
  except Exception:bad+=1;continue
  if isinstance(d,dict) and (d.get('request') or {}).get('path')=='transit/encrypt/orders':
   events.append({'id':d['request'].get('id'),'type':d.get('type'),'bytes':len(line)})
print(json.dumps({'events':events,'parse_errors':bad,'line_sizes':sizes,'bytes':p.stat().st_size if p.exists() else 0}))'''
    return json.loads(podman("exec", "vbb-udp-external", "python", "-c", script, case))


def probe():
    if PROBE.exists():
        return json.loads(PROBE.read_text())
    results = {"suite_id": SUITE, "address": ADDRESS, "cases": []}
    prepare(allow=True)
    try:
        for scenario in ["udp-default", "udp-combined"]:
            case = "probe-" + scenario
            set_case(case)
            os.environ["VBB_UDP_LOG_DIR"] = "/data/" + case
            configure(scenario)
            before = receiver_metrics()
            for size in [1, 50, 100, 250, 500, 750, 1000, 8982]:
                started = time.time()
                status = None
                request_id = None
                error = None
                try:
                    response = vault("transit/encrypt/orders", {"batch_input": request_batch(size)})
                    status = 200
                    request_id = response.get("request_id")
                    valid_response = len(response.get("data", {}).get("batch_results", [])) == size
                except urllib.error.HTTPError as exc:
                    status = exc.code
                    valid_response = False
                    try:
                        body = json.loads(exc.read())
                        error = "; ".join(body.get("errors", []))[:500]
                        request_id = body.get("request_id")
                    except Exception:
                        error = "HTTPError without JSON body"
                results["cases"].append({
                    "scenario": scenario, "items": size, "http_status": status,
                    "request_id": request_id, "valid_response": valid_response,
                    "elapsed_seconds": time.time() - started, "error": error,
                })
                time.sleep(.15)
            configure("none")
            flush_receiver()
            report = read_case(case)
            by_id = {}
            for event in report["events"]:
                by_id.setdefault(event["id"], []).append(event)
            for entry in results["cases"]:
                if entry["scenario"] != scenario:
                    continue
                events = by_id.get(entry["request_id"], []) if entry["request_id"] else []
                entry["audit_request"] = any(event["type"] == "request" for event in events)
                entry["audit_response"] = any(event["type"] == "response" for event in events)
                entry["audit_event_bytes"] = {event["type"]: event["bytes"] for event in events}
                entry["probe_passed"] = bool(entry["valid_response"] and entry["audit_request"] and entry["audit_response"])
            after = receiver_metrics()
            results[scenario] = {
                "receiver_delta": {key: after.get(key, 0) - before.get(key, 0) for key in after},
                "log": report,
            }
    finally:
        restore()
    PROBE.write_text(json.dumps(results, indent=2) + "\n")
    return results


def archive(case):
    flush_receiver()
    path = f"/data/{case}/audit.json"
    script = "import gzip,shutil,os,sys; p=sys.argv[1];\nwith open(p,'rb') as s,gzip.open(p+'.gz','wb',compresslevel=1) as d: shutil.copyfileobj(s,d,1024*1024)\nos.unlink(p)"
    podman("exec", "vbb-udp-external", "python", "-c", script, path)


def run_case(entry, index, total):
    scenario = entry["scenario"]
    label = entry["label"]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{scenario}-{label}"
    os.environ.update(VBB_RUN_ID=run_id, VBB_UDP_LOG_DIR="/data/" + run_id)
    set_case(run_id)
    hcl = ROOT.parent / ("vb-transit-unit.hcl" if label == "unit" else "vb-transit-" + label.split("-")[1] + ".hcl")
    before = receiver_metrics()
    print(f"CASE {index}/{total} {scenario} {label}", flush=True)
    error = None
    try:
        subprocess.run([sys.executable, str(ROOT / "run.py"), scenario, str(hcl), label], check=True)
    except subprocess.CalledProcessError as exc:
        error = f"run.py exit {exc.returncode}"
    finally:
        configure("none")
        flush_receiver()
    after = receiver_metrics()
    folder = RUNS / run_id
    audit = None
    if (folder / "result.json").exists():
        try:
            audit = verify(folder, "/data/" + run_id)
        except Exception as exc:
            audit = {"passed": False, "status": "verification_error", "error": type(exc).__name__ + ": " + str(exc)}
    metadata = {
        "scenario": scenario, "label": label, "external_deployment": DEPLOYMENT,
        "external_metrics_before": before, "external_metrics_after": after,
        "metric_delta": {key: after.get(key, 0) - before.get(key, 0) for key in after},
        "audit_verification": audit, "runner_error": error,
    }
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "udp.json").write_text(json.dumps(metadata, indent=2) + "\n")
    entry.update(run_id=run_id, status="passed" if error is None else "workload_failed",
                 audit_status=audit.get("status") if audit else "not_available",
                 audit_complete=bool(audit and audit.get("passed")))
    MANIFEST.write_text(json.dumps(plan, indent=2) + "\n")
    if (folder / "result.json").exists():
        archive(run_id)
    print(f"RECORDED {run_id}: workload={entry['status']} audit={entry['audit_status']}", flush=True)


probe_result = probe()
if MANIFEST.exists():
    plan = json.loads(MANIFEST.read_text())
else:
    plan = []
    for scenario in ["udp-default", "udp-combined"]:
        for result in probe_result["cases"]:
            if result["scenario"] == scenario and result["probe_passed"]:
                size = result["items"]
                plan.append({"scenario": scenario, "label": "unit" if size == 1 else f"batch-{9000 if size == 8982 else size}", "probe_items": size})
    MANIFEST.write_text(json.dumps(plan, indent=2) + "\n")


def main():
    prepare(allow=True)
    try:
        for index, entry in enumerate(plan, 1):
            if entry.get("status") in ["passed", "workload_failed"]:
                continue
            run_case(entry, index, len(plan))
    finally:
        restore()
        subprocess.run([sys.executable, str(ROOT / "verify_restoration.py"), SUITE], check=True)
    print("UDP SUITE COMPLETE", flush=True)


if __name__ == "__main__":
    main()
