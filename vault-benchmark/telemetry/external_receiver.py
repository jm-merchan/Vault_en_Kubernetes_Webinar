"""TCP audit receiver for controlled lab tests, with per-connection raw logs.

No parsing/truncation on the ingest path. Separate files prevent interleaving
partial TCP frames from different Vault nodes. EOF flush includes fsync, but
Vault receives no per-record durable acknowledgement from this protocol.
"""
import gzip
import http.server
import json
import os
from pathlib import Path
import socket
import threading
import time

ROOT = Path(os.getenv('VBB_TCP_ROOT', '/data'))
ROOT.mkdir(parents=True, exist_ok=True)
CGROUP = Path('/sys/fs/cgroup')
INSTANCE = str(time.time_ns())
LOCK = threading.Lock()
METRICS = {k: 0 for k in ['bytes_written_total', 'entries_written_total',
    'write_errors_total', 'connections_total', 'connections_active',
    'fsync_total', 'compression_active', 'compression_cpu_seconds_total']}


def add(key, value=1):
    with LOCK:
        METRICS[key] += value


def compress(path):
    add('compression_active')
    start = time.thread_time()
    try:
        tmp = path.with_suffix(path.suffix + '.gz.tmp')
        with path.open('rb') as source, gzip.open(tmp, 'wb', compresslevel=6) as dest:
            while chunk := source.read(1024 * 1024):
                dest.write(chunk)
        tmp.rename(path.with_suffix(path.suffix + '.gz'))
        path.unlink()
    except Exception:
        add('write_errors_total')
    finally:
        add('compression_cpu_seconds_total', time.thread_time() - start)
        add('compression_active', -1)


def handle(conn, peer, ident, config):
    folder = ROOT / config.get('case', 'preflight')
    folder.mkdir(mode=0o700, exist_ok=True)
    part = 0
    written = 0
    fd = None
    path = None
    limit = int(config.get('rotate_bytes', 0))
    add('connections_active')
    try:
        while chunk := conn.recv(1024 * 1024):
            if fd is None:
                path = folder / f'{INSTANCE}-conn-{ident:06d}-{part:04d}.json'
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            view = memoryview(chunk)
            while view:
                size = os.write(fd, view)
                view = view[size:]
            add('bytes_written_total', len(chunk))
            add('entries_written_total', chunk.count(b'\n'))
            written += len(chunk)
            # Rotate only at a complete NDJSON boundary; do not split a line.
            if limit and written >= limit and chunk.endswith(b'\n'):
                os.fsync(fd)
                add('fsync_total')
                os.close(fd)
                fd = None
                part += 1
                written = 0
                if config.get('compress'):
                    threading.Thread(target=compress, args=(path,), daemon=True).start()
    except Exception as error:
        add('write_errors_total')
        print(json.dumps({'connection': ident, 'error': type(error).__name__}), flush=True)
    finally:
        if fd is not None:
            try:
                os.fsync(fd)
                add('fsync_total')
            except OSError:
                add('write_errors_total')
            os.close(fd)
        conn.close()
        add('connections_active', -1)


def metrics():
    with LOCK:
        values = dict(METRICS)
    lines = [f'vbb_external_{k} {v}' for k, v in values.items()]
    def emit(k, v, labels=''):
        lines.append(f'vbb_external_{k}{labels} {v}')
    for filename, prefix in [('cpu.stat', 'cpu'), ('memory.events', 'memory_events')]:
        if (CGROUP / filename).exists():
            for line in (CGROUP / filename).read_text().splitlines():
                key, value = line.split()
                emit(prefix + '_' + key.replace('.', '_') + '_total', value)
    if (CGROUP / 'cpu.max').exists():
        quota, period = (CGROUP / 'cpu.max').read_text().split()
        emit('cpu_quota_cores', float(quota) / float(period) if quota != 'max' else -1)
    for filename in ['memory.current', 'memory.max']:
        if (CGROUP / filename).exists():
            value = (CGROUP / filename).read_text().strip()
            emit(filename.replace('.', '_') + '_bytes', value if value != 'max' else -1)
    for kind in ['cpu', 'io', 'memory']:
        if (CGROUP / (kind + '.pressure')).exists():
            for line in (CGROUP / (kind + '.pressure')).read_text().splitlines():
                fields = line.split()
                values = dict(field.split('=') for field in fields[1:])
                emit(kind + '_pressure_seconds_total', float(values['total']) / 1e6,
                     '{stall="' + fields[0] + '"}')
    if (CGROUP / 'io.stat').exists():
        for line in (CGROUP / 'io.stat').read_text().splitlines():
            fields = line.split()
            for key, value in (field.split('=') for field in fields[1:]):
                emit('io_' + key + '_total', value, '{device="' + fields[0] + '"}')
    return '\n'.join(lines) + '\n'


class Metrics(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = metrics().encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; version=0.0.4')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


if __name__ == '__main__':
    threading.Thread(target=http.server.ThreadingHTTPServer(
        ('0.0.0.0', int(os.getenv('VBB_TCP_METRICS_PORT', '9102'))), Metrics
    ).serve_forever, daemon=True).start()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', int(os.getenv('VBB_TCP_PORT', '9090'))))
    server.listen(64)
    ident = 0
    while True:
        conn, peer = server.accept()
        ident += 1
        add('connections_total')
        try:
            config = json.loads((ROOT / 'control.json').read_text())
        except FileNotFoundError:
            config = {'case': 'preflight'}
        threading.Thread(target=handle, args=(conn, peer, ident, config), daemon=True).start()
