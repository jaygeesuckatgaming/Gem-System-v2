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

# TTS Engine Selection: "styletts2", "pocket", or "vibevoice"
TTS_ENGINE = "styletts2"

# StyleTTS2
TTS_ENABLED = True
SEND_RESPONSES_TO_CHAT = True   # If False, responses go to TTS only (not chat)
TTS_URL = "http://127.0.0.1:13300/tts"
TTS_DIFFUSION_STEPS = 20
TTS_EMBEDDING_SCALE = 1.0
TTS_ALPHA = 0.3
TTS_BETA = 0.7
TTS_REFERENCE_VOICE = ""  # Path to a reference voice .wav file
TTS_COPY_TO = ""  # Network share to copy generated audio to (empty = disabled)

# Pocket TTS
POCKET_TTS_URL = "http://127.0.0.1:13301/tts"

# VibeVoice
VIBEVOICE_TTS_URL = "http://127.0.0.1:13000/tts"
VIBEVOICE_MODEL = "microsoft/VibeVoice-1.5B"
VIBEVOICE_INFERENCE_STEPS = 5
VIBEVOICE_NUM_SPEAKERS = 1
VIBEVOICE_CFG_SCALE = 1.3

# Qwen3-TTS
QWEN_TTS_URL = "http://127.0.0.1:13302/tts"

# Audio Player (plays TTS output when not using Neurosync)
AUDIO_PLAYER_ENABLED = True
TTS_OUTPUT_PATH = "tts_output/server_output.wav"
AUDIO_OUTPUT_DEVICE = ""  # Empty = system default
AUDIO_INPUT_DEVICE = ""   # Empty = not set
MUSIC_OUTPUT_DEVICE = ""  # Separate output device for music (empty = use AUDIO_OUTPUT_DEVICE)

# Audio Ducking (lower music volume when TTS speaks)
AUDIO_DUCKING_ENABLED = False
AUDIO_DUCK_AMOUNT = -15
AUDIO_DUCK_ATTACK_MS = 100
AUDIO_DUCK_RELEASE_MS = 500
AUDIO_DUCK_DELAY_S = 0.5   # Delay (seconds) after synthesis before ducking, to align with playback start
AUDIO_DUCK_HOLD_S = 1.0    # Extra time (seconds) to keep music ducked after speech ends

# STT (Speech-to-Text / microphone listener)
STT_WHISPER_MODEL = "base.en"
STT_VAD_AGGRESSIVENESS = 1
STT_SILENCE_THRESHOLD_S = 2.0
STT_PRE_BUFFER_S = 0.5
STT_MIN_DB = -40.0   # Energy gate: audio below this dB level is ignored (matches the VU meter)

# Background music / playlist volume (0.0 - 1.0)
BACKGROUND_VOLUME = 0.5

# Neurosync Blendshapes
BLENDSHAPE_MOUTH_SCALE = 1.0
BLENDSHAPE_EYE_SCALE = 1.0
BLENDSHAPE_EYEBROW_SCALE = 0.6
BLENDSHAPE_EYEWIDE_SCALE = 0.4
BLENDSHAPE_EYESQUINT_SCALE = 1.0

# Neurosync API
NEUROSYNC_LOCAL_URL = "http://127.0.0.1:9000/audio_to_blendshapes"
NEUROSYNC_API_KEY = "YOUR-NEUROSYNC-API-KEY"
NEUROSYNC_REMOTE_URL = "https://api.neurosync.info/audio_to_blendshapes"

# OSC (emotes + movement)
OSC_ENABLED = True
OSC_IP = "127.0.0.1"
OSC_PORT = 10000
OSC_ADDRESS = "/chat/message"

# LiveLink (Unreal Engine facial animation)
LIVELINK_IP = "127.0.0.1"
LIVELINK_PORT = 11111

# Custom OSC actions (phrase -> OSC address + value)
# Each action: {"phrase": "turn off light 1", "address": "/light/1", "value": "off"}
OSC_ACTIONS = []

# Avatar pose/state system: the LLM can change its physical state via [ACTION: X] tags.
# The base pose is "sitting" (idle); the rest mirror the OSC custom action values.
AVATAR_BASE_POSE = "sitting"
# Poses that persist (continuous, e.g. dancing). One-shot gestures revert to base pose.
AVATAR_PERSISTENT_POSES = ["dance1", "dance", "dancing", "stop dancing"]
AVATAR_ACTION_TAG_ENABLED = True   # Parse [ACTION: x] tags from LLM responses
# Talking animation: sent via OSC when the avatar starts/stops speaking
AVATAR_TALK_ANIMATION = "play_talking_animation"
AVATAR_TALK_OSC_ADDRESS = "/chat/message"
AVATAR_TALK_STOP_ANIMATION = "idle"   # OSC value sent when the avatar finishes speaking
AVATAR_TALK_START_DELAY_S = 0.0       # Delay (s) before sending the "start talking" animation
AVATAR_TALK_STOP_DELAY_S = 0.0        # Extra delay (s) before sending the "stop talking" animation

# Idle Actions (autonomous behavior when chat goes quiet)
IDLE_ACTIONS_ENABLED = True
IDLE_INACTIVITY_LIMIT = 60        # Seconds of silence before entering idle state
IDLE_COOLDOWN = 180               # Seconds between idle monologues (avoid spam)
IDLE_OSC_STATE_ADDRESS = "/vtuber/state"     # OSC address for idle/normal state
IDLE_OSC_ACTION_ADDRESS = "/vtuber/action"   # OSC address for talking animation
IDLE_OSC_BORED_VALUE = "bored"
IDLE_OSC_NORMAL_VALUE = "normal"
IDLE_OSC_TALK_VALUE = "talk_thoughtful"
IDLE_OSC_IDLE_VALUE = "idle"
IDLE_TOPICS = [
    "Complain about how weird humans are.",
    "Talk about a random shower thought or philosophical paradox.",
    "Talk about what you were doing before the stream started.",
    "Bring up a random conspiracy theory about video game NPCs.",
    "Ask a random rhetorical question to the silent chat.",
]
IDLE_MONOLOGUE_PROMPT = (
    "Bring up this topic in character, as if it just popped into your head. "
    "Do NOT mention the chat, the stream, or that it's quiet - just start "
    "talking about the topic directly. Speak naturally and conversationally, "
    "as if thinking out loud to yourself. Expand on the topic with a few "
    "sentences (around 3 to 5 sentences), sharing your thoughts, opinions, or "
    "a little story. Don't just state one line and stop - keep it flowing "
    "like a casual ramble. "
    "Topic focus: {topic}"
)

# Twitch Music Check (verify songs against Twitch DJ Program)
TWITCH_MUSIC_CHECK_ENABLED = True

# Laya Fast-Lane Pre-Filter (classifies chat + sends OSC body cues before the LLM)
LAYA_ENABLED = True
LAYA_URL = "http://127.0.0.1:5000/chat"   # Main server endpoint to forward approved messages to
LAYA_ANIMATION_THRESHOLD = 0.75           # Confidence needed to send a non-idle OSC cue
LAYA_REPLY_THRESHOLD = 0.70               # Probability needed to forward a message to the LLM
LAYA_OSC_ADDRESS = "/avatar/command"      # OSC address for body cues
LAYA_ANIMATION_OPTIONS = ["wave", "cheer", "lurk", "blush", "facepalm", "scared", "laugh", "glare", "mindblown", "idle"]
# Per-animation OSC mapping (animation name -> specific OSC address + value).
# Each entry: {"animation": "wave", "address": "/avatar/command", "value": "wave"}
# If an animation is not listed, falls back to LAYA_OSC_ADDRESS + animation name.
LAYA_ANIMATION_MAP = []

# Voice input speaker name (used for memory storage of microphone input)
VOICE_SPEAKER_NAME = "JayGee"

# Browser-Use (visible browser agent, captured by OBS for the stream)
BROWSER_ENABLED = False
BROWSER_LLM_PROVIDER = 'ollama'          # "ollama" (local) or "openai"
BROWSER_OPENAI_MODEL = 'gpt-4o'
BROWSER_OPENAI_API_KEY = ''              # only needed if provider == "openai"
BROWSER_HEADLESS = False                 # False = visible window for stream capture
BROWSER_VIEWPORT_WIDTH = 1280
BROWSER_VIEWPORT_HEIGHT = 720
# Blocked terms/domains the browser agent may not navigate to (case-insensitive).
# Add porn, gambling, malware, and other disallowed sites/keywords here.
BROWSER_BLOCKED_TERMS = [
    'pornhub', 'xvideos', 'xnxx', 'redtube', 'youporn', 'onlyfans',
    'chaturbate', 'porn', 'xxx', 'nsfw', 'hentai', 'adult',
    'gambling', 'casino', 'bet365', 'betway', 'stake',
    'malware', 'phishing', 'ransomware',
]

# OpenCode API
OPENCODE_ENABLED = True
OPENCODE_API_URL = "http://localhost:4096"
OPENCODE_WORKSPACE = ""  # Path to your project workspace

# Vision Service
VISION_ENABLED = True
VISION_SCAN_URL = "http://127.0.0.1:5001/scan"
VISION_GET_IMAGE_URL = "http://127.0.0.1:5001/get_image"
VISION_TRIGGER_WORDS = ["see", "describe", "analyze", "scan", "what is in", "what's in"]
VISION_IMAGE_SOURCE = "cam"
VISION_CAMERA_INDEX = 0
VISION_NDI_SOURCE_NAME = ""

# Weather (Open-Meteo, no API key)
WEATHER_LATITUDE = 12.9276    # Pattaya, Thailand
WEATHER_LONGITUDE = 100.8826

# Game Agent (autonomous gameplay via vision + LLM + OSC)
GAME_AGENT_ENABLED = False
GAME_AGENT_INTERVAL_S = 1.0
GAME_AGENT_MOVE_ADDRESS = "/agent/move"
GAME_AGENT_TURN_ADDRESS = "/agent/turn"
GAME_AGENT_SYSTEM_PROMPT = (
    "You are an AI agent controlling a character in a simple game. You see a "
    "screenshot of the game. Decide how to move and reply with EXACTLY one line "
    "in this format, no extra text:\n"
    "MOVE: <forward|back|stop>  TURN: <left|right|stop>\n"
    "Choose based on what would let the character walk around and avoid obstacles."
)

# Server
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 5000
SERVER_BIND_HOST = "0.0.0.0"   # Bind address for app.run (0.0.0.0 = accept cross-machine requests)

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

# Chat emote meanings (translated before sending to LLM)
EMOTE_MEANINGS = {
    "kappa": "sarcasm/joking",
    "pogchamp": "excitement/amazement",
    "pog": "excitement/amazement",
    "lul": "laughing",
    "lol": "laughing",
    "lmao": "laughing hard",
    "rofl": "laughing hard",
    "kekw": "laughing",
    "omegalul": "laughing hard",
    "monkas": "nervous/anxious",
    "monkaw": "nervous/anxious",
    "sadge": "sad",
    "feelsbadman": "sad/disappointed",
    "feelsgoodman": "happy",
    "pepehands": "crying/sad",
    "pepega": "silly/stupid",
    "4head": "obvious/duh",
    "5head": "clever/smart",
    "gachihyper": "excited",
    "biblethump": "emotional/crying",
    "wutface": "confused",
    "notlikethis": "frustrated",
    "residentsleeper": "bored",
    "poggers": "excited",
    "hype": "excited",
    "gg": "good game",
    "ez": "easy/trash talk",
    "clap": "applause",
    "prayge": "praying/hoping",
    "copium": "denial/hopeful",
    "based": "agreeable/respectable",
    "cringe": "embarrassing",
    "sus": "suspicious",
    "ratio": "disagreement",
    "w": "win/approval",
    "l": "loss/disapproval",
    "f": "paying respects",
    "kreygasm": "excitement",
    "trihard": "trying hard",
    "jebaited": "tricked",
    "gachi": "excited",
    "weirdchamp": "weird/disapproval",
    "yikes": "cringe/awkward",
    "bruh": "disbelief",
    "sheesh": "impressed",
    "noice": "nice",
    "dansgame": "disgusted",
    "babyrage": "angry",
    "angry": "angry",
    "sad": "sad",
    "happy": "happy",
    "love": "love",
    "heart": "love",
    "fire": "awesome",
    "100": "perfect/agreement",
    "ok": "okay",
    "yes": "yes",
    "no": "no",
}

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
