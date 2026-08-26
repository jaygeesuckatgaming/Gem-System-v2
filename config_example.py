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
