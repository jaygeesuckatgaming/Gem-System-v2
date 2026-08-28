"""
Configuration and Settings - EXAMPLE
Copy this file to config.py and fill in your own values.
"""

# Ollama LLM
OLLAMA_MODEL = "gemma4:31b-cloud"
OLLAMA_BASE_URL = "http://localhost:11434"

# Social Stream Ninja
SSN_API_URL = "https://io.socialstream.ninja"
SSN_SESSION_ID = ""  # YOUR_SESSION_ID_HERE
SSN_TARGETS = ["discord", "twitch", "youtube"]

# Cognee Memory
COGNEE_SERVER_URL = "http://127.0.0.1:8011"

# StyleTTS2
TTS_ENABLED = False
TTS_URL = "http://127.0.0.1:13300/tts"
TTS_DIFFUSION_STEPS = 20
TTS_EMBEDDING_SCALE = 1.0
TTS_ALPHA = 0.3
TTS_BETA = 0.7
TTS_REFERENCE_VOICE = "../reference_voices/earn_lucky_pitch_minus_one_samplerate_24000_short.wav"

# Audio Player (plays TTS output when not using Neurosync)
AUDIO_PLAYER_ENABLED = True
TTS_OUTPUT_PATH = "tts_output/server_output.wav"
AUDIO_OUTPUT_DEVICE = ""  # Empty = system default

# Audio Ducking (lower music volume when TTS speaks)
AUDIO_DUCKING_ENABLED = False
AUDIO_DUCK_AMOUNT = -15
AUDIO_DUCK_ATTACK_MS = 100
AUDIO_DUCK_RELEASE_MS = 500

# Neurosync Blendshapes
BLENDSHAPE_MOUTH_SCALE = 1.0
BLENDSHAPE_EYE_SCALE = 1.0
BLENDSHAPE_EYEBROW_SCALE = 0.6
BLENDSHAPE_EYEWIDE_SCALE = 0.4
BLENDSHAPE_EYESQUINT_SCALE = 1.0

# OSC (emotes + movement)
OSC_ENABLED = True
OSC_IP = "127.0.0.1"
OSC_PORT = 10000
OSC_ADDRESS = "/chat/message"

# Twitch Music Check (verify songs against Twitch DJ Program)
TWITCH_MUSIC_CHECK_ENABLED = True

# Voice input speaker name (used for memory storage of microphone input)
VOICE_SPEAKER_NAME = "JayGee"

# OpenCode API
OPENCODE_ENABLED = True
OPENCODE_API_URL = "http://localhost:4096"
OPENCODE_WORKSPACE = "C:/Users/jayge/Documents/AI/Gem-System-v2"

# Server
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 5000

# System Prompt
SYSTEM_PROMPT = """You are Gem.
Your persona is a 35-year-old human woman from Pattaya, Thailand, who is a guest on a YouTube live stream.
You should speak casually and directly.
You can be sarcastic and are not afraid to use light swearing or profanity.
Keep your answers concise, direct, and in character.
Do not act like a typical AI assistant.
Do not use roleplay actions, asterisks, or describe physical movements like *adjusts* or *leans*. Just speak normally.
Do not say things like "If my data is correct" or "According to my records" - just answer naturally as if you remember it yourself.
"""

# Wake Words
WAKE_WORDS = ["gem", "hey gem", "ok gem"]

# Stop words for entity extraction (common words to ignore)
STOP_WORDS = [
    'what', 'who', 'where', 'when', 'why', 'how', 'the', 'and', 'but', 'or',
    'not', 'you', 'your', 'my', 'our', 'their', 'his', 'her', 'its', 'i', 'we',
    'they', 'he', 'she', 'it', 'am', 'is', 'are', 'was', 'were', 'be', 'been',
    'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
    'should', 'may', 'might', 'must', 'can', 'need', 'dare', 'ought', 'used',
    'going', 'come', 'know', 'think', 'see', 'look', 'want', 'like', 'love',
    'hate', 'get', 'put', 'set', 'run', 'move', 'live', 'believe', 'hold',
    'bring', 'happen', 'write', 'provide', 'sit', 'stand', 'lose', 'pay', 'meet',
    'include', 'continue', 'learn', 'change', 'lead', 'understand', 'watch',
    'follow', 'stop', 'create', 'speak', 'read', 'allow', 'add', 'spend', 'grow',
    'open', 'walk', 'win', 'offer', 'remember', 'consider', 'appear', 'buy',
    'wait', 'serve', 'die', 'send', 'expect', 'build', 'stay', 'fall', 'cut',
    'reach', 'kill', 'remain', 'suggest', 'raise', 'pass', 'sell', 'require',
    'report', 'decide', 'pull'
]
