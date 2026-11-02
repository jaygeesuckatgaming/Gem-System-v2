"""Hardware stats server for the GPU/CPU monitor overlay.

Runs on the machine whose hardware you want on stream (for example the server
that runs Ollama), so `gpu_viz.py` on the streaming PC can draw its numbers.

    GET /health -> {"ok": true}
    GET /stats  -> {"host", "time", "gpu": {...}, "cpu": {...}, "ram": {...}}

Start it in an env with psutil. pynvml is used when present; without it the
numbers come from `nvidia-smi` (NVIDIA drivers only):

    python gpu_viz_server.py --port 8092

Allow the port through the server's firewall, then point the overlay at it:

    python gpu_viz.py --server http://192.168.137.129:8092

The sampler runs every half second in the background, so requests are cheap
and the CPU figure is a real interval, not a one-shot 0%.
"""

from __future__ import annotations

import argparse
import json
import platform
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psutil

try:
    import pynvml
    HAS_NVML = True
except ImportError:
    HAS_NVML = False


STATE = {
    'host': socket.gethostname(),
    'platform': f'{platform.system()} {platform.release()}',
    'time': 0.0,
    'gpu': {'available': False},
    'cpu': {'percent': 0.0, 'threads': psutil.cpu_count(logical=True) or 0},
    'ram': {'percent': 0.0},
}
LOCK = threading.Lock()


class Gpu:
    """pynvml when it's installed, else `nvidia-smi`, else nothing."""

    def __init__(self):
        self.handle = None
        self.name = 'N/A'
        self.available = False
        if HAS_NVML:
            try:
                pynvml.nvmlInit()
                self.handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                self.name = pynvml.nvmlDeviceGetName(self.handle)
                self.available = True
                return
            except Exception:
                self.handle = None
        name = self._smi('name')
        if name:
            self.name = name
            self.available = True

    @staticmethod
    def _smi(field: str) -> str:
        try:
            out = subprocess.run(
                ['nvidia-smi', f'--query-gpu={field}', '--format=csv,noheader,nounits'],
                capture_output=True, text=True, timeout=3,
            )
            value = out.stdout.strip().splitlines()[0].strip()
            return '' if value.lower() in ('[n/a]', 'n/a') else value
        except Exception:
            return ''

    @staticmethod
    def _number(text: str):
        try:
            return float(text)
        except (TypeError, ValueError):
            return None

    def read(self) -> dict:
        if self.handle is not None:
            try:
                mem = pynvml.nvmlDeviceGetMemoryInfo(self.handle)
                used_mb = mem.used / (1024 ** 2)
                total_mb = mem.total / (1024 ** 2)
                try:
                    util = pynvml.nvmlDeviceGetUtilizationRates(self.handle).gpu
                except Exception:
                    util = None
                try:
                    temp = pynvml.nvmlDeviceGetTemperature(
                        self.handle, pynvml.NVML_TEMPERATURE_GPU)
                except Exception:
                    temp = None
                return {
                    'available': True,
                    'name': self.name,
                    'vram_used_mb': round(used_mb),
                    'vram_total_mb': round(total_mb),
                    'vram_percent': round(used_mb / total_mb * 100, 1) if total_mb else 0.0,
                    'util_percent': util,
                    'temp_c': temp,
                }
            except Exception:
                pass
        elif self.available:
            used = self._number(self._smi('memory.used'))
            total = self._number(self._smi('memory.total'))
            return {
                'available': True,
                'name': self.name,
                'vram_used_mb': round(used) if used is not None else None,
                'vram_total_mb': round(total) if total is not None else None,
                'vram_percent': round(used / total * 100, 1) if used and total else 0.0,
                'util_percent': self._number(self._smi('utilization.gpu')),
                'temp_c': self._number(self._smi('temperature.gpu')),
            }
        return {'available': False, 'name': self.name}


def sample_forever(gpu: Gpu, interval: float) -> None:
    psutil.cpu_percent(interval=None)  # the first call is always 0
    while True:
        ram = psutil.virtual_memory()
        with LOCK:
            STATE['time'] = time.time()
            STATE['gpu'] = gpu.read()
            STATE['cpu'] = {
                'percent': round(psutil.cpu_percent(interval=None), 1),
                'threads': psutil.cpu_count(logical=True) or 0,
            }
            STATE['ram'] = {
                'percent': round(ram.percent, 1),
                'used_mb': round(ram.used / (1024 ** 2)),
                'total_mb': round(ram.total / (1024 ** 2)),
            }
        time.sleep(interval)


class Handler(BaseHTTPRequestHandler):
    server_version = 'gpu-viz-server/1.0'

    def log_message(self, fmt, *args):
        print(f'[gpu-viz] {self.address_string()} {fmt % args}', flush=True)

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split('?', 1)[0].rstrip('/') or '/'
        if path in ('/', '/stats'):
            with LOCK:
                payload = json.loads(json.dumps(STATE))
            self._send(200, payload)
        elif path == '/health':
            self._send(200, {'ok': True})
        else:
            self._send(404, {'error': 'not found'})


def main() -> None:
    parser = argparse.ArgumentParser(description='Serve this machine\'s GPU/CPU stats.')
    parser.add_argument('--host', default='0.0.0.0', help='bind address (default: all interfaces)')
    parser.add_argument('--port', type=int, default=8092)
    parser.add_argument('--interval', type=float, default=0.5, help='seconds between samples')
    args = parser.parse_args()

    gpu = Gpu()
    thread = threading.Thread(target=sample_forever, args=(gpu, max(0.1, args.interval)), daemon=True)
    thread.start()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f'[gpu-viz] {socket.gethostname()}: GPU {gpu.name!r} '
          f'({"pynvml" if gpu.handle is not None else "nvidia-smi" if gpu.available else "none"})',
          flush=True)
    print(f'[gpu-viz] http://{args.host}:{args.port}/stats — allow this port through the firewall',
          flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if gpu.handle is not None:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass


if __name__ == '__main__':
    main()
