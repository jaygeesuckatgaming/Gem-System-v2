import argparse
import json
import os
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


class HardwareMonitorApp:
    def __init__(self, root, server=""):
        self.root = root
        self.server = (server or "").rstrip("/")
        self.remote_label = urlparse(self.server).netloc or self.server
        self.interval_ms = 500
        self.failures = 0
        self.fetching = False

        self.root.title("Real-Time Hardware Monitor")
        self.root.geometry("500x420")
        self.root.resizable(False, False)
        self.root.configure(bg="#111111")

        self.init_gpu()

        # Title Label
        tk.Label(
            root,
            text=(f"Remote: {self.remote_label}" if self.server
                  else "System Performance History (Last 30s)"),
            fg="#888888", bg="#111111", font=("Segoe UI", 10)
        ).pack(pady=(12, 5))

        # --- GPU Graph ---
        self.gpu_graph = LiveGraph(
            root, title=f"GPU VRAM ({self.remote_label or self.gpu_name})",
            line_color="#76b900", fill_color="#182d00"  # NVIDIA Green
        )
        self.gpu_graph.pack(pady=6)

        # --- CPU Graph ---
        self.cpu_graph = LiveGraph(
            root, title=f"CPU Utilization ({psutil.cpu_count(logical=True)} Threads)",
            line_color="#00aaff", fill_color="#002b40"  # Intel/Tech Blue
        )
        self.cpu_graph.pack(pady=6)

        # Numeric Summary Bar at Bottom
        self.label_info = tk.Label(
            root, text="Initializing...", fg="#bbbbbb", bg="#111111", font=("Segoe UI", 9)
        )
        self.label_info.pack(pady=5)

        # Start monitoring loop
        self.update_stats()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def init_gpu(self):
        self.gpu_available = False
        self.gpu_name = "N/A"
        # (a remote overlay draws the server's GPU; this machine's isn't queried)
        if self.server or not HAS_NVML:
            return
        try:
            pynvml.nvmlInit()
            self.gpu_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            self.gpu_name = pynvml.nvmlDeviceGetName(self.gpu_handle)
            self.gpu_available = True
        except Exception:
            pass

    def update_stats(self):
        if self.server:
            self.update_remote()
        else:
            self.update_local()
        # Update every 500 ms (2 times per second -> 60 points = 30 seconds window)
        self.root.after(self.interval_ms, self.update_stats)

    def update_local(self):
        # 1. Fetch GPU Info
        vram_pct = 0.0
        vram_str = "GPU: N/A"
        if self.gpu_available:
            try:
                mem = pynvml.nvmlDeviceGetMemoryInfo(self.gpu_handle)
                used_mb = mem.used / (1024 ** 2)
                total_mb = mem.total / (1024 ** 2)
                vram_pct = (used_mb / total_mb) * 100
                vram_str = f"VRAM: {used_mb:.0f}/{total_mb:.0f} MB"
            except Exception:
                pass
        self.gpu_graph.add_point(vram_pct)

        # 2. Fetch CPU Info
        cpu_pct = psutil.cpu_percent(interval=None)
        self.cpu_graph.add_point(cpu_pct)

        # 3. Update bottom info label
        ram = psutil.virtual_memory()
        self.label_info.config(
            text=f"{vram_str}  |  CPU: {cpu_pct:.1f}%  |  Sys RAM: {ram.percent:.1f}%"
        )

    def update_remote(self):
        if self.fetching:
            return
        self.fetching = True

        def work():
            try:
                with urllib.request.urlopen(f"{self.server}/stats", timeout=2.0) as response:
                    data = json.load(response)
                self.root.after(0, lambda: self.apply_remote(data, None))
            except Exception as exc:
                self.root.after(0, lambda: self.apply_remote(None, exc))

        threading.Thread(target=work, daemon=True).start()

    def apply_remote(self, data, error):
        self.fetching = False
        if error is not None or not data:
            self.failures += 1
            if self.failures == 1 or self.failures % 20 == 0:
                self.label_info.config(
                    text=f"{self.remote_label}: offline ({self.failures} missed)")
            return

        self.failures = 0
        gpu = data.get("gpu") or {}
        cpu = data.get("cpu") or {}
        ram = data.get("ram") or {}

        name = gpu.get("name") or self.remote_label
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
        gpu_extra = ("  " + " ".join(bits)) if bits else ""
        self.label_info.config(
            text=(f"{vram}{gpu_extra}  |  CPU: {float(cpu.get('percent') or 0):.1f}%  |  "
                  f"RAM: {float(ram.get('percent') or 0):.1f}%")
        )

    def on_close(self):
        if self.gpu_available:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass
        self.root.destroy()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Draw this machine's hardware, or a server's.")
    parser.add_argument(
        "--server", default=os.environ.get("GPU_STATS_URL", ""),
        help="stats server base URL, e.g. http://192.168.137.129:8092 "
             "(default: $GPU_STATS_URL; empty draws this machine)",
    )
    args = parser.parse_args()
    root = tk.Tk()
    app = HardwareMonitorApp(root, server=args.server)
    root.mainloop()
