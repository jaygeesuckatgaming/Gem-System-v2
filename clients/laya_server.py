"""
Laya Fast-Lane Pre-Filter Server

Sits between Social Stream Ninja and the main Gem-System v2 server (main.py).

Receives every chat message and runs the local Laya model to:
  1. Classify an animation/body cue and send it DIRECTLY to Unreal via OSC
     (the "fast lane" — one cheap forward pass, no LLM delay).
  2. Decide whether the message warrants a full reply ("slow lane" gate).

Only approved messages are forwarded to main.py's /chat endpoint; the rest are
dropped (but still trigger a body cue).

Run with the 'laya' conda env's Python (see start_scripts/start_laya.bat).
Binds port 5002 (separate from main.py's 5000).
"""

import os
os.environ["USE_TF"] = "0"

import sys
import io
# Add the project root to sys.path so `import config` works when run directly
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Force UTF-8 stdout/stderr to avoid UnicodeEncodeError on Windows (cp1252 console)
if sys.stdout and hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from quart import Quart, request, jsonify
from pythonosc import udp_client, osc_message_builder
import httpx

import config

app = Quart(__name__)

# ---------------------------------------------------------------------------
# Laya model (lazy load — loaded once on first request)
# ---------------------------------------------------------------------------
MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "models", "laya")

_laya_agent = None


def _load_laya():
    """Load the Laya model once. Returns None if unavailable (graceful degradation)."""
    global _laya_agent
    if _laya_agent is None:
        try:
            import laya as laya_lib  # noqa: F401 - external library
            if os.path.isdir(MODEL_PATH):
                _laya_agent = laya_lib.load(MODEL_PATH)
                print(f"Laya model loaded from {MODEL_PATH}")
            else:
                _laya_agent = laya_lib.load("convaiinnovations/laya")
                print("Laya model loaded from default registry")
        except ImportError:
            print("'laya' package not installed - running without Laya classification")
        except Exception as e:
            print(f"Failed to load Laya: {e}")
    return _laya_agent


# ---------------------------------------------------------------------------
# OSC (fast-lane body cues)
# ---------------------------------------------------------------------------
def _send_osc(address: str, value: str) -> bool:
    """Send an OSC message using config's IP/port and the string+True format."""
    if not address:
        print(f"OSC skipped: empty address (value='{value}')")
        return False
    try:
        builder = osc_message_builder.OscMessageBuilder(address=address)
        builder.add_arg(str(value), builder.ARG_TYPE_STRING)
        builder.add_arg(True, builder.ARG_TYPE_TRUE)
        client = udp_client.SimpleUDPClient(config.OSC_IP, config.OSC_PORT)
        client.send(builder.build())
        return True
    except Exception as e:
        print(f"Laya OSC failed: {e}")
        return False


def _resolve_animation_osc(animation: str):
    """Return (address, value) for an animation, using the animation map if present."""
    for entry in getattr(config, 'LAYA_ANIMATION_MAP', []) or []:
        if entry.get('animation', '').lower() == animation.lower():
            return entry.get('address', config.LAYA_OSC_ADDRESS), entry.get('value', animation)
    return config.LAYA_OSC_ADDRESS, animation


# ---------------------------------------------------------------------------
# Chat endpoint (receives from Social Stream Ninja)
# ---------------------------------------------------------------------------
@app.route("/chat", methods=["POST"])
async def handle_chat():
    payload = await request.get_json()
    if not payload:
        return jsonify({"status": "ignored", "reason": "no payload"}), 400

    chat_message = payload.get("chatmessage", "") or payload.get("chat", "")
    chatter_name = payload.get("chatname", "Viewer") or payload.get("name", "Viewer")

    if not chat_message:
        return jsonify({"status": "ignored"}), 200

    laya_agent = _load_laya()

    # If Laya isn't available (or disabled), pass everything through unfiltered
    if laya_agent is None or not config.LAYA_ENABLED:
        await _forward_to_main(chatter_name, chat_message)
        return jsonify({"status": "processed", "gated": False}), 200

    questions = {
        "animation": {
            "type": "choice",
            "instructions": "Which streaming interaction best fits the vibe or context of this message?",
            "criteria": {opt: opt for opt in config.LAYA_ANIMATION_OPTIONS}
        },
        "should_reply": {
            "type": "noul",
            "instructions": "Is this message directly engaging, asking a question, or talking directly to the stream host?"
        }
    }

    try:
        result = laya_agent.predict({"text": chat_message}, questions)
        answers = result["answers"]
    except Exception as e:
        print(f"Laya predict error: {e}", flush=True)
        await _forward_to_main(chatter_name, chat_message)
        return jsonify({"status": "processed", "gated": False}), 200

    # --- FAST LANE: body cue -> OSC (sent directly, no LLM) ---
    animation = answers["animation"].get("choice", "idle")
    anim_confidence = answers["animation"].get("answer_confidence",
                                              answers["animation"].get("confidence", 0.0))

    if anim_confidence > config.LAYA_ANIMATION_THRESHOLD:
        addr, val = _resolve_animation_osc(animation)
        _send_osc(addr, val)
        print(f"OSC Sent: {animation} ({anim_confidence:.2f} confidence)", flush=True)

    # --- SLOW LANE: reply gating -> forward to main.py ---
    reply_probability = answers["should_reply"].get("noul", 0.0)

    # Messages that explicitly address Gem (or the wake words) always pass through
    addressed_to_gem = any(
        w in chat_message.lower()
        for w in getattr(config, 'WAKE_WORDS', []) + ['gem', 'gemma']
    )

    if addressed_to_gem or reply_probability > config.LAYA_REPLY_THRESHOLD:
        if addressed_to_gem:
            print(f"Addressed to Gem - forwarding (P={reply_probability:.2f}).", flush=True)
        else:
            print(f"Filter approved (P={reply_probability:.2f}). Forwarding to main server.", flush=True)
        await _forward_to_main(chatter_name, chat_message)
    else:
        print(f"Dropped noise (P={reply_probability:.2f}).", flush=True)

    return jsonify({"status": "processed"}), 200


async def _forward_to_main(chatter_name: str, chat_message: str):
    """Forward an approved message to the main server's /chat endpoint."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                config.LAYA_URL,
                json={"chatmessage": chat_message, "chatname": chatter_name}
            )
            print(f"Forward to main server: HTTP {resp.status_code}", flush=True)
    except Exception as e:
        print(f"Forward to main server failed: {type(e).__name__}: {e}", flush=True)


@app.route("/health", methods=["GET"])
async def health():
    return jsonify({
        "status": "ok",
        "laya_loaded": _laya_agent is not None,
        "enabled": config.LAYA_ENABLED
    })


if __name__ == "__main__":
    # Load the model eagerly at startup so the user sees a clear confirmation
    print("Loading Laya model...", flush=True)
    _load_laya()
    if _laya_agent is not None:
        print("Laya model ready.", flush=True)
    else:
        print("WARNING: Laya model failed to load - messages will pass through unfiltered.", flush=True)

    # Binds a separate port to avoid clashing with the main server (5000)
    app.run(host="127.0.0.1", port=5002)
