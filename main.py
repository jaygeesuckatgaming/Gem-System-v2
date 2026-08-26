"""
Gem-System v2 - Main Quart Server
Receives chat from Social Stream Ninja, sends to Ollama, broadcasts response
"""

import asyncio
import html
import json
import os
from collections import deque
from quart import Quart, request, jsonify
from quart_cors import cors

import config
from clients import LLMClient, SSNClient, CogneeClient, TTSClient
from clients.audio_player import AudioPlayer

app = Quart(__name__)
app = cors(app, allow_origin="*")

# Initialize clients
llm = LLMClient(model=config.OLLAMA_MODEL, base_url=config.OLLAMA_BASE_URL)
ssn = SSNClient(api_url=config.SSN_API_URL, session_id=config.SSN_SESSION_ID)
cognee = CogneeClient(server_url=config.COGNEE_SERVER_URL)
tts = TTSClient(tts_url=config.TTS_URL)

# Audio player (plays TTS output when not using Neurosync)
_tts_output_path = os.path.join(os.path.dirname(__file__), config.TTS_OUTPUT_PATH)
audio_player = AudioPlayer(watch_path=_tts_output_path, device_name=config.AUDIO_OUTPUT_DEVICE or None)

# Track recent AI responses to prevent echo loops
_last_ai_responses = deque(maxlen=10)

# Settings persistence file
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "settings.json")


def load_persisted_settings():
    """Load settings from settings.json (overrides config.py defaults)"""
    if not os.path.exists(SETTINGS_FILE):
        return
    try:
        with open(SETTINGS_FILE, "r") as f:
            data = json.load(f)
        
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
        if 'audio_ducking_enabled' in data:
            config.AUDIO_DUCKING_ENABLED = data['audio_ducking_enabled']
        if 'audio_duck_amount' in data:
            config.AUDIO_DUCK_AMOUNT = data['audio_duck_amount']
        if 'audio_duck_attack_ms' in data:
            config.AUDIO_DUCK_ATTACK_MS = data['audio_duck_attack_ms']
        if 'audio_duck_release_ms' in data:
            config.AUDIO_DUCK_RELEASE_MS = data['audio_duck_release_ms']
    except Exception as e:
        print(f"Failed to load settings.json: {e}")


def save_persisted_settings():
    """Save TTS settings to settings.json"""
    try:
        data = {
            'tts_enabled': config.TTS_ENABLED,
            'tts_url': config.TTS_URL,
            'tts_diffusion_steps': config.TTS_DIFFUSION_STEPS,
            'tts_embedding_scale': config.TTS_EMBEDDING_SCALE,
            'tts_alpha': config.TTS_ALPHA,
            'tts_beta': config.TTS_BETA,
            'tts_reference_voice': config.TTS_REFERENCE_VOICE,
            'audio_player_enabled': config.AUDIO_PLAYER_ENABLED,
            'audio_output_device': config.AUDIO_OUTPUT_DEVICE,
            'audio_ducking_enabled': config.AUDIO_DUCKING_ENABLED,
            'audio_duck_amount': config.AUDIO_DUCK_AMOUNT,
            'audio_duck_attack_ms': config.AUDIO_DUCK_ATTACK_MS,
            'audio_duck_release_ms': config.AUDIO_DUCK_RELEASE_MS
        }
        with open(SETTINGS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Failed to save settings.json: {e}")


# Load persisted settings on startup
load_persisted_settings()


async def handle_incoming_message(data: dict):
    """Process incoming chat from SSN WebSocket"""
    # Extract message data
    message = data.get('chatmessage', '')
    speaker = data.get('chatname', 'Unknown')
    
    print(f"\n[CHAT] {speaker}: {message}")
    
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
    
    # Store user message in memory
    await cognee.remember(speaker, message)
    
    # Recall memory context
    memory_context = await get_memory_context(speaker, message)
    
    # Get response from LLM
    system_prompt = config.SYSTEM_PROMPT
    if memory_context:
        system_prompt = f"{system_prompt}\n\n{memory_context}"
    
    response = await llm.chat(message, system_prompt=system_prompt)
    print(f"[GEM] {response}")
    
    # Store AI response in memory
    await cognee.remember("Gem", response)
    
    # Track response to prevent echo
    _last_ai_responses.append(html.unescape(response).strip())
    
    # Send response to TTS (if enabled)
    if config.TTS_ENABLED:
        await tts.speak(response)
    
    # Send response to SSN
    await ssn.send_message(response, targets=config.SSN_TARGETS)


async def get_memory_context(speaker: str, message: str) -> str:
    """Retrieve relevant memories for the current message"""
    import re
    
    memory_context = ""
    
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
    entities = re.findall(r'\b[A-Z][a-z]+\b', message)
    entities = [e for e in entities if e.lower() not in config.STOP_WORDS]
    
    for entity in entities[:3]:
        entity_results = await cognee.recall(f"[chat] {entity}:", top_k=3)
        if not entity_results:
            entity_results = await cognee.recall(f"{entity}:", top_k=3)
        if not entity_results:
            entity_results = await cognee.recall(f"{entity}", top_k=3)
        
        if entity_results:
            memory_context += f"\n\nThings you remember about {entity}:"
            for result in entity_results:
                memory_context += f"\n- {result}"
    
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


@app.route('/api/settings', methods=['GET'])
async def api_get_settings():
    """Get current settings for GUI"""
    return jsonify({
        'system_prompt': config.SYSTEM_PROMPT,
        'wake_words': config.WAKE_WORDS,
        'ollama_model': config.OLLAMA_MODEL,
        'ssn_session_id': config.SSN_SESSION_ID
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
    
    # Persist TTS settings to file
    save_persisted_settings()
    
    return jsonify({'status': 'ok'})


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


@app.route('/chat', methods=['POST'])
async def chat():
    """HTTP chat endpoint (alternative to WebSocket)"""
    data = await request.get_json()
    await handle_incoming_message(data)
    return jsonify({'status': 'ok'})


async def start_background_tasks():
    """Start SSN WebSocket listener in background"""
    # Start WebSocket listener
    asyncio.create_task(ssn.start_websocket_listener())


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
    
    # Check TTS connection (if enabled)
    if config.TTS_ENABLED:
        await tts.check_connection()
        # Start audio player (plays TTS output when not using Neurosync)
        if config.AUDIO_PLAYER_ENABLED:
            audio_player.start()
    
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
