# Repos — What Lives Where

**Audience:** AI coding assistants + maintainer. **Answers:** "which repo is that, what branch,
where does it push, and what is it for?"

Last verified: 2026-11-03.

## Active (the current layout)

```
C:\Users\jayge\Documents\AI
├── Gem-System-v2
└── m8_games
    ├── m8
    ├── OpenCE
    └── hlsdk-portable
```

| Repo | Branch | Origin | Purpose |
|---|---|---|---|
| `Gem-System-v2` | `main` | `jaygeesuckatgaming/Gem-System-v2` | The panel (`:8080`), `main.py` (`:5000`), Laya (`:5002`), Whisper (`:13310`), the m8 TTS adapter (`:8091`), the Cognee server (`:8011`) and these docs |
| `m8_games/m8` | `gem-m8` | `jaygeesuckatgaming/m8` (fork of `chasmlol/m8`) | The **brain**: game link (`:47800`), persona/prompts, memory, eyes (`:8090`), decisions/LLM/TTS orchestration. Started by `start-m8.bat` (“m8 - Gem Brain”) |
| `m8_games/OpenCE` | `m8-kevin` | `jaygeesuckatgaming/OpenCE` (fork of `OpenCommunityEdition/OpenCE`) | The **Halo engine** + companion (`build/windows/halo.exe`); the 1.8 GB maps are in `data/` |
| `m8_games/hlsdk-portable` | `gem-hlm8` | `jaygeesuckatgaming/hlsdk-portable` (fork of `FWGS/hlsdk-portable`) | The **Half-Life/GoldSrc mod** (server link + follower, client voice + eyes); installed into the Steam `Half-Life/hlm8` folder |

Nested engine repos these use:

| Repo | Branch | Origin | Note |
|---|---|---|---|
| `Gem-System-v2/tts/StyleTTS2` | `main` | `jaygeesuckatgaming/StyleTTS2` | The voice engine (`:13300`); gitignored by `Gem-System-v2`, but required |
| `m8_games/hlsdk-portable/freevgui` | submodule | `FWGS/freevgui` | The SDK's GUI library; initialise with `git submodule update --init --recursive` |

## Not repos (services, pip packages, external)

- **Ollama** (`:11434`, the server PC) — LLM + vision for m8; `main.py` has its own chat model.
- **Cognee** — the pip package behind `Gem-System-v2/cognee/cognee_server.py` (memory `:8011`).
- **faster-whisper** — the package behind `clients/whisper_server.py`.
- **Social Stream Ninja** — the browser extension / cloud relay; its local relay is `ssn_relay.py` in Gem-System-v2.
- **OBS + Voicemeeter**, the **Unreal avatar** project, and the **Steam Half-Life install** — outside this tree.

## Archived (not used by the panel; the GitHub repos remain)

All under `C:\Users\jayge\Documents\AI\_archive\`:

- `chasm-20261103` — the legacy NPC backend (`:7341`, profile + 6-verb action book) and its
  Parakeet engine. Stopped and moved 2026-11-03.
- `xbox-OpenCE-20261103` — the legacy `chasm-bridge` source (its maps were moved to
  `m8_games/OpenCE/data` before archiving).
- `chasm-bridge-fnv-20261103` — the Fallout: New Vegas experiment.
- `Not_Used-20261103` — the old "not used" pile (`ollama-log-proxy_org`, `releases`).
- `AI-clean-20261103/` — the old m8 (with its `halo/` clone) and the old working hlsdk clone
  (`hlsdk-mate`; its `gem-hlm8` is now on `jaygeesuckatgaming/hlsdk-portable`).
- `xbox-OpenCE-build-20261103` — the old OpenCE build/artifacts.
- `m8-fork`, `Gem-System`, `Old_Stuff`, `opence-gem`, `chasm_system` — older copies.

`xbox\` itself stays: it holds the Halo ISO/extract tools and `vJoySetup.exe`, not a repo.

## Remotes worth knowing

- The two game forks and the m8 fork are **your forks**; their upstreams are
  `OpenCommunityEdition/OpenCE`, `FWGS/hlsdk-portable` and `chasmlol/m8` (the clean clones were
  made from your forks, so `upstream` is not configured in them by default).
- `Gem-System-v2` pushes straight to your repo.
