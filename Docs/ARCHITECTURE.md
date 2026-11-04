# Architecture — Processes, Ports, and Who Talks to Whom

**Audience:** AI coding assistants + maintainer. **Answers:** "what process is that, on what
port, in which conda env, and how do the pieces connect?"

Last verified: 2026-11-03. Ports/URLs are defaults from `config_example.py` — live values come
from `config.py` (single source of truth, rewritten in place by `save_config()`, main.py:460).

## 1. System diagram

```mermaid
flowchart LR
    subgraph Internet
        TW[Twitch / YouTube / Discord]
        SSNC[SSN cloud relay<br/>wss://io.socialstream.ninja]
    end

    subgraph Local machine["Local machine (Windows)"]
        GUI[gui.py<br/>control panel]
        MAIN[main.py MCP server<br/>:5000]
        SSNR[ssn_relay.py<br/>ws://127.0.0.1:3000]
        LAYA[laya_server.py<br/>:5002]
        LISTEN[listen.py<br/>Whisper STT]
        COG[cognee_server.py<br/>:8011]
        VIS[vision.py<br/>:5001 + face recognition]
        OLLAMA[Ollama<br/>http://localhost:11434]
        TTS[TTS server<br/>:13300 / :13000 / :13301 / :13302]
        COMFY[ComfyUI + YuE2<br/>:8188]
        OC[OpenCode API<br/>:4096]
        WT[watcher_to_face.py<br/>Neurosync]
        GPUVIZ[extras/gpu_viz.py<br/>now_playing.py overlays]
        GAME[game_agent.py]
        DRIVE[drive_game/<br/>Ursina 3D highway<br/>API :5010]
        FACES[models/faces/<br/>YuNet+SFace ONNX<br/>+ enrolled embeddings]
    end

    UE[Unreal Engine avatar<br/>OSC :10000 + LiveLink]
    OBS[OBS + Voicemeeter]

    TW -->|chat via browser extension| SSNR
    SSNR -->|POST /chat| MAIN
    SSNC -.->|alternative inbound path| SSNR
    TW -->|chat posts directly| LAYA
    LAYA -->|approved msgs → POST /chat| MAIN
    LAYA -.->|animation cues| UE
    LISTEN -->|POST /process + /api/voice_activity| MAIN
    MAIN -->|remember / recall| COG
    MAIN -->|chat| OLLAMA
    MAIN -->|speak text| TTS
    TTS -->|writes server_output.wav| WAV[(tts_output/<br/>server_output.wav)]
    WAV --> WT
    WT -->|blendshapes| UE
    MAIN -->|type_1 + duration, poses, emotes| UE
    MAIN -->|music requests| COMFY
    MAIN <-->|tasks| OC
    MAIN -->|get_image base64| VIS
    OBS -->|NDI frames| VIS
    VIS -->|face appeared events<br/>POST /api/face_event| MAIN
    VIS -.-> FACES
    MAIN -->|sendChat| SSNR
    SSNR -->|outbound chat| TW
    MAIN -->|music play/duck| OBS
    GAME -->|frames from VIS, OSC moves| UE
    MAIN -->|forward !drive commands| DRIVE
    DRIVE -->|crash / leader events<br/>POST /api/game/event| MAIN
    DRIVE -.->|window captured by OBS| OBS
    GUI -.->|HTTP settings/status + launches .bat files| MAIN
    GUI -.-> COG
    GPUVIZ -.-> OBS
```

**Two-machine option:** if `TTS_COPY_TO` (network share) is set, the TTS WAV and
`current_pose.txt` are copied to a second machine which runs `watcher_to_face` and drives the
Unreal avatar there (main.py:2540-2547).

## 2. Process / service map

| Process | Start script (conda env) | Port / URL | Role |
|---|---|---|---|
| **main.py** (MCP server) | `start_mcp.bat` (`mcp_env_2`) | `:5000` (bind `0.0.0.0` via `SERVER_BIND_HOST`) | The hub: message pipeline, all `/api/*` endpoints, OSC sender, settings persistence, face-event greetings. Auto-started by gui.py |
| **gui.py** | `start_gui.bat` (`mcp_env_2`) | — | Control panel (19 tabs). Launches every service as detached consoles; edits settings via `POST /api/settings` (main.py:1905); polls `GET /api/status` every 5s; face enrollment UI proxies through main.py |
| **cognee/cognee_server.py** | `start_cognee.bat` (`cognee`) | `:8011` | Long-term memory graph: `POST /remember`, `POST /recall`, `GET /health`, `GET/POST /settings` (rewrites its own `.env`) |
| **clients/laya_server.py** | `start_laya.bat` (`laya`) | `:5002` | Optional pre-filter between SSN and main.py. Local Laya model (in `models/laya/`) classifies animation cues (→ OSC direct) and gates which messages deserve an LLM reply |
| **ssn_relay.py** | `start_ssn_relay.bat` (`mcp_env_2`) | `ws://127.0.0.1:3000` | Local replacement for the SSN cloud relay. Implements the SSN WebSocket room protocol (`{"join", "out", "in"}`, `{"action": "sendChat"}`) |
| **clients/listen.py** | `start_listen.bat` (`mcp_env_2`) | — | Microphone → faster-whisper → `POST /process`; VAD pings `POST /api/voice_activity` |
| **vision.py** | `start_vision.bat` (`mcp_env_2`) | `:5001` | Camera/NDI frames + **face recognition** (YuNet+SFace). Endpoints: `GET /get_image` (base64 JPEG for the multimodal LLM), `GET /scan` (local VLM), `/ndi/sources` (list NDI streams on the network — powers the GUI's "Scan NDI" dropdown), `/faces/current`, `/faces/scan`, `/faces/list`, `/faces/enroll`, `/faces/refresh`, `DELETE /faces/<name>`. NDI source default "OBS Mixxx" — recognition watches the stream output. Pushes appearance events to main.py |
| **TTS — StyleTTS2** | `start_styletts2.bat` (`styletts2`) | `:13300` | Default engine (`TTS_ENGINE = "styletts2"`). Writes the WAV. Digits in text cause 500s — numbers must be words |
| **TTS — VibeVoice** | `start_vibevoice.bat` (`vibevoice`) | `:13000` | Alternative engine (`postapp.py`) |
| **TTS — Pocket TTS** | `start_pockettts.bat` (`mcp_env_2` or `pocket-tts`) | `:13301` | Alternative engine; own `settings.ini` (device/speed) |
| **TTS — Qwen3-TTS** | `start_qwen_tts.bat` (`qwen3-tts_312`) | `:13302` | Alternative engine |
| **Ollama** | external install | `http://localhost:11434` | LLM inference: main chat model, vision (multimodal), browser-driving model, Twitch song-request parsing (`llm.chat_sync`), idle monologues, face greetings |
| **ComfyUI + YuE2** | external / GUI Music Gen tab | `127.0.0.1:8188` | AI song generation. Workflow JSON `clients/comfyui_yue/yue2_full.json`, prompt injected into every node with a `style` input, seeds randomized |
| **OpenCode API** | external | `:4096` | AI coding agent for "oc ..." commands (enabled via `OPENCODE_ENABLED`) |
| **Neurosync: merged_watcher_to_face.py** | `start_merged_watcher_to_face.bat` (`mcp_env_2`) | — (uses Local API internally) | Watches the TTS WAV → audio-to-blendshape transformer → LiveLink → Unreal. **Owns talk animation + ducking timing.** GUI's "Start Neurosync" launches this |
| **Neurosync: neurosync_local_api.py** | `start_neurosync_localapi.bat` | — | Standalone blendshape API (merged script embeds it) |
| **game_agent.py** | `start_game_agent.bat` (`mcp_env_2`) | — | Autonomous gameplay experiment: frames from vision → OSC move/turn commands to Unreal. Independent of the chat pipeline |
| **drive_game** (`drive_game/`) | `start_drive_game.bat` (`drive_game`) | `:5010` API + Ursina window | Chat-driven 3D highway game: up to 12 viewer cars, `!left/!right/!faster/...` commands, wide pack camera, leaderboard. main.py forwards commands and receives crash/leader events for commentary. Disabled unless `GAME_DRIVE_ENABLED = True` |
| **extras**: gpu_viz.py / now_playing.py / token_usage.py | `start_GPU_Viz.bat` etc. (`mcp_env_2`) | — | OBS overlays: hardware graphs, now-playing (reads `now_playing_state.txt`), token usage. Also spawnable inside the GUI Extras tab |
| **Unreal Engine** | external | OSC `:10000` (`OSC_IP`/`OSC_PORT`), LiveLink | The avatar. Receives animation commands (strings + bool), talk notifications (address + float duration), idle-state values |

## 2.1 Port reference (quick lookup)

Every listening/outbound port in the system, as verified against `config.py` and the code on
2026-10-24. The process map above says *why* each exists; this table is the fast lookup.
Live values come from `config.py` — the defaults below can drift from the comment in
`config_example.py`.

| Port | Proto | Service | Config key / source |
|---|---|---|---|
| **5000** | HTTP | `main.py` MCP/API hub (binds `0.0.0.0` via `SERVER_BIND_HOST`) | `SERVER_PORT`, `MCP_PORT` (config.py:308, :314) |
| 5001 | HTTP | `vision.py` — `/get_image`, `/scan`, `/faces/*` | hardcoded (vision.py:1012), mirrored by `VISION_*_URL` |
| 5002 | HTTP | `clients/laya_server.py` pre-filter | hardcoded (clients/laya_server.py:218) |
| 5010 | HTTP | `drive_game/` API | `GAME_DRIVE_PORT` / `GAME_DRIVE_URL` (config.py:276-277) |
| 8011 | HTTP | `cognee/cognee_server.py` memory graph | `COGNEE_SERVER_URL` (config.py:32) |
| 3000 | WS | `ssn_relay.py` — SSN local relay | hardcoded `HOST`/`PORT` (ssn_relay.py:19-20) |
| 13300 | HTTP | StyleTTS2 (default engine) | `TTS_URL` (config.py:40) + `tts/StyleTTS2/settings.ini` |
| 13000 | HTTP | VibeVoice | `VIBEVOICE_TTS_URL` (config.py:57); also legacy `Neurosync/NeuroSync_Player/app.py` |
| 13301 | HTTP | Pocket TTS | `POCKET_TTS_URL` (config.py:54) + `tts/pocket-tts/settings.ini` |
| 13302 | HTTP | Qwen3-TTS | `QWEN_TTS_URL` (config.py:64) + `tts/Qwen3-TTS/settings.ini` |
| 9000 | HTTP | Neurosync Local API (`audio_to_blendshapes`) | `NEUROSYNC_LOCAL_URL` (config.py:100) |
| 13310 | HTTP | Neurosync audio listener (LAN push from main.py; merged watcher listens) | `NEUROSYNC_AUDIO_LISTEN_PORT`, `NEUROSYNC_AUDIO_PUSH_URL` (config.py:50-51) |
| 8080 | HTTP | `panel.py` NiceGUI control panel (alternative to `gui.py`) | hardcoded (panel.py:150) |
| 11433 | HTTP | Ollama | `OLLAMA_BASE_URL` (config.py:7) — **code defaults and `config_example.py` say 11434** |
| 8188 | HTTP | ComfyUI + YuE2 song generation | `MUSIC_GEN_COMFYUI_URL` (config.py:170) |
| 4096 | HTTP | OpenCode API (`oc ...` commands) | `OPENCODE_API_URL` (config.py:223) |
| **10000** | **UDP** | OSC to the Unreal avatar (animation commands, talk notices) | `OSC_PORT` (config.py:107) at `OSC_IP` |
| **11111** | **UDP** | LiveLink to the Unreal avatar (facial blendshapes) | `LIVELINK_PORT` (config.py:112) at `LIVELINK_IP` |

Notes:

- `gui.py` uses Tk and listens on nothing; `clients/listen.py`, `game_agent.py`, and the
  `extras/*` overlays are portless too.
- `config.py:179` `LAYA_URL` is `http://127.0.0.1:5000/chat` — that is main.py's **port 5000**
  (the forwarding destination), not Laya's own 5002.
- `panel.py:147` iframes `http://localhost:8089/index_1.html`; nothing in this repo serves
  8089, so it is external/legacy.
- Legacy, unused Neurosync references in `Neurosync/NeuroSync_Player/config.py`: 5050 (local
  LLM), 8000 (local TTS), 6969 (transcription), 7070 (embeddings). The merged watcher path
  does not use them.
- No OBS WebSocket: music play/duck goes through the local audio stack, not `:4455`.

## 3. Shared state files

| File | Written by | Read by | Content |
|---|---|---|---|
| `config.py` | `save_config()` (main.py:460) via `POST /api/settings` | **every process** | All settings — the cross-process database |
| `tts_output/server_output.wav` | active TTS server (`TTS_OUTPUT_PATH`) | AudioPlayer, watcher_to_face, optional network-share copy | The current/latest utterance — single overwritten file |
| `current_pose.txt` | `_persist_pose()` (main.py:2527) | watcher process (local or 2nd machine) | Current avatar pose to restore after speech |
| `known_speakers.json` | main.py:444 | main.py:432 | Seen chatnames (nickname resolution) |
| `background_state.json` | `music.save_background_state()` (clients/music_client.py:755, shutdown main.py:2826) | `music.resume_background_from_state()` (startup main.py:2791) | Background song + position, survives restarts |
| `now_playing_state.txt` | MusicClient (clients/music_client.py:455) | `extras/now_playing.py` overlay | Current song for OBS |
| `token_usage_state.json` | LLMClient (clients/llm_client.py:29) | LLMClient; `extras/token_usage.py` overlay | Cumulative LLM token usage |
| `models/faces/enrolled/` | vision.py `FaceRecognizer` (enroll endpoint / photos folder) | vision.py scan loop | Per-person SFace embeddings (`<name>.json`) + thumbnails (`<name>.jpg`). Gitignored with the rest of `models/` — biometric data never enters the repo |
| `models/faces/photos/` | you (drop `<name>.jpg`) | vision.py `refresh_from_photos` | Enrollment photo drop zone |
| `clients/listen.ini` | — | **nobody** (vestigial) | Superseded by config.py |
| `music/twitch_restricted_artists.json` | maintainer | twitch_music_checker | Twitch DJ Program restricted artists |

## 4. Startup order

1. **gui.py** starts (optionally auto-launches main.py, gui.py:91).
2. From GUI tabs, satellites start in any order; each is a detached console running a
   `start_scripts/*.bat` in its own conda env. Reasonable order: Cognee → MCP → a TTS server →
   listener/vision/Laya as wanted (README.md:99-113).
3. **main.py `startup()` hook** (main.py:2770-2820), in order: capture event loop → check LLM,
   SSN, Cognee, music → **resume background music from state** → check TTS + start AudioPlayer
   (if `AUDIO_PLAYER_ENABLED`) → check OpenCode/vision/browser (if enabled) → start Twitch
   EventSub (if enabled) → start idle monitor loop (`start_background_tasks`,
   main.py:2757-2766).
4. **vision.py** startup (own process): camera/NDI stream first, then — if
   `VISION_FACE_RECOGNITION_ENABLED` — loads YuNet+SFace, enrolls any new photos from
   `models/faces/photos/`, and starts the recognition scan thread (events flow to main.py
   `/api/face_event`).

**Shutdown** (`after_serving`, main.py:2823-2835): save background music state → stop Twitch →
close browser. Everything else dies with its console window.

## 5. Communication rules (why it's built this way)

- **Processes never import each other.** Cross-process = HTTP to main.py/cognee/TTS/ComfyUI/vision
  + shared `config.py` + state files. The only in-process wiring is main.py ↔ `clients/*.py`
  (and vision.py ↔ its own FaceRecognizer).
- **One writer per setting:** the GUI (via main.py `POST /api/settings`) is the only thing that
  should write `config.py`. Hand edits get overwritten by the next GUI save of that key.
- **Satellite envs are isolated** because the ML stacks conflict (torch versions, CUDA, etc.) —
  that's why StyleTTS2 / cognee / laya / vibevoice each have their own conda env, and why
  `requirements.txt` alone doesn't install everything (see README for per-module setup).
- **Fire-and-forget `/chat`** (main.py:2718) and `/api/face_event` (main.py:2709) exist because
  callers (Laya, SSN, vision.py) must not block on the LLM+TTS pipeline.
- **Face recognition runs in vision.py, not main.py**, because it needs the raw frames at a
  fixed cadence; main.py only reacts to pushed appearance events and pulls `/faces/current`
  (5s cache) when it needs on-screen context.

## 6. Game companion — m8 - Gem (canonical)

```mermaid
flowchart LR
    subgraph GS["Gem-System-v2 (:8080 panel)"]
        PANEL["Control panel :8080"]
        LAYA["Laya :5002<br/>decisions"]
        TTS["StyleTTS2 :13300<br/>the voice engine"]
        STT["Whisper :13310<br/>STT"]
        ADAPT["m8 TTS adapter :8091<br/>Breeze → StyleTTS2"]
        MAIN["main.py (VTuber)"]
        COG["Cognee :8011<br/>shared memory"]
    end

    M8["m8 brain :47800<br/>page :8090<br/>persona · memory · eyes"]
    OLL["Ollama :11434<br/>LLM + vision"]
    GAME["Game<br/>Half-Life (hlsdk-portable)<br/>OpenCE (Halo, m8-kevin)"]
    VP["voice_player<br/>(m8_games/m8)"]
    VM["Voicemeeter"]
    UE["Unreal avatar (OSC)"]

    PANEL -.->|start / monitor| LAYA
    PANEL -.-> TTS
    PANEL -.-> STT
    PANEL -.-> ADAPT
    MAIN -->|chat memory| COG
    M8 <-->|sessions, player| COG
    M8 -->|do / speak| LAYA
    M8 -->|line + eyes| OLL
    M8 -->|mic PCM| STT
    M8 <-->|state/events/eyes ↔ actions/PCM| GAME
    M8 -->|text| ADAPT
    ADAPT -->|/tts| TTS
    TTS -->|WAV → PCM| ADAPT
    ADAPT -->|PCM| M8
    GAME -->|engine audio + waveOut voice| VM
    MAIN -->|speak| TTS
    TTS -->|server_output.wav| VP
    VP -->|AUX| VM
    VM -->|Out B1 mic| M8
    MAIN -->|type_1 / poses| UE
```

**The two voice paths** — in-game, m8 sends text to the **m8 TTS adapter** (`:8091`), which
calls **StyleTTS2** (`:13300`) and returns raw PCM; m8 forwards it to the game, which plays it
through waveOut (device chosen in the panel). For the stream's own TTS, `main.py` asks
StyleTTS2 directly; it writes `tts_output/server_output.wav`, which `voice_player` (now in
`m8_games/m8`) plays to Voicemeeter AUX. The adapter sends `no_save`, so m8's lines never enter
that file (no double playback).

**Mic**: `Voicemeeter Out B1` → m8 (Silero VAD) → Whisper. **Memory**: Cognee is one graph,
shared by `main.py` (chat) and m8 (play sessions, `source = "halo"`).

| Process | Port | Role |
|---|---|---|
| `m8_games/m8/m8/target/release/m8.exe m8.toml` | **47800** | brain/link: game state in, actions + speech out |
| `clients/m8_styletts2_adapter.py` | **8091** | Breeze TTS 2 API → StyleTTS2 (raw PCM) |
| `tts/StyleTTS2/watcher.py` | **13300** | actual voice engine |
| `clients/whisper_server.py` | **13310** | STT for the mic |
| `clients/laya_server.py` | **5002** | `[kev]` decision model (`/v1/systemone`) |
| Ollama | **11434** | `[llm]` `gemma3-4b-ctx`, vision `gemma3:4b-it-qat` |
| `cognee/cognee_server.py` | **8011** | `[memory]` shared Cognee memory (sessions, player) |
| `m8_games/m8/voice_player.py` | — | plays `tts_output/server_output.wav` to Voicemeeter AUX; barge-in via `m8_games/m8/voice_stop.txt` |
| `m8_games/OpenCE/build/windows/halo.exe` | — | OpenCE + `m8.patch` (the companion body) |

The game connects to m8 over `mate_link` (`47800`): `companion.c` sends the feed, m8 replies
with structured actions (`unit_control`), and the voice comes from the m8 TTS adapter →
StyleTTS2. Mic: `Voicemeeter Out B1` → Silero VAD → Whisper. Panel: **Games → m8 - Gem**.
The same process serves its page on **8090**: `/history` (every model call, with the pictures
Gem looked at) and `/eyes` — the player's view grabbed about once a second for the panel and an
OBS Browser Source (`/eyes.png` is the latest frame).
The name is set in two places at once by the panel: the game's `config.toml`
`[companion] name` and `m8.toml`'s `[mate] name`. Memory is shared with the stream: m8 writes
each session to Cognee (`:8011`, `[memory]` in `m8.toml`, `source = "halo"`) and recalls past
sessions + the player at connect.

**Legacy:** the chasm NPC path (`:7341`) is archived under `_archive/chasm-20261103/` and
`_archive/xbox-OpenCE-20261103/`, not in the panel; it commanded existing NPCs through the
`opence` profile/action book and called StyleTTS2/Whisper directly.