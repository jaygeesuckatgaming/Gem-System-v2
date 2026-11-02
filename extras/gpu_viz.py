"""Hardware monitor overlay: this machine's GPU/CPU, and optionally a server's.

    python gpu_viz.py
        this PC only
    python gpu_viz.py --server http://192.168.137.129:8092
        this PC and that server side by side
    GPU_STATS_URL=http://host:8092 python gpu_viz.py
        the same, without the argument

The server side comes from `gpu_viz_server.py`, which runs on the other
machine and serves the same numbers at `/stats`.
"""

import argparse
import json
import os
import socket
import threading
import tkinter as tk
import urllib.request
from collections import deque
from urllib.parse import urlparse

import psutil

try:
    import pynvml
    HAS_NVML = True
except ImportError:
    HAS_NVML = False


class LiveGraph(tk.Canvas):
    """Custom Canvas widget that renders a scrolling history line graph."""
    def __init__(self, parent, width=460, height=140, max_points=60, line_color="#00e5ff", fill_color="#003847", title="Metric"):
        super().__init__(parent, width=width, height=height, bg="#181818", highlightthickness=1, highlightbackground="#333333")
        self.w = width
        self.h = height
        self.max_points = max_points
        self.line_color = line_color
        self.fill_color = fill_color
        self.title = title

        # Fixed-length queue to store the history (0% to 100%)
        self.data = deque([0.0] * self.max_points, maxlen=self.max_points)

    def add_point(self, value):
        """Add a new value (0 - 100) and redraw the graph."""
        self.data.append(max(0.0, min(100.0, value)))
        self.draw()

    def draw(self):
        self.delete("all")

        # 1. Draw subtle background grid lines (25%, 50%, 75%)
        for pct in [0.25, 0.50, 0.75]:
            y = self.h - (pct * self.h)
            self.create_line(0, y, self.w, y, fill="#272727", dash=(2, 4))

        # 2. Build coordinate points for the line
        step_x = self.w / (self.max_points - 1)
        points = []
        for i, val in enumerate(self.data):
            x = i * step_x
            y = self.h - (val / 100.0 * self.h)
            # Add top padding so 100% line doesn't clip off-screen
            y = max(2, min(self.h - 2, y))
            points.extend([x, y])

        # 3. Draw filled area under the line
        polygon_points = [0, self.h] + points + [self.w, self.h]
        self.create_polygon(polygon_points, fill=self.fill_color, outline="")

        # 4. Draw the main history line
        self.create_line(points, fill=self.line_color, width=2, smooth=True)

        # 5. Draw Title & Current Value on top
        current_val = self.data[-1]
        self.create_text(10, 15, text=self.title, fill="#ffffff", anchor="w", font=("Segoe UI", 9, "bold"))
        self.create_text(self.w - 10, 15, text=f"{current_val:.1f}%", fill=self.line_color, anchor="e", font=("Segoe UI", 10, "bold"))


class Collector:
    """This machine's numbers, in the same shape gpu_viz_server.py serves."""

    def __init__(self):
        self.available = False
        self.name = "N/A"
        self.handle = None
        if HAS_NVML:
            try:
                pynvml.nvmlInit()
                self.handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                self.name = pynvml.nvmlDeviceGetName(self.handle)
                self.available = True
            except Exception:
                self.handle = None
        psutil.cpu_percent(interval=None)  # the first call is always 0

    def read(self):
        gpu = {"available": self.available, "name": self.name}
        if self.handle is not None:
            try:
                mem = pynvml.nvmlDeviceGetMemoryInfo(self.handle)
                used_mb = mem.used / (1024 ** 2)
                total_mb = mem.total / (1024 ** 2)
                gpu.update(
                    vram_used_mb=round(used_mb),
                    vram_total_mb=round(total_mb),
                    vram_percent=round(used_mb / total_mb * 100, 1) if total_mb else 0.0,
                )
                try:
                    gpu["util_percent"] = pynvml.nvmlDeviceGetUtilizationRates(self.handle).gpu
                except Exception:
                    pass
                try:
                    gpu["temp_c"] = pynvml.nvmlDeviceGetTemperature(
                        self.handle, pynvml.NVML_TEMPERATURE_GPU)
                except Exception:
                    pass
            except Exception:
                pass
        ram = psutil.virtual_memory()
        return {
            "host": socket.gethostname(),
            "gpu": gpu,
            "cpu": {
                "percent": round(psutil.cpu_percent(interval=None), 1),
                "threads": psutil.cpu_count(logical=True) or 0,
            },
            "ram": {"percent": round(ram.percent, 1)},
        }

    def close(self):
        if self.handle is not None:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass


class Column:
    """One machine's two graphs and its summary line."""

    def __init__(self, parent, title, server=""):
        self.server = server.rstrip("/")
        self.failures = 0
        self.fetching = False
        self.host = ""
        self.label_text = title

        self.frame = tk.Frame(parent, bg="#111111")
        self.title = tk.Label(
            self.frame, text=title, fg="#888888", bg="#111111", font=("Segoe UI", 10, "bold"))
        self.title.pack(pady=(6, 4))

        self.gpu_graph = LiveGraph(
            self.frame, title="GPU VRAM (starting…)",
            line_color="#76b900", fill_color="#182d00")  # NVIDIA Green
        self.gpu_graph.pack(pady=4)

        self.cpu_graph = LiveGraph(
            self.frame, title=f"CPU Utilization ({psutil.cpu_count(logical=True)} Threads)",
            line_color="#00aaff", fill_color="#002b40")  # Intel/Tech Blue
        self.cpu_graph.pack(pady=4)

        self.info = tk.Label(
            self.frame, text="Initializing...", fg="#bbbbbb", bg="#111111",
            font=("Segoe UI", 9))
        self.info.pack(pady=4)

    def apply(self, data, error=None):
        if error is not None or not data:
            self.failures += 1
            if self.failures == 1 or self.failures % 20 == 0:
                self.info.config(text=f"offline ({self.failures} missed)")
            return

        self.failures = 0
        gpu = data.get("gpu") or {}
        cpu = data.get("cpu") or {}
        ram = data.get("ram") or {}

        host = data.get("host")
        if host and host != self.host:
            self.host = host
            self.title.config(text=f"{self.label_text} ({host})")

        name = gpu.get("name") or "N/A"
        gpu_title = f"GPU VRAM ({name})"
        if self.gpu_graph.title != gpu_title:
            self.gpu_graph.title = gpu_title
        threads = cpu.get("threads") or psutil.cpu_count(logical=True)
        cpu_title = f"CPU Utilization ({threads} Threads)"
        if self.cpu_graph.title != cpu_title:
            self.cpu_graph.title = cpu_title

        self.gpu_graph.add_point(float(gpu.get("vram_percent") or 0.0))
        self.cpu_graph.add_point(float(cpu.get("percent") or 0.0))

        if gpu.get("available"):
            vram = (f"VRAM: {float(gpu.get('vram_used_mb') or 0):.0f}/"
                    f"{float(gpu.get('vram_total_mb') or 0):.0f} MB")
        else:
            vram = "GPU: N/A"
        bits = []
        if gpu.get("util_percent") is not None:
            bits.append(f"GPU: {float(gpu['util_percent']):.0f}%")
        if gpu.get("temp_c") is not None:
            bits.append(f"{float(gpu['temp_c']):.0f}°C")
        extra = ("  " + " ".join(bits)) if bits else ""
        self.info.config(
            text=(f"{vram}{extra}  |  CPU: {float(cpu.get('percent') or 0):.1f}%  |  "
                  f"RAM: {float(ram.get('percent') or 0):.1f}%")
        )


class HardwareMonitorApp:
    def __init__(self, root, server="", local=True):
        self.root = root
        root.title("Real-Time Hardware Monitor")
        root.resizable(False, False)
        root.configure(bg="#111111")
        self.closed = False

        self.collector = Collector() if local else None
        self.server = (server or "").rstrip("/")

        body = tk.Frame(root, bg="#111111")
        body.pack(padx=8, pady=4)

        self.local_column = None
        self.remote_column = None
        if local:
            self.local_column = Column(body, "THIS PC")
            self.local_column.frame.pack(side=tk.LEFT, padx=6)
        if self.server:
            self.remote_column = Column(body, "SERVER", server=self.server)
            self.remote_column.frame.pack(side=tk.LEFT, padx=6)

        if local and self.server:
            root.geometry("1010x440")
        else:
            root.geometry("500x440")

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.tick()

    def tick(self):
        if self.closed:
            return
        if self.local_column is not None:
            self.local_column.apply(self.collector.read())
        if self.remote_column is not None:
            self.fetch_remote(self.remote_column)
        self.root.after(500, self.tick)

    def fetch_remote(self, column):
        if column.fetching:
            return
        column.fetching = True

        def work():
            try:
                with urllib.request.urlopen(f"{column.server}/stats", timeout=2.0) as response:
                    data = json.load(response)
                error = None
            except Exception as exc:
                data, error = None, exc
            try:
                self.root.after(0, lambda: self.finish_remote(column, data, error))
            except Exception:
                pass

        threading.Thread(target=work, daemon=True).start()

    def finish_remote(self, column, data, error):
        column.fetching = False
        if self.closed:
            return
        column.apply(data, error)

    def on_close(self):
        self.closed = True
        if self.collector is not None:
            self.collector.close()
        self.root.destroy()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Draw this machine's hardware, and a server's.")
    parser.add_argument(
        "--server", default=os.environ.get("GPU_STATS_URL", ""),
        help="stats server base URL, e.g. http://192.168.137.129:8092 "
             "(default: $GPU_STATS_URL). Its graphs go beside this PC's.",
    )
    parser.add_argument(
        "--no-local", action="store_true",
        help="leave out this PC and show only the server",
    )
    args = parser.parse_args()

    root = tk.Tk()
    app = HardwareMonitorApp(root, server=args.server, local=not args.no_local)
    root.mainloop()
