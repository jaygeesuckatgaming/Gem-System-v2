import tkinter as tk
from collections import deque
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
    def __init__(self, root):
        self.root = root
        self.root.title("Real-Time Hardware Monitor")
        self.root.geometry("500x420")
        self.root.resizable(False, False)
        self.root.configure(bg="#111111")

        self.init_gpu()

        # Title Label
        tk.Label(
            root, text="System Performance History (Last 30s)", 
            fg="#888888", bg="#111111", font=("Segoe UI", 10)
        ).pack(pady=(12, 5))

        # --- GPU Graph ---
        self.gpu_graph = LiveGraph(
            root, title=f"GPU VRAM ({self.gpu_name})", 
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
        if HAS_NVML:
            try:
                pynvml.nvmlInit()
                self.gpu_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                self.gpu_name = pynvml.nvmlDeviceGetName(self.gpu_handle)
                self.gpu_available = True
            except Exception:
                pass

    def update_stats(self):
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
            except:
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

        # Update every 500 ms (2 times per second -> 60 points = 30 seconds window)
        self.root.after(500, self.update_stats)

    def on_close(self):
        if self.gpu_available:
            try:
                pynvml.nvmlShutdown()
            except:
                pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = HardwareMonitorApp(root)
    root.mainloop()