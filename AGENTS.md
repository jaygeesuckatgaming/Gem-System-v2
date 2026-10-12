# AGENTS.md — Guide for AI Coding Assistants

You are working on **Gem-System v2**, a Windows-based AI VTuber livestreaming platform.
"Gem" is an animated avatar in Unreal Engine that chats with viewers on Twitch/YouTube/Discord,
speaks via TTS, plays and generates music, browses the web, watches its own stream via
OpenCV face recognition, and remembers past conversations.

Last verified: 2026-10-12. All `file:line` references are as of this date — re-verify against
code before relying on them, and **update them (and the docs below) whenever you change
behavior**.

## The 30-second mental model

`main.py` is the hub — a Quart async server on **port 5000** (the "MCP server"). Everything else is
either an HTTP client wired into it, or a separate local process it talks to:

```
Chat platforms → Social Stream Ninja (SSN)
    → [optional Laya pre-filter :5002] → POST /chat (main.py :5000)
    → guards → wake-word gate → intent interceptors → Ollama LLM
    → send_response() → TTS server → WAV file → AudioPlayer / watcher_to_face
    → Unreal avatar (OSC commands + LiveLink blendshapes) → chat reply (SSN outbound)

vision.py (:5001) watches the OBS output (NDI) → face recognition (YuNet+SFace)
    → appeared-events POST /api/face_event → greeting + memory + LLM context
```

## Documentation index (read the one matching your task)

| Doc | Answers |
|---|---|
| [Docs/MESSAGE-PIPELINE.md](Docs/MESSAGE-PIPELINE.md) | "What happens to a chat message, in what order?" — intake paths, guards, wake words, interceptor chain, LLM path, response broadcast, audio/animation timing |
| [Docs/COMMANDS.md](Docs/COMMANDS.md) | "What does phrase X trigger?" — every trigger pattern → intent → handler → action |
| [Docs/ARCHITECTURE.md](Docs/ARCHITECTURE.md) | "What process is that, on what port?" — full process/service map, state files, startup/shutdown order |
| [Docs/SUBSYSTEMS.md](Docs/SUBSYSTEMS.md) | "How does subsystem X work?" — per-subsystem reference (LLM, TTS, music, memory, vision+faces, Twitch, browser, idle, Laya, Neurosync, GUI) |
| [FOLDER_TREE.md](FOLDER_TREE.md) | Directory layout |

## Critical facts

- **`config.py` is the single source of truth** for ALL settings (gitignored; template:
  `config_example.py`). Every process reads it. Runtime changes are **written back into
  `config.py` by regex rewriting** in `save_config()` (main.py:460) — never edit settings any
  other way, and never hand-edit a value the GUI owns without expecting it to be overwritten.
- **`main.py` (2,847 lines)** holds the message pipeline (~main.py:1100-1564), all HTTP
  endpoints, OSC helpers, and persistence. The one giant function to know is
  `handle_incoming_message()` (main.py:1100).
- **Interceptor-first design**: most intents (music, countdown, time, weather, OpenCode, URLs,
  vision, "who do you see") are handled by phrase matching *before* the LLM. The LLM only
  handles conversation plus two tool calls: `trigger_animation` and `browse_web`
  (main.py:1520-1545).
- **`gui.py` (3,866 lines)** is the control panel: it launches every service via
  `start_scripts/*.bat` (each in its own conda env, own console window) and edits settings via
  `POST /api/settings` → `save_config()`.
- **Face recognition lives in vision.py** (not main.py): a scan thread every 5s matches faces
  against `models/faces/enrolled/` (SFace embeddings, threshold 0.363) and pushes
  appearance events to main.py `/api/face_event`, which handles greetings (throttled) and
  memory. Enroll people via the GUI Vision tab or by dropping `<name>.jpg` into
  `models/faces/photos/`. `models/` is gitignored — enrollments never enter the repo.
- **`Docs/` + this file are the system documentation.** Keep them accurate when you change
  behavior — they are how future AI sessions (and the maintainer) get an overview.

## Top gotchas (things that will surprise you)

1. **"jim" is rewritten to "Gem"** in every incoming message before processing (main.py:1112) —
   an alternate wake name, not a bug.
2. **Wake-word gate**: messages that don't contain a wake word (default `["gem", "hey gem",
   "ok gem"]`, config.py `WAKE_WORDS`) are silently dropped (main.py:1137-1144). Interceptor
   extractors also strip the wake-word prefix themselves (e.g. main.py:659).
3. **Echo guards**: messages from speakers `gem`/`gem_chadee`/`gem-chadee` are ignored, and any
   incoming message identical to one of the last 10 AI responses is ignored (main.py:1122-1131).
4. **Talk animation + music ducking are owned by `watcher_to_face`** (Neurosync process), NOT
   main.py — it watches the TTS output WAV file. main.py only sends OSC `type_1` + the WAV
   duration after sending to chat (main.py:169-180, 234-244).
5. **TTS output is a single overwritten file** (`tts_output/server_output.wav`,
   `TTS_OUTPUT_PATH`) shared by consumers (AudioPlayer, watcher_to_face, network-share copy).
   Countdowns chunk TTS calls with delays for exactly this reason (main.py:1313-1320), and
   face greetings are gap-limited (20s) + skipped while TTS plays so they never collide.
6. **StyleTTS2 requires numbers spelled as words** (digits cause 500 errors) — hence
   `_number_to_words()` (main.py:912).
7. **`config.py` is rewritten in place** by `save_config()` using regex, including multiline
   `SYSTEM_PROMPT`, `OSC_ACTIONS`, and `LAYA_*` structures (main.py:578-631). If you add a new
   setting, add it to both `config_example.py` AND the `settings` dict in `save_config()` if the
   GUI should persist it.
8. **Hardcoded locale bias**: current time is always injected in `Asia/Bangkok` (main.py:1490);
   time/weather locations default to Pattaya; city→timezone is a hardcoded dict (main.py:976).
9. **Fire-and-forget intake endpoints**: `POST /chat` (main.py:2718) and
   `POST /api/face_event` (main.py:2709) return 200 immediately; the whole LLM+TTS pipeline
   runs as a detached task. Don't await them expecting a response payload.
10. **Two ways settings mutate live clients**: `POST /api/settings` (main.py:1905) both rewrites
    `config.py` AND updates live client objects in one handler (~70 keys). Read its code before
    assuming a restart is needed after a settings change.
11. **Face recognition watches the OBS output** (NDI "OBS Mixxx"). If Gem's own avatar face is
    visible in the stream, enroll it too — otherwise it triggers endless "unknown person"
    reports. Face events are flicker-safe (10s grace) and absence-gated (120s) before
    re-reporting.

## Testing / verification

- `test_ollama.py` — smoke test: can the configured Ollama model chat?
- `test_ssn_relay.py` — integration test for the local SSN WebSocket relay.
- No formal test suite. Manual verification: start services from `gui.py` (auto-starts main.py),
  then `GET http://127.0.0.1:5000/health`, `GET /api/status`, or `POST /api/tts` with
  `{"text": "hello"}` to exercise the full speak pipeline.
- Face recognition: start vision.py (with OBS output via NDI), then `GET
  http://127.0.0.1:5001/faces/current`, enroll via `POST /api/vision/faces/enroll`
  `{"name": "..."}` (exactly one face on camera), drop a `<name>.jpg` into
  `models/faces/photos/` + `POST /api/vision/faces/refresh`.
- Most Python code runs in the `mcp_env_2` conda env; satellites have their own envs (see
  `start_scripts/*.bat` and Docs/ARCHITECTURE.md).

## Conventions

- Windows-only system. Paths in scripts use backslashes; conda envs via miniconda.
- Interceptors live in main.py as `extract_*` / `is_*` functions; each must strip the wake word
  itself before parsing.
- Subprocess communication is HTTP (main.py endpoints) + shared `config.py` + a few state files —
  never direct imports across processes.
- New chat-triggered behavior: add an `is_/extract_` matcher + an interceptor block inside
  `handle_incoming_message()` (before the default LLM path), and document it in
  Docs/COMMANDS.md.