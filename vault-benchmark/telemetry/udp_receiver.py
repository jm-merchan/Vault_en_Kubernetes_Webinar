"""Raw UDP audit receiver for the controlled Transit laboratory.

Each UDP datagram is appended unchanged. Datagram boundaries are atomic, but
delivery is not acknowledged and the kernel may drop datagrams under load.
"""
import http.server
import json
import os
from pathlib import Path
import socket
import threading

ROOT = Path(os.getenv("VBB_UDP_ROOT", "/data"))
ROOT.mkdir(parents=True, exist_ok=True)
CGROUP = Path("/sys/fs/cgroup")
LOCK = threading.Lock()
METRICS = {key: 0 for key in [
    "bytes_written_total", "datagrams_total", "entries_written_total",
    "write_errors_total", "truncated_datagrams_total", "fsync_total",
]}


def add(key, value=1):
    with LOCK:
        METRICS[key] += value


def kernel_udp():
    lines = Path("/proc/net/snmp").read_text().splitlines()
    for index, line in enumerate(lines[:-1]):
        if line.startswith("Udp:") and lines[index + 1].startswith("Udp:"):
            keys = line.split()[1:]
            values = lines[index + 1].split()[1:]
            return dict(zip(keys, values))
    return {}


def metrics(server):
    with LOCK:
        values = dict(METRICS)
    lines = [f"vbb_udp_{key} {value}" for key, value in values.items()]
    lines.append(f"vbb_udp_socket_receive_buffer_bytes {server.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)}")
    for key, value in kernel_udp().items():
        lines.append(f"vbb_udp_kernel_{key.lower()}_total {value}")
    for filename, prefix in [("cpu.stat", "cpu"), ("memory.events", "memory_events")]:
        path = CGROUP / filename
        if path.exists():
            for line in path.read_text().splitlines():
                key, value = line.split()
                lines.append(f"vbb_udp_{prefix}_{key.replace('.', '_')}_total {value}")
    if (CGROUP / "cpu.max").exists():
        quota, period = (CGROUP / "cpu.max").read_text().split()
        value = float(quota) / float(period) if quota != "max" else -1
        lines.append(f"vbb_udp_cpu_quota_cores {value}")
    for filename in ["memory.current", "memory.max"]:
        path = CGROUP / filename
        if path.exists():
            value = path.read_text().strip()
            lines.append(f"vbb_udp_{filename.replace('.', '_')}_bytes {value if value != 'max' else -1}")
    return "\n".join(lines) + "\n"


class Metrics(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = metrics(self.server.udp_server).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


def control():
    try:
        return json.loads((ROOT / "control.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"case": "preflight"}


if __name__ == "__main__":
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, int(os.getenv("VBB_UDP_RCVBUF", str(16 * 1024 * 1024))))
    udp.bind(("0.0.0.0", int(os.getenv("VBB_UDP_PORT", "9090"))))
    httpd = http.server.ThreadingHTTPServer(("0.0.0.0", int(os.getenv("VBB_UDP_METRICS_PORT", "9102"))), Metrics)
    httpd.udp_server = udp
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    current_case = None
    fd = None
    while True:
        payload, _, flags, peer = udp.recvmsg(65535)
        case = control().get("case", "preflight")
        if case != current_case:
            if fd is not None:
                os.fsync(fd)
                add("fsync_total")
                os.close(fd)
            folder = ROOT / case
            folder.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd = os.open(folder / "audit.json", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            current_case = case
        try:
            view = memoryview(payload)
            while view:
                size = os.write(fd, view)
                view = view[size:]
            add("bytes_written_total", len(payload))
            add("datagrams_total")
            add("entries_written_total", payload.count(b"\n"))
            if flags & socket.MSG_TRUNC:
                add("truncated_datagrams_total")
        except OSError:
            add("write_errors_total")

