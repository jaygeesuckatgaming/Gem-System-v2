"""The one local Whisper server, shared by Gem and the m8 companion.

A tiny stdlib HTTP server around faster-whisper, so a game (or a mic loop) can
turn a WAV into text without loading Whisper twice.

    GET  /health      -> {"ok": true, "model": "base.en", "route": "gem"}
    POST /route       -> {"route": "gem"|"m8"}   (live switch, no restart)
    POST /transcribe  -> raw WAV body; {"text": "...", "language": "en"}
    POST /v1/audio/transcriptions -> OpenAI-style multipart (what m8 sends)

One Whisper model serves both consumers, but only the routed one receives
transcripts. config.py's MIC_ROUTE says who that is:
    "gem" -> Gem's mic listener (clients/listen.py) gets the text; m8 gets ""
    "m8"  -> the m8 adapter gets the text; Gem's listener gets ""

The caller is identified by the `X-Mic-Client` header (Gem's listener sends
`gem`), falling back to the multipart `model` field (`gem`/`m8`), and otherwise
treated as m8 — m8 is the only other client and sends `model=whisper-1`.

Run it in mcp_env_2 (faster-whisper lives there):

    conda run -n mcp_env_2 python clients/whisper_server.py

or start_scripts/start_whisper_server.bat. Port 13310 by default; override
with WHISPER_PORT, and the model with WHISPER_MODEL (otherwise config.py's
STT_WHISPER_MODEL).
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from faster_whisper import WhisperModel

try:
    import config as app_config
except Exception:
    app_config = None

try:
    from config import STT_WHISPER_MODEL as CONFIG_MODEL
except Exception:
    CONFIG_MODEL = "base.en"

HOST = os.environ.get("WHISPER_HOST", "127.0.0.1")
PORT = int(os.environ.get("WHISPER_PORT", "13310"))
MODEL_NAME = os.environ.get("WHISPER_MODEL", CONFIG_MODEL or "base.en")
MAXIMUM_BODY = 32 * 1024 * 1024  # a long push-to-talk clip

print(f"[whisper] loading {MODEL_NAME} (device auto, int8)...", flush=True)
model = WhisperModel(MODEL_NAME, device="auto", compute_type="int8")
print(f"[whisper] ready on http://{HOST}:{PORT}", flush=True)

transcribe_lock = threading.Lock()

# Set by POST /route; wins over config.py until the next restart. The panel
# writes config.py too, so a restart comes back to the same place.
_route_override: str | None = None


def current_route() -> str:
    if _route_override in ("gem", "m8"):
        return _route_override
    value = str(getattr(app_config, "MIC_ROUTE", "gem") or "gem").strip().lower()
    return value if value in ("gem", "m8") else "gem"


def client_of(header_value: str | None, model_field: str | None) -> str:
    """Which consumer sent this request. Untagged means m8."""
    for value in (header_value, model_field):
        value = str(value or "").strip().lower()
        if value in ("gem", "m8"):
            return value
    return "m8"



def transcribe_wav(data: bytes) -> dict:
    """Transcribe one WAV body. faster-whisper is happiest with a file path."""
    handle, path = tempfile.mkstemp(prefix="opence-", suffix=".wav")
    try:
        with os.fdopen(handle, "wb") as output:
            output.write(data)
        with transcribe_lock:
            segments, info = model.transcribe(
                path,
                language="en",
                beam_size=5,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 350},
            )
            text = " ".join(segment.text.strip() for segment in segments).strip()
        return {
            "text": text,
            "language": getattr(info, "language", "en"),
            "duration": getattr(info, "duration", None),
        }
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


class Handler(BaseHTTPRequestHandler):
    server_version = "OpenCEWhisper/1.0"

    def log_message(self, fmt, *args):
        print(f"[whisper] {self.address_string()} {fmt % args}", flush=True)

    def _send(self, status: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path.rstrip("/") in ("/health", ""):
            self._send(200, {
                "ok": True,
                "model": MODEL_NAME,
                "route": current_route(),
            })
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        global _route_override
        path = self.path.rstrip("/")

        if path == "/route":
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            body = self.rfile.read(length) if 0 < length <= 4096 else b"{}"
            try:
                wanted = str(json.loads(body or b"{}").get("route", "")).strip().lower()
            except (ValueError, AttributeError):
                wanted = ""
            if wanted not in ("gem", "m8"):
                self._send(400, {"error": "route must be 'gem' or 'm8'"})
                return
            _route_override = wanted
            print(f"[whisper] mic route -> {wanted}", flush=True)
            self._send(200, {"ok": True, "route": wanted})
            return

        if path not in ("/transcribe", "/v1/audio/transcriptions"):
            self._send(404, {"error": "not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            self._send(400, {"error": "empty body"})
            return
        if length > MAXIMUM_BODY:
            self._send(413, {"error": "audio too long"})
            return

        data = self.rfile.read(length)
        model_field = None
        # Accept a raw WAV (/transcribe) or an OpenAI-style multipart upload
        # (/v1/audio/transcriptions), whose `file` part is the WAV.
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" in content_type:
            message = BytesParser(policy=default).parsebytes(
                f"Content-Type: {content_type}\r\n\r\n".encode("latin-1") + data
            )
            audio = b""
            if message.is_multipart():
                for part in message.iter_parts():
                    name = part.get_param("name", header="content-disposition")
                    if name == "file":
                        audio = part.get_payload(decode=True) or b""
                    elif name == "model":
                        payload = part.get_payload(decode=True) or b""
                        model_field = payload.decode("utf-8", "ignore")
            data = audio

        client = client_of(self.headers.get("X-Mic-Client"), model_field)
        route = current_route()
        if client != route:
            # The other consumer gets silence: no temp file, no Whisper run.
            self._send(200, {
                "text": "",
                "language": "en",
                "skipped": True,
                "route": route,
                "client": client,
            })
            return

        if not data.startswith(b"RIFF"):
            self._send(400, {"error": "expected a WAV body"})
            return

        try:
            self._send(200, transcribe_wav(data))
        except Exception as exc:
            print(f"[whisper] transcription failed: {exc}", flush=True)
            self._send(500, {"error": str(exc)})


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"[whisper] listening on http://{HOST}:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
