"""Local HTTP API for Gem Drive.

main.py forwards `!commands` to `POST /api/command` and reads state from
`GET /api/state`. The server deliberately uses the standard library so the game
has no web-framework dependency.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional, Tuple

from .sim import DriveSim


class GameRequestHandler(BaseHTTPRequestHandler):
    @property
    def game_sim(self) -> DriveSim:
        return self.server.sim  # type: ignore[attr-defined]

    def do_GET(self) -> None:  # noqa: N802 (http.server naming)
        path = self.path.split("?", 1)[0]
        if path == "/health":
            self._send_json(
                200,
                {
                    "status": "ok",
                    "paused": self.game_sim.paused,
                    "active_cars": len(self.game_sim.players),
                },
            )
        elif path == "/api/state":
            self._send_json(200, self.game_sim.snapshot())
        else:
            self._send_json(404, {"status": "error", "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        data = self._read_json()
        if data is None:
            self._send_json(400, {"status": "error", "error": "invalid json"})
            return

        if path == "/api/command":
            user = str(data.get("user") or "viewer")
            command = str(data.get("command") or "")
            result = self.game_sim.command(user, command)
            if result.get("accepted"):
                print(
                    f"[GAME] {user}: !{result['command']} "
                    f"lane={result.get('lane')} speed={result.get('speed')}",
                    flush=True,
                )
            self._send_json(200, result)
            return

        if path == "/api/control":
            action = str(data.get("action") or "").lower()
            if action == "pause":
                self.game_sim.set_paused(True)
            elif action == "resume":
                self.game_sim.set_paused(False)
            elif action == "reset":
                self.game_sim.reset()
            elif action == "spawn_traffic":
                self.game_sim.spawn_traffic(
                    count=int(data.get("count", 1)),
                    ahead=float(data.get("ahead", 120.0)),
                )
            elif action == "traffic_density":
                if not self.game_sim.set_traffic_density(
                    str(data.get("density") or "")
                ):
                    self._send_json(
                        400,
                        {"status": "error", "error": "unknown density"},
                    )
                    return
            elif action == "demo":
                self.game_sim.set_demo(
                    bool(data.get("enabled", True)),
                    int(data.get("cars", 6)),
                )
            elif action == "force_crash":
                if not self.game_sim.force_crash(str(data.get("user") or "")):
                    self._send_json(404, {"status": "error", "error": "car not found"})
                    return
            else:
                self._send_json(400, {"status": "error", "error": "unknown action"})
                return
            self._send_json(200, {"status": "ok", "action": action})
            return

        self._send_json(404, {"status": "error", "error": "not found"})

    def _read_json(self) -> Optional[Dict[str, Any]]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            value = json.loads(raw or b"{}")
            return value if isinstance(value, dict) else None
        except (ValueError, json.JSONDecodeError):
            return None

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # Keep the game console readable; command accepts are logged above.
        return


class GameHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: Tuple[str, int], sim: DriveSim) -> None:
        super().__init__(address, GameRequestHandler)
        self.sim = sim


def start_server(
    sim: DriveSim, host: str = "127.0.0.1", port: int = 5010
) -> Optional[ThreadingHTTPServer]:
    """Start the API on a daemon thread. Returns None if the port is busy."""
    try:
        server = GameHTTPServer((host, port), sim)
    except OSError as exc:
        print(f"[GAME] Could not bind {host}:{port}: {exc}", flush=True)
        return None
    thread = threading.Thread(target=server.serve_forever, name="gem-drive-api", daemon=True)
    thread.start()
    print(f"[GAME] API listening on http://{host}:{port}", flush=True)
    return server
