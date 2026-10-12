# Gem-System v2 — Documentation Index

**Audience:** AI coding assistants + maintainer. **Answers:** "what does X do, where is it, and
what triggers it?"

Last verified: 2026-10-11. When you change system behavior, update the affected doc below AND
the `file:line` references in it.

## Where to look

| I want to know... | Read |
|---|---|
| What happens to a chat message, in what order (guards, wake words, interceptors, LLM, TTS, timings) | [MESSAGE-PIPELINE.md](MESSAGE-PIPELINE.md) |
| What a specific chat phrase triggers (every command catalog) | [COMMANDS.md](COMMANDS.md) |
| What process/port/env each service runs in, state files, startup order | [ARCHITECTURE.md](ARCHITECTURE.md) |
| How a specific subsystem works internally (LLM, TTS, music, memory, Twitch, Laya, Neurosync, GUI, ...) | [SUBSYSTEMS.md](SUBSYSTEMS.md) |
| Directory layout | [../FOLDER_TREE.md](../FOLDER_TREE.md) |
| AI-assistant quick facts + gotchas (entry point) | [../AGENTS.md](../AGENTS.md) |
| Installation (conda envs, submodules, prerequisites) | [../README.md](../README.md) |

## The 10-second version

`main.py` is a Quart server on port 5000. Chat platforms → Social Stream Ninja →
(optional Laya pre-filter) → `POST /chat` → guards → wake-word gate → phrase interceptors →
Ollama LLM → response → TTS server writes a WAV → AudioPlayer / Neurosync watcher_to_face →
Unreal avatar (OSC + LiveLink) + chat outbound (SSN). `config.py` is the single source of
truth for all settings and is regex-rewritten in place by `POST /api/settings` so every
process stays in sync. `gui.py` launches and configures everything.