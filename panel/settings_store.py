"""Settings loading + saving for the NiceGUI control panel.

- LOAD: imports config.py directly (fresh import on each page render) so all
  fields populate with NO services running.
- SAVE: the panel is the file writer — config.py is rewritten via the shared
  config_writer (same rules as main.py's save_config), then live updates are
  pushed to whatever is running:
    * main.py  -> POST /api/settings   (updates its live clients, no restart)
    * vision.py -> POST :5001/settings (updates stream + recognizer, no restart)

Key routing: main.py consumes the snake_case payload keys below; vision.py
consumes its own config-dict keys. Keys absent from a service's map are
simply not pushed to that service (the file write carries them).
"""

import importlib.util
import os

import httpx

from config_writer import write_config_values

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(PROJECT_ROOT, 'config.py')

MAIN_URL = 'http://127.0.0.1:5000'
VISION_URL = 'http://127.0.0.1:5001'

# config.py KEY -> main.py /api/settings payload key (None = main.py doesn't consume it)
MAIN_KEY_MAP = {
    'OLLAMA_MODEL': 'ollama_model',
    'SYSTEM_PROMPT': 'system_prompt',
    'WAKE_WORDS': 'wake_words',
    'VOICE_SPEAKER_NAME': 'voice_speaker_name',
    'VISION_ENABLED': 'vision_enabled',
    'VISION_SCAN_URL': 'vision_scan_url',
    'VISION_GET_IMAGE_URL': 'vision_get_image_url',
    'VISION_TRIGGER_WORDS': 'vision_trigger_words',
    'VISION_IMAGE_SOURCE': 'vision_image_source',
    'VISION_CAMERA_INDEX': 'vision_camera_index',
    'VISION_NDI_SOURCE_NAME': 'vision_ndi_source_name',
    'VISION_FRAME_MAX_EDGE': 'vision_frame_max_edge',
    'VISION_WATCH_LABEL': 'vision_watch_label',
    'VISION_FACE_RECOGNITION_ENABLED': 'vision_face_recognition_enabled',
    'VISION_FACE_SCAN_INTERVAL_S': 'vision_face_scan_interval_s',
    'VISION_FACE_MATCH_THRESHOLD': 'vision_face_match_threshold',
    'VISION_FACE_DETECTION_THRESHOLD': 'vision_face_detection_threshold',
    'VISION_FACE_MIN_WIDTH_PX': 'vision_face_min_width_px',
    'VISION_FACE_GREET_ENABLED': 'vision_face_greet_enabled',
    'VISION_FACE_GREET_COOLDOWN_S': 'vision_face_greet_cooldown_s',
    'VISION_FACE_ABSENCE_RESET_S': 'vision_face_absence_reset_s',
    'VISION_FACE_REPORT_UNKNOWN': 'vision_face_report_unknown',
    # Audio
    'AUDIO_PLAYER_ENABLED': 'audio_player_enabled',
    'AUDIO_OUTPUT_DEVICE': 'audio_output_device',
    'MUSIC_OUTPUT_DEVICE': 'music_output_device',
    'AUDIO_DUCKING_ENABLED': 'audio_ducking_enabled',
    'AUDIO_DUCK_AMOUNT': 'audio_duck_amount',
    'AUDIO_DUCK_ATTACK_MS': 'audio_duck_attack_ms',
    'AUDIO_DUCK_RELEASE_MS': 'audio_duck_release_ms',
    'AUDIO_DUCK_DELAY_S': 'audio_duck_delay_s',
    'AUDIO_DUCK_HOLD_S': 'audio_duck_hold_s',
    # TTS
    'TTS_ENABLED': 'tts_enabled',
    'TTS_ENGINE': 'tts_engine',
    'TTS_URL': 'tts_url',
    'POCKET_TTS_URL': 'pocket_tts_url',
    'VIBEVOICE_TTS_URL': 'vibevoice_tts_url',
    'QWEN_TTS_URL': 'qwen_tts_url',
    'MING_TTS_URL': 'ming_tts_url',
    'AUDIO8_TTS_URL': 'audio8_tts_url',
    'VIBEVOICE_MODEL': 'vibevoice_model',
    'VIBEVOICE_INFERENCE_STEPS': 'vibevoice_inference_steps',
    'TTS_DIFFUSION_STEPS': 'tts_diffusion_steps',
    'TTS_EMBEDDING_SCALE': 'tts_embedding_scale',
    'TTS_ALPHA': 'tts_alpha',
    'TTS_BETA': 'tts_beta',
    'TTS_REFERENCE_VOICE': 'tts_reference_voice',
    'TTS_COPY_TO': 'tts_copy_to',
    'SEND_RESPONSES_TO_CHAT': 'send_responses_to_chat',
    # Neurosync / avatar
    'BLENDSHAPE_MOUTH_SCALE': 'blendshape_mouth_scale',
    'BLENDSHAPE_EYE_SCALE': 'blendshape_eye_scale',
    'BLENDSHAPE_EYEBROW_SCALE': 'blendshape_eyebrow_scale',
    'BLENDSHAPE_EYEWIDE_SCALE': 'blendshape_eyewide_scale',
    'BLENDSHAPE_EYESQUINT_SCALE': 'blendshape_eyesquint_scale',
    'OSC_IP': 'osc_ip',
    'OSC_PORT': 'osc_port',
    'OSC_ADDRESS': 'osc_address',
    'OSC_RECEIVE_IP': 'osc_receive_ip',
    'OSC_RECEIVE_PORT': 'osc_receive_port',
    'OSC_RECEIVE_VERBOSE': 'osc_receive_verbose',
    'LIVELINK_IP': 'livelink_ip',
    'LIVELINK_PORT': 'livelink_port',
    'TTS_OUTPUT_PATH': 'tts_output_path',
    'AVATAR_TALK_START_DELAY_S': 'avatar_talk_start_delay_s',
    'AVATAR_TALK_STOP_DELAY_S': 'avatar_talk_stop_delay_s',
    # Music
    'BACKGROUND_VOLUME': 'background_volume',
    'MUSIC_GEN_ENABLED': 'music_gen_enabled',
    'MUSIC_GEN_COMFYUI_URL': 'music_gen_comfyui_url',
    'MUSIC_GEN_WORKFLOW_FILE': 'music_gen_workflow_file',
    'MUSIC_GEN_TEXT_NODE_ID': 'music_gen_text_node_id',
    # Browser use
    'BROWSER_ENABLED': 'browser_enabled',
    'BROWSER_LLM_PROVIDER': 'browser_llm_provider',
    'BROWSER_OLLAMA_MODEL': 'browser_ollama_model',
    'BROWSER_OPENAI_MODEL': 'browser_openai_model',
    'BROWSER_OPENAI_API_KEY': 'browser_openai_api_key',
    'BROWSER_HEADLESS': 'browser_headless',
    'BROWSER_VIEWPORT_WIDTH': 'browser_viewport_width',
    'BROWSER_VIEWPORT_HEIGHT': 'browser_viewport_height',
    'BROWSER_WINDOW_X': 'browser_window_x',
    'BROWSER_WINDOW_Y': 'browser_window_y',
    # SSN
    'SSN_SESSION_ID': 'ssn_session_id',
    'SSN_TARGETS': 'ssn_targets',
    # STT (speech-to-text listener)
    'STT_WHISPER_MODEL': 'stt_whisper_model',
    'STT_VAD_AGGRESSIVENESS': 'stt_vad_aggressiveness',
    'STT_SILENCE_THRESHOLD_S': 'stt_silence_threshold_s',
    'STT_PRE_BUFFER_S': 'stt_pre_buffer_s',
    'STT_MIN_DB': 'stt_min_db',
    'STT_SERVER_URL': 'stt_server_url',
    'MIC_ROUTE': 'mic_route',
    # Twitch
    'TWITCH_ENABLED': 'twitch_enabled',
    'TWITCH_CLIENT_ID': 'twitch_client_id',
    'TWITCH_CLIENT_SECRET': 'twitch_client_secret',
    'TWITCH_OAUTH_TOKEN': 'twitch_oauth_token',
    'TWITCH_REFRESH_TOKEN': 'twitch_refresh_token',
    'TWITCH_CHANNEL': 'twitch_channel',
    'TWITCH_SUB_ANIMATION': 'twitch_sub_animation',
    'TWITCH_SUB_ANIMATION_DUCK_S': 'twitch_sub_animation_duck_s',
    # Gem Drive (game process reads tuning at startup; these are live in main.py)
    'GAME_DRIVE_ENABLED': 'game_drive_enabled',
    'GAME_DRIVE_SUPPRESS_IDLE': 'game_drive_suppress_idle',
    'GAME_DRIVE_URL': 'game_drive_url',
    'GAME_DRIVE_COMMENTARY_ENABLED': 'game_drive_commentary_enabled',
    'GAME_DRIVE_COMMENTARY_COOLDOWN_S': 'game_drive_commentary_cooldown_s',
    'GAME_DRIVE_COMMENTARY_USE_LLM': 'game_drive_commentary_use_llm',
    # Idle actions / monologues
    'IDLE_ACTIONS_ENABLED': 'idle_actions_enabled',
    'IDLE_INACTIVITY_LIMIT': 'idle_inactivity_limit',
    'IDLE_COOLDOWN': 'idle_cooldown',
    'IDLE_OSC_STATE_ADDRESS': 'idle_osc_state_address',
    'IDLE_OSC_ACTION_ADDRESS': 'idle_osc_action_address',
    'IDLE_OSC_BORED_VALUE': 'idle_osc_bored_value',
    'IDLE_OSC_NORMAL_VALUE': 'idle_osc_normal_value',
    'IDLE_OSC_TALK_VALUE': 'idle_osc_talk_value',
    'IDLE_OSC_IDLE_VALUE': 'idle_osc_idle_value',
    'IDLE_TOPICS': 'idle_topics',
    'IDLE_MONOLOGUE_PROMPT': 'idle_monologue_prompt',
    # Note: AUDIO_INPUT_DEVICE is pushed via the dedicated
    # POST /api/audio/input_device endpoint (see audio_tab.save handler).
}

# config.py KEY -> vision.py /settings payload key (None = vision.py doesn't consume it)
VISION_KEY_MAP = {
    'VISION_IMAGE_SOURCE': 'image_source',
    'VISION_CAMERA_INDEX': 'camera_index',
    'VISION_NDI_SOURCE_NAME': 'ndi_source_name',
    'VISION_FRAME_MAX_EDGE': 'frame_max_edge',
    'VISION_FACE_RECOGNITION_ENABLED': 'face_recognition_enabled',
    'VISION_FACE_SCAN_INTERVAL_S': 'face_scan_interval_s',
    'VISION_FACE_MATCH_THRESHOLD': 'face_match_threshold',
    'VISION_FACE_DETECTION_THRESHOLD': 'face_detection_threshold',
    'VISION_FACE_MIN_WIDTH_PX': 'face_min_width_px',
    'VISION_FACE_ABSENCE_RESET_S': 'face_absence_reset_s',
    'VISION_FACE_REPORT_UNKNOWN': 'face_report_unknown',
    'VISION_FACE_IGNORE_NAMES': 'face_ignore_names',
}


def load_config():
    """Freshly import config.py and return the module (fields populate
    without any service running)."""
    spec = importlib.util.spec_from_file_location('panel_config', CONFIG_FILE)
    cfg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cfg)
    return cfg


# Multiline / structured keys routed through the shared writer's special path
SPECIAL_KEYS = {'SYSTEM_PROMPT', 'GAME_AGENT_SYSTEM_PROMPT', 'OSC_ACTIONS',
                'ISO_OSC_ACTIONS',
                'IDLE_TOPICS', 'IDLE_MONOLOGUE_PROMPT',
                'LAYA_ANIMATION_MAP', 'LAYA_ANIMATION_OPTIONS', 'BROWSER_BLOCKED_TERMS'}


def save(values):
    """Persist settings and push live updates to running services.

    values: {CONFIG_KEY: python_value} — written to config.py, then pushed
    to main.py and/or vision.py if they answer their health endpoints.
    Returns (file_ok, pushed: dict of which service accepted a push).
    """
    updates = {k: (v, isinstance(v, str)) for k, v in values.items()
               if k not in SPECIAL_KEYS}
    special = {k: values[k] for k in values if k in SPECIAL_KEYS}
    file_ok = write_config_values(CONFIG_FILE, updates, special)

    pushed = {}
    main_payload = {MAIN_KEY_MAP[k]: v for k, v in values.items() if k in MAIN_KEY_MAP}
    if main_payload:
        try:
            with httpx.Client(timeout=5.0) as client:
                r = client.post(f'{MAIN_URL}/api/settings', json=main_payload)
                if r.status_code == 200:
                    pushed['main'] = True
        except Exception:
            pass

    vision_payload = {VISION_KEY_MAP[k]: v for k, v in values.items() if k in VISION_KEY_MAP}
    if vision_payload:
        try:
            with httpx.Client(timeout=5.0) as client:
                r = client.post(f'{VISION_URL}/settings', json=vision_payload)
                if r.status_code == 200:
                    pushed['vision'] = True
        except Exception:
            pass

    return file_ok, pushed