"""Deploy the sibling UDP receiver and add it to the lab Prometheus targets."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from collect import api
from common import ROOT, kub

STATE = Path(os.getenv("VBB_STATE_DIR", "/tmp/vault/vbb-udp-external"))
STATE.mkdir(mode=0o700, parents=True, exist_ok=True)


def podman(*args):
    return subprocess.check_output(["podman", *args], stderr=subprocess.PIPE).decode()


def main():
    existing = podman("ps", "-a", "--filter", "name=^vbb-udp-external$", "--format", "{{.Names}}").strip()
    if existing:
        info = json.loads(podman("inspect", "vbb-udp-external"))[0]
        if not info["State"]["Running"]:
            podman("start", "vbb-udp-external")
            info = json.loads(podman("inspect", "vbb-udp-external"))[0]
    else:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "udp_receiver.py").write_bytes((ROOT / "udp_receiver.py").read_bytes())
            (path / "Containerfile").write_text(
                "FROM docker.io/library/python:3.12-slim\n"
                "COPY udp_receiver.py /app/receiver.py\n"
                'ENTRYPOINT ["python", "-u", "/app/receiver.py"]\n'
            )
            subprocess.run(["podman", "build", "-t", "localhost/vbb-udp-external:20261029", directory], check=True)
        if subprocess.run(["podman", "volume", "exists", "vbb-udp-external-data"]).returncode:
            podman("volume", "create", "vbb-udp-external-data")
        podman(
            "run", "-d", "--name", "vbb-udp-external", "--network", "workshop-k8s",
            "--cpus", "2", "--memory", "512m", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--read-only", "--tmpfs", "/tmp",
            "-v", "vbb-udp-external-data:/data", "localhost/vbb-udp-external:20261029",
        )
        info = json.loads(podman("inspect", "vbb-udp-external"))[0]
    ip = info["NetworkSettings"]["Networks"]["workshop-k8s"]["IPAddress"]
    deployment = {
        "ip": ip, "address": ip + ":9090", "metrics": ip + ":9102",
        "image": info["Image"], "container_id": info["Id"],
        "cpu_quota": info["HostConfig"]["CpuQuota"],
        "cpu_period": info["HostConfig"]["CpuPeriod"], "network": "workshop-k8s",
        "published_ports": info["NetworkSettings"]["Ports"], "volume": "vbb-udp-external-data",
    }
    (STATE / "deployment.json").write_text(json.dumps(deployment, indent=2))

    before = float(podman("exec", "vbb-udp-external", "python", "-c",
        "import urllib.request,re;d=urllib.request.urlopen('http://127.0.0.1:9102/metrics').read().decode();print(re.search(r'vbb_udp_datagrams_total (.+)',d).group(1))"))
    for index in range(3):
        kub("exec", f"vault-{index}", "-c", "vault", "--", "sh", "-c", f"printf preflight-{index} | nc -u -w 1 {ip} 9090")
    for _ in range(30):
        after = float(podman("exec", "vbb-udp-external", "python", "-c",
            "import urllib.request,re;d=urllib.request.urlopen('http://127.0.0.1:9102/metrics').read().decode();print(re.search(r'vbb_udp_datagrams_total (.+)',d).group(1))"))
        if after - before >= 3:
            break
        time.sleep(.2)
    else:
        raise RuntimeError("UDP receiver did not observe all three Vault-node preflight datagrams")

    cm = json.loads(kub("get", "cm", "vbb-prometheus-config", "-o", "json"))
    config = json.loads(cm["data"]["prometheus.yml"])
    jobs = {entry["job_name"] for entry in config["scrape_configs"]}
    if "udp-external" not in jobs:
        config["scrape_configs"].append({
            "job_name": "udp-external",
            "static_configs": [{"targets": [ip + ":9102"], "labels": {"location": "outside-minikube"}}],
        })
        kub("patch", "cm", "vbb-prometheus-config", "--type=merge", "-p", json.dumps({"data": {"prometheus.yml": json.dumps(config)}}))
        for _ in range(90):
            if "udp-external" in kub("exec", "deployment/vbb-prometheus", "--", "cat", "/etc/prometheus/prometheus.yml"):
                break
            time.sleep(1)
        else:
            raise RuntimeError("Projected Prometheus configuration did not update")
        kub("exec", "deployment/vbb-prometheus", "--", "sh", "-c", "kill -HUP 1")
    for _ in range(30):
        targets = api("targets")["activeTargets"]
        if len(targets) == 12 and all(target["health"] == "up" for target in targets):
            break
        time.sleep(2)
    else:
        raise RuntimeError("Expected 12 healthy Prometheus targets after UDP setup")
    print("External UDP receiver ready at " + ip + "; three-node delivery and 12 Prometheus targets verified.")


if __name__ == "__main__":
    main()

