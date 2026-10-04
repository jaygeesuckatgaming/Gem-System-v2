"""
Game Agent - autonomous gameplay via vision + LLM + OSC.

Standalone experiment (does NOT touch the streaming system). It:
  1. Captures a frame from the vision service (NDI / camera).
  2. Sends the frame + a navigation prompt to the vision LLM (Gemma).
  3. Parses the LLM's decision into a movement command.
  4. Sends the command to Unreal via OSC (e.g. /agent/move, /agent/turn).

Run this separately from main.py (it only shares config + the vision service).
"""

import os
import sys
import time
import json
import re

import ollama

# Add project root so we can import config.py
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config

# ---------------------------------------------------------------------------
# OSC (same string+True format Unreal expects, mirroring main.py)
# ---------------------------------------------------------------------------
def send_osc(address: str, value: str) -> bool:
    from pythonosc import udp_client, osc_message_builder
    builder = osc_message_builder.OscMessageBuilder(address=address)
    builder.add_arg(str(value), builder.ARG_TYPE_STRING)
    builder.add_arg(True, builder.ARG_TYPE_TRUE)
    client = udp_client.SimpleUDPClient(config.OSC_IP, config.OSC_PORT)
    client.send(builder.build())
    print(f"OSC -> {address} = {value}")
    return True


# ---------------------------------------------------------------------------
# Vision (reuse the vision service over HTTP)
# ---------------------------------------------------------------------------
def get_frame_base64() -> str:
    """Fetch a base64 JPEG frame from the vision service."""
    import httpx
    try:
        r = httpx.get(config.VISION_GET_IMAGE_URL, timeout=15.0)
        if r.status_code == 200:
            return r.json().get("image_base64", "")
    except Exception as e:
        print(f"Vision fetch failed: {e}")
    return ""


# ---------------------------------------------------------------------------
# LLM (Gemma vision via Ollama)
# ---------------------------------------------------------------------------
client = ollama.Client(host=config.OLLAMA_BASE_URL)

SYSTEM_PROMPT = getattr(config, 'GAME_AGENT_SYSTEM_PROMPT', (
    "You are an AI agent controlling a character in a simple game. You see a "
    "screenshot of the game. Decide how to move and reply with EXACTLY one line "
    "in this format, no extra text:\n"
    "MOVE: <forward|back|stop>  TURN: <left|right|stop>\n"
    "Choose based on what would let the character walk around and avoid obstacles."
))
MOVE_ADDRESS = getattr(config, 'GAME_AGENT_MOVE_ADDRESS', '/agent/move')
TURN_ADDRESS = getattr(config, 'GAME_AGENT_TURN_ADDRESS', '/agent/turn')


def ask_vision(image_b64: str) -> str:
    """Send the frame + prompt to the vision LLM and return its decision."""
    try:
        response = client.chat(
            model=config.OLLAMA_MODEL,
            messages=[
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {
                    'role': 'user',
                    'content': 'What should the character do next?',
                    'images': [image_b64],
                },
            ],
        )
        return response['message']['content'].strip()
    except Exception as e:
        print(f"LLM error: {e}")
        return ""


def parse_decision(text: str):
    """Parse the LLM output into (move, turn). Returns None if not parseable."""
    move_match = re.search(r'MOVE:\s*(forward|back|stop)', text, re.IGNORECASE)
    turn_match = re.search(r'TURN:\s*(left|right|stop)', text, re.IGNORECASE)
    if not move_match and not turn_match:
        return None
    move = move_match.group(1).lower() if move_match else "stop"
    turn = turn_match.group(1).lower() if turn_match else "stop"
    return move, turn


# ---------------------------------------------------------------------------
# Main agent loop
# ---------------------------------------------------------------------------
def main():
    interval = float(getattr(config, 'GAME_AGENT_INTERVAL_S', 1.0))
    print("Game Agent starting. Ctrl+C to stop.")
    print(f"  model={config.OLLAMA_MODEL}  osc={config.OSC_IP}:{config.OSC_PORT}  interval={interval}s")

    while True:
        try:
            image_b64 = get_frame_base64()
            if not image_b64:
                print("No frame; stopping movement and retrying.")
                send_osc(MOVE_ADDRESS, "stop")
                send_osc(TURN_ADDRESS, "stop")
                time.sleep(interval)
                continue

            decision_text = ask_vision(image_b64)
            print(f"LLM: {decision_text}")

            decision = parse_decision(decision_text)
            if decision is None:
                print("Could not parse decision; stopping.")
                send_osc(MOVE_ADDRESS, "stop")
                send_osc(TURN_ADDRESS, "stop")
            else:
                move, turn = decision
                send_osc(MOVE_ADDRESS, move)
                send_osc(TURN_ADDRESS, turn)

            time.sleep(interval)

        except KeyboardInterrupt:
            print("\nStopping agent.")
            send_osc(MOVE_ADDRESS, "stop")
            send_osc(TURN_ADDRESS, "stop")
            break
        except Exception as e:
            print(f"Loop error: {e}")
            time.sleep(interval)


if __name__ == "__main__":
    main()
