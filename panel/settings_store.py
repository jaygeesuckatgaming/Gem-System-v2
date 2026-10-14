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


def save(values):
    """Persist settings and push live updates to running services.

    values: {CONFIG_KEY: python_value} — written to config.py, then pushed
    to main.py and/or vision.py if they answer their health endpoints.
    Returns (file_ok, pushed: dict of which service accepted a push).
    """
    file_ok = write_config_values(
        CONFIG_FILE,
        {k: (v, isinstance(v, str)) for k, v in values.items()},
    )

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