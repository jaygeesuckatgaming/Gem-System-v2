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
from datetime import datetime
from zoneinfo import ZoneInfo
from quart import Quart, request, jsonify
from quart_cors import cors

import config
from clients import LLMClient, SSNClient, CogneeClient, TTSClient, MusicClient, OpenCodeClient, VisionClient
from clients.audio_player import AudioPlayer
from clients.opencode_client import format_opencode_response

app = Quart(__name__)
app = cors(app, allow_origin="*")

# Initialize clients
llm = LLMClient(model=config.OLLAMA_MODEL, base_url=config.OLLAMA_BASE_URL)
ssn = SSNClient(api_url=config.SSN_API_URL, session_id=config.SSN_SESSION_ID)
cognee = CogneeClient(server_url=config.COGNEE_SERVER_URL)
tts = TTSClient(tts_url=config.TTS_URL)
music = MusicClient(device_name=config.AUDIO_OUTPUT_DEVICE or None)
opencode = OpenCodeClient(api_url=config.OPENCODE_API_URL, workspace=config.OPENCODE_WORKSPACE)
vision = VisionClient(scan_url=config.VISION_SCAN_URL, get_image_url=config.VISION_GET_IMAGE_URL)

# Audio player (plays TTS output when not using Neurosync)
_tts_output_path = os.path.join(os.path.dirname(__file__), config.TTS_OUTPUT_PATH)
audio_player = AudioPlayer(watch_path=_tts_output_path, device_name=config.AUDIO_OUTPUT_DEVICE or None)

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
            'TTS_ENABLED': (config.TTS_ENABLED, False),
            'TTS_URL': (config.TTS_URL, True),
            'TTS_DIFFUSION_STEPS': (config.TTS_DIFFUSION_STEPS, False),
            'TTS_EMBEDDING_SCALE': (config.TTS_EMBEDDING_SCALE, False),
            'TTS_ALPHA': (config.TTS_ALPHA, False),
            'TTS_BETA': (config.TTS_BETA, False),
            'TTS_REFERENCE_VOICE': (config.TTS_REFERENCE_VOICE, True),
            'AUDIO_PLAYER_ENABLED': (config.AUDIO_PLAYER_ENABLED, False),
            'AUDIO_OUTPUT_DEVICE': (config.AUDIO_OUTPUT_DEVICE, True),
            'AUDIO_INPUT_DEVICE': (config.AUDIO_INPUT_DEVICE, True),
            'AUDIO_DUCKING_ENABLED': (config.AUDIO_DUCKING_ENABLED, False),
            'AUDIO_DUCK_AMOUNT': (config.AUDIO_DUCK_AMOUNT, False),
            'AUDIO_DUCK_ATTACK_MS': (config.AUDIO_DUCK_ATTACK_MS, False),
            'AUDIO_DUCK_RELEASE_MS': (config.AUDIO_DUCK_RELEASE_MS, False),
            'BLENDSHAPE_MOUTH_SCALE': (config.BLENDSHAPE_MOUTH_SCALE, False),
            'BLENDSHAPE_EYE_SCALE': (config.BLENDSHAPE_EYE_SCALE, False),
            'BLENDSHAPE_EYEBROW_SCALE': (config.BLENDSHAPE_EYEBROW_SCALE, False),
            'BLENDSHAPE_EYEWIDE_SCALE': (config.BLENDSHAPE_EYEWIDE_SCALE, False),
            'BLENDSHAPE_EYESQUINT_SCALE': (config.BLENDSHAPE_EYESQUINT_SCALE, False),
            'OSC_ENABLED': (config.OSC_ENABLED, False),
            'OSC_IP': (config.OSC_IP, True),
            'OSC_PORT': (config.OSC_PORT, False),
            'OSC_ADDRESS': (config.OSC_ADDRESS, True),
            'LIVELINK_IP': (config.LIVELINK_IP, True),
            'LIVELINK_PORT': (config.LIVELINK_PORT, False),
            'TWITCH_MUSIC_CHECK_ENABLED': (config.TWITCH_MUSIC_CHECK_ENABLED, False),
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
            'SSN_SESSION_ID': (config.SSN_SESSION_ID, True),
            'OLLAMA_MODEL': (config.OLLAMA_MODEL, True),
        }

        for key, (value, is_string) in settings.items():
            if is_string:
                new_value = f'"{value}"'
            else:
                new_value = str(value)
            # Replace the assignment line
            pattern = re.compile(rf'^{key}\s*=\s*.*$', re.MULTILINE)
            content = pattern.sub(f'{key} = {new_value}', content)

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


async def handle_incoming_message(data: dict):
    """Process incoming chat from SSN WebSocket"""
    # Extract message data
    message = data.get('chatmessage', '')
    speaker = data.get('chatname', 'Unknown')
    
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
    
    # Check for song command (intercept before LLM)
    song_name = extract_song_command(message)
    if song_name:
        print(f"🎵 Song command detected: '{song_name}'")
        
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
        
        music.download_song(song_name)
        await ssn.send_message(f"🎵 Got it! Downloading '{song_name}'...", targets=config.SSN_TARGETS)
        return
    
    # Check for custom OSC action (intercept before LLM)
    osc_action = match_osc_action(message)
    if osc_action:
        print(f"🎛️ OSC action detected: '{osc_action.get('phrase')}'")
        address = osc_action.get('address', config.OSC_ADDRESS)
        value = osc_action.get('value', '')
        send_osc_message(address, value)
        await ssn.send_message(f"🎛️ Done! {osc_action.get('phrase')}", targets=config.SSN_TARGETS)
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
        
        # Get scene description from vision service
        vision_context = await vision.get_scene_description()
        if vision_context:
            # Include vision context in the LLM prompt
            system_prompt = f"{config.SYSTEM_PROMPT}\n\nYou can see the current scene: {vision_context}"
            response = await llm.chat(message, system_prompt=system_prompt)
        else:
            response = await llm.chat(message, system_prompt=config.SYSTEM_PROMPT)
        
        print(f"[GEM] {response}")
        await cognee.remember("Gem", response)
        _last_ai_responses.append(html.unescape(response).strip())
        if config.TTS_ENABLED:
            await tts.speak(response)
        await ssn.send_message(response, targets=config.SSN_TARGETS)
        return
    
    # Check for time query (intercept before LLM so it uses the real time)
    if is_time_command(message):
        print(f"🕐 Time command detected: '{message}'")
        await cognee.remember(speaker, message)
        location = extract_time_location(message)
        time_ctx = get_time_for_location(location)
        print(f"🕐 Time context: '{time_ctx}'")
        # Force the LLM to use the actual time, not make up its own answer
        response = await llm.chat(
            f"{time_ctx} User asks: '{message}'. Give ONLY the actual time shown above, be concise.",
            system_prompt=config.SYSTEM_PROMPT
        )
        print(f"[GEM] {response}")
        await cognee.remember("Gem", response)
        _last_ai_responses.append(html.unescape(response).strip())
        if config.TTS_ENABLED:
            await tts.speak(response)
        await ssn.send_message(response, targets=config.SSN_TARGETS)
        return

    # Store user message in memory
    await cognee.remember(speaker, message)
    
    # Translate emotes so the LLM understands them
    llm_message = translate_emotes(message)
    
    # Recall memory context
    memory_context = await get_memory_context(speaker, message)
    
    # Get response from LLM
    system_prompt = config.SYSTEM_PROMPT
    if memory_context:
        system_prompt = f"{system_prompt}\n\n{memory_context}"
    
    response = await llm.chat(llm_message, system_prompt=system_prompt)
    print(f"[GEM] {response}")
    
    # Store AI response in memory
    await cognee.remember("Gem", response)
    
    # Track response to prevent echo
    _last_ai_responses.append(html.unescape(response).strip())
    
    # Send response to TTS first (it takes time to synthesize)
    if config.TTS_ENABLED:
        await tts.speak(response)
    
    # Send response to SSN (chat appears after audio is ready)
    await ssn.send_message(response, targets=config.SSN_TARGETS)


async def get_memory_context(speaker: str, message: str) -> str:
    """Retrieve relevant memories for the current message (with overall timeout)"""
    import re
    
    memory_context = ""
    
    try:
        # Wrap the whole recall in a timeout so it can't block the chat
        async with asyncio.timeout(3.0):
            # 1. Get user profile
            user_results = await cognee.recall(f"[chat] {speaker}:", top_k=5)
            if not user_results:
                user_results = await cognee.recall(f"{speaker}:", top_k=5)
            if not user_results:
                user_results = await cognee.recall(f"{speaker}", top_k=5)
            
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
                entity_results = await cognee.recall(f"[chat] {term}:", top_k=3)
                if not entity_results:
                    entity_results = await cognee.recall(f"{term}:", top_k=3)
                if not entity_results:
                    entity_results = await cognee.recall(f"{term}", top_k=3)
                
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
        'cognee': cognee.enabled
    })


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
            'enabled': tts.enabled,
            'tts_url': config.TTS_URL,
            'diffusion_steps': config.TTS_DIFFUSION_STEPS,
            'embedding_scale': config.TTS_EMBEDDING_SCALE,
            'alpha': config.TTS_ALPHA,
            'beta': config.TTS_BETA,
            'reference_voice': config.TTS_REFERENCE_VOICE,
            'audio_player_enabled': config.AUDIO_PLAYER_ENABLED
        },
        'audio': {
            'output_device': config.AUDIO_OUTPUT_DEVICE,
            'ducking_enabled': config.AUDIO_DUCKING_ENABLED,
            'duck_amount': config.AUDIO_DUCK_AMOUNT,
            'attack_ms': config.AUDIO_DUCK_ATTACK_MS,
            'release_ms': config.AUDIO_DUCK_RELEASE_MS
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
        'voice_speaker_name': config.VOICE_SPEAKER_NAME
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
    if 'tts_url' in data:
        config.TTS_URL = data['tts_url']
        tts.tts_url = data['tts_url']
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
    if 'audio_player_enabled' in data:
        config.AUDIO_PLAYER_ENABLED = data['audio_player_enabled']
    if 'audio_output_device' in data:
        config.AUDIO_OUTPUT_DEVICE = data['audio_output_device']
        audio_player.device_name = data['audio_output_device'] or None
    if 'audio_ducking_enabled' in data:
        config.AUDIO_DUCKING_ENABLED = data['audio_ducking_enabled']
    if 'audio_duck_amount' in data:
        config.AUDIO_DUCK_AMOUNT = data['audio_duck_amount']
    if 'audio_duck_attack_ms' in data:
        config.AUDIO_DUCK_ATTACK_MS = data['audio_duck_attack_ms']
    if 'audio_duck_release_ms' in data:
        config.AUDIO_DUCK_RELEASE_MS = data['audio_duck_release_ms']
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
    if 'livelink_ip' in data:
        config.LIVELINK_IP = data['livelink_ip']
    if 'livelink_port' in data:
        config.LIVELINK_PORT = data['livelink_port']
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


def send_osc_emote(emote_name: str) -> bool:
    """Send an emote via OSC (UDP)"""
    return send_osc_message(config.OSC_ADDRESS, emote_name)


def send_osc_message(address: str, value) -> bool:
    """Send a generic OSC message (UDP) with a string value"""
    import socket
    
    try:
        ip = config.OSC_IP
        port = config.OSC_PORT
        
        # Build OSC message
        address_bytes = address.encode('utf-8')
        address_padded = address_bytes + b'\x00' * ((4 - len(address_bytes) % 4) % 4)
        type_tag = b',s\x00\x00'
        value_str = str(value)
        str_len = len(value_str.encode('utf-8'))
        length_bytes = str_len.to_bytes(4, 'big')
        arg_bytes = value_str.encode('utf-8')
        arg_padded = arg_bytes + b'\x00' * ((4 - len(arg_bytes) % 4) % 4)
        message = address_padded + type_tag + length_bytes + arg_padded
        
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(message, (ip, port))
        
        print(f"OSC SENT: '{value_str}' to {ip}:{port} {address}")
        return True
    except Exception as e:
        print(f"OSC failed: {e}")
        return False


def match_osc_action(text: str):
    """Match a message against custom OSC actions.
    Returns the matched action dict, or None.
    """
    text_lower = text.lower().strip()
    for action in config.OSC_ACTIONS:
        phrase = action.get('phrase', '').lower().strip()
        if phrase and phrase in text_lower:
            return action
    return None


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
    """Test TTS from GUI"""
    data = await request.get_json()
    text = data.get('text', '')
    
    success = await tts.speak(text)
    return jsonify({'status': 'ok' if success else 'error'})


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
    await handle_incoming_message(data)
    return jsonify({'status': 'ok'})


@app.route('/process', methods=['POST'])
async def process():
    """Process transcribed audio from listen.py (microphone input)"""
    data = await request.get_json()
    text = data.get('text', '') or data.get('chatmessage', '')
    source = data.get('source', 'microphone')
    
    if not text:
        return jsonify({'status': 'error', 'error': 'No text provided'}), 400
    
    print(f"\n[VOICE] {text}")
    
    # Prevent echo loop - ignore if the transcribed text matches a recent AI response
    # (the microphone picks up Gem's own voice and re-transcribes it)
    text_clean = html.unescape(text).strip()
    for last_response in _last_ai_responses:
        if text_clean == last_response:
            print(f"  → Ignoring echo of last AI response")
            return jsonify({'status': 'ok', 'ignored': 'echo'})
    
    # Voice input doesn't need a wake word - process directly
    # Check for song command
    song_name = extract_song_command(text)
    if song_name:
        print(f"🎵 Song command detected: '{song_name}'")
        await cognee.remember(config.VOICE_SPEAKER_NAME, text)
        if config.TWITCH_MUSIC_CHECK_ENABLED:
            result = music.verify_song(song_name)
            if result.get('status') == 'restricted':
                await ssn.send_message(result.get('message', "Sorry, that song is restricted."), targets=config.SSN_TARGETS)
                return jsonify({'status': 'ok'})
        music.download_song(song_name)
        await ssn.send_message(f"🎵 Got it! Downloading '{song_name}'...", targets=config.SSN_TARGETS)
        return jsonify({'status': 'ok'})
    
    # Check for custom OSC action
    osc_action = match_osc_action(text)
    if osc_action:
        print(f"🎛️ OSC action detected: '{osc_action.get('phrase')}'")
        send_osc_message(osc_action.get('address', config.OSC_ADDRESS), osc_action.get('value', ''))
        await ssn.send_message(f"🎛️ Done! {osc_action.get('phrase')}", targets=config.SSN_TARGETS)
        return jsonify({'status': 'ok'})
    
    # Store in memory
    await cognee.remember(config.VOICE_SPEAKER_NAME, text)
    
    # Recall memory context
    memory_context = await get_memory_context(config.VOICE_SPEAKER_NAME, text)
    
    # Get response from LLM
    system_prompt = config.SYSTEM_PROMPT
    if memory_context:
        system_prompt = f"{system_prompt}\n\n{memory_context}"
    
    response = await llm.chat(text, system_prompt=system_prompt)
    print(f"[GEM] {response}")
    
    # Store AI response in memory
    await cognee.remember("Gem", response)
    
    # Track response to prevent echo
    _last_ai_responses.append(html.unescape(response).strip())
    
    # Send response to TTS first (it takes time to synthesize)
    if config.TTS_ENABLED:
        await tts.speak(response)
    
    # Send response to SSN (chat appears after audio is ready)
    await ssn.send_message(response, targets=config.SSN_TARGETS)
    
    return jsonify({'status': 'ok', 'response': response})


async def start_background_tasks():
    """Start background tasks"""
    # NOTE: SSN chat is received via HTTP POST (the "post" feature), not WebSocket.
    # The WebSocket listener is disabled to prevent duplicate message processing.
    # If you switch to WebSocket-only chat, re-enable by uncommenting below:
    # ssn.on_message = handle_incoming_message
    # asyncio.create_task(ssn.start_websocket_listener())
    pass


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
    
    # Start background tasks
    await start_background_tasks()


if __name__ == '__main__':
    print("=" * 60)
    print("Gem-System v2")
    print("=" * 60)
    print(f"LLM: {config.OLLAMA_MODEL}")
    print(f"SSN: {config.SSN_API_URL}")
    print(f"Server: http://{config.SERVER_HOST}:{config.SERVER_PORT}")
    print("=" * 60)
    
    app.run(host=config.SERVER_HOST, port=config.SERVER_PORT)
