# Gem-System-v2

**Windows Installation:**

**Pre requirements**

**For sound routing install [Voicemeter Banana**](https://vb-audio.com/Voicemeeter/banana.htm)

**For chat routing install [Social Stream Ninja**](https://github.com/steveseguin/social_stream/releases)

**For Ollama models you need [Ollama**](https://ollama.com/download/OllamaSetup.exe)

**\*Note for ollama you can use ollama for the cloud models by for example running ollama run gemma4:31b-cloud**


**Gem-System-v2 (Main System)**

cd to were you want to install it

conda create --name mcp\_env\_2 python=Python 3.11.15 -y

conda activate mcp\_env\_2

git clone [https://github.com/jaygeesuckatgaming/Gem-System-v2.git](https://github.com/jaygeesuckatgaming/Gem-System-v2.git)

cd to /Gem-System-V2/

Rename config\_example.py to config.py


**Cognee (Memory)**

conda create --name cognee python=Python 3.11.15 -y

conda activate cognee

```
***pip install cognee***
```


**Neurosync (LiveLink/Blendshapes)**

cd to /Gem-System-V2/

create a folder called Neurosync

cd to /Gem-System-V2/Neurosync

git clone [https://github.com/jaygeesuckatgaming/NeuroSync\_Player.git](https://github.com/jaygeesuckatgaming/NeuroSync_Player.git)

git clone [https://github.com/jaygeesuckatgaming/NeuroSync\_Local\_API.git](https://github.com/jaygeesuckatgaming/NeuroSync_Local_API.git)

You also need to download the [transformer](https://huggingface.co/convaitech/NEUROSYNC/blob/main/model.pth) to 

\\Gem-System-v2\\Neurosync\\NeuroSync\_Local\_API\\utils\\model





**StyleTTS2**

conda create --name styletts2 python=Python 3.11.15 -y

conda activate styletts2

cd to \\Gem-System-v2\\tts

git clone [https://github.com/jaygeesuckatgaming/StyleTTS2.git](https://github.com/jaygeesuckatgaming/StyleTTS2.git)

Additional steps for styletts2

you need to install espeak [http://sourceforge.net/projects/espeak/files/espeak/espeak-1.48/setup\_espeak-1.48.04.exe](http://sourceforge.net/projects/espeak/files/espeak/espeak-1.48/setup_espeak-1.48.04.exe)

After installing espeak you have to edit your enviroment settings


To start it all up go to \\Gem-System-v2\\start\_scripts and run start\_gui.bat

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

```
Gem-System-v2/  
├── .gitignore  
├── .project\_root  
├── README.md  
├── FOLDER\_TREE.md  
├── config.py                      \# Single source of truth for all settings (gitignored)  
├── config\_example.py              \# Example config template  
├── main.py                        \# Main Quart server (HTTP API + message routing)  
├── gui.py                         \# Control panel GUI (customtkinter)  
├── ssn\_relay.py                   \# Local Social Stream Ninja relay server  
├── vision.py                      \# Vision service (NDI / camera)  
├── test\_ollama.py  
├── test\_ssn\_relay.py  
├── requirements.txt  
├── mcp\_settings.ini               \# Legacy settings (being migrated to config.py)  
│  
├── clients/                       \# Client integrations  
│   ├── \_\_init\_\_.py  
│   ├── audio\_player.py            \# Plays TTS output  
│   ├── cognee\_client.py           \# Cognee memory HTTP client  
│   ├── llm\_client.py              \# LLM (Ollama) client  
│   ├── music\_client.py            \# Music requests / downloads / playback  
│   ├── opencode\_client.py         \# OpenCode integration  
│   ├── ssn\_client.py              \# Social Stream Ninja client  
│   ├── tts\_client.py              \# TTS client  
│   ├── vision\_client.py           \# Vision client  
│   ├── listen.py                  \# Audio listener (Whisper STT)  
│   └── listen.ini  
│  
├── music/                         \# Music subsystem  
│   ├── download\_worker.py         \# yt-dlp download worker  
│   ├── dual\_audio\_player.py       \# Dual-track (karaoke) player  
│   ├── headless\_dual\_audio.py     \# Headless sounddevice player  
│   ├── song\_library.py            \# Karaoke song library  
│   ├── song\_wakeword.py           \# Song wakeword handler  
│   ├── twitch\_music\_checker.py    \# Twitch DJ Program restrictions  
│   ├── requests/                  \# Downloaded MP3 requests (gitignored)  
│   │   └── karaoke/               \# Karaoke dual-track songs (gitignored)  
│   └── background\_songs/          \# Background music (gitignored)  
│  
├── extras/                        \# Extra tools (Extras tab)  
│   ├── \_\_init\_\_.py  
│   ├── gpu\_viz.py                 \# Hardware monitor (GPU/CPU/RAM graphs)  
│   └── now\_playing.py             \# Now-playing overlay (OBS capture)  
│  
├── cognee/                        \# Cognee memory server  
│   ├── cognee\_server.py  
│   └── .env.example  
│  
├── cognee\_data/                   \# Cognee memory data (gitignored)  
├── cognee\_system/                 \# Cognee system databases (gitignored)  
│   └── databases/  
│  
├── tts/                           \# Text-to-speech engines  
│   ├── pocket-tts/                \# Pocket TTS (submodule)  
│   ├── StyleTTS2/                 \# StyleTTS2 (submodule)  
│   └── reference\_voices/          \# Reference voice audio (gitignored)  
│  
├── tts\_output/                    \# Generated TTS audio (gitignored)  
│  
├── Neurosync/                     \# Face animation (submodules)  
│   ├── NeuroSync\_Local\_API/       \# Local API server  
│   └── NeuroSync\_Player/          \# Player / watcher-to-face  
│  
├── Docs/                          \# Documentation  
│  
└── start\_scripts/                 \# Launcher batch scripts  
    ├── start\_cognee.bat  
    ├── start\_gui.bat  
    ├── start\_listen.bat  
    ├── start\_mcp.bat  
    ├── start\_mcp\_prompt.bat  
    ├── start\_neurosync\_localapi.bat  
    ├── start\_neurosync\_watcher\_to\_face.bat  
    ├── start\_pockettts.bat  
    ├── start\_pockettts - CLI.bat  
    ├── start\_ssn\_relay.bat  
    ├── start\_styletts2.bat  
    ├── start\_vision.bat  
    └── start\_GPU\_Viz.bat
```

## Notes

- **`config.py`** is the single source of truth for settings (Rename `config\_example.py to config.py`).

- **Submodules** (`tts/pocket-tts`, `tts/StyleTTS2`, `Neurosync/\*`) are separate git repos.

- **Runtime state files** (`background\_state.json`, `now\_playing\_state.txt`) are gitignored.

- **Large binaries** (downloaded music, TTS output, reference voices) are gitignored.


