"""
Gem-System v2 - Main Quart Server
Receives chat from Social Stream Ninja, sends to Ollama, broadcasts response
"""

import asyncio
import html
import json
import os
import re
from collections import deque
from typing import Optional
from datetime import datetime
from zoneinfo import ZoneInfo
from quart import Quart, request, jsonify
from quart_cors import cors

import config
from clients import LLMClient, SSNClient, CogneeClient, TTSClient, MusicClient, OpenCodeClient, VisionClient, WeatherClient
from clients.audio_player import AudioPlayer
from clients.opencode_client import format_opencode_response
from clients.idle_manager import IdleManager
from clients.browser_client import BrowserClient

app = Quart(__name__)
app = cors(app, allow_origin="*")

# Initialize clients
llm = LLMClient(model=config.OLLAMA_MODEL, base_url=config.OLLAMA_BASE_URL)
ssn = SSNClient(api_url=config.SSN_API_URL, session_id=config.SSN_SESSION_ID)
cognee = CogneeClient(server_url=config.COGNEE_SERVER_URL)
def _tts_url_for_engine():
    if config.TTS_ENGINE == "pocket":
        return config.POCKET_TTS_URL
    if config.TTS_ENGINE == "vibevoice":
        return config.VIBEVOICE_TTS_URL
    if config.TTS_ENGINE == "qwen":
        return config.QWEN_TTS_URL
    return config.TTS_URL

tts = TTSClient(tts_url=_tts_url_for_engine())
music = MusicClient(device_name=config.AUDIO_OUTPUT_DEVICE or None)
music.background_volume = getattr(config, 'BACKGROUND_VOLUME', 0.5)
music.music_device_name = getattr(config, 'MUSIC_OUTPUT_DEVICE', '') or None

# Wire the LLM into the Twitch music checker so it can parse song requests
music.twitch_checker.llm_parse_function = llm.chat_sync
opencode = OpenCodeClient(api_url=config.OPENCODE_API_URL, workspace=config.OPENCODE_WORKSPACE)
vision = VisionClient(scan_url=config.VISION_SCAN_URL, get_image_url=config.VISION_GET_IMAGE_URL)
weather = WeatherClient(latitude=config.WEATHER_LATITUDE, longitude=config.WEATHER_LONGITUDE)
browser = BrowserClient(
    provider=getattr(config, 'BROWSER_LLM_PROVIDER', 'ollama'),
    ollama_model=config.OLLAMA_MODEL,
    ollama_host=config.OLLAMA_BASE_URL,
    openai_model=getattr(config, 'BROWSER_OPENAI_MODEL', 'gpt-4o'),
    openai_api_key=getattr(config, 'BROWSER_OPENAI_API_KEY', ''),
    headless=getattr(config, 'BROWSER_HEADLESS', False),
    viewport_width=getattr(config, 'BROWSER_VIEWPORT_WIDTH', 1280),
    viewport_height=getattr(config, 'BROWSER_VIEWPORT_HEIGHT', 720),
)

# Record downloaded songs to memory so Gem remembers them
def _on_download_complete(query: str):
    asyncio.create_task(cognee.remember("Gem", f"Gem downloaded the song: {query}"))

music.on_download_complete = _on_download_complete

# Idle manager (autonomous behavior when chat goes quiet)
idle = IdleManager(
    inactivity_limit=config.IDLE_INACTIVITY_LIMIT,
    cooldown=config.IDLE_COOLDOWN,
    enabled=config.IDLE_ACTIONS_ENABLED,
    osc_state_address=config.IDLE_OSC_STATE_ADDRESS,
    osc_action_address=config.IDLE_OSC_ACTION_ADDRESS,
    osc_bored_value=config.IDLE_OSC_BORED_VALUE,
    osc_normal_value=config.IDLE_OSC_NORMAL_VALUE,
    osc_talk_value=config.IDLE_OSC_TALK_VALUE,
    osc_idle_value=config.IDLE_OSC_IDLE_VALUE,
    topics=config.IDLE_TOPICS,
)
def _idle_send_osc(address: str, value: str):
    # Only send OSC if a value is actually set (empty = skip, to avoid sending
    # blank commands that break other animations).
    if value:
        send_osc_message(address, value)

idle.send_osc = _idle_send_osc


def resume_current_pose():
    """Send the OSC command to return the avatar to its current pose after speaking.
    If the pose is the base 'sitting', send the stop/idle animation instead.
    NOTE: The talking animation is now handled by watcher_to_face (which owns
    actual playback timing). This function is only used for explicit pose changes."""
    global current_pose
    stop_anim = getattr(config, 'AVATAR_TALK_STOP_ANIMATION', 'idle')
    talk_addr = getattr(config, 'AVATAR_TALK_OSC_ADDRESS', config.OSC_ADDRESS)

    pose = current_pose
    if pose in (config.AVATAR_BASE_POSE, 'idle', 'sitting', 'stand', 'standing'):
        send_osc_message(talk_addr, stop_anim)
        return

    # Re-send the current pose's OSC command (e.g. resume dancing)
    for osc_action in config.OSC_ACTIONS:
        if osc_action.get('value', '').lower() == pose.lower():
            send_osc_message(osc_action.get('address', config.OSC_ADDRESS), osc_action.get('value', ''))
            return

    send_osc_message(talk_addr, stop_anim)


async def send_response(response: str):
    """Send a response to TTS and (optionally) to chat.
    Audio ducking + talking animation are driven by watcher_to_face (the process
    that actually plays the audio), so this only handles TTS + chat."""
    if config.TTS_ENABLED:
        await tts.speak(response)

    if config.SEND_RESPONSES_TO_CHAT:
        await ssn.send_message(response, targets=config.SSN_TARGETS)


def _estimate_speech_seconds(text: str) -> float:
    """Rough estimate of speech duration in seconds (~150 words/min)."""
    words = len(text.split())
    if words == 0:
        return 0.0
    return words / 2.5  # ~150 wpm


def _get_tts_wav_seconds() -> float:
    """Return the duration (seconds) of the last TTS output wav, if present."""
    try:
        import soundfile as sf
        path = os.path.join(os.path.dirname(__file__), config.TTS_OUTPUT_PATH)
        if os.path.exists(path):
            info = sf.info(path)
            return float(info.frames) / float(info.samplerate)
    except Exception:
        pass
    return 0.0


async def _get_idle_memories() -> str:
    """Gather recent chat context for the idle monologue.
    Uses the in-memory chat history (reliable) plus cognee recall (if available)."""
    parts = []

    # 1. In-memory recent chat history (always available)
    chat = get_chat_history_context()
    if chat:
        parts.append(chat)

    # 2. Cognee memory recall (best-effort, short timeout)
    try:
        import asyncio
        results = await asyncio.wait_for(
            cognee.recall("memorable moments, jokes, and interesting conversations from chat", top_k=6),
            timeout=2.0
        )
        if results:
            parts.append("Other things you remember:\n" + "\n".join(f"- {r}" for r in results))
    except Exception as e:
        print(f"[IDLE] Memory recall skipped: {e}")

    return "\n\n".join(parts)


async def _idle_monologue(topic: str):
    """Generate and speak an idle monologue via the LLM + TTS."""
    monologue_prompt = config.IDLE_MONOLOGUE_PROMPT.format(topic=topic)
    memory_context = await _get_idle_memories()

    system_prompt = f"{config.SYSTEM_PROMPT}\n\n{monologue_prompt}"
    if memory_context:
        system_prompt = (
            f"{system_prompt}\n\n{memory_context}\n"
            f"Feel free to weave these past chat memories into what you say, "
            f"referencing people, jokes, or events from earlier conversations."
        )

    response = await llm.chat("", system_prompt=system_prompt)
    print(f"[IDLE MONOLOGUE] {response}")

    await cognee.remember("Gem", response)
    _last_ai_responses.append(html.unescape(response).strip())
    add_to_chat_history("Gem", response)

    await send_response(response)


idle.on_monologue = _idle_monologue


def _idle_interrupt():
    """Stop the currently playing monologue audio."""
    audio_player.stop_playback()

idle.on_interrupt = _idle_interrupt

# Audio player (plays TTS output when not using Neurosync)
_tts_output_path = os.path.join(os.path.dirname(__file__), config.TTS_OUTPUT_PATH)
audio_player = AudioPlayer(watch_path=_tts_output_path, device_name=config.AUDIO_OUTPUT_DEVICE or None)

# Let the idle manager know when the VTuber is speaking (to avoid piling up monologues)
idle.is_speaking_check = audio_player.is_playing

# Wire ducking callbacks (lower music volume when TTS speaks)
def _duck_music():
    if config.AUDIO_DUCKING_ENABLED:
        music.duck_music(
            duck_amount=config.AUDIO_DUCK_AMOUNT,
            attack_ms=config.AUDIO_DUCK_ATTACK_MS,
            release_ms=config.AUDIO_DUCK_RELEASE_MS
        )

def _unduck_music():
    if config.AUDIO_DUCKING_ENABLED:
        music.unduck_music(release_ms=config.AUDIO_DUCK_RELEASE_MS)

audio_player.duck_callback = _duck_music
audio_player.unduck_callback = _unduck_music

# Track recent AI responses to prevent echo loops
_last_ai_responses = deque(maxlen=10)

# Pause flag: when True, the MCP ignores incoming chat (acts as a mute/standby)
_paused = False

# Current avatar pose (base is "sitting"). The LLM can change this via [ACTION: x] tags.
current_pose = config.AVATAR_BASE_POSE

# Rolling chat history so the LLM has context of the recent conversation
_recent_chat = deque(maxlen=20)


def add_to_chat_history(speaker: str, text: str):
    """Add a message to the rolling chat history."""
    _recent_chat.append(f"{speaker}: {text}")


def get_chat_history_context() -> str:
    """Return the recent chat history as a context string for the LLM."""
    if not _recent_chat:
        return ""
    return "Recent chat history:\n" + "\n".join(_recent_chat)

# Track known speakers (for nickname resolution)
_known_speakers = set()
_KNOWN_SPEAKERS_FILE = os.path.join(os.path.dirname(__file__), "known_speakers.json")


def load_known_speakers():
    """Load known speakers from file"""
    global _known_speakers
    try:
        if os.path.exists(_KNOWN_SPEAKERS_FILE):
            with open(_KNOWN_SPEAKERS_FILE, "r") as f:
                _known_speakers = set(json.load(f))
    except Exception as e:
        print(f"Failed to load known speakers: {e}")


def save_known_speakers():
    """Save known speakers to file"""
    try:
        with open(_KNOWN_SPEAKERS_FILE, "w") as f:
            json.dump(list(_known_speakers), f)
    except Exception as e:
        print(f"Failed to save known speakers: {e}")


load_known_speakers()

# Settings persistence: config.py is the single source of truth.
# Runtime changes are written back to config.py so all processes read the same values.
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.py")


def save_config():
    """Write current runtime settings back to config.py (single source of truth)."""
    import re
    try:
        with open(CONFIG_FILE, "r") as f:
            content = f.read()

        # Map of setting name -> (value, is_string)
        settings = {
            'TTS_ENGINE': (config.TTS_ENGINE, True),
            'TTS_ENABLED': (config.TTS_ENABLED, False),
            'SEND_RESPONSES_TO_CHAT': (config.SEND_RESPONSES_TO_CHAT, False),
            'TTS_URL': (config.TTS_URL, True),
            'POCKET_TTS_URL': (config.POCKET_TTS_URL, True),
            'VIBEVOICE_TTS_URL': (config.VIBEVOICE_TTS_URL, True),
            'QWEN_TTS_URL': (config.QWEN_TTS_URL, True),
            'VIBEVOICE_MODEL': (config.VIBEVOICE_MODEL, True),
            'VIBEVOICE_INFERENCE_STEPS': (config.VIBEVOICE_INFERENCE_STEPS, False),
            'TTS_DIFFUSION_STEPS': (config.TTS_DIFFUSION_STEPS, False),
            'TTS_EMBEDDING_SCALE': (config.TTS_EMBEDDING_SCALE, False),
            'TTS_ALPHA': (config.TTS_ALPHA, False),
            'TTS_BETA': (config.TTS_BETA, False),
            'TTS_REFERENCE_VOICE': (config.TTS_REFERENCE_VOICE, True),
            'TTS_COPY_TO': (config.TTS_COPY_TO, True),
            'TTS_OUTPUT_PATH': (config.TTS_OUTPUT_PATH, True),
            'AUDIO_PLAYER_ENABLED': (config.AUDIO_PLAYER_ENABLED, False),
            'AUDIO_OUTPUT_DEVICE': (config.AUDIO_OUTPUT_DEVICE, True),
            'MUSIC_OUTPUT_DEVICE': (config.MUSIC_OUTPUT_DEVICE, True),
            'AUDIO_INPUT_DEVICE': (config.AUDIO_INPUT_DEVICE, True),
            'AUDIO_DUCKING_ENABLED': (config.AUDIO_DUCKING_ENABLED, False),
            'AUDIO_DUCK_AMOUNT': (config.AUDIO_DUCK_AMOUNT, False),
            'AUDIO_DUCK_ATTACK_MS': (config.AUDIO_DUCK_ATTACK_MS, False),
            'AUDIO_DUCK_RELEASE_MS': (config.AUDIO_DUCK_RELEASE_MS, False),
            'AUDIO_DUCK_DELAY_S': (config.AUDIO_DUCK_DELAY_S, False),
            'AUDIO_DUCK_HOLD_S': (config.AUDIO_DUCK_HOLD_S, False),
            'AVATAR_TALK_START_DELAY_S': (config.AVATAR_TALK_START_DELAY_S, False),
            'AVATAR_TALK_STOP_DELAY_S': (config.AVATAR_TALK_STOP_DELAY_S, False),
            'STT_WHISPER_MODEL': (config.STT_WHISPER_MODEL, True),
            'STT_VAD_AGGRESSIVENESS': (config.STT_VAD_AGGRESSIVENESS, False),
            'STT_SILENCE_THRESHOLD_S': (config.STT_SILENCE_THRESHOLD_S, False),
            'STT_PRE_BUFFER_S': (config.STT_PRE_BUFFER_S, False),
            'STT_MIN_DB': (config.STT_MIN_DB, False),
            'BACKGROUND_VOLUME': (config.BACKGROUND_VOLUME, False),
            'BLENDSHAPE_MOUTH_SCALE': (config.BLENDSHAPE_MOUTH_SCALE, False),
            'BLENDSHAPE_EYE_SCALE': (config.BLENDSHAPE_EYE_SCALE, False),
            'BLENDSHAPE_EYEBROW_SCALE': (config.BLENDSHAPE_EYEBROW_SCALE, False),
            'BLENDSHAPE_EYEWIDE_SCALE': (config.BLENDSHAPE_EYEWIDE_SCALE, False),
            'BLENDSHAPE_EYESQUINT_SCALE': (config.BLENDSHAPE_EYESQUINT_SCALE, False),
            'OSC_ENABLED': (config.OSC_ENABLED, False),
            'OSC_IP': (config.OSC_IP, True),
            'OSC_PORT': (config.OSC_PORT, False),
            'OSC_ADDRESS': (config.OSC_ADDRESS, True),
            'IDLE_ACTIONS_ENABLED': (config.IDLE_ACTIONS_ENABLED, False),
            'IDLE_INACTIVITY_LIMIT': (config.IDLE_INACTIVITY_LIMIT, False),
            'IDLE_COOLDOWN': (config.IDLE_COOLDOWN, False),
            'IDLE_OSC_STATE_ADDRESS': (config.IDLE_OSC_STATE_ADDRESS, True),
            'IDLE_OSC_ACTION_ADDRESS': (config.IDLE_OSC_ACTION_ADDRESS, True),
            'IDLE_OSC_BORED_VALUE': (config.IDLE_OSC_BORED_VALUE, True),
            'IDLE_OSC_NORMAL_VALUE': (config.IDLE_OSC_NORMAL_VALUE, True),
            'IDLE_OSC_TALK_VALUE': (config.IDLE_OSC_TALK_VALUE, True),
            'IDLE_OSC_IDLE_VALUE': (config.IDLE_OSC_IDLE_VALUE, True),
            'LIVELINK_IP': (config.LIVELINK_IP, True),
            'LIVELINK_PORT': (config.LIVELINK_PORT, False),
            'TWITCH_MUSIC_CHECK_ENABLED': (config.TWITCH_MUSIC_CHECK_ENABLED, False),
            'LAYA_ENABLED': (config.LAYA_ENABLED, False),
            'LAYA_URL': (config.LAYA_URL, True),
            'LAYA_ANIMATION_THRESHOLD': (config.LAYA_ANIMATION_THRESHOLD, False),
            'LAYA_REPLY_THRESHOLD': (config.LAYA_REPLY_THRESHOLD, False),
            'LAYA_OSC_ADDRESS': (config.LAYA_OSC_ADDRESS, True),
            'VOICE_SPEAKER_NAME': (config.VOICE_SPEAKER_NAME, True),
            'OPENCODE_ENABLED': (config.OPENCODE_ENABLED, False),
            'OPENCODE_API_URL': (config.OPENCODE_API_URL, True),
            'OPENCODE_WORKSPACE': (config.OPENCODE_WORKSPACE, True),
            'VISION_ENABLED': (config.VISION_ENABLED, False),
            'VISION_SCAN_URL': (config.VISION_SCAN_URL, True),
            'VISION_GET_IMAGE_URL': (config.VISION_GET_IMAGE_URL, True),
            'VISION_IMAGE_SOURCE': (config.VISION_IMAGE_SOURCE, True),
            'VISION_CAMERA_INDEX': (config.VISION_CAMERA_INDEX, False),
            'VISION_NDI_SOURCE_NAME': (config.VISION_NDI_SOURCE_NAME, True),
            'BROWSER_ENABLED': (config.BROWSER_ENABLED, False),
            'BROWSER_LLM_PROVIDER': (config.BROWSER_LLM_PROVIDER, True),
            'BROWSER_OPENAI_MODEL': (config.BROWSER_OPENAI_MODEL, True),
            'BROWSER_OPENAI_API_KEY': (config.BROWSER_OPENAI_API_KEY, True),
            'BROWSER_HEADLESS': (config.BROWSER_HEADLESS, False),
            'BROWSER_VIEWPORT_WIDTH': (config.BROWSER_VIEWPORT_WIDTH, False),
            'BROWSER_VIEWPORT_HEIGHT': (config.BROWSER_VIEWPORT_HEIGHT, False),
            'GAME_AGENT_ENABLED': (config.GAME_AGENT_ENABLED, False),
            'GAME_AGENT_INTERVAL_S': (config.GAME_AGENT_INTERVAL_S, False),
            'GAME_AGENT_MOVE_ADDRESS': (config.GAME_AGENT_MOVE_ADDRESS, True),
            'GAME_AGENT_TURN_ADDRESS': (config.GAME_AGENT_TURN_ADDRESS, True),
            'SSN_SESSION_ID': (config.SSN_SESSION_ID, True),
            'OLLAMA_MODEL': (config.OLLAMA_MODEL, True),
        }

        for key, (value, is_string) in settings.items():
            if is_string:
                new_value = repr(str(value))
            else:
                new_value = str(value)
            # Replace the assignment line (function replacement avoids escape interpretation)
            pattern = re.compile(rf'^{key}\s*=\s*.*$', re.MULTILINE)
            content = pattern.sub(lambda m, kv=f'{key} = {new_value}': kv, content)

        # Persist SYSTEM_PROMPT (multiline triple-quoted string, handled separately)
        # Use a function replacement so backslashes in the value aren't interpreted as escapes.
        prompt_literal = repr(config.SYSTEM_PROMPT)
        prompt_pattern = re.compile(r'^SYSTEM_PROMPT\s*=\s*""".*?"""\s*$', re.MULTILINE | re.DOTALL)
        if prompt_pattern.search(content):
            content = prompt_pattern.sub(lambda m: f'SYSTEM_PROMPT = {prompt_literal}', content)
        else:
            content += f'\nSYSTEM_PROMPT = {prompt_literal}\n'

        # Persist GAME_AGENT_SYSTEM_PROMPT (multiline, handled separately).
        # Match both parenthesized and plain (single-line) definitions, up to the
        # closing paren or end-of-line, so a rewrite never leaves an orphan.
        game_prompt_literal = repr(config.GAME_AGENT_SYSTEM_PROMPT)
        game_prompt_pattern = re.compile(
            r'^GAME_AGENT_SYSTEM_PROMPT\s*=\s*(?:\([^\n]*\n(?:.*\n)*?\)|.*?)(?=\n#|\n[A-Z_]+|\Z)',
            re.MULTILINE
        )
        if game_prompt_pattern.search(content):
            content = game_prompt_pattern.sub(lambda m: f'GAME_AGENT_SYSTEM_PROMPT = {game_prompt_literal}', content)
        else:
            content += f'\nGAME_AGENT_SYSTEM_PROMPT = {game_prompt_literal}\n'

        # Persist OSC_ACTIONS (a list of dicts, handled separately)
        import pprint
        actions_literal = pprint.pformat(config.OSC_ACTIONS, width=120)
        osc_pattern = re.compile(r'^OSC_ACTIONS\s*=\s*\[.*?\]\s*$', re.MULTILINE | re.DOTALL)
        if osc_pattern.search(content):
            content = osc_pattern.sub(f'OSC_ACTIONS = {actions_literal}', content)
        else:
            content += f'\nOSC_ACTIONS = {actions_literal}\n'

        # Persist LAYA_ANIMATION_MAP (a list of dicts, handled separately)
        laya_map_literal = pprint.pformat(config.LAYA_ANIMATION_MAP, width=120)
        laya_pattern = re.compile(r'^LAYA_ANIMATION_MAP\s*=\s*\[.*?\]\s*$', re.MULTILINE | re.DOTALL)
        if laya_pattern.search(content):
            content = laya_pattern.sub(f'LAYA_ANIMATION_MAP = {laya_map_literal}', content)
        else:
            content += f'\nLAYA_ANIMATION_MAP = {laya_map_literal}\n'

        # Persist LAYA_ANIMATION_OPTIONS (a list of strings, handled separately)
        options_literal = pprint.pformat(config.LAYA_ANIMATION_OPTIONS, width=120)
        options_pattern = re.compile(r'^LAYA_ANIMATION_OPTIONS\s*=\s*\[.*?\]\s*$', re.MULTILINE | re.DOTALL)
        if options_pattern.search(content):
            content = options_pattern.sub(f'LAYA_ANIMATION_OPTIONS = {options_literal}', content)
        else:
            content += f'\nLAYA_ANIMATION_OPTIONS = {options_literal}\n'

        # Persist BROWSER_BLOCKED_TERMS (a list of strings, handled separately)
        blocked_literal = pprint.pformat(config.BROWSER_BLOCKED_TERMS, width=120)
        blocked_pattern = re.compile(r'^BROWSER_BLOCKED_TERMS\s*=\s*\[.*?\]\s*$', re.MULTILINE | re.DOTALL)
        if blocked_pattern.search(content):
            content = blocked_pattern.sub(f'BROWSER_BLOCKED_TERMS = {blocked_literal}', content)
        else:
            content += f'\nBROWSER_BLOCKED_TERMS = {blocked_literal}\n'

        with open(CONFIG_FILE, "w") as f:
            f.write(content)
        print("✓ Settings written to config.py")
    except Exception as e:
        print(f"Failed to save config.py: {e}")


# config.py is the single source of truth - no separate load needed.
# Runtime changes are written back to config.py via save_config().


def extract_song_command(text: str):
    """Extract song name from a song request command.
    Returns the song name, or None if not a song command.
    """
    text_lower = text.lower().strip()
    
    # Remove wake word prefix first
    for word in config.WAKE_WORDS:
        if text_lower.startswith(word.lower()):
            text_lower = text_lower[len(word):].strip()
            break
    
    # Song command patterns
    patterns = [
        "play the song ",
        "sing the song ",
        "download song ",
        "download the song ",
        "get song ",
        "can you play ",
        "play ",
        "sing ",
    ]
    
    for pattern in patterns:
        if text_lower.startswith(pattern):
            song_name = text_lower[len(pattern):].strip()
            if song_name:
                return song_name
    
    return None


def extract_dedication(text: str) -> Optional[str]:
    """Extract a dedication target from a song request (e.g. 'dedicate it to Teenz').
    Returns the dedication name, or None if no dedication.
    """
    import re
    text_lower = text.lower()
    patterns = [
        r'dedicate (?:it|this|the song)?\s*(?:to|for)\s+([a-z0-9_@]+)',
        r'for\s+([a-z0-9_@]+)\s*$',
    ]
    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            name = match.group(1).strip()
            if name:
                return name
    return None


def extract_sing_command(text: str):
    """Extract song name from a 'sing the song' command (karaoke library).
    Returns the song name, or None if not a sing command.
    """
    text_lower = text.lower().strip()
    
    # Remove wake word prefix first
    for word in config.WAKE_WORDS:
        if text_lower.startswith(word.lower()):
            text_lower = text_lower[len(word):].strip()
            break
    
    # Sing command patterns (karaoke library, not download)
    patterns = [
        "can you sing the song ",
        "can you sing ",
        "sing the song ",
        "sing ",
    ]
    
    for pattern in patterns:
        if text_lower.startswith(pattern):
            song_name = text_lower[len(pattern):].strip()
            if song_name:
                return song_name
    
    return None


def extract_opencode_command(text: str):
    """Extract OpenCode command from a message.
    Returns the command, or None if not an OpenCode command.
    """
    text_lower = text.lower().strip()
    
    # Remove wake word prefix first
    for word in config.WAKE_WORDS:
        if text_lower.startswith(word.lower()):
            text_lower = text_lower[len(word):].strip()
            break
    
    # OpenCode trigger patterns
    triggers = ["oc ", "use oc ", "try oc ", "ask oc ", "open code ", "opencode "]
    for trigger in triggers:
        if text_lower.startswith(trigger):
            command = text_lower[len(trigger):].strip()
            if command:
                return command
    
    return None


def is_vision_command(text: str) -> bool:
    """Check if a message is a vision command (contains trigger words)"""
    text_lower = text.lower().strip()
    for word in config.VISION_TRIGGER_WORDS:
        if word.lower() in text_lower:
            return True
    return False


def is_stop_music_command(text: str) -> bool:
    """Check if a message is a stop-music command."""
    text_lower = text.lower().strip()
    phrases = [
        "stop the music",
        "stop music",
        "stop the song",
        "stop playing",
        "stop the song playing",
    ]
    return any(phrase in text_lower for phrase in phrases)


def is_resume_background_command(text: str) -> bool:
    """Check if a message is a resume-background-music command."""
    text_lower = text.lower().strip()
    phrases = [
        "resume the background music",
        "resume background music",
        "resume the background song",
        "resume background song",
        "play the background music",
        "play background music",
    ]
    return any(phrase in text_lower for phrase in phrases)


def is_list_songs_command(text: str) -> bool:
    """Check if a message is asking to list downloaded songs."""
    text_lower = text.lower().strip()
    phrases = [
        "what songs have you downloaded",
        "what songs did you download",
        "list your songs",
        "list the songs",
        "list downloaded songs",
        "what songs do you have",
        "what songs are downloaded",
        "songs you have downloaded",
        "songs you downloaded",
    ]
    return any(phrase in text_lower for phrase in phrases)


def is_playlist_command(text: str) -> bool:
    """Check if a message is asking to play the playlist folder."""
    text_lower = text.lower().strip()
    phrases = [
        "play my playlist",
        "play the playlist",
        "play playlist",
        "start my playlist",
        "start the playlist",
        "start playlist",
        "play my music",
        "play the music folder",
    ]
    return any(phrase in text_lower for phrase in phrases)


def is_stop_playlist_command(text: str) -> bool:
    """Check if a message is asking to stop the playlist."""
    text_lower = text.lower().strip()
    phrases = [
        "stop my playlist",
        "stop the playlist",
        "stop playlist",
        "stop my music",
        "stop the music folder",
    ]
    return any(phrase in text_lower for phrase in phrases)


def translate_emotes(text: str) -> str:
    """Translate chat emotes into their meanings so the LLM understands them.
    Returns the original text with emote meanings appended in brackets.
    """
    if not text:
        return text
    
    text_lower = text.lower()
    found_emotes = []
    for emote, meaning in config.EMOTE_MEANINGS.items():
        if emote in text_lower:
            found_emotes.append(f"{emote}={meaning}")
    
    if found_emotes:
        return f"{text} [emotes: {', '.join(found_emotes)}]"
    return text


def resolve_speaker_name(name: str) -> str:
    """Resolve a nickname/partial name to a full known speaker username.
    E.g. 'Frank' -> '@frankturner9594' if that speaker is known.
    """
    name_lower = name.lower().lstrip('@')
    
    # Exact match first
    for speaker in _known_speakers:
        if speaker.lower().lstrip('@') == name_lower:
            return speaker
    
    # Partial match (nickname is a prefix of the username)
    for speaker in _known_speakers:
        speaker_clean = speaker.lower().lstrip('@')
        if speaker_clean.startswith(name_lower) and len(name_lower) >= 3:
            return speaker
    
    return name


# Common city -> IANA timezone mapping (no external geocoding needed)
_CITY_TIMEZONES = {
    'pattaya': 'Asia/Bangkok',
    'bangkok': 'Asia/Bangkok',
    'thailand': 'Asia/Bangkok',
    'phuket': 'Asia/Bangkok',
    'chiang mai': 'Asia/Bangkok',
    'london': 'Europe/London',
    'new york': 'America/New_York',
    'nyc': 'America/New_York',
    'los angeles': 'America/Los_Angeles',
    'la': 'America/Los_Angeles',
    'chicago': 'America/Chicago',
    'tokyo': 'Asia/Tokyo',
    'sydney': 'Australia/Sydney',
    'paris': 'Europe/Paris',
    'berlin': 'Europe/Berlin',
    'dubai': 'Asia/Dubai',
    'singapore': 'Asia/Singapore',
    'hong kong': 'Asia/Hong_Kong',
    'seoul': 'Asia/Seoul',
    'mumbai': 'Asia/Kolkata',
    'delhi': 'Asia/Kolkata',
    'manila': 'Asia/Manila',
    'jakarta': 'Asia/Jakarta',
    'moscow': 'Europe/Moscow',
    'toronto': 'America/Toronto',
    'vancouver': 'America/Vancouver',
    'mexico city': 'America/Mexico_City',
    'sao paulo': 'America/Sao_Paulo',
    'amsterdam': 'Europe/Amsterdam',
    'madrid': 'Europe/Madrid',
    'rome': 'Europe/Rome',
    'stockholm': 'Europe/Stockholm',
    'oslo': 'Europe/Oslo',
    'copenhagen': 'Europe/Copenhagen',
    'helsinki': 'Europe/Helsinki',
    'athens': 'Europe/Athens',
    'istanbul': 'Europe/Istanbul',
    'cairo': 'Africa/Cairo',
    'johannesburg': 'Africa/Johannesburg',
    'lagos': 'Africa/Lagos',
    'nairobi': 'Africa/Nairobi',
    'auckland': 'Pacific/Auckland',
    'honolulu': 'Pacific/Honolulu',
}


def get_time_for_location(location_name: str) -> str:
    """Return the current time for a location using IANA timezones."""
    if not location_name:
        return "No location specified."

    loc_lower = location_name.lower().strip()
    tz_name = _CITY_TIMEZONES.get(loc_lower)

    if not tz_name:
        # Try partial match against known cities
        for city, tz in _CITY_TIMEZONES.items():
            if city in loc_lower or loc_lower in city:
                tz_name = tz
                break

    if not tz_name:
        return f"I couldn't find the timezone for '{location_name}'."

    try:
        target_time = datetime.now(ZoneInfo(tz_name))
        formatted_time = target_time.strftime("%I:%M %p on %A")
        city_name = location_name.strip()
        return f"The time in {city_name} is {formatted_time}."
    except Exception as e:
        print(f"Time lookup failed: {e}")
        return "I had trouble looking up the time."


def is_time_command(text: str) -> bool:
    """Check if a message is asking for the current time."""
    text_lower = text.lower().strip()
    return any(
        k in text_lower
        for k in ["time is it", "what time", "current time", "what's the time", "whats the time"]
    )


def extract_time_location(text: str) -> str:
    """Extract a location from a time query, defaulting to Pattaya."""
    text_lower = text.lower().strip()
    # Remove common time-query phrases
    for phrase in ["what time is it in", "what time is it", "what's the time in",
                   "whats the time in", "what's the time", "whats the time",
                   "current time in", "current time", "time in", "time is it in"]:
        text_lower = text_lower.replace(phrase, "")
    text_lower = text_lower.strip(" ?.,!").strip()
    if not text_lower:
        return "Pattaya"
    return text_lower


def is_weather_command(text: str) -> bool:
    """Check if a message is asking about the weather."""
    text_lower = text.lower().strip()
    triggers = [
        "weather", "temperature", "how hot", "how cold", "is it raining",
        "is it sunny", "forecast", "humidity", "wind speed",
    ]
    return any(t in text_lower for t in triggers)


def extract_weather_location(text: str) -> str:
    """Extract a location from a weather query, defaulting to Pattaya."""
    text_lower = text.lower()
    for phrase in ["weather in ", "weather like in ", "temperature in ", "forecast in ",
                   "weather for ", "weather at ", "weather like at "]:
        if phrase in text_lower:
            rest = text_lower.split(phrase, 1)[1].strip(" ?.,!")
            if rest:
                return rest
    # Fallback: if a known city name is present, use it
    for city in ["pattaya", "bangkok", "phuket", "chiang mai", "london", "new york", "tokyo"]:
        if city in text_lower:
            return city
    return "Pattaya"


async def handle_incoming_message(data: dict):
    """Process incoming chat from SSN WebSocket"""
    # If paused, silently ignore all incoming messages
    if _paused:
        return

    # Extract message data
    message = data.get('chatmessage', '')
    speaker = data.get('chatname', 'Unknown')

    # Replace alternate wake names (e.g. "jim") with "Gem" early, so the LLM
    # never sees the wrong name (not in chat history, not in the prompt).
    message = re.sub(r'\bjim\b', 'Gem', message, flags=re.IGNORECASE)

    print(f"\n[CHAT] {speaker}: {message}")
    
    # Track known speakers (for nickname resolution)
    if speaker and speaker != 'Unknown' and speaker not in _known_speakers:
        _known_speakers.add(speaker)
        save_known_speakers()
    
    # Ignore messages from our own bot (prevents self-triggering)
    if speaker.lower() in ['gem', 'gem_chadee', 'gem-chadee']:
        print(f"  → Ignoring message from own bot ({speaker})")
        return
    
    # Ignore echo of our own responses
    message_clean = html.unescape(message).strip()
    for last_response in _last_ai_responses:
        if message_clean == last_response:
            print(f"  → Ignoring echo of last AI response")
            return
    
    # Track chat activity for the idle manager (any real message resets the timer)
    idle.update_activity()
    
    # Check for wake word
    wake_word = None
    for word in config.WAKE_WORDS:
        if word.lower() in message.lower():
            wake_word = word
            break
    
    if not wake_word:
        return  # No wake word, ignore
    
    # Check for "sing the song" command (karaoke library, before download)
    sing_name = extract_sing_command(message)
    if sing_name:
        print(f"🎤 Sing command detected: '{sing_name}'")
        await cognee.remember(speaker, message)
        
        # Try to find and play from the karaoke library
        result = music.library.find_song(sing_name)
        if result:
            music.play_song(sing_name)
            await ssn.send_message(f"🎤 Singing '{sing_name}'!", targets=config.SSN_TARGETS)
        else:
            # Not in library, fall back to download
            await ssn.send_message(f"🎤 I don't have '{sing_name}' in my library, downloading it instead...", targets=config.SSN_TARGETS)
            music.download_song(sing_name)
        return
    
    # Check for playlist command (play all MP3s in the playlist folder) - BEFORE song command
    if is_playlist_command(message):
        print(f"🎵 Playlist command detected: '{message}'")
        await cognee.remember(speaker, message)
        if music.play_playlist():
            count = len(music.list_playlist_songs())
            await ssn.send_message(f"🎵 Playing your playlist ({count} songs)!", targets=config.SSN_TARGETS)
        else:
            await ssn.send_message("Your playlist folder is empty.", targets=config.SSN_TARGETS)
        return
    
    # Check for stop playlist command
    if is_stop_playlist_command(message):
        print(f"🛑 Stop playlist command detected: '{message}'")
        await cognee.remember(speaker, message)
        music.stop_playlist()
        await ssn.send_message("🛑 Stopped the playlist.", targets=config.SSN_TARGETS)
        return
    
    # Check for song command (intercept before LLM)
    song_name = extract_song_command(message)
    if song_name:
        print(f"🎵 Song command detected: '{song_name}'")
        
        # Extract dedication (e.g. "dedicate it to Teenz")
        dedication = extract_dedication(message)
        
        # Store the song request in memory
        await cognee.remember(speaker, message)
        
        # Check Twitch DJ Program restrictions
        if config.TWITCH_MUSIC_CHECK_ENABLED:
            result = music.verify_song(song_name)
            status = result.get('status', 'error')
            
            if status == 'restricted':
                await ssn.send_message(result.get('message', "Sorry, that song is restricted."), targets=config.SSN_TARGETS)
                return
            elif status == 'error':
                await ssn.send_message(result.get('message', "I couldn't identify that song."), targets=config.SSN_TARGETS)
                return
            # 'allowed' or 'not_found' -> proceed with download
        
        # Check if the song already exists locally before downloading
        existing = music.check_song_exists(song_name)
        if existing:
            music.play_mp3(existing)
            if dedication:
                await ssn.send_message(f"🎵 Playing '{existing}' - dedicated to {dedication}!", targets=config.SSN_TARGETS)
            else:
                await ssn.send_message(f"🎵 Already have '{existing}' - playing it now!", targets=config.SSN_TARGETS)
            return
        
        music.download_song(song_name)
        if dedication:
            await ssn.send_message(f"🎵 Got it! Downloading '{song_name}' - dedicated to {dedication}!", targets=config.SSN_TARGETS)
        else:
            await ssn.send_message(f"🎵 Got it! Downloading '{song_name}'...", targets=config.SSN_TARGETS)
        return
    
    # Check for stop music command (intercept before LLM)
    if is_stop_music_command(message):
        print(f"🛑 Stop music command detected: '{message}'")
        await cognee.remember(speaker, message)
        if music.now_playing:
            was_playing = music.now_playing
            music.stop_music()
            await cognee.remember("Gem", f"Gem stopped the music (was playing {was_playing})")
            await ssn.send_message("🛑 Stopped the music.", targets=config.SSN_TARGETS)
        else:
            await ssn.send_message("Nothing's playing right now.", targets=config.SSN_TARGETS)
        return
    
    # Check for resume background music command (intercept before LLM)
    if is_resume_background_command(message):
        print(f"▶️ Resume background music command detected: '{message}'")
        await cognee.remember(speaker, message)
        if music.restart_background_song():
            await ssn.send_message("▶️ Background music is back on.", targets=config.SSN_TARGETS)
        else:
            await ssn.send_message("I don't have a background song set.", targets=config.SSN_TARGETS)
        return
    
    # Check for list downloaded songs command (intercept before LLM)
    if is_list_songs_command(message):
        print(f"📋 List songs command detected: '{message}'")
        await cognee.remember(speaker, message)
        songs = music.list_downloaded_songs()
        if songs:
            song_list = ", ".join(songs)
            await ssn.send_message(f"🎵 I have these songs downloaded: {song_list}", targets=config.SSN_TARGETS)
        else:
            await ssn.send_message("I don't have any songs downloaded yet.", targets=config.SSN_TARGETS)
        return
    
    # Check for OpenCode command (intercept before LLM)
    oc_command = extract_opencode_command(message)
    if oc_command and config.OPENCODE_ENABLED:
        print(f"💻 OpenCode command detected: '{oc_command}'")
        await cognee.remember(speaker, message)
        try:
            oc_result = await opencode.execute_task(oc_command)
            formatted = format_opencode_response(oc_result)
            await ssn.send_message(formatted, targets=config.SSN_TARGETS)
            await cognee.remember("Gem", formatted)
        except Exception as e:
            await ssn.send_message(f"OpenCode error: {e}", targets=config.SSN_TARGETS)
        return
    
    # Check for vision command (intercept before LLM)
    if config.VISION_ENABLED and is_vision_command(message):
        print(f"👁️ Vision command detected: '{message}'")
        await cognee.remember(speaker, message)
        
        # Get the actual image and send it to the multimodal LLM (Gemma).
        image_base64 = await vision.get_image_base64()
        if image_base64:
            response = await llm.chat_with_image(message, image_base64, system_prompt=config.SYSTEM_PROMPT)
        else:
            response = await llm.chat(message, system_prompt=config.SYSTEM_PROMPT)
        
        print(f"[GEM] {response}")
        await cognee.remember("Gem", response)
        _last_ai_responses.append(html.unescape(response).strip())
        await send_response(response)
        return
    
    # Check for time query (intercept before LLM so it uses the real time)
    if is_time_command(message):
        print(f"🕐 Time command detected: '{message}'")
        await cognee.remember(speaker, message)
        location = extract_time_location(message)
        time_ctx = get_time_for_location(location)
        print(f"🕐 Time context: '{time_ctx}'")
        # Force the LLM to use the actual time, but answer in-character (nuanced).
        response = await llm.chat(
            f"{time_ctx} User asks: '{message}'. Answer in character as Gem. "
            f"Use the exact time shown above, but deliver it naturally and with your "
            f"usual personality - you can add a playful remark, a comment about the "
            f"time of day, or a casual aside. Keep it to 1-2 sentences and never "
            f"invent a different time.",
            system_prompt=config.SYSTEM_PROMPT
        )
        print(f"[GEM] {response}")
        await cognee.remember("Gem", response)
        _last_ai_responses.append(html.unescape(response).strip())
        await send_response(response)
        return

    # Check for weather query (intercept before LLM so it uses the real weather)
    if is_weather_command(message):
        print(f"🌤️ Weather command detected: '{message}'")
        await cognee.remember(speaker, message)
        location = extract_weather_location(message)
        result = await weather.get_weather_for_location(location)
        if result:
            desc = weather.describe_weather(result["weather"])
            print(f"🌤️ Weather context: {result['location']}: {desc}")
            response = await llm.chat(
                f"The current weather in {result['location']} is: {desc}. "
                f"User asks: '{message}'. Answer in character as Gem, using the real "
                f"weather data above. Be natural and add a touch of personality. "
                f"Never invent different weather.",
                system_prompt=config.SYSTEM_PROMPT
            )
        else:
            response = await llm.chat(
                f"User asked about the weather: '{message}'. I couldn't fetch live "
                f"weather data. Answer in character and say I couldn't get the weather.",
                system_prompt=config.SYSTEM_PROMPT
            )
        print(f"[GEM] {response}")
        await cognee.remember("Gem", response)
        _last_ai_responses.append(html.unescape(response).strip())
        await send_response(response)
        return

    # Store user message in memory
    await cognee.remember(speaker, message)
    
    # Add to rolling chat history
    add_to_chat_history(speaker, message)
    
    # Translate emotes so the LLM understands them
    llm_message = translate_emotes(message)
    
    # Recall memory context
    memory_context = await get_memory_context(speaker, message)
    
    # Get response from LLM
    system_prompt = config.SYSTEM_PROMPT
    
    # Inject the actual current date/time so the LLM never guesses the wrong day
    now = datetime.now(ZoneInfo("Asia/Bangkok"))
    system_prompt = f"{system_prompt}\n\nToday is {now.strftime('%A, %B %d, %Y')}. The current time is {now.strftime('%I:%M %p')}."
    
    # Inject the avatar's current physical state
    if config.AVATAR_ACTION_TAG_ENABLED:
        state_context = get_avatar_state_context()
        system_prompt = f"{system_prompt}\n\n{state_context}"
    
    if memory_context:
        system_prompt = f"{system_prompt}\n\n{memory_context}"
    
    # Include recent chat history so the LLM knows what was just said
    chat_history = get_chat_history_context()
    if chat_history:
        system_prompt = f"{system_prompt}\n\n{chat_history}"
    
    # Build tools for the LLM (animations + browser via generic tools)
    tools = []
    if config.AVATAR_ACTION_TAG_ENABLED:
        tools.extend(get_animation_tools())
    if browser.enabled and getattr(config, 'BROWSER_ENABLED', False):
        tools.extend(get_browser_tools())

    # Let the LLM respond; it may also request an animation or a browse task.
    response, tool_calls = await llm.chat_with_tools(
        llm_message, system_prompt=system_prompt, tools=tools or None
    )
    print(f"[GEM] {response}")

    # Execute any tools the LLM requested (question-vs-request is the LLM's job).
    browser_result = None
    for call in tool_calls:
        action = extract_tool_action(call)
        if action:
            apply_action_tag(action)
            continue

        browse_task = extract_browser_task(call)
        if browse_task:
            blocked = find_blocked_term(browse_task)
            if blocked:
                print(f"[BROWSER] Blocked task containing '{blocked}': {browse_task}")
                browser_result = "Blocked. This request was refused because it matched a disallowed topic."
            else:
                browser_result = await browser.run_task(browse_task)

    # If a browse task ran, hand its result back to the LLM for a chat reply.
    if browser_result is not None:
        followup = await llm.chat(
            f"You browsed the web for: '{browser_result}'. "
            f"Summarize the outcome in character as Gem, in 1-3 sentences, "
            f"for the person who asked.",
            system_prompt=system_prompt,
        )
        if followup and not followup.startswith("Error"):
            response = followup

    # If the LLM only returned a tool call and no text, give it a fallback line.
    if not response.strip() and tool_calls:
        response = "Got it!"

    # Store AI response in memory
    await cognee.remember("Gem", response)
    
    # Add AI response to rolling chat history
    add_to_chat_history("Gem", response)
    
    # Track response to prevent echo
    _last_ai_responses.append(html.unescape(response).strip())
    
    # Send response to TTS and (optionally) chat
    await send_response(response)


async def get_memory_context(speaker: str, message: str) -> str:
    """Retrieve relevant memories for the current message (with overall timeout)"""
    import re
    
    memory_context = ""
    
    try:
        # Wrap the whole recall in a timeout so it can't block the chat
        async with asyncio.timeout(3.0):
            # 1. Get user profile (natural-language queries work better with semantic search)
            user_results = await cognee.recall(f"what do I remember about {speaker}", top_k=5)
            if not user_results:
                user_results = await cognee.recall(f"conversations with {speaker}", top_k=5)
            if not user_results:
                user_results = await cognee.recall(speaker, top_k=5)
            
            if user_results:
                memory_context += f"\n\nThings you remember about {speaker}:"
                for result in user_results:
                    memory_context += f"\n- {result}"
            
            # 2. Search for entities mentioned in message
            # First, check if any known speaker is mentioned (case-insensitive)
            message_lower = message.lower()
            mentioned_speakers = []
            for known in _known_speakers:
                known_clean = known.lower().lstrip('@')
                # Check if the full username or a meaningful part is mentioned
                if known_clean in message_lower:
                    mentioned_speakers.append(known)
                elif len(known_clean) >= 4 and known_clean[:4] in message_lower:
                    mentioned_speakers.append(known)
            
            # Also extract capitalized words as fallback
            entities = re.findall(r'\b[A-Z][a-z]+\b', message)
            entities = [e for e in entities if e.lower() not in config.STOP_WORDS]
            
            # Combine: known speakers first, then generic entities
            search_terms = mentioned_speakers[:3]
            for entity in entities[:3]:
                resolved = resolve_speaker_name(entity)
                if resolved not in search_terms:
                    search_terms.append(resolved)
            
            for term in search_terms[:3]:
                entity_results = await cognee.recall(f"what do I remember about {term}", top_k=3)
                if not entity_results:
                    entity_results = await cognee.recall(f"conversations with {term}", top_k=3)
                if not entity_results:
                    entity_results = await cognee.recall(term, top_k=3)
                
                if entity_results:
                    memory_context += f"\n\nThings you remember about {term}:"
                    for result in entity_results:
                        memory_context += f"\n- {result}"
    except (asyncio.TimeoutError, Exception):
        print("⏱️ Memory recall timed out, proceeding without context")
    
    return memory_context


@app.route('/health', methods=['GET'])
async def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'ok',
        'llm': llm.enabled,
        'ssn': ssn.enabled,
        'cognee': cognee.enabled,
        'paused': _paused
    })


@app.route('/api/pause', methods=['POST'])
async def api_pause():
    """Pause the MCP - ignore incoming chat messages"""
    global _paused
    _paused = True
    idle.enabled = False
    print("⏸️ MCP PAUSED - ignoring incoming chat")
    return jsonify({'status': 'ok', 'paused': True})


@app.route('/api/resume', methods=['POST'])
async def api_resume():
    """Resume the MCP - process incoming chat messages again"""
    global _paused
    _paused = False
    idle.enabled = config.IDLE_ACTIONS_ENABLED
    print("▶️ MCP RESUMED - processing incoming chat")
    return jsonify({'status': 'ok', 'paused': False})


@app.route('/api/status', methods=['GET'])
async def api_status():
    """Full status for GUI"""
    return jsonify({
        'llm': {
            'enabled': llm.enabled,
            'model': config.OLLAMA_MODEL,
            'base_url': config.OLLAMA_BASE_URL
        },
        'ssn': {
            'enabled': ssn.enabled,
            'api_url': config.SSN_API_URL,
            'session_id': config.SSN_SESSION_ID
        },
        'cognee': {
            'enabled': cognee.enabled,
            'server_url': config.COGNEE_SERVER_URL
        },
        'tts': {
            'enabled': config.TTS_ENABLED,
            'engine': config.TTS_ENGINE,
            'tts_url': config.TTS_URL,
            'pocket_tts_url': config.POCKET_TTS_URL,
            'vibevoice_tts_url': config.VIBEVOICE_TTS_URL,
            'qwen_tts_url': config.QWEN_TTS_URL,
            'vibevoice_model': config.VIBEVOICE_MODEL,
            'vibevoice_inference_steps': config.VIBEVOICE_INFERENCE_STEPS,
            'diffusion_steps': config.TTS_DIFFUSION_STEPS,
            'embedding_scale': config.TTS_EMBEDDING_SCALE,
            'alpha': config.TTS_ALPHA,
            'beta': config.TTS_BETA,
            'reference_voice': config.TTS_REFERENCE_VOICE,
            'copy_to': config.TTS_COPY_TO,
            'audio_player_enabled': config.AUDIO_PLAYER_ENABLED,
            'send_responses_to_chat': config.SEND_RESPONSES_TO_CHAT
        },
        'audio': {
            'output_device': config.AUDIO_OUTPUT_DEVICE,
            'music_output_device': config.MUSIC_OUTPUT_DEVICE,
            'ducking_enabled': config.AUDIO_DUCKING_ENABLED,
            'duck_amount': config.AUDIO_DUCK_AMOUNT,
            'attack_ms': config.AUDIO_DUCK_ATTACK_MS,
            'release_ms': config.AUDIO_DUCK_RELEASE_MS,
            'duck_delay_s': config.AUDIO_DUCK_DELAY_S,
            'duck_hold_s': config.AUDIO_DUCK_HOLD_S
        },
        'stt': {
            'whisper_model': config.STT_WHISPER_MODEL,
            'vad_aggressiveness': config.STT_VAD_AGGRESSIVENESS,
            'silence_threshold_s': config.STT_SILENCE_THRESHOLD_S,
            'pre_buffer_s': config.STT_PRE_BUFFER_S,
            'min_db': config.STT_MIN_DB
        },
        'neurosync': {
            'mouth_scale': config.BLENDSHAPE_MOUTH_SCALE,
            'eye_scale': config.BLENDSHAPE_EYE_SCALE,
            'eyebrow_scale': config.BLENDSHAPE_EYEBROW_SCALE,
            'eyewide_scale': config.BLENDSHAPE_EYEWIDE_SCALE,
            'eyesquint_scale': config.BLENDSHAPE_EYESQUINT_SCALE,
            'osc': {
                'enabled': config.OSC_ENABLED,
                'ip': config.OSC_IP,
                'port': config.OSC_PORT,
                'address': config.OSC_ADDRESS
            },
            'livelink': {
                'ip': config.LIVELINK_IP,
                'port': config.LIVELINK_PORT
            },
            'watcher_audio_path': config.TTS_OUTPUT_PATH,
            'avatar': {
                'talk_animation': config.AVATAR_TALK_ANIMATION,
                'talk_osc_address': config.AVATAR_TALK_OSC_ADDRESS,
                'talk_stop_animation': config.AVATAR_TALK_STOP_ANIMATION,
                'talk_start_delay_s': config.AVATAR_TALK_START_DELAY_S,
                'talk_stop_delay_s': config.AVATAR_TALK_STOP_DELAY_S,
            }
        },
        'opencode': {
            'enabled': config.OPENCODE_ENABLED,
            'connected': opencode.enabled,
            'api_url': config.OPENCODE_API_URL,
            'workspace': config.OPENCODE_WORKSPACE
        },
        'vision': {
            'enabled': config.VISION_ENABLED,
            'connected': vision.enabled,
            'scan_url': config.VISION_SCAN_URL,
            'get_image_url': config.VISION_GET_IMAGE_URL,
            'image_source': config.VISION_IMAGE_SOURCE,
            'camera_index': config.VISION_CAMERA_INDEX,
            'ndi_source_name': config.VISION_NDI_SOURCE_NAME
        },
        'browser': {
            'enabled': config.BROWSER_ENABLED,
            'connected': browser.enabled,
            'llm_provider': config.BROWSER_LLM_PROVIDER,
            'openai_model': config.BROWSER_OPENAI_MODEL,
            'openai_api_key': config.BROWSER_OPENAI_API_KEY,
            'headless': config.BROWSER_HEADLESS,
            'viewport_width': config.BROWSER_VIEWPORT_WIDTH,
            'viewport_height': config.BROWSER_VIEWPORT_HEIGHT
        },
        'game_agent': {
            'enabled': config.GAME_AGENT_ENABLED,
            'interval_s': config.GAME_AGENT_INTERVAL_S,
            'move_address': config.GAME_AGENT_MOVE_ADDRESS,
            'turn_address': config.GAME_AGENT_TURN_ADDRESS,
            'system_prompt': config.GAME_AGENT_SYSTEM_PROMPT
        }
    })


@app.route('/api/audio/devices', methods=['GET'])
async def api_audio_devices():
    """List available audio output devices"""
    devices = []
    try:
        import sounddevice as sd
        for dev in sd.query_devices():
            if dev['max_output_channels'] > 0:
                devices.append({
                    'index': dev['index'],
                    'name': dev['name']
                })
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e), 'devices': []}), 500
    
    return jsonify({'status': 'ok', 'devices': devices})


@app.route('/api/audio/input_devices', methods=['GET'])
async def api_audio_input_devices():
    """List available audio input devices"""
    devices = []
    try:
        import sounddevice as sd
        for dev in sd.query_devices():
            if dev['max_input_channels'] > 0:
                devices.append({
                    'index': dev['index'],
                    'name': dev['name']
                })
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e), 'devices': []}), 500
    
    return jsonify({'status': 'ok', 'devices': devices})


@app.route('/api/audio/input_device', methods=['GET'])
async def api_audio_get_input_device():
    """Get the current input device from config.py"""
    return jsonify({'status': 'ok', 'selected_input': config.AUDIO_INPUT_DEVICE})


@app.route('/api/audio/input_device', methods=['POST'])
async def api_audio_set_input_device():
    """Set the input device in config.py"""
    data = await request.get_json()
    device_string = data.get('device', '')
    
    config.AUDIO_INPUT_DEVICE = device_string
    save_config()
    return jsonify({'status': 'ok'})


@app.route('/api/settings', methods=['GET'])
async def api_get_settings():
    """Get current settings for GUI"""
    return jsonify({
        'system_prompt': config.SYSTEM_PROMPT,
        'wake_words': config.WAKE_WORDS,
        'ollama_model': config.OLLAMA_MODEL,
        'ssn_session_id': config.SSN_SESSION_ID,
        'voice_speaker_name': config.VOICE_SPEAKER_NAME,
        'idle_actions_enabled': config.IDLE_ACTIONS_ENABLED,
        'idle_inactivity_limit': config.IDLE_INACTIVITY_LIMIT,
        'idle_cooldown': config.IDLE_COOLDOWN,
        'idle_osc_state_address': config.IDLE_OSC_STATE_ADDRESS,
        'idle_osc_action_address': config.IDLE_OSC_ACTION_ADDRESS,
        'idle_osc_bored_value': config.IDLE_OSC_BORED_VALUE,
        'idle_osc_normal_value': config.IDLE_OSC_NORMAL_VALUE,
        'idle_osc_talk_value': config.IDLE_OSC_TALK_VALUE,
        'idle_osc_idle_value': config.IDLE_OSC_IDLE_VALUE,
        'idle_topics': config.IDLE_TOPICS,
        'idle_monologue_prompt': config.IDLE_MONOLOGUE_PROMPT,
        'laya_enabled': config.LAYA_ENABLED,
        'laya_url': config.LAYA_URL,
        'laya_animation_threshold': config.LAYA_ANIMATION_THRESHOLD,
        'laya_reply_threshold': config.LAYA_REPLY_THRESHOLD,
        'laya_osc_address': config.LAYA_OSC_ADDRESS,
        'laya_animation_options': config.LAYA_ANIMATION_OPTIONS,
        'laya_animation_map': config.LAYA_ANIMATION_MAP,
    })


@app.route('/api/settings', methods=['POST'])
async def api_update_settings():
    """Update settings from GUI"""
    data = await request.get_json()
    
    if 'system_prompt' in data:
        config.SYSTEM_PROMPT = data['system_prompt']
    if 'wake_words' in data:
        config.WAKE_WORDS = data['wake_words']
    if 'ollama_model' in data:
        config.OLLAMA_MODEL = data['ollama_model']
        llm.model = data['ollama_model']
    if 'ssn_session_id' in data:
        config.SSN_SESSION_ID = data['ssn_session_id']
        ssn.session_id = data['ssn_session_id']
    if 'voice_speaker_name' in data:
        config.VOICE_SPEAKER_NAME = data['voice_speaker_name']
    if 'ssn_targets' in data:
        config.SSN_TARGETS = data['ssn_targets']
    if 'tts_enabled' in data:
        config.TTS_ENABLED = data['tts_enabled']
    if 'send_responses_to_chat' in data:
        config.SEND_RESPONSES_TO_CHAT = data['send_responses_to_chat']
    if 'tts_engine' in data:
        config.TTS_ENGINE = data['tts_engine']
        tts.tts_url = _tts_url_for_engine()
        # Re-check connection against the new engine's URL
        await tts.check_connection()
    if 'tts_url' in data:
        config.TTS_URL = data['tts_url']
        if config.TTS_ENGINE not in ("pocket", "vibevoice"):
            tts.tts_url = data['tts_url']
    if 'pocket_tts_url' in data:
        config.POCKET_TTS_URL = data['pocket_tts_url']
        if config.TTS_ENGINE == "pocket":
            tts.tts_url = data['pocket_tts_url']
    if 'vibevoice_tts_url' in data:
        config.VIBEVOICE_TTS_URL = data['vibevoice_tts_url']
        if config.TTS_ENGINE == "vibevoice":
            tts.tts_url = data['vibevoice_tts_url']
    if 'qwen_tts_url' in data:
        config.QWEN_TTS_URL = data['qwen_tts_url']
        if config.TTS_ENGINE == "qwen":
            tts.tts_url = data['qwen_tts_url']
    if 'vibevoice_model' in data:
        config.VIBEVOICE_MODEL = data['vibevoice_model']
    if 'vibevoice_inference_steps' in data:
        config.VIBEVOICE_INFERENCE_STEPS = data['vibevoice_inference_steps']
    if 'tts_diffusion_steps' in data:
        config.TTS_DIFFUSION_STEPS = data['tts_diffusion_steps']
    if 'tts_embedding_scale' in data:
        config.TTS_EMBEDDING_SCALE = data['tts_embedding_scale']
    if 'tts_alpha' in data:
        config.TTS_ALPHA = data['tts_alpha']
    if 'tts_beta' in data:
        config.TTS_BETA = data['tts_beta']
    if 'tts_reference_voice' in data:
        config.TTS_REFERENCE_VOICE = data['tts_reference_voice']
    if 'tts_copy_to' in data:
        config.TTS_COPY_TO = data['tts_copy_to']
    if 'audio_player_enabled' in data:
        config.AUDIO_PLAYER_ENABLED = data['audio_player_enabled']
    if 'audio_output_device' in data:
        config.AUDIO_OUTPUT_DEVICE = data['audio_output_device']
        audio_player.device_name = data['audio_output_device'] or None
    if 'music_output_device' in data:
        config.MUSIC_OUTPUT_DEVICE = data['music_output_device']
        music.music_device_name = data['music_output_device'] or None
    if 'audio_ducking_enabled' in data:
        config.AUDIO_DUCKING_ENABLED = data['audio_ducking_enabled']
    if 'audio_duck_amount' in data:
        config.AUDIO_DUCK_AMOUNT = data['audio_duck_amount']
    if 'audio_duck_attack_ms' in data:
        config.AUDIO_DUCK_ATTACK_MS = data['audio_duck_attack_ms']
    if 'audio_duck_release_ms' in data:
        config.AUDIO_DUCK_RELEASE_MS = data['audio_duck_release_ms']
    if 'audio_duck_delay_s' in data:
        config.AUDIO_DUCK_DELAY_S = data['audio_duck_delay_s']
    if 'audio_duck_hold_s' in data:
        config.AUDIO_DUCK_HOLD_S = data['audio_duck_hold_s']
    if 'tts_output_path' in data:
        config.TTS_OUTPUT_PATH = data['tts_output_path']
    if 'stt_whisper_model' in data:
        config.STT_WHISPER_MODEL = data['stt_whisper_model']
    if 'stt_vad_aggressiveness' in data:
        config.STT_VAD_AGGRESSIVENESS = data['stt_vad_aggressiveness']
    if 'stt_silence_threshold_s' in data:
        config.STT_SILENCE_THRESHOLD_S = data['stt_silence_threshold_s']
    if 'stt_pre_buffer_s' in data:
        config.STT_PRE_BUFFER_S = data['stt_pre_buffer_s']
    if 'stt_min_db' in data:
        config.STT_MIN_DB = data['stt_min_db']
    if 'blendshape_mouth_scale' in data:
        config.BLENDSHAPE_MOUTH_SCALE = data['blendshape_mouth_scale']
    if 'blendshape_eye_scale' in data:
        config.BLENDSHAPE_EYE_SCALE = data['blendshape_eye_scale']
    if 'blendshape_eyebrow_scale' in data:
        config.BLENDSHAPE_EYEBROW_SCALE = data['blendshape_eyebrow_scale']
    if 'blendshape_eyewide_scale' in data:
        config.BLENDSHAPE_EYEWIDE_SCALE = data['blendshape_eyewide_scale']
    if 'blendshape_eyesquint_scale' in data:
        config.BLENDSHAPE_EYESQUINT_SCALE = data['blendshape_eyesquint_scale']
    if 'osc_ip' in data:
        config.OSC_IP = data['osc_ip']
    if 'osc_port' in data:
        config.OSC_PORT = data['osc_port']
    if 'osc_address' in data:
        config.OSC_ADDRESS = data['osc_address']
    if 'osc_actions' in data:
        config.OSC_ACTIONS = data['osc_actions']
    if 'idle_actions_enabled' in data:
        config.IDLE_ACTIONS_ENABLED = data['idle_actions_enabled']
        idle.enabled = data['idle_actions_enabled']
    if 'idle_inactivity_limit' in data:
        config.IDLE_INACTIVITY_LIMIT = data['idle_inactivity_limit']
        idle.inactivity_limit = data['idle_inactivity_limit']
    if 'idle_cooldown' in data:
        config.IDLE_COOLDOWN = data['idle_cooldown']
        idle.cooldown = data['idle_cooldown']
    if 'idle_osc_state_address' in data:
        config.IDLE_OSC_STATE_ADDRESS = data['idle_osc_state_address']
        idle.osc_state_address = data['idle_osc_state_address']
    if 'idle_osc_action_address' in data:
        config.IDLE_OSC_ACTION_ADDRESS = data['idle_osc_action_address']
        idle.osc_action_address = data['idle_osc_action_address']
    if 'idle_osc_bored_value' in data:
        config.IDLE_OSC_BORED_VALUE = data['idle_osc_bored_value']
        idle.osc_bored_value = data['idle_osc_bored_value']
    if 'idle_osc_normal_value' in data:
        config.IDLE_OSC_NORMAL_VALUE = data['idle_osc_normal_value']
        idle.osc_normal_value = data['idle_osc_normal_value']
    if 'idle_osc_talk_value' in data:
        config.IDLE_OSC_TALK_VALUE = data['idle_osc_talk_value']
        idle.osc_talk_value = data['idle_osc_talk_value']
    if 'idle_osc_idle_value' in data:
        config.IDLE_OSC_IDLE_VALUE = data['idle_osc_idle_value']
        idle.osc_idle_value = data['idle_osc_idle_value']
    if 'idle_topics' in data:
        config.IDLE_TOPICS = data['idle_topics']
        idle.topics = data['idle_topics']
    if 'idle_monologue_prompt' in data:
        config.IDLE_MONOLOGUE_PROMPT = data['idle_monologue_prompt']
    if 'livelink_ip' in data:
        config.LIVELINK_IP = data['livelink_ip']
    if 'livelink_port' in data:
        config.LIVELINK_PORT = data['livelink_port']
    if 'avatar_talk_start_delay_s' in data:
        config.AVATAR_TALK_START_DELAY_S = data['avatar_talk_start_delay_s']
    if 'avatar_talk_stop_delay_s' in data:
        config.AVATAR_TALK_STOP_DELAY_S = data['avatar_talk_stop_delay_s']
    if 'opencode_enabled' in data:
        config.OPENCODE_ENABLED = data['opencode_enabled']
    if 'opencode_api_url' in data:
        config.OPENCODE_API_URL = data['opencode_api_url']
        opencode.api_url = data['opencode_api_url'].rstrip('/')
    if 'opencode_workspace' in data:
        config.OPENCODE_WORKSPACE = data['opencode_workspace']
        opencode.workspace = data['opencode_workspace']
    if 'vision_enabled' in data:
        config.VISION_ENABLED = data['vision_enabled']
    if 'vision_scan_url' in data:
        config.VISION_SCAN_URL = data['vision_scan_url']
        vision.scan_url = data['vision_scan_url']
    if 'vision_get_image_url' in data:
        config.VISION_GET_IMAGE_URL = data['vision_get_image_url']
        vision.get_image_url = data['vision_get_image_url']
    if 'vision_trigger_words' in data:
        config.VISION_TRIGGER_WORDS = data['vision_trigger_words']
    if 'vision_image_source' in data:
        config.VISION_IMAGE_SOURCE = data['vision_image_source']
    if 'vision_camera_index' in data:
        config.VISION_CAMERA_INDEX = data['vision_camera_index']
    if 'vision_ndi_source_name' in data:
        config.VISION_NDI_SOURCE_NAME = data['vision_ndi_source_name']
    if 'browser_enabled' in data:
        config.BROWSER_ENABLED = data['browser_enabled']
    if 'browser_llm_provider' in data:
        config.BROWSER_LLM_PROVIDER = data['browser_llm_provider']
        browser.provider = data['browser_llm_provider']
    if 'browser_openai_model' in data:
        config.BROWSER_OPENAI_MODEL = data['browser_openai_model']
        browser.openai_model = data['browser_openai_model']
    if 'browser_openai_api_key' in data:
        config.BROWSER_OPENAI_API_KEY = data['browser_openai_api_key']
        browser.openai_api_key = data['browser_openai_api_key']
    if 'browser_headless' in data:
        config.BROWSER_HEADLESS = data['browser_headless']
        browser.headless = data['browser_headless']
    if 'browser_viewport_width' in data:
        config.BROWSER_VIEWPORT_WIDTH = data['browser_viewport_width']
        browser.viewport_width = data['browser_viewport_width']
    if 'browser_viewport_height' in data:
        config.BROWSER_VIEWPORT_HEIGHT = data['browser_viewport_height']
        browser.viewport_height = data['browser_viewport_height']
    if 'game_agent_enabled' in data:
        config.GAME_AGENT_ENABLED = data['game_agent_enabled']
    if 'game_agent_interval_s' in data:
        config.GAME_AGENT_INTERVAL_S = data['game_agent_interval_s']
    if 'game_agent_move_address' in data:
        config.GAME_AGENT_MOVE_ADDRESS = data['game_agent_move_address']
    if 'game_agent_turn_address' in data:
        config.GAME_AGENT_TURN_ADDRESS = data['game_agent_turn_address']
    if 'game_agent_system_prompt' in data:
        config.GAME_AGENT_SYSTEM_PROMPT = data['game_agent_system_prompt']
    if 'background_volume' in data:
        config.BACKGROUND_VOLUME = data['background_volume']
        music.background_volume = data['background_volume']
    if 'laya_enabled' in data:
        config.LAYA_ENABLED = data['laya_enabled']
    if 'laya_url' in data:
        config.LAYA_URL = data['laya_url']
    if 'laya_animation_threshold' in data:
        config.LAYA_ANIMATION_THRESHOLD = data['laya_animation_threshold']
    if 'laya_reply_threshold' in data:
        config.LAYA_REPLY_THRESHOLD = data['laya_reply_threshold']
    if 'laya_osc_address' in data:
        config.LAYA_OSC_ADDRESS = data['laya_osc_address']
    if 'laya_animation_options' in data:
        config.LAYA_ANIMATION_OPTIONS = data['laya_animation_options']
    if 'laya_animation_map' in data:
        config.LAYA_ANIMATION_MAP = data['laya_animation_map']
    
    # Persist settings to config.py (single source of truth)
    save_config()
    
    return jsonify({'status': 'ok'})


@app.route('/api/vision/image', methods=['GET'])
async def api_vision_image():
    """Proxy the current camera image from the vision service"""
    image_base64 = await vision.get_image_base64()
    if image_base64:
        return jsonify({'status': 'ok', 'image_base64': image_base64})
    return jsonify({'status': 'error', 'error': 'Vision service not available'}), 503


@app.route('/api/vision/cameras', methods=['GET'])
async def api_vision_cameras():
    """Scan for available cameras"""
    import cv2
    cameras = []
    for index in range(10):
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if cap.isOpened():
            cameras.append(index)
            cap.release()
    return jsonify({'status': 'ok', 'cameras': cameras})


@app.route('/api/osc/actions', methods=['GET'])
async def api_osc_actions_get():
    """Get custom OSC actions"""
    return jsonify({'status': 'ok', 'actions': config.OSC_ACTIONS})


@app.route('/api/osc/actions', methods=['POST'])
async def api_osc_actions_set():
    """Set custom OSC actions"""
    data = await request.get_json()
    actions = data.get('actions', [])
    config.OSC_ACTIONS = actions
    save_config()
    return jsonify({'status': 'ok'})


@app.route('/api/osc/emote', methods=['POST'])
async def api_osc_emote():
    """Send an OSC emote"""
    data = await request.get_json()
    emote_name = data.get('emote', '')
    if not emote_name:
        return jsonify({'status': 'error', 'error': 'No emote specified'}), 400
    
    success = send_osc_emote(emote_name)
    return jsonify({'status': 'ok' if success else 'error'})


@app.route('/api/osc/test', methods=['POST'])
async def api_osc_test():
    """Send a raw OSC message (address + value) for testing"""
    data = await request.get_json()
    address = data.get('address', '')
    value = data.get('value', '')
    if not address:
        return jsonify({'status': 'error', 'error': 'No address specified'}), 400
    
    success = send_osc_message(address, value)
    return jsonify({'status': 'ok' if success else 'error'})


def send_osc_emote(emote_name: str) -> bool:
    """Send an emote via OSC (UDP)"""
    return send_osc_message(config.OSC_ADDRESS, emote_name)


def send_osc_message(address: str, value) -> bool:
    """Send a generic OSC message (UDP) with a string value + True bool.
    Matches the format Unreal expects (string + True)."""
    if not address:
        print(f"OSC skipped: empty address (value='{value}')")
        return False
    try:
        from pythonosc import udp_client, osc_message_builder
        builder = osc_message_builder.OscMessageBuilder(address=address)
        builder.add_arg(str(value), builder.ARG_TYPE_STRING)
        builder.add_arg(True, builder.ARG_TYPE_TRUE)
        client = udp_client.SimpleUDPClient(config.OSC_IP, config.OSC_PORT)
        client.send(builder.build())
        print(f"OSC SENT: '{value}' to {config.OSC_IP}:{config.OSC_PORT} {address}")
        return True
    except Exception as e:
        print(f"OSC failed: {e}")
        return False


def get_avatar_state_context() -> str:
    """Return the avatar's current physical state for injection into the system prompt."""
    global current_pose
    return f"[Gem's current physical state: {current_pose}]"


def apply_action_tag(action: str) -> bool:
    """Send the OSC command for an action and update the current pose.
    Returns True if the action was recognized and sent."""
    global current_pose

    action_lower = action.lower()

    # If it's the base pose, just update state (no OSC needed)
    if action_lower in (config.AVATAR_BASE_POSE, 'idle', 'sitting', 'stand', 'standing'):
        current_pose = action_lower
        _persist_pose()
        print(f"[AVATAR] Pose set to: {current_pose}")
        return True

    # Look up the matching OSC action by value
    for osc_action in config.OSC_ACTIONS:
        if osc_action.get('value', '').lower() == action_lower:
            send_osc_message(osc_action.get('address', config.OSC_ADDRESS), osc_action.get('value', ''))
            current_pose = action_lower
            _persist_pose()
            print(f"[AVATAR] Action '{action_lower}' sent via OSC, pose updated.")
            return True

    # No exact match — try fuzzy matching against known action values
    resolved = resolve_action_value(action_lower)
    if resolved and resolved != action_lower:
        return apply_action_tag(resolved)

    # No match — leave pose unchanged
    print(f"[AVATAR] Unrecognized action '{action}', ignoring.")
    return False


def _animation_enum_values() -> list:
    """Collect the known animation names for the tool's enum (from OSC_ACTIONS)."""
    values = []
    for action in config.OSC_ACTIONS:
        value = action.get('value', '')
        if value and value not in values:
            values.append(value)
    return values


def get_animation_tools():
    """Build the LLM tool schema for triggering an avatar animation.

    Uses a single generic `trigger_animation` tool. When OSC_ACTIONS defines
    known values they're exposed as an enum; otherwise the action is a free
    string the LLM picks itself (resolved via fuzzy match later).
    """
    enum_values = _animation_enum_values()

    action_param: dict = {"type": "string", "description": "The animation to trigger."}
    if enum_values:
        action_param["enum"] = enum_values

    return [{
        "type": "function",
        "function": {
            "name": "trigger_animation",
            "description": (
                "Triggers a physical animation on the avatar. Only call this when "
                "the user is explicitly asking you to perform the action right now. "
                "Do NOT call it when the user is merely asking whether you CAN do "
                "something, or asking a hypothetical question."
            ),
            "parameters": {
                "type": "object",
                "properties": {"action": action_param},
                "required": ["action"],
            },
        },
    }]


def extract_tool_action(call: dict) -> str:
    """Extract the animation name from a raw LLM tool-call dict, or '' if not ours."""
    fn = call.get('function', {}) or {}
    if fn.get('name') != 'trigger_animation':
        return ''
    try:
        args = fn.get('arguments', {}) or {}
        if isinstance(args, str):
            import json as _json
            args = _json.loads(args)
    except Exception:
        args = {}
    return (args.get('action') or '').strip()


def get_browser_tools():
    """Build the LLM tool schema for the browser-use agent."""
    blocked = ", ".join(getattr(config, 'BROWSER_BLOCKED_TERMS', [])) or "none"
    return [{
        "type": "function",
        "function": {
            "name": "browse_web",
            "description": (
                "Open a web browser and perform a task for the user, such as "
                "looking something up, reading a page, or navigating a site. "
                "Only call this when the user is explicitly asking you to browse "
                "the web or look something up right now. "
                f"Refuse requests involving these disallowed topics: {blocked}."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "A clear, self-contained description of what to do in the browser.",
                    },
                },
                "required": ["task"],
            },
        },
    }]


def find_blocked_term(text: str) -> str:
    """Return the first blocked term found in text (case-insensitive), or ''."""
    text_lower = text.lower()
    for term in getattr(config, 'BROWSER_BLOCKED_TERMS', []):
        if term.lower() in text_lower:
            return term
    return ''


def extract_browser_task(call: dict) -> str:
    """Extract the task string from a raw LLM tool-call dict, or '' if not ours."""
    fn = call.get('function', {}) or {}
    if fn.get('name') != 'browse_web':
        return ''
    try:
        args = fn.get('arguments', {}) or {}
        if isinstance(args, str):
            import json as _json
            args = _json.loads(args)
    except Exception:
        args = {}
    return (args.get('task') or '').strip()


def resolve_action_value(action: str) -> str:
    """Fuzzy-match a free action string to the closest known OSC action value.

    Returns the matched value (as stored in OSC_ACTIONS), or the original
    action if nothing matches well enough.
    """
    if not config.OSC_ACTIONS:
        return action

    action_lower = action.lower().strip()
    if not action_lower:
        return action

    # Exact match
    for osc_action in config.OSC_ACTIONS:
        value = osc_action.get('value', '')
        if value.lower() == action_lower:
            return value

    # Substring / containment match (either direction)
    for osc_action in config.OSC_ACTIONS:
        value = osc_action.get('value', '')
        v = value.lower()
        if v and (v in action_lower or action_lower in v):
            return value

    return action


def _persist_pose():
    """Write the current avatar pose to a file so the separate watcher process
    can restore it after speaking (e.g. keep dancing instead of going idle).
    Writes locally AND to the network share (so the watcher on the other
    computer can read it)."""
    global current_pose
    path = os.path.join(os.path.dirname(__file__), "current_pose.txt")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(current_pose)
    except Exception as e:
        print(f"Failed to persist pose: {e}")

    # Also write to the network share so the watcher on the other computer sees it
    try:
        copy_to = getattr(config, 'TTS_COPY_TO', '')
        if copy_to:
            import shutil
            shutil.copy2(path, os.path.join(copy_to, "current_pose.txt"))
    except Exception as e:
        print(f"Failed to copy pose to network share: {e}")


@app.route('/api/recall', methods=['POST'])
async def api_recall():
    """Test memory recall from GUI"""
    data = await request.get_json()
    query = data.get('query', '')
    top_k = data.get('top_k', 5)
    
    results = await cognee.recall(query, top_k=top_k)
    return jsonify({'status': 'ok', 'results': results})


@app.route('/api/tts', methods=['POST'])
async def api_tts():
    """Test TTS from GUI (full pipeline, including talk animation + ducking)"""
    data = await request.get_json()
    text = data.get('text', '')

    await send_response(text)
    return jsonify({'status': 'ok'})


@app.route('/api/music/songs', methods=['GET'])
async def api_music_songs():
    """List available karaoke songs"""
    songs = music.list_songs()
    return jsonify({'status': 'ok', 'songs': songs})


@app.route('/api/music/queue', methods=['GET'])
async def api_music_queue():
    """Get current song queue"""
    return jsonify({'status': 'ok', 'queue': music.get_queue()})


@app.route('/api/music/queue', methods=['POST'])
async def api_music_add_queue():
    """Add song to queue"""
    data = await request.get_json()
    song_name = data.get('song', '')
    if not song_name:
        return jsonify({'status': 'error', 'error': 'No song specified'}), 400
    music.add_to_queue(song_name)
    return jsonify({'status': 'ok'})


@app.route('/api/music/queue', methods=['DELETE'])
async def api_music_clear_queue():
    """Clear song queue"""
    music.clear_queue()
    return jsonify({'status': 'ok'})


@app.route('/api/music/download', methods=['POST'])
async def api_music_download():
    """Download a song"""
    data = await request.get_json()
    query = data.get('query', '')
    if not query:
        return jsonify({'status': 'error', 'error': 'No query specified'}), 400
    success = music.download_song(query)
    return jsonify({'status': 'ok' if success else 'error'})


@app.route('/api/music/status', methods=['GET'])
async def api_music_status():
    """Get music download status"""
    return jsonify({'status': 'ok', **music.get_download_status()})


@app.route('/api/music/play', methods=['POST'])
async def api_music_play():
    """Play a karaoke song"""
    data = await request.get_json()
    song_name = data.get('song', '')
    if not song_name:
        return jsonify({'status': 'error', 'error': 'No song specified'}), 400
    success = music.play_song(song_name)
    return jsonify({'status': 'ok' if success else 'error'})


@app.route('/api/music/background', methods=['GET'])
async def api_music_background_list():
    """List background songs"""
    songs = music.list_background_songs()
    status = music.get_background_status()
    return jsonify({'status': 'ok', 'songs': songs, 'current': status['current']})


@app.route('/api/music/background', methods=['POST'])
async def api_music_background_set():
    """Set background song"""
    data = await request.get_json()
    song_name = data.get('song', '')
    if not song_name:
        return jsonify({'status': 'error', 'error': 'No song specified'}), 400
    success = music.set_background_song(song_name)
    return jsonify({'status': 'ok' if success else 'error'})


@app.route('/api/music/background/stop', methods=['POST'])
async def api_music_background_stop():
    """Stop background song"""
    success = music.stop_background_song()
    return jsonify({'status': 'ok' if success else 'error'})


@app.route('/api/music/background/pause', methods=['POST'])
async def api_music_background_pause():
    """Pause/resume background song"""
    data = await request.get_json()
    if data.get('resume'):
        success = music.resume_background_song()
    else:
        success = music.pause_background_song()
    return jsonify({'status': 'ok' if success else 'error'})


@app.route('/api/music/background/status', methods=['GET'])
async def api_music_background_status():
    """Get background song playback status (position, duration, paused)"""
    status = music.get_background_status()
    status['position'] = music.get_background_position()
    status['duration'] = music.get_background_duration()
    return jsonify({'status': 'ok', **status})


@app.route('/api/music/background/volume', methods=['POST'])
async def api_music_background_volume():
    """Set background music volume (0.0 to 1.0)"""
    data = await request.get_json()
    volume = data.get('volume', 1.0)
    success = music.set_background_volume(volume)
    return jsonify({'status': 'ok' if success else 'error'})


@app.route('/api/music/duck', methods=['POST'])
async def api_music_duck():
    """Duck background music (lower volume) when TTS speaks"""
    if not config.AUDIO_DUCKING_ENABLED:
        return jsonify({'status': 'ok', 'ducked': False})
    data = await request.get_json(silent=True) or {}
    music.duck_music(
        duck_amount=data.get('duck_amount', config.AUDIO_DUCK_AMOUNT),
        attack_ms=data.get('attack_ms', config.AUDIO_DUCK_ATTACK_MS),
        release_ms=data.get('release_ms', config.AUDIO_DUCK_RELEASE_MS)
    )
    return jsonify({'status': 'ok', 'ducked': True})


@app.route('/api/music/unduck', methods=['POST'])
async def api_music_unduck():
    """Restore background music volume after TTS finishes"""
    if not config.AUDIO_DUCKING_ENABLED:
        return jsonify({'status': 'ok', 'unducked': False})
    data = await request.get_json(silent=True) or {}
    music.unduck_music(release_ms=data.get('release_ms', config.AUDIO_DUCK_RELEASE_MS))
    return jsonify({'status': 'ok', 'unducked': True})


@app.route('/chat', methods=['POST'])
async def chat():
    """HTTP chat endpoint (alternative to WebSocket)"""
    data = await request.get_json()
    # Fire-and-forget: process in the background so the caller (e.g. Laya)
    # isn't blocked waiting for the full LLM + TTS pipeline to finish.
    asyncio.create_task(handle_incoming_message(data))
    return jsonify({'status': 'ok'})


@app.route('/process', methods=['POST'])
async def process():
    """Process transcribed audio from listen.py (microphone input).
    Pipes the transcribed text into the normal chat handler."""
    data = await request.get_json()
    text = data.get('text', '') or data.get('chatmessage', '')
    
    if not text:
        return jsonify({'status': 'error', 'error': 'No text provided'}), 400
    
    print(f"\n[VOICE] {text}")
    
    # Pipe voice input into the normal chat handler (same path as chat messages)
    await handle_incoming_message({
        'chatmessage': text,
        'chatname': config.VOICE_SPEAKER_NAME,
    })
    
    return jsonify({'status': 'ok'})


async def start_background_tasks():
    """Start background tasks"""
    # NOTE: SSN chat is received via HTTP POST (the "post" feature), not WebSocket.
    # The WebSocket listener is disabled to prevent duplicate message processing.
    # If you switch to WebSocket-only chat, re-enable by uncommenting below:
    # ssn.on_message = handle_incoming_message
    # asyncio.create_task(ssn.start_websocket_listener())

    # Start the idle manager monitor loop (autonomous behavior)
    asyncio.create_task(idle.monitor_loop())


@app.before_serving
async def startup():
    """Initialize connections on server start"""
    print("Starting Gem-System v2...")
    
    # Check LLM connection
    await llm.check_connection()
    
    # Check SSN connection
    await ssn.check_connection()
    
    # Check Cognee connection
    await cognee.check_connection()
    
    # Check music system
    music.check_connection()
    
    # Resume background music from saved state (if any)
    music.resume_background_from_state()
    
    # Check TTS connection (if enabled)
    if config.TTS_ENABLED:
        await tts.check_connection()
        # Start audio player (plays TTS output when not using Neurosync)
        if config.AUDIO_PLAYER_ENABLED:
            audio_player.start()
    
    # Check OpenCode connection (if enabled)
    if config.OPENCODE_ENABLED:
        await opencode.check_connection()
    
    # Check vision service (if enabled)
    if config.VISION_ENABLED:
        await vision.check_connection()
    
    # Check browser-use (if enabled)
    if getattr(config, 'BROWSER_ENABLED', False):
        browser.check_connection()
    
    # Start background tasks
    await start_background_tasks()


@app.after_serving
async def shutdown():
    """Save state on server shutdown"""
    print("Shutting down Gem-System v2...")
    music.save_background_state()
    try:
        await browser.close()
    except Exception:
        pass


if __name__ == '__main__':
    print("=" * 60)
    print("Gem-System v2")
    print("=" * 60)
    print(f"LLM: {config.OLLAMA_MODEL}")
    print(f"SSN: {config.SSN_API_URL}")
    print(f"Server: http://{config.SERVER_HOST}:{config.SERVER_PORT}")
    print("=" * 60)
    
    bind_host = getattr(config, 'SERVER_BIND_HOST', config.SERVER_HOST)
    app.run(host=bind_host, port=config.SERVER_PORT)
