# AGENTS.md — Guide for AI Coding Assistants

You are working on **Gem-System v2**, a Windows-based AI VTuber livestreaming platform.
"Gem" is an animated avatar in Unreal Engine that chats with viewers on Twitch/YouTube/Discord,
speaks via TTS, plays and generates music, browses the web, watches its own stream via
OpenCV face recognition, and remembers past conversations.

Last verified: 2026-10-20. All `file:line` references are as of this date — re-verify against
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

drive_game/ (:5010, Ursina window) ← !commands forwarded by main.py
    → crash/leader events POST /api/game/event → Gem commentary (throttled TTS + chat)
```

## Game companion — m8 - Gem (canonical, the Halo path)

Halo: Combat Evolved campaign companion. The Gem panel's **Games → m8 - Gem** tab
starts and monitors it.

- **Game**: `C:\Users\jayge\Documents\AI\AI-clean\m8\halo\build\windows\halo.exe`
  (OpenCE + `m8.patch`, branch `m8-kevin`). Data root: `xbox/OpenCE/build/windows`.
- **Brain/link**: `AI-clean/m8/m8/target/release/m8.exe m8.toml` (`:47800`), launched by
  `AI-clean/m8/start-m8.bat`.
- **Services it calls** (all Gem-System-v2): Laya `:5002` (`[kev]` decisions), Ollama
  `:11434` (`[llm]` `gemma3-4b-ctx`, vision `gemma3:4b-it-qat`), m8 TTS adapter `:8091`
  → StyleTTS2 `:13300` (`[mate] voice_server`), Whisper `:13310` (`[stt]`), Silero VAD
  inside m8, mic `Voicemeeter Out B1`.
- **Voice playback**: the game plays m8's PCM (the GoldSrc client through waveOut, OpenCE
  through its own audio). The m8 TTS adapter sends `no_save`, so StyleTTS2 doesn't write
  `tts_output/server_output.wav` for m8's lines — otherwise the Python `voice_player`
  (which plays that file to Voicemeeter AUX) plays every line a second time. (The check is a
  local patch in the gitignored `tts/StyleTTS2/watcher.py`.) The game's waveOut device is
  `hlm8/mate_audio_device.txt` (the Half-Life tab's Voice output card; a name substring, empty
  = system default). The engine's own sound (gunfire, ambience) is GoldSrc's `snd_device` in
  `hlm8/config.cfg` (the tab's Game audio output card; exact name; restart the game). m8 writes
  `AI-clean/m8/voice_stop.txt` on barge-in.
- **Panel**: `M8_ROOT` defaults to `AI-clean/m8`; Games opens on **m8 - Gem**; the Games
  page has `Start m8 TTS adapter` and `Start m8`; the Audio tab has `STT`.
- **Name**: the companion's name is one setting in two files — the game's `config.toml`
  `[companion] name` (state/event/console text; env `HALO_COMPANION_NAME`) and `m8.toml`'s
  `[mate] name` (prompts, voice, feed). The m8 tab's **Companion → Name** box writes both;
  restart m8 and OpenCE to apply. Persona prompts use the `{name}` placeholder.
- **Eyes**: m8 serves `/eyes` (`:8090`) — the player's view at ~1 fps, transparent, for an OBS
  Browser Source — and `/eyes.png` (latest frame; with no game, the newest saved view). The
  frames the brain itself looks at are saved in `logs/views/` and shown in `/history`; the feed
  and a Laya "look" serialise on one view request at a time.
- **Memory**: m8 shares the stream's Cognee memory (`[memory]` in `m8.toml`, server
  `:8011`). It writes under `source = "halo"` — a session-start line, notable events batched
  every `flush_seconds` (30), the levels reached, and a closing summary — and on game connect
  recalls past sessions and what it knows about the player. `get_memory_context` also asks for
  Halo sessions, so chat-Gem remembers them.
- **m8 patches** live on branch **`gem-m8`** of `jaygeesuckatgaming/m8` (`7344d8a`):
  mic device by name, Ollama `model`/`vision_model`, `max_tokens` reply ceiling (50 cut lines
  mid-word; default 200), whole-line TTS batching, barge-in flag,
  the Gem rename (`[mate] name`, `{name}` in the persona prompt, `examples/kevin` kept
  as the persona folder name), and the shared Cognee memory (`src/memory.rs`, `[memory]`). The companion's in-game text lives in `OpenCE` branch
  **`m8-kevin`** (`450a8692`, `port/linux/game/companion.c` + `port/linux/src/port_config.c`);
  the companion also has the ai-player cliff guard (edge probe, turn or stop, follows the
  Chief down a drop but never a void); the game's own `KEVIN MIC` key and `kevin` console
  command keep their upstream names.

### Half-Life — the same mate in GoldSrc (`hlsdk-mate`)

The m8 link is game-agnostic; `AI-clean/hlsdk-mate` is the GoldSrc adapter (branch `gem-hlm8`,
kept local). It builds an HLSDK-portable mod whose server DLL connects to the same
`127.0.0.1:47800` link: `dlls/mate.cpp` (socket, state/orders) and `dlls/mate_world.cpp` (a
`monster_barney` follower, `gem_mate` targetname, follow/hold/attack, catch-up teleport); the
client DLL plays m8's PCM (`cl_dll/mate_audio.cpp` + `mate_wave.cpp`, waveOut). Commands are
spoken ("Gem, stay here" / "follow me" / "attack") and m8 acts on them directly, not via Laya.
Build/install/launch: `build_hlm8.bat`, `install_hlm8.bat`, `start_hlm8.bat`; the panel's
**Games → Half-Life** tab drives them and shows the companion state. **Model**:
`hlm8/mate_model.txt` (the tab's Companion model card); Barney, scientist, grunt and G-Man
are precached, so Apply respawns her with the new body; a custom model is precached at map
load, so it needs the map reloaded. The body must be an NPC model: player models (Gina,
Gordon) have no companion animations and the AI cannot walk them. Barniel (the female Barney) lives in `hlm8/models/` as `Barniel.mdl` with its IDSQ
bodygroups `Barniel01..03.mdl` and talking head `BarnielT.mdl` (the main model loads those
files itself; do not precache the IDSQ ones), and `mate_model.txt` points at
`models/Barniel.mdl`. Vanilla Barneys stay vanilla, and the female voice overrides are not
installed. **Eyes**: the server turns m8's view requests into a `MateView` message; the client
grabs the rendered frame (`glReadPixels`, 960 wide, before the HUD) into `hlm8/mate_view.raw`;
the server forwards it as a view frame, so `/eyes` and the vision model work in GoldSrc.

### Legacy: the chasm NPC path

`C:\Users\jayge\Documents\AI\chasm` + `xbox/OpenCE` (branch `chasm-bridge`, `:7341`) is
the older "command an existing NPC" engine (profile + 6-verb action book, StyleTTS2/Whisper
called by the bridge directly). It is **kept on disk but no longer in the panel** and is not
the current path. The `ai-player` network-co-op experiment and `halo_brain.py` are removed.

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
  `config.py` by regex rewriting** in `save_config()` (main.py:461) — never edit settings any
  other way, and never hand-edit a value the GUI owns without expecting it to be overwritten.
- **`main.py` (3,032 lines)** holds the message pipeline (~main.py:1115-1597), all HTTP
  endpoints, OSC helpers, and persistence. The one giant function to know is
  `handle_incoming_message()` (main.py:1115).
- **Interceptor-first design**: most intents (music, countdown, time, weather, OpenCode, URLs,
  vision, "who do you see") are handled by phrase matching *before* the LLM. The LLM only
  handles conversation plus two tool calls: `trigger_animation` and `browse_web`
  (main.py:1547-1552).
- **`gui.py` (3,866 lines)** is the control panel: it launches every service via
  `start_scripts/*.bat` (each in its own conda env, own console window) and edits settings via
  `POST /api/settings` → `save_config()`.
- **`drive_game/` is a separate Ursina game process** (`start_drive_game.bat`, conda env
  `drive_game`, API :5010). Viewers drive with `!left`, `!right`, `!faster`, `!slower`,
  `!brake`, `!join`, `!leave`, `!score`. main.py forwards commands before the wake-word gate
  (main.py:1153) and throttles Gem's commentary from `/api/game/event` (main.py:2795).
  `GAME_DRIVE_ENABLED` is off by default. Custom models live in `models/cars/`
  (gitignored; per-viewer files named after the chatname) — see `drive_game/MODELS.md`.
- **Face recognition lives in vision.py** (not main.py): a scan thread every 5s matches faces
  against `models/faces/enrolled/` (SFace embeddings, threshold 0.363) and pushes
  appearance events to main.py `/api/face_event`, which handles greetings (throttled) and
  memory. Enroll people via the GUI Vision tab or by dropping `<name>.jpg` into
  `models/faces/photos/`. `models/` is gitignored — enrollments never enter the repo.
- **`Docs/` + this file are the system documentation.** Keep them accurate when you change
  behavior — they are how future AI sessions (and the maintainer) get an overview.

## Top gotchas (things that will surprise you)

1. **"jim" is rewritten to "Gem"** in every incoming message before processing (main.py:1128) —
   an alternate wake name, not a bug.
2. **Wake-word gate**: messages that don't contain a wake word (default `["gem", "hey gem",
   "ok gem"]`, config.py `WAKE_WORDS`) are silently dropped (main.py:1159-1167). Interceptor
   extractors also strip the wake-word prefix themselves (e.g. main.py:626).
3. **Echo guards**: messages from speakers `gem`/`gem_chadee`/`gem-chadee` are ignored, and any
   incoming message identical to one of the last 10 AI responses is ignored (main.py:1137-1146).
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
12. **Gem Drive `!` commands deliberately bypass the wake-word gate** (main.py:1153-1157).
    They are inert unless `GAME_DRIVE_ENABLED = True` and the command is in
    `GAME_DRIVE_COMMANDS`; they never enter chat history, memory, or the LLM. Laya also
    forwards any `!` message directly (clients/laya_server.py:114).

## Testing / verification

- `test_ollama.py` — smoke test: can the configured Ollama model chat?
- `test_ssn_relay.py` — integration test for the local SSN WebSocket relay.
- `drive_game/tests/test_sim.py` — pure simulation tests (24 tests, no Ursina needed):
  `conda run -n drive_game python -m pytest drive_game/tests -q`.
- Gem Drive smoke test: `python -m drive_game --headless --ticks 900`, or run the window and
  `POST /api/command {"user":"tester","command":"left"}` to `http://127.0.0.1:5010`.
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
  Docs/COMMANDS.md. The one exception is the `!` game-command hook, which runs *before* the
  wake-word gate by design (main.py:1153).