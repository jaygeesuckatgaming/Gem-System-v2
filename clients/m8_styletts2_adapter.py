"""Breeze-compatible TTS adapter in front of StyleTTS2 for m8.

m8's `Voice::stream` speaks Breeze TTS 2's API:
  GET  /health            -> {"sample_rate": 24000}
  POST /v1/audio/speech   -> multipart (text, instruction, ref_audio, ...)
                             and the reply is RAW 16-bit little-endian mono PCM.

StyleTTS2 speaks its own `POST /tts` JSON API and returns a WAV. This adapter
takes m8's request, calls StyleTTS2, strips the WAV header and returns the PCM
m8 expects. The reference clip m8 sends is ignored (StyleTTS2 uses the voice
its server was started with).

Run in mcp_env_2 (stdlib only):
    python clients/m8_styletts2_adapter.py
Port 8091 by default; STYLE_TTS_URL overrides the StyleTTS2 endpoint.
"""

from __future__ import annotations

import json
import os
import re
import struct
import threading
import urllib.error
import urllib.request
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STYLE_TTS_URL = os.environ.get("STYLE_TTS_URL", "http://127.0.0.1:13300/tts")
HOST = os.environ.get("M8_TTS_HOST", "127.0.0.1")
PORT = int(os.environ.get("M8_TTS_PORT", "8091"))
SAMPLE_RATE = 24000
MAXIMUM_BODY = 16 * 1024 * 1024

speak_lock = threading.Lock()


def multipart_fields(body: bytes, content_type: str) -> dict:
    """Reads the text fields m8's multipart carries (the reference audio is skipped)."""
    message = BytesParser(policy=default).parsebytes(
        f"Content-Type: {content_type}\r\n\r\n".encode("latin-1") + body
    )
    fields = {}
    if not message.is_multipart():
        return fields
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name or name == "ref_audio":
            continue
        payload = part.get_payload(decode=True) or b""
        fields[name] = payload.decode("utf-8", "replace")
    return fields


def clean_text(text: str) -> str:
    # StyleTTS2 reads brackets and asterisks; m8 already passes delivery notes
    # separately, so anything left is noise.
    text = re.sub(r"\[[^\]]*\]", " ", text)
    text = text.replace("*", " ").replace("_", " ")
    return re.sub(r"\s+", " ", text).strip()


def wav_pcm(wav: bytes) -> tuple[bytes, int]:
    """Returns (PCM bytes, sample rate) from a RIFF/WAVE file."""
    if len(wav) < 12 or wav[:4] != b"RIFF" or wav[8:12] != b"WAVE":
        raise ValueError("StyleTTS2 did not return a WAV")
    rate = SAMPLE_RATE
    offset = 12
    while offset + 8 <= len(wav):
        kind = wav[offset:offset + 4]
        size = struct.unpack("<I", wav[offset + 4:offset + 8])[0]
        body = wav[offset + 8:offset + 8 + size]
        if kind == b"fmt " and len(body) >= 16:
            rate = struct.unpack("<I", body[4:8])[0]
        elif kind == b"data":
            return body, rate
        offset += 8 + size + (size & 1)
    raise ValueError("StyleTTS2's WAV has no data chunk")


def synth(text: str) -> tuple[bytes, int]:
    request = urllib.request.Request(
        STYLE_TTS_URL,
        data=json.dumps({"chatmessage": text, "text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        wav = response.read()
    return wav_pcm(wav)


class Handler(BaseHTTPRequestHandler):
    server_version = "m8StyleTTS2/1.0"

    def log_message(self, fmt, *args):
        print(f"[tts-adapter] {self.address_string()} {fmt % args}", flush=True)

    def _json(self, status: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/") in ("/health", ""):
            self._json(200, {"ok": True, "sample_rate": SAMPLE_RATE})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path.rstrip("/") != "/v1/audio/speech":
            self._json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            self._json(400, {"error": "empty body"})
            return
        if length > MAXIMUM_BODY:
            self._json(413, {"error": "request too large"})
            return

        body = self.rfile.read(length)
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self._json(400, {"error": "expected multipart/form-data"})
            return

        fields = multipart_fields(body, content_type)
        text = clean_text(fields.get("text", ""))
        if not text:
            self._json(400, {"error": "no text"})
            return

        try:
            with speak_lock:
                pcm, rate = synth(text)
        except urllib.error.HTTPError as exc:
            self._json(502, {"error": f"StyleTTS2 HTTP {exc.code}"})
            return
        except Exception as exc:
            print(f"[tts-adapter] synthesis failed: {exc}", flush=True)
            self._json(502, {"error": str(exc)})
            return

        self.send_response(200)
        self.send_header("Content-Type", f"audio/L16; rate={rate}; channels=1")
        self.send_header("Content-Length", str(len(pcm)))
        self.end_headers()
        self.wfile.write(pcm)


if __name__ == "__main__":
    print(f"[tts-adapter] StyleTTS2 {STYLE_TTS_URL} -> http://{HOST}:{PORT}", flush=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
