"""
OSC Receiver
Listens for UDP OSC messages sent by Unreal Engine (or any other OSC sender)
and dispatches them to registered Python callbacks.

The socket is served on a daemon thread, so it never blocks Quart/asyncio.
Callbacks may be sync or async; async ones are scheduled on the event loop
given to ``set_event_loop()``.

Usage (from main.py, right after the other clients are created):

    from clients.osc_receiver import OSCReceiver

    osc_rx = OSCReceiver(host='0.0.0.0', port=9000)
    osc_rx.set_event_loop(asyncio.get_running_loop())   # only if you use async callbacks
    osc_rx.on('/game/score', on_game_score)             # callback(address, *args)
    osc_rx.on('*', on_any_osc)                          # every message
    osc_rx.start()

Callback signature::

    def on_game_score(address: str, *args): ...
    async def on_game_score(address: str, *args): ...

Address patterns follow python-osc conventions: ``*`` matches within one level
(``/game/*`` matches ``/game/score`` but not ``/game/a/b``) and ``?`` matches a
single character. ``"*"`` as the whole pattern registers a catch-all that sees
every message.

Standalone test (no Gem-System needed)::

    python -m clients.osc_receiver --port 9000
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import re
import threading
import time
from collections import deque
from typing import Any, Awaitable, Callable, Deque, Dict, List, Optional, Pattern, Tuple

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer

Callback = Callable[..., Optional[Awaitable[Any]]]

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 9000


def _compile_pattern(pattern: str) -> Pattern[str]:
    """python-osc style address pattern -> regex (``*`` = one level, ``?`` = char)."""
    parts = []
    for char in pattern:
        if char == "*":
            parts.append("[^/]*")
        elif char == "?":
            parts.append(".")
        else:
            parts.append(re.escape(char))
    return re.compile("^" + "".join(parts) + "$")


class OSCReceiver:
    """Threaded OSC/UDP receiver with a small callback router.

    ``on("/game/score", cb)``        exact address
    ``on("/game/*", cb)``            one-level wildcard
    ``on("*", cb)``                  every message (catch-all)
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        verbose: bool = True,
        history: int = 100,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.verbose = verbose

        self._dispatcher = Dispatcher()
        self._catch_all: List[Callback] = []
        # (pattern, callback, compiled regex)
        self._handlers: List[Tuple[str, Callback, Pattern[str]]] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock = threading.Lock()
        self._server: Optional[ThreadingOSCUDPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()

        self._history: Deque[Dict[str, Any]] = deque(maxlen=max(1, int(history)))
        self.message_count = 0
        self.last_message: Optional[Dict[str, Any]] = None
        self.started_at: Optional[float] = None
        self.last_error: Optional[str] = None

        # One entry point for every datagram; routing is done below so each
        # message is recorded exactly once and the catch-all sees everything.
        self._dispatcher.set_default_handler(self._handle)

    # ------------------------------------------------------------------ setup
    def set_event_loop(self, loop: Optional[asyncio.AbstractEventLoop]) -> None:
        """Event loop used to schedule async callbacks (optional)."""
        self._loop = loop

    def on(self, address: str, callback: Callback) -> Callback:
        """Register a callback for an OSC address pattern. Usable as a decorator."""
        address = (address or "").strip()
        if not address:
            raise ValueError("OSC address pattern must not be empty")
        with self._lock:
            if address == "*":
                self._catch_all.append(callback)
            else:
                self._handlers.append((address, callback, _compile_pattern(address)))
        return callback

    def off(self, address: Optional[str] = None, callback: Optional[Callback] = None) -> None:
        """Remove handlers. Both filters are optional (``off()`` clears all)."""
        with self._lock:
            if address == "*":
                if callback is None:
                    self._catch_all.clear()
                else:
                    self._catch_all = [c for c in self._catch_all if c is not callback]
                return
            self._handlers = [
                (addr, cb, rx)
                for addr, cb, rx in self._handlers
                if not ((address is None or addr == address)
                        and (callback is None or cb is callback))
            ]
            if address is None and callback is None:
                self._catch_all.clear()

    # ------------------------------------------------------------- dispatching
    def _handle(self, address: str, *args: Any) -> None:
        """Called on the socket thread for every incoming OSC message."""
        entry = {"address": address, "args": list(args), "time": time.time()}
        with self._lock:
            self.message_count += 1
            self.last_message = entry
            self._history.append(entry)
            matched = [(cb, rx) for _, cb, rx in self._handlers if rx.match(address)]
            catch_all = list(self._catch_all)

        for callback, _rx in matched:
            self._invoke(callback, address, args)
        for callback in catch_all:
            self._invoke(callback, address, args)

        if not matched and not catch_all and self.verbose:
            print(f"[OSC RX] {address} {list(args)}")

    def _invoke(self, callback: Callback, address: str, args: Tuple[Any, ...]) -> None:
        try:
            result = callback(address, *args)
        except Exception as exc:  # a bad handler must never kill the socket
            print(f"[OSC RX] handler error for {address}: {exc}")
            return
        if inspect.isawaitable(result):
            loop = self._loop
            if loop is not None and loop.is_running():
                asyncio.run_coroutine_threadsafe(result, loop)
            else:
                print(f"[OSC RX] async handler for {address} ignored (no event loop set)")
                close = getattr(result, "close", None)
                if callable(close):
                    close()

    # -------------------------------------------------------------- lifecycle
    def start(self) -> bool:
        """Bind the UDP socket and start serving. Returns False on bind failure."""
        if self.is_running:
            return True
        try:
            self._server = ThreadingOSCUDPServer(
                (self.host, self.port), self._dispatcher
            )
            self._server.daemon_threads = True
        except OSError as exc:
            self.last_error = str(exc)
            print(f"[OSC RX] failed to bind {self.host}:{self.port} — {exc}")
            self._server = None
            return False

        self._thread = threading.Thread(
            target=self._serve, name="osc-receiver", daemon=True
        )
        self._thread.start()
        self._ready.wait(timeout=2.0)
        self.started_at = time.time()
        if self.verbose:
            print(f"[OSC RX] listening on udp://{self.host}:{self.port}")
        return True

    def _serve(self) -> None:
        self._ready.set()
        server = self._server
        if server is None:
            return
        try:
            server.serve_forever(poll_interval=0.25)
        except Exception as exc:
            self.last_error = str(exc)
            print(f"[OSC RX] server stopped: {exc}")
        finally:
            self._ready.clear()

    def stop(self) -> None:
        """Shut the socket down and stop the thread."""
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        if server is not None:
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                pass
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        if self.verbose:
            print("[OSC RX] stopped")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------ reads
    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Most recent messages, oldest first."""
        with self._lock:
            items = list(self._history)
        return items[-max(1, int(limit)):]

    def status(self) -> Dict[str, Any]:
        with self._lock:
            count = self.message_count
            last = dict(self.last_message) if self.last_message else None
            patterns = sorted({addr for addr, _, _ in self._handlers})
            catch_all = len(self._catch_all)
        return {
            "running": self.is_running,
            "host": self.host,
            "port": self.port,
            "messages": count,
            "last": last,
            "patterns": patterns,
            "catch_all": catch_all,
            "started_at": self.started_at,
            "last_error": self.last_error,
        }


def from_config(config_module) -> OSCReceiver:
    """Build a receiver from an optional OSC_RECEIVE_* config block.

    Falls back to 0.0.0.0:9000 when the keys are absent, so this module can be
    wired into main.py before the config keys exist.
    """
    return OSCReceiver(
        host=getattr(config_module, "OSC_RECEIVE_IP", DEFAULT_HOST),
        port=getattr(config_module, "OSC_RECEIVE_PORT", DEFAULT_PORT),
        verbose=getattr(config_module, "OSC_RECEIVE_VERBOSE", True),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Standalone OSC receiver (debug)")
    parser.add_argument("--host", default=DEFAULT_HOST, help="bind address")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="bind UDP port")
    args = parser.parse_args()

    receiver = OSCReceiver(host=args.host, port=args.port)
    if not receiver.start():
        raise SystemExit(1)
    print("Printing every OSC message. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        receiver.stop()


if __name__ == "__main__":
    main()
