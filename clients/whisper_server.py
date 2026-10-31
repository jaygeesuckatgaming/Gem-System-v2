"""Local Whisper transcription server for the OpenCE bridge.

A tiny stdlib HTTP server around faster-whisper, so the game can turn a push-
to-talk WAV into text without pulling Whisper into the C process.

    GET  /health      -> {"ok": true, "model": "base.en"}
    POST /transcribe  -> raw WAV body; {"text": "...", "language": "en"}

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
            self._send(200, {"ok": True, "model": MODEL_NAME})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path.rstrip("/") not in ("/transcribe", "/v1/audio/transcriptions"):
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
                    if part.get_param("name", header="content-disposition") == "file":
                        audio = part.get_payload(decode=True) or b""
                        break
            data = audio
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
