# Gem-System v2 — Folder Tree

```
Gem-System-v2/
├── .gitignore
├── .project_root
├── README.md
├── FOLDER_TREE.md
├── config.py                      # Single source of truth for all settings (gitignored)
├── config_example.py              # Example config template
├── main.py                        # Main Quart server (HTTP API + message routing)
├── gui.py                         # Control panel GUI (customtkinter)
├── ssn_relay.py                   # Local Social Stream Ninja relay server
├── vision.py                      # Vision service (NDI / camera)
├── test_ollama.py
├── test_ssn_relay.py
├── requirements.txt
├── mcp_settings.ini               # Legacy settings (being migrated to config.py)
│
├── clients/                       # Client integrations
│   ├── __init__.py
│   ├── audio_player.py            # Plays TTS output
│   ├── cognee_client.py           # Cognee memory HTTP client
│   ├── llm_client.py              # LLM (Ollama) client
│   ├── music_client.py            # Music requests / downloads / playback
│   ├── opencode_client.py         # OpenCode integration
│   ├── ssn_client.py              # Social Stream Ninja client
│   ├── tts_client.py              # TTS client
│   ├── vision_client.py           # Vision client
│   ├── listen.py                  # Audio listener (Whisper STT)
│   └── listen.ini
│
├── music/                         # Music subsystem
│   ├── download_worker.py         # yt-dlp download worker
│   ├── dual_audio_player.py       # Dual-track (karaoke) player
│   ├── headless_dual_audio.py     # Headless sounddevice player
│   ├── song_library.py            # Karaoke song library
│   ├── song_wakeword.py           # Song wakeword handler
│   ├── twitch_music_checker.py    # Twitch DJ Program restrictions
│   ├── requests/                  # Downloaded MP3 requests (gitignored)
│   │   └── karaoke/               # Karaoke dual-track songs (gitignored)
│   └── background_songs/          # Background music (gitignored)
│
├── extras/                        # Extra tools (Extras tab)
│   ├── __init__.py
│   ├── gpu_viz.py                 # Hardware monitor (GPU/CPU/RAM graphs)
│   └── now_playing.py             # Now-playing overlay (OBS capture)
│
├── cognee/                        # Cognee memory server
│   ├── cognee_server.py
│   └── .env.example
│
├── cognee_data/                   # Cognee memory data (gitignored)
├── cognee_system/                 # Cognee system databases (gitignored)
│   └── databases/
│
├── tts/                           # Text-to-speech engines
│   ├── pocket-tts/                # Pocket TTS (submodule)
│   ├── StyleTTS2/                 # StyleTTS2 (submodule)
│   └── reference_voices/          # Reference voice audio (gitignored)
│
├── tts_output/                    # Generated TTS audio (gitignored)
│
├── Neurosync/                     # Face animation (submodules)
│   ├── NeuroSync_Local_API/       # Local API server
│   └── NeuroSync_Player/          # Player / watcher-to-face
│
├── Docs/                          # Documentation
│
└── start_scripts/                 # Launcher batch scripts
    ├── start_cognee.bat
    ├── start_gui.bat
    ├── start_listen.bat
    ├── start_mcp.bat
    ├── start_mcp_prompt.bat
    ├── start_neurosync_localapi.bat
    ├── start_neurosync_watcher_to_face.bat
    ├── start_pockettts.bat
    ├── start_pockettts - CLI.bat
    ├── start_ssn_relay.bat
    ├── start_styletts2.bat
    ├── start_vision.bat
    └── start_GPU_Viz.bat
```

## Notes

- **`config.py`** is the single source of truth for settings (gitignored — copy from `config_example.py`).
- **Submodules** (`tts/pocket-tts`, `tts/StyleTTS2`, `Neurosync/*`) are separate git repos.
- **Runtime state files** (`background_state.json`, `now_playing_state.txt`) are gitignored.
- **Large binaries** (downloaded music, TTS output, reference voices) are gitignored.
