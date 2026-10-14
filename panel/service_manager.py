"""Service orchestration for the NiceGUI control panel.

Starts services via their start_scripts/*.bat (each in its own console window,
same as the old tkinter GUI), tracks the PIDs it started for real Stop
buttons (taskkill /T kills the whole cmd -> python tree), and polls each
service's health endpoint for true running state — so manually closed
consoles are detected automatically, and externally started services show
up as running too.
"""

import os
import subprocess

import httpx
from nicegui import ui

CREATE_NEW_CONSOLE = 0x00000010
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Registry — grows as tabs migrate to the new panel
SERVICES = {
    'mcp': {
        'title': 'MCP',
        'bat': os.path.join(PROJECT_ROOT, 'start_scripts', 'start_mcp.bat'),
        'health': 'http://127.0.0.1:5000/health',
        'port': 5000,
    },
    'vision': {
        'title': 'Vision',
        'bat': os.path.join(PROJECT_ROOT, 'start_scripts', 'start_vision.bat'),
        'health': 'http://127.0.0.1:5001/health',
        'port': 5001,
    },
}


def pids_by_port(port):
    """Find PIDs listening on a TCP port via netstat (Windows)."""
    if not port:
        return []
    try:
        out = subprocess.run(['netstat', '-ano'], capture_output=True, text=True,
                             timeout=15).stdout
        pids = []
        for line in out.splitlines():
            if 'LISTENING' in line.upper() and f':{port} ' in line:
                try:
                    pids.append(int(line.split()[-1]))
                except ValueError:
                    pass
        return list(dict.fromkeys(pids))  # dedupe, keep order
    except Exception:
        return []


def kill_tree(pid, also_kill_cmd_parent=False):
    """Kill a process tree. Best-effort: also kill a leftover cmd.exe parent,
    so stopping a service started from a .bat doesn't leave an empty console
    window behind."""
    subprocess.run(['taskkill', '/T', '/F', '/PID', str(pid)], capture_output=True)
    if also_kill_cmd_parent:
        try:
            import psutil
            parent = psutil.Process(pid).parent()
            if parent is not None and parent.name().lower().startswith('cmd'):
                subprocess.run(['taskkill', '/T', '/F', '/PID', str(parent.pid)],
                               capture_output=True)
        except Exception:
            pass


class ServiceManager:
    def __init__(self):
        self.pids = {}                                   # name -> pid (only services WE started)
        self.status = {name: False for name in SERVICES}
        self._dots = {}
        self._buttons = {}
        self._status_labels = {}

    # --- Actions -------------------------------------------------------------
    def toggle(self, name):
        """Single stable click handler: start when stopped, stop when running."""
        if self.status.get(name):
            self.stop(name)
        else:
            self.start(name)

    def start(self, name):
        """Launch the service's .bat in its own console window."""
        info = SERVICES[name]
        try:
            proc = subprocess.Popen(
                ['cmd', '/c', info['bat']],
                creationflags=CREATE_NEW_CONSOLE,
                cwd=PROJECT_ROOT,
            )
            self.pids[name] = proc.pid
            ui.notify(f"Starting {info['title']} (pid {proc.pid})")
        except Exception as e:
            ui.notify(f"Failed to start {info['title']}: {e}", type='negative')

    def stop(self, name):
        """Stop a service: kill its process tree. Works for panel-started
        services (tracked PID) AND externally started ones (PID found by the
        port it's listening on), with clear feedback either way."""
        info = SERVICES[name]
        pid = self.pids.pop(name, None)
        if pid:
            kill_tree(pid)
            ui.notify(f"Stopped {info['title']} (pid {pid})")
        else:
            # Started outside the panel (or panel was restarted) — find it by port
            port_pids = pids_by_port(info.get('port'))
            if port_pids:
                for p in port_pids:
                    kill_tree(p, also_kill_cmd_parent=True)
                ui.notify(f"Stopped {info['title']} (pid {', '.join(map(str, port_pids))} — "
                          f"started outside the panel)")
            else:
                ui.notify(f"{info['title']} doesn't appear to be running", type='warning')
                return
        # Optimistic refresh; the health poll corrects this if it survived
        self.status[name] = False
        self._refresh_chip(name)

    async def is_running(self, name):
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(SERVICES[name]['health'])
                return r.status_code == 200
        except Exception:
            return False

    async def poll_all(self):
        """Health-poll every service and refresh the header chips."""
        for name in SERVICES:
            self.status[name] = await self.is_running(name)
            self._refresh_chip(name)

    # --- UI --------------------------------------------------------------------
    def render_header(self):
        """Header chips: status dot + title + start/stop button per service."""
        with ui.row().classes('items-center gap-2'):
            for name, info in SERVICES.items():
                with ui.row().classes('items-center gap-1 rounded-lg px-2 py-1 bg-slate-700'):
                    self._dots[name] = ui.icon('circle').classes('text-slate-400 text-xs')
                    self._status_labels[name] = ui.label(info['title']).classes('text-sm')
                    self._buttons[name] = (
                        ui.button('', icon='play_arrow',
                                  on_click=lambda n=name: self.toggle(n))
                        .props('flat dense size=sm color=green')
                        .tooltip('Start / stop')
                    )
        # Poll immediately and every 3 seconds
        ui.timer(3.0, self.poll_all, immediate=True)

    def _refresh_chip(self, name):
        """Appearance-only chip update (the click handler is bound once and
        decides start-vs-stop from the current state). Stop always works:
        tracked PID for panel-started services, port lookup for external ones."""
        running = self.status[name]
        dot = self._dots.get(name)
        btn = self._buttons.get(name)
        if dot is not None:
            dot.classes(replace='text-xs ' + ('text-green-400' if running else 'text-slate-400'))
        if btn is not None:
            if running:
                btn.icon = 'stop'
                btn.props('color=red')
            else:
                btn.icon = 'play_arrow'
                btn.props('color=green')
            btn.props(remove='disable')