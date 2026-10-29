"""Compare no-audit and file-default with Minikube using the full Podman VM.

The suite records and restores the original Minikube cgroup limits in finally.
Vault pods have no Kubernetes CPU or memory limits, so the expanded node quota
is available to them while the load generator and telemetry remain co-located.
"""
from datetime import datetime, timezone
import gzip
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

from common import ROOT, kub
from external_verify import verify
from scenarios import configure, prepare, restore

STATE = Path(os.environ.get("VBB_STATE_DIR", "/tmp/vault/vbb-file-max"))
STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
RUNS = ROOT.parent / "runs"
SUITE = os.environ.get("VBB_SUITE_ID", "20261029-file-max-vm")
MANIFEST = RUNS / (SUITE + "-plan.json")
RESOURCE_STATE = STATE / "resource-state.json"
os.environ.update(VBB_EXPECTED_TARGETS="12", VBB_SUITE_ID=SUITE, VBB_AWAKE_MANAGED="1")
subprocess.Popen(["caffeinate", "-is", "-w", str(os.getpid())], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for signum in [signal.SIGTERM, signal.SIGINT]:
    signal.signal(signum, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))


def output(*command):
    return subprocess.check_output(command, stderr=subprocess.PIPE).decode()


def inspect_minikube():
    info = json.loads(output("podman", "inspect", "workshop-k8s"))[0]
    host = info["HostConfig"]
    guest = output("minikube", "-p", "workshop-k8s", "ssh", "--", "cat /sys/fs/cgroup/cpu.max; cat /sys/fs/cgroup/memory.max; nproc; grep MemTotal /proc/meminfo").splitlines()
    return {
        "container_id": info["Id"], "nano_cpus": host["NanoCpus"],
        "cpu_quota": host["CpuQuota"], "cpu_period": host["CpuPeriod"],
        "memory": host["Memory"], "guest_cpu_max": guest[0],
        "guest_memory_max": guest[1], "guest_nproc": int(guest[2]),
        "guest_memtotal": guest[3],
    }


def wait_limits(cpu, memory):
    for _ in range(60):
        state = inspect_minikube()
        if state["guest_cpu_max"] == cpu and state["guest_memory_max"] == memory:
            return state
        time.sleep(.5)
    raise RuntimeError("Minikube cgroup limits did not converge: " + json.dumps(state))


def expand_resources():
    if RESOURCE_STATE.exists():
        state = json.loads(RESOURCE_STATE.read_text())
        original = state["original"]
    else:
        original = inspect_minikube()
        state = {"original": original, "restored": False}
        RESOURCE_STATE.write_text(json.dumps(state, indent=2) + "\n")
        os.chmod(RESOURCE_STATE, 0o600)
    # Podman does not remove an existing memory limit when update receives 0.
    # Set the container to the Podman machine's full configured 12 GiB instead.
    subprocess.run(["podman", "update", "--cpus", "8", "--memory", "12288m", "workshop-k8s"], check=True)
    expanded = wait_limits("800000 100000", str(12 * 1024 ** 3))
    state.update(expanded=expanded, restored=False, expanded_at=datetime.now(timezone.utc).isoformat())
    RESOURCE_STATE.write_text(json.dumps(state, indent=2) + "\n")
    print("Minikube expanded to 8 CPU and the Podman VM's full 12 GiB: " + json.dumps(expanded), flush=True)
    time.sleep(15)
    return state


def restore_resources():
    if not RESOURCE_STATE.exists():
        return
    state = json.loads(RESOURCE_STATE.read_text())
    original = state["original"]
    cpu = original["nano_cpus"] / 1e9
    memory = original["memory"]
    subprocess.run(["podman", "update", "--cpus", str(cpu), "--memory", str(memory), "workshop-k8s"], check=True)
    expected_cpu = f"{int(cpu * 100000)} 100000"
    restored_state = wait_limits(expected_cpu, str(memory))
    state.update(restored=True, restored_at=datetime.now(timezone.utc).isoformat(), restored_state=restored_state)
    RESOURCE_STATE.write_text(json.dumps(state, indent=2) + "\n")
    print("Minikube resource limits restored: " + json.dumps(restored_state), flush=True)


def free_bytes():
    text = output("minikube", "-p", "workshop-k8s", "ssh", "--", "df -B1 --output=avail /var | tail -1")
    return int(text.strip())


def archive(logdir):
    script = "import glob,gzip,shutil,os,sys\nfor p in glob.glob(sys.argv[1]+'/*.json*'):\n if p.endswith('.gz'): continue\n with open(p,'rb') as s,gzip.open(p+'.gz','wb',compresslevel=1) as d: shutil.copyfileobj(s,d,1024*1024)\n os.unlink(p)"
    for index in range(3):
        kub("exec", f"deployment/vbb-socket-{index}", "--", "python", "-c", script, logdir)


def run_case(entry, index, total, resource_state):
    scenario = entry["scenario"]
    label = entry["label"]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{scenario}-{label}-maxvm"
    logdir = "/vault/audit/vbb-file-max/" + run_id
    os.environ.update(VBB_RUN_ID=run_id, VBB_FILE_PATH=logdir + "/audit.json")
    configure("none")
    if scenario != "none":
        for node in range(3):
            kub("exec", f"vault-{node}", "-c", "vault", "--", "mkdir", "-p", logdir)
    if free_bytes() < 10 * 1024 ** 3:
        raise RuntimeError("Less than 10 GiB free before " + run_id)
    hcl = ROOT.parent / ("vb-transit-unit.hcl" if label == "unit" else "vb-transit-" + label.split("-")[1] + ".hcl")
    print(f"CASE {index}/{total} {scenario} {label}", flush=True)
    subprocess.run([sys.executable, str(ROOT / "run.py"), scenario, str(hcl), label], check=True)
    folder = RUNS / run_id
    audit = verify(folder, logdir)
    if scenario != "none" and not audit["passed"]:
        raise RuntimeError("File audit count validation failed: " + run_id)
    metadata = {
        "scenario": scenario, "label": label, "log_directory": logdir,
        "resource_state": resource_state, "resource_state_during_case": inspect_minikube(),
        "free_bytes_after_case": free_bytes(), "audit_verification": audit,
        "scope_note": "Vault pods have no Kubernetes limits; Minikube, generator, telemetry, Raft and file audit share the 8-CPU Podman VM.",
    }
    (folder / "max-resources.json").write_text(json.dumps(metadata, indent=2) + "\n")
    entry.update(run_id=run_id, status="passed", audit_status=audit["status"])
    MANIFEST.write_text(json.dumps(plan, indent=2) + "\n")
    if scenario != "none":
        configure("none")
        archive(logdir)
    print("VERIFIED " + run_id + " audit=" + audit["status"], flush=True)


if MANIFEST.exists():
    plan = json.loads(MANIFEST.read_text())
else:
    plan = []
    sizes = ["unit", "batch-50", "batch-100", "batch-250", "batch-500", "batch-750", "batch-1000", "batch-9000"]
    for position, label in enumerate(sizes):
        order = ["none", "file-default"] if position % 2 == 0 else ["file-default", "none"]
        plan.extend({"scenario": scenario, "label": label} for scenario in order)
    MANIFEST.write_text(json.dumps(plan, indent=2) + "\n")


def main():
    try:
        resource_state = expand_resources()
        try:
            prepare(allow=True)
            for index, entry in enumerate(plan, 1):
                if entry.get("status") == "passed":
                    continue
                run_case(entry, index, len(plan), resource_state)
        finally:
            if (STATE / "original.json").exists():
                restore()
                subprocess.run([sys.executable, str(ROOT / "verify_restoration.py"), SUITE], check=True)
    finally:
        restore_resources()
    print("FILE MAX-VM SUITE COMPLETE", flush=True)


if __name__ == "__main__":
    main()
