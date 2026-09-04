<div align="center">

# Gem-System-v2

**Windows Installation:**

**Pre requirements**
</div>
**For sound routing install [Voicemeter Banana](https://vb-audio.com/Voicemeeter/banana.htm)**

**For chat routing install [Social Stream Ninja](https://github.com/steveseguin/social_stream/releases)**

**For Ollama models you need [Ollama](https://ollama.com/download/OllamaSetup.exe)**

***Note for ollama you can use ollama for the cloud models by for example running ollama run gemma4:31b-cloud**

  
  

**Gem-System-v2 (Main System)**

cd to were you want to install it

conda create --name mcp_env_2 python=Python 3.11.15 -y

conda activate mcp_env_2

git clone [https://github.com/jaygeesuckatgaming/Gem-System-v2.git](https://github.com/jaygeesuckatgaming/Gem-System-v2.git)

cd to /Gem-System-V2/

Rename config_example.py to config.py

  

**Cognee** **(Memory)**

conda create --name cognee python=Python 3.11.15 -y

conda activate cognee

_pip install cognee_

  

**Neurosync** **(LiveLink/Blendshapes)**

cd to /Gem-System-V2/

create a folder called Neurosync

cd to /Gem-System-V2/Neurosync

git clone [https://github.com/jaygeesuckatgaming/NeuroSync_Player.git](https://github.com/jaygeesuckatgaming/NeuroSync_Player.git)

git clone [https://github.com/jaygeesuckatgaming/NeuroSync_Local_API.git](https://github.com/jaygeesuckatgaming/NeuroSync_Local_API.git)

You also need to download the [transformer](https://huggingface.co/convaitech/NEUROSYNC/blob/main/model.pth) to

\Gem-System-v2\Neurosync\NeuroSync_Local_API\utils\model

  
  

  
  

  
  

  
  

**StyleTTS2**

conda create --name styletts2 python=Python 3.11.15 -y

conda activate styletts2

cd to \Gem-System-v2\tts

git clone [https://github.com/jaygeesuckatgaming/StyleTTS2.git](https://github.com/jaygeesuckatgaming/StyleTTS2.git)

Additional steps for styletts2

you need to install espeak [http://sourceforge.net/projects/espeak/files/espeak/espeak-1.48/setup_espeak-1.48.04.exe](http://sourceforge.net/projects/espeak/files/espeak/espeak-1.48/setup_espeak-1.48.04.exe)

After installing espeak you have to edit your enviroment settings
![After installing espeak you have to edit your enviroment settings](https://i.ibb.co/JwMY8Pgw/2026-09-04-185542.png)

  

To start it all up go to \Gem-System-v2\start_scripts and run start_gui.bat

Now you have to set your basic settings for thr different modules.

When everything is set start by clicking on

1. Start Cognee Server

2. Start MCP Server

3. If you want TTS I suggest using StyleTTS2 just click on Start StyleTTS2

4. For TTS audio playback if you don’t want to use Neurosync click the Enable Audio Player in the TTS Tab. If using Neurosync keep that off.

5. If you want Livelink Blendshapes go to the Neurosync Tab

1. Click Start Local API

2. Click Start Watcher To Face

  
  

  
  

  
  

  
  

  
  

  
  

  
  

# Gem-System v2 — Folder Tree

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

## Notes

-   **config.py** is the single source of truth for settings (Rename config_example.py to config.py).
    
-   **Submodules** (tts/pocket-tts, tts/StyleTTS2, Neurosync/*) are separate git repos.
    
-   **Runtime state files** (background_state.json, now_playing_state.txt) are gitignored.
    
-   **Large binaries** (downloaded music, TTS output, reference voices) are gitignored.

