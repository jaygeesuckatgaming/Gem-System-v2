"""
Gem's Halo brain - the LLM commander for the native AI co-op player.

The OpenCE bot (port/linux/game/ai_player.c, the "ai-player" branch) writes
ai_state.json every 100 ms and reads ai_goal.json. This process is the missing
brain layer: it reads the state, asks the configured Ollama model for an order
(follow / engage / hold / retreat / regroup / idle), and writes the goal. The
bot does the aiming and firing at 30 Hz; the LLM decides intent, exactly as
chasm's action book gave whitelisted orders to an NPC.

Run with start_scripts/start_halo_brain.bat (mcp_env_2, which has `ollama`).
"""

import http.server
import json
import os
import re
import sys
import threading
import time

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config

try:
    import ollama
except ImportError:  # pragma: no cover - the bat picks an env with it
    ollama = None

# ---------------------------------------------------------------------------
# Where the game writes/reads. Defaults match opence-gem; override with env.
# ---------------------------------------------------------------------------
GAME_CONFIG = os.environ.get(
    "GEM_AI_CONFIG", r"C:\Users\jayge\Documents\AI\opence-gem\config.toml"
)


def _toml_string(path, key, default):
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return default
    match = re.search(r'^\s*' + re.escape(key) + r'\s*=\s*"([^"]*)"', text, re.M)
    return match.group(1) if match else default


STATE_PATH = os.environ.get(
    "GEM_AI_STATE", _toml_string(GAME_CONFIG, "state_path", "ai_state.json")
)
GOAL_PATH = os.environ.get(
    "GEM_AI_GOAL", _toml_string(GAME_CONFIG, "goal_path", "ai_goal.json")
)
# the game's "gembot follow" console command leaves an order here
ORDER_PATH = os.path.join(os.path.dirname(GOAL_PATH) or ".", "ai_order.json")


def _sibling_order_path(path):
    """The other instance's order file: the console command may be typed into
    either window, and each writes beside its own goal."""
    if "opence-gem" in path:
        return path.replace("opence-gem", "opence-human", 1)
    return None


ORDER_PATHS = [ORDER_PATH]
_sibling = _sibling_order_path(ORDER_PATH)
if _sibling:
    ORDER_PATHS.append(_sibling)
ORDER_PATHS += [p for p in os.environ.get("HALO_BRAIN_ORDERS", "").split(os.pathsep) if p]

MODEL = (
    os.environ.get("HALO_BRAIN_MODEL")
    or getattr(config, "HALO_BRAIN_MODEL", "")
    or "gemma3:4b-it-qat"
)
BASE_URL = (
    os.environ.get("HALO_BRAIN_OLLAMA")
    or getattr(config, "OLLAMA_BASE_URL", "http://localhost:11434")
)

MODES = ("follow", "engage", "hold", "retreat", "regroup", "idle")
# the bot holds its ground unless the player asks it to come along
FALLBACK = "hold"
# how old a state file may be before the brain stops writing goals, seconds
STATE_FRESH_S = 1.0
# how often the goal is refreshed (the bot treats it as stale after 2 s)
WRITE_INTERVAL_S = 0.25
# how often the LLM is asked (slow models just make this longer in practice)
DECIDE_INTERVAL_S = 1.0

SYSTEM_PROMPT = """You are Gem, an AI co-op player in Halo: Combat Evolved.
You are the commander: you choose ONE order, and your body does the aiming and
firing. You cannot see the screen; use the state given.

Orders:
- hold: stay where you are and fight what you see (the default)
- engage: advance on the enemies and fight them
- follow: come along with the other player, do not fight
- retreat: fall back to the other player, still firing
- regroup: run to the other player, do not fight
- idle: stand still

Rules:
- follow ONLY when the player explicitly asks you to come along ("follow me",
  "come with me", "stick with me"). Never choose follow on your own.
- otherwise hold, or engage when there are enemies to close with
- body health (health) below 0.35: retreat or regroup
- shields recharge on their own: do not retreat for low shields alone
- enemies nearby and ammunition left: engage
- no enemies: hold
- no ammunition and enemies near: retreat
Keep orders stable unless something changes.

Reply with JSON only, exactly:
{"mode": "follow|engage|hold|retreat|regroup|idle", "say": "short line or empty"}"""

_lock = threading.Lock()
_latest = {"mode": FALLBACK, "say": "", "source": "start"}
_directive = {"mode": None, "until": 0.0}

# what a player says, and the order it gives: a human co-op player hears these
ORDER_WORDS = (
    ("follow", ("follow me", "follow", "come with", "stick with", "with me",
                "come along", "escort me")),
    ("hold", ("hold", "stay", "stop", "wait here", "don't move", "dont move",
              "guard", "cover me")),
    ("engage", ("attack", "engage", "go get", "kill", "take them", "open fire",
                "fight them", "push up")),
    ("retreat", ("retreat", "fall back", "pull back", "run away", "get back")),
    ("regroup", ("regroup", "come back", "return to me", "back to me")),
    ("idle", ("idle", "stand still", "do nothing")),
)

COMMAND_PORT = int(os.environ.get("HALO_BRAIN_PORT", "8095"))


def classify_order(text):
    lowered = (text or "").strip().lower()
    if not lowered:
        return None
    for mode, phrases in ORDER_WORDS:
        for phrase in phrases:
            if phrase in lowered:
                return mode
    return None


def set_directive(mode, seconds=0.0):
    """A player's spoken or typed order: it lasts until another order (or the
    optional seconds), as a human would keep doing what was asked. The order
    takes effect at once, not at the next decision tick."""
    until = time.time() + seconds if seconds > 0 else float("inf")
    with _lock:
        _directive["mode"] = mode
        _directive["until"] = until
        _latest["mode"] = mode
        _latest["say"] = ""
        _latest["source"] = "order"
    print(f"[order] {mode}", flush=True)


def directive_mode():
    with _lock:
        mode = _directive["mode"]
        until = _directive["until"]
    if mode is not None and time.time() < until:
        return mode
    return None


class _OrderHandler(http.server.BaseHTTPRequestHandler):
    def _reply(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._reply({"ok": True, "order": directive_mode()})
        else:
            self._reply({"ok": False, "error": "not found"}, 404)

    def do_POST(self):
        if self.path != "/command":
            self._reply({"ok": False, "error": "not found"}, 404)
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(body or b"{}")
        except ValueError:
            data = {}
        mode = str(data.get("mode", "")).strip().lower()
        if mode not in MODES:
            mode = classify_order(data.get("text", ""))
        if mode not in MODES:
            self._reply({"ok": False, "error": "no order in that"}, 400)
            return
        set_directive(mode, float(data.get("seconds", 0) or 0))
        self._reply({"ok": True, "mode": mode})

    def log_message(self, format, *args):
        pass


def start_commands():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", COMMAND_PORT), _OrderHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"  orders: POST http://127.0.0.1:{COMMAND_PORT}/command "
          '{"text":"follow me"}', flush=True)


def read_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as handle:
            state = json.load(handle)
        return state, os.path.getmtime(STATE_PATH)
    except (OSError, ValueError):
        return None, 0.0


def state_fresh(mtime):
    return mtime > 0.0 and (time.time() - mtime) <= STATE_FRESH_S


def bot_clock(state):
    """Map the wall clock onto the bot's uptime clock (system_milliseconds)."""
    now_ms = int(time.time() * 1000)
    offset = now_ms - int(state.get("time_ms", now_ms))
    return now_ms - offset


def describe(state):
    return (
        "health {health:.2f} (body), shields {shields:.2f};"
        " ammo {loaded}/{total}; enemies within 60 m: {count}"
        " (nearest {nearest:.1f} m); other player {distance:.1f} m away;"
        " current order: {goal}".format(
            health=float(state.get("health", 1.0)),
            shields=float(state.get("shields", 0.0)),
            loaded=int(state.get("ammo_loaded", 0)),
            total=int(state.get("ammo_total", 0)),
            count=int(state.get("enemy_count", 0)),
            nearest=float(state.get("nearest_enemy", 0.0)),
            distance=float(state.get("distance", 0.0)),
            goal=state.get("goal", "none"),
        )
    )


def rule_decision(state):
    """What to do when the model is unavailable or returns nonsense."""
    health = float(state.get("health", 1.0))
    enemies = int(state.get("enemy_count", 0))
    ammo = int(state.get("ammo_loaded", 0)) + int(state.get("ammo_total", 0))
    if health < 0.35:
        return "retreat"
    if enemies > 0:
        return "engage" if ammo > 0 else "retreat"
    return "hold"


def parse_reply(text):
    data = {}
    try:
        data = json.loads(text)
    except ValueError:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                data = json.loads(match.group(0))
            except ValueError:
                data = {}
    mode = str(data.get("mode", "")).strip().lower()
    if mode not in MODES:
        mode = None
    say = str(data.get("say", "")).strip()[:200]
    return mode, say


def ask_model(state):
    if ollama is None:
        return None, ""
    client = ollama.Client(host=BASE_URL)
    try:
        response = client.chat(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": describe(state)},
            ],
            format="json",
            options={"temperature": 0.4},
        )
        return parse_reply(response["message"]["content"])
    except Exception as error:  # noqa: BLE001 - any failure falls back
        print(f"[brain] model error: {error}", flush=True)
        return None, ""


def decide_loop():
    while True:
        state, mtime = read_state()
        if state is None or not state_fresh(mtime):
            time.sleep(DECIDE_INTERVAL_S)
            continue

        # a player's order outranks the model's own judgement
        mode = directive_mode()
        say = ""
        source = "order"
        if mode is None:
            model_mode, model_say = ask_model(state)
            # an order may have arrived while the model was thinking: it wins
            mode = directive_mode()
            if mode is not None:
                say = ""
                source = "order"
            else:
                mode = model_mode
                say = model_say
                source = "model"
                if mode is None:
                    mode = rule_decision(state)
                    say = ""
                    source = "rules"
                # a human co-op player comes along when asked, not on its own
                if mode == "follow":
                    mode = "hold"
                    say = ""
                    source = "hold"

        with _lock:
            changed = mode != _latest["mode"]
            _latest.update({"mode": mode, "say": say, "source": source})
            spoken = say

        if changed:
            print(f"[brain] {mode} ({source}) {spoken}".rstrip(), flush=True)
        time.sleep(DECIDE_INTERVAL_S)


def order_loop():
    """The game's console writes ai_order.json ("gembot follow"): apply it at
    once, then remove it so it is not applied again. Either instance's file
    is watched, whichever window the command was typed into."""
    while True:
        for path in ORDER_PATHS:
            try:
                with open(path, encoding="utf-8") as handle:
                    data = json.load(handle)
            except (OSError, ValueError):
                continue
            mode = str(data.get("mode", "")).strip().lower()
            if mode in MODES:
                set_directive(mode)
            try:
                os.remove(path)
            except OSError:
                pass
        time.sleep(0.2)


def write_loop():
    while True:
        state, mtime = read_state()
        if state is not None and state_fresh(mtime):
            with _lock:
                mode = _latest["mode"]
                say = _latest["say"]
            goal = {
                "version": 1,
                "time_ms": bot_clock(state),
                "mode": mode,
                "say": say,
            }
            try:
                temporary = GOAL_PATH + ".tmp"
                with open(temporary, "w", encoding="utf-8") as handle:
                    json.dump(goal, handle)
                os.replace(temporary, GOAL_PATH)
            except OSError:
                # the game may be reading it; try a direct write next tick
                try:
                    with open(GOAL_PATH, "w", encoding="utf-8") as handle:
                        json.dump(goal, handle)
                except OSError:
                    pass
        time.sleep(WRITE_INTERVAL_S)


def main():
    print("Gem Halo brain")
    print(f"  state: {STATE_PATH}")
    print(f"  goal:  {GOAL_PATH}")
    print(f"  order: {', '.join(ORDER_PATHS)}")
    print(f"  model: {MODEL} at {BASE_URL}")
    print("  orders: " + ", ".join(MODES))
    start_commands()
    threading.Thread(target=decide_loop, daemon=True).start()
    threading.Thread(target=order_loop, daemon=True).start()
    try:
        write_loop()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
