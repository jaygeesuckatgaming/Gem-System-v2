# Commands & Triggers — What Phrase X Does

**Audience:** AI coding assistants + maintainer. **Answers:** "what does this chat phrase
trigger, and where is it handled?"

Last verified: 2026-10-12. All `file:line` refs are as of this date.

**Universal rules** (enforced before anything in this catalog runs — see
[MESSAGE-PIPELINE.md](MESSAGE-PIPELINE.md)):

- Message must contain a **wake word** from `config.WAKE_WORDS` (default `"gem"`, `"hey gem"`,
  `"ok gem"`) — anywhere in the message (substring, not prefix).
- `"jim"` is rewritten to `"Gem"` first (main.py:1112), so "jim play X" works too.
- Matching is **case-insensitive**; `extract_*` functions strip the wake-word prefix themselves
  before pattern matching.
- Interceptors run in the order listed below — **first match wins**, the LLM never sees the
  message. To add a new command: `is_/extract_` matcher + block inside
  `handle_incoming_message()`, then add a row here.

## 1. Music — song requests & playback

| Phrase (prefix match on rest after wake word) | Handler | Action |
|---|---|---|
| `play the song <X>` / `sing the song <X>` / `download song <X>` / `download the song <X>` / `get song <X>` / `can you play <X>` / `play <X>` / `sing <X>` | `extract_song_command` main.py:652 → block main.py:1231 | Order: 1) match generated song → play it; 2) if `TWITCH_MUSIC_CHECK_ENABLED`, `music.verify_song` (Twitch DJ Program gate — restricted → refused, main.py:1251-1261); 3) local file → `play_mp3`; 4) else yt-dlp download → auto-play → memory event |
| `... dedicate it to <name>` / `... for <name>` (appended to song request) | `extract_dedication` main.py:685 | Dedication mentioned in chat acknowledgement |
| `can you sing the song <X>` / `can you sing <X>` / `sing the song <X>` / `sing <X>` | `extract_sing_command` main.py:704 → block main.py:1182 | **Karaoke library first** (`music/requests/karaoke/` dual-track stems via Voicemeeter); not in library → download fallback. Runs BEFORE generic song cmd |
| `play my playlist` / `play the playlist` / `play playlist` / `start my playlist` / `start the playlist` / `start playlist` / `play my music` / `play the music folder` | `is_playlist_command` main.py:823 → block main.py:1199 | Plays all MP3s in playlist folder |
| `stop my playlist` / `stop the playlist` / `stop playlist` / `stop my music` / `stop the music folder` | `is_stop_playlist_command` main.py:839 → block main.py:1210 | Stops playlist |
| `stop the music` / `stop music` / `stop the song` / `stop playing` / `stop the song playing` | `is_stop_music_command` main.py:779 → block main.py:1279 | Stops request player; memory event recorded |
| `resume the background music` / `resume background music` / `play the background music` (+song variants) | `is_resume_background_command` main.py:792 → block main.py:1346 | Restarts background song |
| `what songs have you downloaded` / `list your songs` / `list the songs` / `list downloaded songs` / `what songs do you have` / `songs you downloaded` (+variants) | `is_list_songs_command` main.py:806 → block main.py:1356 | Replies with library listing |
| `play the latest song you created` / `play your latest song` / `play the song you just made` / `play my latest song` (+variants) | `is_play_latest_command` main.py:896 → block main.py:1219 | Plays newest AI-generated song |

## 2. Music — AI generation

| Phrase (contains, after wake-word strip) | Handler | Action |
|---|---|---|
| `make a song in this style <X>` / `make a song in the style <X>` / `make a song <X>` / `make music <X>` / `create a song <X>` / `compose a song <X>` | `extract_make_song_command` main.py:868 → block main.py:1328 (requires `MUSIC_GEN_ENABLED`) | ComfyUI+YuE2 generation, prompt injected into every workflow node with a `style` input. One at a time (busy-guard). On completion: memory event + LLM in-character "your song is ready" announcement (main.py:109-121) |
| `count down from X to Y` (regex: `count\s*(down|from)?...`, main.py:858) | `extract_countdown_command` main.py:852 → block main.py:1303 | Sequence generated in code ("LLMs can't count reliably"), numbers spelled as words, cap `COUNTDOWN_MAX` (100), TTS in chunks of `COUNTDOWN_TTS_CHUNK` (10) with `COUNTDOWN_CHUNK_DELAY_S` (3.0s) waits so chunks don't overwrite each other |

## 3. OpenCode (coding agent)

| Phrase (prefix) | Handler | Action |
|---|---|---|
| `oc <command>` / `use oc ...` / `try oc ...` / `ask oc ...` / `open code ...` / `opencode ...` | `extract_opencode_command` main.py:733 → block main.py:1369 (requires `OPENCODE_ENABLED`) | `opencode.execute_task` in its workspace; output cleaned by `format_opencode_response` and posted to chat; stored in memory |

## 4. Vision & face recognition

| Trigger (contained anywhere) | Handler | Action |
|---|---|---|
| `who do you see` / `who can you see` / `who do you recognize` / `who's on screen` / `who is on screen` / `whos on screen` / `who's on the screen` / `who is on the screen` / `who is that on screen` / `who's that on screen` / `who is with you` / `who's with you` | `is_who_do_you_see_command` main.py:765 → block main.py:1381 (requires `VISION_FACE_RECOGNITION_ENABLED`) | Answers from face recognition: visible names (from vision `/faces/current`, cached 5s) + camera frame → multimodal LLM, told not to invent people. Runs BEFORE the generic vision trigger (these phrases contain "see") |
| any of `config.VISION_TRIGGER_WORDS` — default: `see`, `describe`, `analyze`, `scan`, `what is in`, `what's in` (your live config adds `look at the screen`) | `is_vision_command` main.py:756 → block main.py:1408 (requires `VISION_ENABLED`) | Fetches base64 frame from vision service (`:5001`) → multimodal `llm.chat_with_image` → normal `send_response` |

> ⚠️ `"see"` is a substring — "gem do you see" triggers vision (but "who do you see" is
> caught by the face-recognition interceptor first). Tune `VISION_TRIGGER_WORDS` if this
> over-fires.

> **Face recognition is also always-on context**: when `VISION_FACE_RECOGNITION_ENABLED`, the
> LLM path injects "People currently visible on your stream camera: ..." into every system
> prompt (main.py:1507-1510), and appearance events (pushed from vision.py) trigger
> memory events + throttled in-character greetings without any chat phrase (see §8).

## 5. Time & weather

| Trigger (contained anywhere) | Handler | Action |
|---|---|---|
| `time is it` / `what time` / `current time` / `what's the time` / `whats the time` | `is_time_command` main.py:1051 → block main.py:1426 | Location extracted (default **Pattaya**), timezone from hardcoded city map (main.py:976-1020), real time handed to LLM with "never invent a different time" instruction |
| `weather` / `temperature` / `how hot` / `how cold` / `is it raining` / `is it sunny` / `forecast` / `humidity` / `wind speed` | `is_weather_command` main.py:1074 → block main.py:1448 | Location extracted (default **Pattaya**), Open-Meteo current weather described by code (main.py `describe_weather` via clients/weather_client.py:96), LLM narrates in-character |

## 6. Browser

| Trigger | Handler | Action |
|---|---|---|
| Message contains `https?://...` (regex, main.py:1149) + `BROWSER_ENABLED` | URL intercept main.py:1146 | Browser agent navigates to URL and completes the request; result summarized in-character. Blocked-terms filter first (`find_blocked_term` main.py:2474) |
| LLM decides to call `browse_web` tool (main.py:2446-2471) | LLM tool call, executed main.py:1529-1536 | Same agent, driven by the chat LLM; result fed back for an in-character reply (main.py:1537-1545) |

## 7. Avatar animation (LLM tool call, not phrase-matched)

| Trigger | Handler | Action |
|---|---|---|
| LLM calls `trigger_animation(action)` tool (main.py:2399-2428) | `extract_tool_action` main.py:2431 → `apply_action_tag` | Fuzzy-matches action to `config.OSC_ACTIONS` values (`resolve_action_value` main.py:2498), sends OSC command to Unreal, persists pose to `current_pose.txt` (+ network share, main.py:2527-2547). Enum-restricted when `OSC_ACTIONS` defined. Tool description tells the LLM to only fire on explicit "do it now" requests |

Also see: emotes in any LLM-path message get glossed via `config.EMOTE_MEANINGS`
(`translate_emotes` main.py:937) — not a trigger, but affects what the LLM sees.

## 8. Things that are NOT chat commands (no wake word needed)

| Trigger | Entry | Action |
|---|---|---|
| Twitch sub/resub/gift/follow/raid/cheer | `handle_twitch_event` main.py:197 (EventSub, startup main.py:2813-2817) | Canned thank-you via `send_response`; sub events fire `TWITCH_SUB_ANIMATION` with ducking (main.py:183-194) |
| **Face appears on stream** (recognized or unknown) | vision.py `FaceRecognizer` scan loop → `POST /api/face_event` (main.py:2709) → `handle_face_event` main.py:254 | Memory event ("Gem sees X on the stream camera") + in-character greeting via `send_response` when `VISION_FACE_GREET_ENABLED` (per-person cooldown `VISION_FACE_GREET_COOLDOWN_S`, global 20s gap, skipped while TTS plays). Unknowns reported when `VISION_FACE_REPORT_UNKNOWN` |
| Chat silence for `IDLE_INACTIVITY_LIMIT` (120s) | `IdleManager.monitor_loop` (clients/idle_manager.py:134) | Topic from `config.IDLE_TOPICS` → LLM monologue w/ memory context → `send_response`; OSC state values bored/normal/talk/idle |
| GUI "Test TTS" | `POST /api/tts` main.py:2561 | Full `send_response` pipeline |
| GUI test emotes/animations | `POST /api/osc/emote`, `/api/osc/test_animation`, `/api/osc/test` (main.py:2270-2299) | Direct OSC sends |
| GUI face enrollment | `POST /api/vision/faces/enroll` (main.py:2223, proxied to vision.py) | Enrolls the person currently on camera (exactly one face required); re-enrolling averages samples |
| Mic speech (any) | `POST /api/voice_activity` main.py:2728 | Resets idle timer only |
| Mic transcription | `POST /process` main.py:2736 | Enters the normal pipeline as speaker `VOICE_SPEAKER_NAME` |

## 9. Laya fast-lane (optional pre-filter, before main.py)

When `LAYA_ENABLED` and the SSN extension posts to Laya (`:5002`) instead of main.py
directly, `clients/laya_server.py` classifies every message with the local Laya model
(`models/laya/`):

- **Animation cue**: if an animation from `LAYA_ANIMATION_MAP` is detected with probability ≥
  `LAYA_ANIMATION_THRESHOLD`, Laya sends the OSC body cue **directly to Unreal** — no LLM
  round-trip, so the avatar reacts instantly.
- **Reply gate**: message is forwarded to `POST /chat` (main.py:2718) only if
  `should_reply` ≥ `LAYA_REPLY_THRESHOLD`; wake-word messages always pass.
- Dropped messages still produce the body cue. Without Laya running, SSN posts to main.py
  directly and this layer doesn't exist.

## 10. Where the full phrase lists live (for maintenance)

All matchers are in main.py between `extract_song_command` (main.py:652) and
`extract_weather_location` (main.py:1084) — a contiguous block of pure functions, no state.
Wake words: `config.WAKE_WORDS` (config_example.py:243). Vision words:
`config.VISION_TRIGGER_WORDS` (config_example.py:204). Emote glosses:
`config.EMOTE_MEANINGS` (config_example.py:246). Idle topics: `config.IDLE_TOPICS`. Face
recognition keys: `config.VISION_FACE_*` (config_example.py:209-220).