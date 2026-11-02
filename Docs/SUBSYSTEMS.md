# Subsystems Reference — How Each Part Works

**Audience:** AI coding assistants + maintainer. **Answers:** "how does subsystem X work
internally, and what should I know before changing it?"

Last verified: 2026-10-12. `file:line` refs as of this date. Cross-links:
[MESSAGE-PIPELINE.md](MESSAGE-PIPELINE.md) (who calls what),
[COMMANDS.md](COMMANDS.md) (chat triggers), [ARCHITECTURE.md](ARCHITECTURE.md) (ports/processes).

## LLM (brain) — `clients/llm_client.py`

`LLMClient` wraps a local **Ollama** server (`OLLAMA_MODEL`, `OLLAMA_BASE_URL`, default
`http://localhost:11434`). Methods: `chat` (plain), `chat_with_tools` (returns
`(content, tool_calls)`), `chat_with_image` (multimodal), `chat_sync` (for background threads,
used by the Twitch song checker), `check_connection`. Cumulative token usage persisted to
`token_usage_state.json` (clients/llm_client.py:29).

**System prompt assembly happens in main.py** (main.py:1486-1504), not the client: persona +
current time (`Asia/Bangkok` hardcoded, main.py:1490) + avatar state + memory context + last
20 chat messages + **who is visible on the stream camera** (face recognition, main.py:1506-1510).
Instantiated at main.py:32; model swap at runtime via GUI settings.

## Memory — `clients/cognee_client.py` + `cognee/cognee_server.py`

Cognee (knowledge-graph memory) behind an HTTP server on `:8011`. `remember()` is
**fire-and-forget** (`asyncio.create_task`, clients/cognee_client.py:30) so chat is never
blocked; `recall()` has a 5s client timeout, and main.py wraps recall with a 3s overall budget
(`get_memory_context`, main.py:1682, with 3-tier fallback queries). Every user message,
AI response, and notable action (song downloaded/generated, music stopped, face appearances) is
stored. The server serializes writes behind an asyncio lock and queries session memory first,
then the global graph. Its `POST /settings` rewrites the cognee `.env` (LLM/embedding provider) —
requires a cognee server restart.

**The in-game Gem shares this memory.** m8 (`[memory]` in `m8.toml`) writes under
`source = "halo"`: a session-start line, the game's notable events (kills, shields, deaths,
pickups, objectives, story lines) batched into one entry every `flush_seconds` (30), each level
reached at a checkpoint, and a closing summary when the game disconnects. On game connect it
recalls past sessions and what it knows about the player, and puts both in the prompt. Chat-Gem
gets Halo back through `get_memory_context`, which asks `"times Gem played Halo with {speaker}"`.
Entries are persisted in `cognee_data/` + `cognee_system/databases/` (no `session_id`, so the
global graph); the m8 tab's **Memory** card shows Cognee's health and can test a recall.

## TTS — `clients/tts_client.py` + `tts/*`

Engine-agnostic HTTP POST (`{"chatmessage", "text"}` — both keys for engine compatibility).
Engine selected by `config.TTS_ENGINE` (`styletts2` | `pocket` | `vibevoice` | `qwen` | `ming`),
URL resolved in `_tts_url_for_engine()` (main.py:36-46). The TTS **server** writes
`tts_output/server_output.wav` (`TTS_OUTPUT_PATH`) — nothing is streamed.
The NiceGUI TTS page (`panel/tabs/tts_tab.py`) uses per-engine sub-tabs (General /
StyleTTS2 / Pocket / VibeVoice / Qwen3 / Ming / Test).

- **StyleTTS2** (`:13300`): reference-voice cloning; params `TTS_DIFFUSION_STEPS`,
  `TTS_EMBEDDING_SCALE`, `TTS_ALPHA/BETA`, `TTS_REFERENCE_VOICE` (in `tts/reference_voices/`).
  **Digits in text cause 500 errors** — that's why `_number_to_words()` exists (main.py:912).
  The GUI also pushes params directly to the StyleTTS2 server's own `/settings`
  (gui.py:3123-3141).
- **Pocket** (`:13301`), **VibeVoice** (`:13000`), **Qwen3** (`:13302`): alternates; Pocket's
  device/speed live in `tts/pocket-tts/settings.ini` (GUI writes it directly, gui.py:3004-3018).
- **Ming-3.0-tts-0.5B** (`:13303`, `tts/Ming-3.0-tts/server.py`): 0.5B Qwen2.5-based TTS with
  a DiT flow head + AudioVAE + Campplus speaker encoder; **44.1 kHz** output. Voice cloning
  uses a Campplus speaker embedding computed once from
  `tts/reference_voices/earn_lucky_pitch_minus_one_samplerate_44000_10sec.wav`
  (cached at `tts/Ming-3.0-tts/reference_voices/earn_lucky_10sec_spk.pt`), so no transcript is
  needed. Settings in `tts/Ming-3.0-tts/settings.ini`, live-editable via `GET/POST /settings`:
  `cfg`, `sigma`, `temperature`, `max_length`, `max_decode_steps`, `raw_text`, `trim_silence`,
  `seed`, `language`, `reference_voice`/`spk_emb_path` (recomputes the speaker embedding),
  `copy_to`/`copy_enabled`. `device`, `model_path`, and `text_normalization` require a restart;
  `text_normalization=False` (no pynini). Requires CUDA torch in the `Ming-3.0-tts` env for
  usable speed (falls back to CPU).

**Consumers of the WAV** (the tricky part): `AudioPlayer` (below) and/or Neurosync
`watcher_to_face` on this or a second machine (file copied to `TTS_COPY_TO` network share).
main.py itself never plays audio — after TTS it only notifies Unreal via OSC
(main.py:175-181).

## Audio playback + ducking — `clients/audio_player.py`

`AudioPlayer` (pygame) watches the TTS WAV, waits for file-size stability, plays it on
`AUDIO_OUTPUT_DEVICE`, fires `duck_callback`/`unduck_callback` around playback
(wired at main.py:389-403 → `music.duck_music/unduck_music` with `AUDIO_DUCK_AMOUNT`,
attack/release ramps). `stop_playback()` interrupts instantly (idle monologues, main.py:377).
`is_playing()` feeds the idle manager AND the face-greeting gate. Enabled by
`AUDIO_PLAYER_ENABLED`; if you use Neurosync for lip-sync, typically only ONE consumer plays
the audio.

## Music — `clients/music_client.py` (878 lines) + `music/*`

`MusicClient` owns four playback domains:

1. **Request songs** (`music/requests/`): `download_song` → thread → `download_worker.py`
   (ytmusicapi search → yt-dlp `-x mp3`) → auto-plays via `_SDMusicPlayer` (sounddevice,
   separate `MUSIC_OUTPUT_DEVICE`) → `on_download_complete` callback → cognee memory
   (main.py:97-100). Queue managed one-at-a-time by a worker loop.
2. **Karaoke** (`music/requests/karaoke/`): `SongLibrary` (music/song_library.py) pairs
   stems (`_vocals`/`_instrumental`, `_track1`/`_track2`, `_a`/`_b`, …) and
   `headless_dual_audio.play_dual` plays them on two devices (Voicemeeter VAIO + AUX) so the
   vocal track can be muted separately (music/headless_dual_audio.py:58).
3. **Background music** (`music/background_songs/`): looped player with pause/resume, volume,
   **ducking**, and state persisted across restarts via `background_state.json`
   (saved in shutdown main.py:2826, resumed in startup main.py:2791).
4. **Playlist mode**: plays every MP3 in the playlist folder sequentially.

**Twitch DJ compliance**: `music/twitch_music_checker.py` — parses "artist - track" via regex
(or `llm.chat_sync` fallback, wired main.py:61), checks restricted-artist blacklist
(`twitch_restricted_artists.json`), optionally scrapes Twitch's DJ catalog with headless
Playwright. Gate applied in the song-request interceptor (main.py:1251-1261) when
`TWITCH_MUSIC_CHECK_ENABLED`.

`now_playing_state.txt` is written on play (clients/music_client.py:455) for the
`extras/now_playing.py` OBS overlay.

## Music generation — `clients/music_gen_client.py` + `clients/comfyui_yue/`

`MusicGenClient` runs a ComfyUI workflow (default `clients/comfyui_yue/yue2_full.json`, YuE2
nodes, `:8188`) over WebSocket: injects the style prompt into **every node with a `style`
input** (node IDs 22/23), randomizes all seeds (workflow ships with hardcoded seeds — without
this every song would be identical), waits for execution, downloads output via
`/history`+`/view`, converts to MP3 (ffmpeg libmp3lame) into `music/generated/`. One-at-a-time
guard. Completion callback (main.py:102-107) → memory + LLM announcement. Trigger phrases in
COMMANDS.md §2. `comfyui_yue/comfyui_yue.py` is an early standalone prototype — not used by
main.py.

## Vision + Face recognition — `vision.py` (service `:5001`) + `clients/vision_client.py`

**Camera service** (default): serves `GET /get_image` → base64 JPEG (640x480) for
`llm.chat_with_image` in the vision interceptor (main.py:1408-1424); sources: webcam index or
**NDI** (default source name "OBS Mixxx" — frames come straight out of OBS over the network, so
the face recognition literally watches the stream). **VLM mode** (`enable_local_vlm`) runs a
local SmolVLM and answers `GET /scan` with a sentence. `game_agent.py` consumes `/get_image`
too (independent loop).

**Face recognition** (`VISION_FACE_RECOGNITION_ENABLED`): pure OpenCV —
`cv2.FaceDetectorYN` (YuNet detector) + `cv2.FaceRecognizerSF` (SFace 128-d embeddings),
models in `models/faces/` (downloaded from the official opencv_zoo repo; `models/` is
gitignored, so enrolled faces never enter the repo). The `FaceRecognizer` class (vision.py)
runs a scan thread every `VISION_FACE_SCAN_INTERVAL_S` (5s) that:
- detects faces (frames downscaled to ≤960px for speed), aligns + embeds each face,
  cosine-matches against enrolled embeddings (≥ `VISION_FACE_MATCH_THRESHOLD`, 0.363 = the
  SFace identity threshold),
- tracks presence: visible = seen within a 10s grace window; an "appeared" event fires only
  after someone has been off-screen > `VISION_FACE_ABSENCE_RESET_S` (120s) — flicker-safe,
- pushes events to main.py `POST /api/face_event` (main.py:2709) → `handle_face_event()`
  (main.py:254): memory event + throttled in-character greeting (per-person
  `VISION_FACE_GREET_COOLDOWN_S`, global 20s gap, skipped while TTS plays — shared WAV).
  Unknown faces are reported ("someone new") when `VISION_FACE_REPORT_UNKNOWN`.

**Enrollment**: (a) GUI Vision tab: name + "Enroll from Camera" → `POST /api/vision/faces/enroll`
(main.py:2223) — requires exactly one face on screen; re-enrolling averages samples;
(b) photo drop folder `models/faces/photos/` — `<name>.jpg` auto-enrolls on vision start or
`POST /api/vision/faces/refresh`. Enrollments live in `models/faces/enrolled/`
(`<name>.json` embedding + `<name>.jpg` thumbnail). Vision service endpoints:
`/faces/current`, `/faces/scan`, `/faces/list`, `/faces/enroll`, `/faces/refresh`,
`DELETE /faces/<name>`.

**Integration in main.py**: on-screen people are injected into every LLM system prompt
(main.py:1506-1510, 5s-cached fetch via `get_on_screen_people_context` main.py:232), and
"who do you see" is answered by its own interceptor (main.py:1381, before the generic vision
trigger). ⚠️ If the avatar's own face is visible in the OBS output, enroll it too or it will
keep triggering "unknown person" reports.

## Idle behavior — `clients/idle_manager.py`

Background loop (5s tick, started main.py:2765) with two config knobs:
`IDLE_INACTIVITY_LIMIT` (120s of silence) and `IDLE_COOLDOWN` (90s between monologues). On
fire: OSC state address gets `IDLE_OSC_BORED_VALUE` → topic from `IDLE_TOPICS` → callback into
main.py `_idle_monologue` (main.py:349-369) builds system prompt = persona + monologue
template + chat history + 2s-timeout cognee recall → LLM → `send_response`. Interrupts:
`update_activity()` on any message (main.py:1134) or mic VAD (main.py:2732) stop playback via
`on_interrupt` (main.py:375-379). Won't fire while TTS is playing (`is_speaking_check`,
main.py:386). Empty OSC values are skipped (main.py:137-143) so blank config can't break
animations.

## Twitch events — `clients/twitch_client.py`

Direct **twitchio EventSub over WebSocket** (independent of SSN chat). Subscribes to 6 event
types (sub, sub message, gift, follow, raid, cheer). `start()` at server startup when
`TWITCH_ENABLED` (main.py:2813-2817). Events → `handle_twitch_event` (main.py:197-221): canned
thank-you line → `send_response` (TTS+chat); sub events also trigger `TWITCH_SUB_ANIMATION`
with music ducking for `TWITCH_SUB_ANIMATION_DUCK_S` seconds (`trigger_animation_with_duck`,
main.py:183-194).

## Chat transport — `clients/ssn_client.py` + `ssn_relay.py`

Outbound: `send_message` POSTs `{"action": "sendChat"}` to the SSN overlay API, chunked at
word boundaries (`max_length=200`), one POST per platform in `SSN_TARGETS`
(discord/twitch/youtube). Inbound: SSN's browser extension pushes chat via HTTP
`POST /chat` ("post" feature); the WebSocket listener in `ssn_client.py` exists but is
**disabled** (main.py:2762-2766) to prevent double-processing. `ssn_relay.py` reimplements the
SSN cloud relay locally on `ws://127.0.0.1:3000` with the same room protocol
(`join` with `out`/`in` channel numbers; `sendChat` broadcasts to matching `in` members) —
protocol-compatible with `test_ssn_relay.py`.

## Browser agent — `clients/browser_client.py`

`browser_use` library driving a real Chrome (persistent profile in `browser_profile/`,
1280x720, window positioned on an OBS-captured monitor — raw `--window-position` arg so
negative coordinates work). Driving LLM configurable: `BROWSER_LLM_PROVIDER` ollama (default
`glm-5.3-flash:cloud`-class) or OpenAI. `FenceStrippingChatOllama` (clients/browser_client.py:40)
strips ```` ```json ```` fences local models add — pydantic validation fails without it.
Two entry paths: URL intercept (main.py:1146) and LLM `browse_web` tool (main.py:1533); both
apply `BROWSER_BLOCKED_TERMS` filtering (main.py:2474) and both summarize results in-character.

## Weather — `clients/weather_client.py`

Open-Meteo (no API key) + its geocoding API. Default coords Pattaya. `describe_weather` maps
WMO codes to words. Used only by the weather interceptor (main.py:1448-1470); the LLM is
explicitly forbidden from inventing different weather.

## Laya pre-filter — `clients/laya_server.py` + `models/laya/`

Separate Quart server (`:5002`) with the local Laya RL-tuned model (ModernBERT-large encoder).
Per message: classifies an **animation** option (sent straight to OSC if ≥
`LAYA_ANIMATION_THRESHOLD` — instant avatar reaction, no LLM) and a **should_reply**
probability (message forwarded to main.py `/chat` only if ≥ `LAYA_REPLY_THRESHOLD`; wake-word
messages always pass). Dropped messages still get their body cue. Graceful degradation: if
Laya is down, SSN posts straight to main.py and nothing else changes. Maps/options
(`LAYA_ANIMATION_MAP`, `LAYA_ANIMATION_OPTIONS`) are persisted in config.py by
`save_config()` (main.py:609-623).

## STT — `clients/listen.py`

Own process. webrtcvad + smoothed dB energy gate → pre-roll buffer → segmentation →
faster-whisper (default `openai/whisper-base.en`, English, beam 5) → `POST /process` (text
enters the normal pipeline as `VOICE_SPEAKER_NAME`, default "JayGee") + activity pings to
`/api/voice_activity`. All tuning (model, VAD aggressiveness, silence threshold, pre-buffer,
dB gate) from `config.py`. `listen.ini` is vestigial.

## Neurosync (face animation) — `Neurosync/*`

Two submodules: **NeuroSync_Local_API** hosts the audio→blendshape transformer
(`neurosync_local_api.py`, model in `utils/model`); **NeuroSync_Player**
`watcher_to_face.py`/`merged_watcher_to_face.py` watches the TTS WAV, sends audio to the
Local API, streams returned blendshapes into Unreal via **LiveLink** (`LIVELINK_IP/PORT`),
applies `BLENDSHAPE_*_SCALE` intensity sliders, and **owns talk animation + music ducking
timing** (not main.py — comments at main.py:149-151, 170-172). GUI's Neurosync tab starts the
merged pipeline and configures blendshape scales, talk delays, and quick emotes
(`POST /api/osc/emote`, main.py:2270).

## Gem Drive — `drive_game/` (chat-controlled 3D highway)

Standalone slow-paced driving game where every viewer can own a car. It renders with
**Ursina/Panda3D** in its own `drive_game` conda env and exposes a stdlib HTTP API on
**127.0.0.1:5010** (`drive_game/server.py`). Disabled unless `GAME_DRIVE_ENABLED = True`.

- **Simulation** (`drive_game/sim.py`, no Ursina imports): 4 lanes, lane-based steering
  (no twitch physics), cruise speed 6–22 u/s, `!faster/!slower/!brake`, auto-join, 12-car cap,
  3-minute inactivity TTL, 2s per-viewer cooldown + 12 commands/s global rate limit. Traffic
  density is a live preset (`GAME_DRIVE_TRAFFIC_DENSITY`: off/sparse/normal/dense; Games tab
  applies it without a restart) and spawns ahead and recycles; player-traffic hits crash
  (5s respawn), player-player proximity
  auto-brakes. Score = metres + 20/overtake; leaderboard by best run. Rubber-banding nudges
  stragglers/leaders so the pack stays in frame. `tick()` sub-steps at 50ms so long frames or
  tests cannot skip collisions.
- **Render + camera** (`drive_game/app.py`): asset-free cubes/planes. Default camera is a
  **fixed rig** (`GAME_DRIVE_CAMERA_MODE="fixed"`) at a constant offset/look-at relative to the
  pack centre (`GAME_DRIVE_CAMERA_OFFSET_*` / `LOOK_*`, Games tab) — no auto-zoom, orbit or
  switching; `P` pause, `R` reset, `F11` fullscreen. Set mode to `wide` to restore the old
  auto-zoom pack camera with `F2` chase-leader / `F3` orbit. HUD shows top 5, car count, average
  speed and crash/leader toasts.
  World-space `Text` labels use `scale≈24`; colours must be `color.rgb32` (Ursina `color.rgb`
  takes 0–1 floats and clamps to white).
- **Custom models**: `GAME_DRIVE_CAR_MODEL`, `GAME_DRIVE_TRAFFIC_MODEL`, and per-viewer
  files in `models/cars/players/<chatname>.<ext>` (GLB/GLTF/OBJ/BAM). Auto-scaled to
  `CAR_LENGTH`, auto-yaw for X-long models, colored plate under each player. See
  [../drive_game/MODELS.md](../drive_game/MODELS.md).
- **Demo mode**: `DriveSim.set_demo(True, n)` spawns auto-driving `Demo 1…N` cars
  (panel Games → Demo Mode, or `python -m drive_game --demo --demo-cars 6`).
  Demo cars leave `GAME_DRIVE_DEMO_RESERVED_SLOTS` (2) grid slots free, and a real
  viewer's `!join` evicts the least-recently-active demo car if the grid is full.
  Demo events are flagged `demo` and skipped by the event forwarder/commentary, so
  model and tuning tests stay silent.
- **Chat bridge** (`main.py`): `extract_game_command` (main.py:744) matches `!cmd` in
  `handle_incoming_message` **before** the wake-word gate (main.py:1153) and forwards
  fire-and-forget to `/api/command`. Commands are not stored in memory or chat history and never
  reach the LLM. `clients/laya_server.py:114` lets `!` messages bypass the Laya model.
- **Commentary**: the game POSTs `crash` / `leader` / `milestone` / `session_start` events to
  `POST /api/game/event` (main.py:2795) → `handle_game_event` (main.py:2953). Throttled by
  `GAME_DRIVE_COMMENTARY_COOLDOWN_S` (45s), one short LLM line (or canned fallback) through
  `send_response`, skipped while paused or while AudioPlayer is speaking.
- **Run it**: `start_scripts/start_drive_game.bat` (env `drive_game`). `python -m drive_game
  --headless --ticks 900` simulates without a window; `pytest drive_game/tests -q` runs the
  unit tests. API: `GET /api/state`, `POST /api/command`, `POST /api/control`
  (`pause|resume|reset|spawn_traffic|force_crash`).

## Game agent — `game_agent.py`

Standalone autonomous-gameplay experiment, deliberately decoupled from the stream pipeline:
frame from vision `/get_image` → Ollama VLM constrained to `MOVE: <forward|back|stop>
TURN: <left|right|stop>` → parsed → OSC `/agent/move`/`/agent/turn` (config
`GAME_AGENT_*`). Always sends "stop" on failure/interrupt. Started from GUI Game Agent tab.

## GUI — `gui.py`

CustomTkinter control panel, 19 tabs, one window per concern (Status/LLM/Memory/TTS/Audio/
Music Requests/Music Gen/Neurosync/OSC/OpenCode/Browser Use/Vision/SSN/Twitch/Extras/Idle/
Laya/STT/Game Agent). Two jobs:

1. **Orchestration**: `_launch_detached` (gui.py:154-165) runs `start_scripts/*.bat` via
   `subprocess.Popen('start "" ...', shell=True)` — each service in its own console + conda
   env. main.py is auto-started at GUI launch (gui.py:91) if not already running.
2. **Configuration**: nearly everything flows through `POST /api/settings` (main.py:1905) —
   a ~70-key god-endpoint that mutates live client objects AND rewrites config.py. Status
   lights poll `GET /api/status` every 5s (gui.py:2586). Exceptions that bypass main.py:
   Cognee settings (port 8011), StyleTTS2 `/settings`, Pocket `settings.ini`.

Runtime control endpoints the GUI calls: pause/resume MCP, music download/queue/play/
background/volume/duck, OSC emote/animation tests, camera scan, monitors, audio devices,
face enrollment/list/delete (via `/api/vision/faces/*` proxies, main.py:2209-2250). Extras
tab launches gpu_viz / now_playing / token_usage / text scroller in their own consoles.

## Game companion — m8 - Gem (canonical)

The Halo: Combat Evolved campaign companion, and the only game path. Two processes:

1. **The game** — `AI-clean/m8/halo/build/windows/halo.exe` (OpenCE + `m8.patch`). Its
   `companion.c` spawns Gem beside the player, drives her body through `unit_control`
   (move, aim, fire, reload, cover, grenades, melee, vehicles, jump/crouch), and its
   `mate_link.c` exchanges framed JSON + PCM with m8 on **47800**.
2. **`AI-Clean/m8/m8/target/release/m8.exe m8.toml`** — the brain. It keeps the feed,
   asks **Laya** (`[kev]`, `:5002`) for the quick decision, **Ollama** (`[llm]`,
   `gemma3-4b-ctx`) for the line/vision, and sends speech to the **m8 TTS adapter**
   (`:8091`, Breeze API → StyleTTS2 `:13300`). Mic: `Voicemeeter Out B1` → Silero VAD →
   **Whisper** (`[stt]`, `:13310`).

Voice is played by `AI-clean/voice_player.py` (Gem's `AudioPlayer`) from
`tts_output/server_output.wav` to Voicemeeter AUX; m8 writes `AI-clean/m8/voice_stop.txt`
when the player talks over Gem, and the player stops the file. Persona: `examples/kevin`
(`system_prompt.txt`, `combat_prompt.txt`, `radio_prompt.txt`, `levels/`). Settings:
`m8.toml` (`[mate]`, `[mic]`, `[stt]`, `[kev]`, `[llm]`, `[game]`) and the game's
`[companion]` block (name, voice/radio volume, speech cooldown; KEVIN SETUP on the profile
menu). **Name**: `companion.name` (game text) and `[mate] name` (persona/voice) are written
together by the panel's **Companion → Name** box; the prompts read it as `{name}`.
**Eyes**: m8's page on `:8090` serves `/eyes` — the player's view grabbed about once a second,
transparent, for the panel card and an OBS Browser Source — and `/eyes.png`, the latest frame.
The frames the brain itself looks at are saved in `logs/views/` and shown in `/history`; the
feed and a Laya "look" take turns on one view request.

**Legacy:** chasm (`chasm/` + `xbox/OpenCE` `chasm-bridge`, `:7341`) commands existing
NPCs through a profile/action book; it is kept on disk but no longer in the panel.