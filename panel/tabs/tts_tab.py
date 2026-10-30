"""TTS tab for the NiceGUI control panel.

Per-engine sub-tabs (StyleTTS2 / Pocket / VibeVoice / Qwen3 / Ming / Audio 8)
plus a General tab for the active engine, behavior toggles and the single
global Save button, and a Test tab. A live status label checks the active
engine's URL.

The Audio 8 tab also lets you pick a reference-voice file from disk and
transcribe it with faster-whisper to fill the zero-shot cloning transcript.
"""

import asyncio
import configparser
import json
import os
import re
import subprocess
import sys
import time

import httpx
from nicegui import ui

from panel import settings_store

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
POCKET_INI = os.path.join(PROJECT_ROOT, 'tts', 'pocket-tts', 'settings.ini')
MING_INI = os.path.join(PROJECT_ROOT, 'tts', 'Ming-3.0-tts', 'settings.ini')
AUDIO8_INI = os.path.join(PROJECT_ROOT, 'tts', 'Audio8_TTS', 'settings.ini')
REFERENCE_DIR = os.path.join(PROJECT_ROOT, 'tts', 'reference_voices')
TRANSCRIBE_SCRIPT = os.path.join(PROJECT_ROOT, 'clients', 'transcribe_audio.py')
CREATE_NEW_CONSOLE = 0x00000010

ENGINES = {
    'styletts2': 'StyleTTS2',
    'pocket': 'Pocket TTS',
    'vibevoice': 'VibeVoice',
    'qwen': 'Qwen3-TTS',
    'ming': 'Ming 3.0',
    'audio8': 'Audio 8',
}

START_SCRIPTS = {
    'styletts2': 'start_styletts2.bat',
    'pocket': 'start_pockettts.bat',
    'vibevoice': 'start_vibevoice.bat',
    'qwen': 'start_qwen_tts.bat',
    'ming': 'start_Ming_30_tts.bat',
    'audio8': 'start_audio8_tts.bat',
}

URL_KEYS = {
    'styletts2': 'TTS_URL',
    'pocket': 'POCKET_TTS_URL',
    'vibevoice': 'VIBEVOICE_TTS_URL',
    'qwen': 'QWEN_TTS_URL',
    'ming': 'MING_TTS_URL',
    'audio8': 'AUDIO8_TTS_URL',
}


def _launch_engine(engine):
    bat = os.path.join(PROJECT_ROOT, 'start_scripts', START_SCRIPTS.get(engine, ''))
    if not os.path.exists(bat):
        ui.notify(f'No start script for {engine}', type='negative')
        return
    subprocess.Popen(['cmd', '/c', bat], creationflags=CREATE_NEW_CONSOLE, cwd=PROJECT_ROOT)
    ui.notify(f'Starting {engine} server...')


def _read_pocket_ini():
    cfg = configparser.ConfigParser()
    cfg.read(POCKET_INI)
    device = cfg.get('TTS', 'device', fallback='cpu')
    speed = cfg.getfloat('TTS', 'speed', fallback=1.0)
    return device, speed


def _normalize_copy_path(path):
    path = (path or '').strip()
    backslash = chr(92)
    if path.startswith(backslash) and not path.startswith(backslash * 2):
        return backslash + path
    return path


def _read_ming_ini():
    cfg = configparser.ConfigParser()
    cfg.read(MING_INI)
    return {
        'device': cfg.get('TTS', 'device', fallback='cuda:0'),
        'reference_voice': cfg.get('TTS', 'reference_voice', fallback=''),
        'spk_emb_path': cfg.get('TTS', 'spk_emb_path', fallback=''),
        'language': cfg.get('TTS', 'language', fallback='English'),
        'cfg': cfg.getfloat('TTS', 'cfg', fallback=2.0),
        'sigma': cfg.getfloat('TTS', 'sigma', fallback=0.25),
        'temperature': cfg.getfloat('TTS', 'temperature', fallback=0.0),
        'max_length': cfg.getint('TTS', 'max_length', fallback=24),
        'max_decode_steps': cfg.getint('TTS', 'max_decode_steps', fallback=1000),
        'raw_text': cfg.getboolean('TTS', 'raw_text', fallback=False),
        'trim_silence': cfg.getboolean('TTS', 'trim_silence', fallback=True),
        'seed': cfg.getint('TTS', 'seed', fallback=-1),
        'copy_to': _normalize_copy_path(cfg.get('TTS', 'copy_to', fallback='')),
        'copy_enabled': cfg.getboolean('TTS', 'copy_enabled', fallback=True),
    }


def _write_ming_ini(**values):
    cfg = configparser.ConfigParser()
    cfg.read(MING_INI)
    if not cfg.has_section('TTS'):
        cfg.add_section('TTS')
    for key, value in values.items():
        if value is None:
            continue
        if key == 'copy_to':
            value = _normalize_copy_path(value)
        if isinstance(value, bool):
            cfg.set('TTS', key, 'true' if value else 'false')
        else:
            cfg.set('TTS', key, str(value))
    with open(MING_INI, 'w') as f:
        cfg.write(f)


def _write_pocket_ini(device=None, speed=None):
    cfg = configparser.ConfigParser()
    cfg.read(POCKET_INI)
    if not cfg.has_section('TTS'):
        cfg.add_section('TTS')
    if device is not None:
        cfg.set('TTS', 'device', device)
    if speed is not None:
        cfg.set('TTS', 'speed', f'{round(speed, 2)}')
    with open(POCKET_INI, 'w') as f:
        cfg.write(f)


def _read_audio8_ini():
    cfg = configparser.ConfigParser()
    cfg.read(AUDIO8_INI)
    return {
        'model': cfg.get('TTS', 'model', fallback='Edge0/Audio8-TTS-Realistic-0.6b'),
        'device': cfg.get('TTS', 'device', fallback='auto'),
        'dtype': cfg.get('TTS', 'dtype', fallback='auto'),
        'reference_audio': cfg.get('TTS', 'reference_audio', fallback=''),
        'reference_text': cfg.get('TTS', 'reference_text', fallback=''),
        'temperature': cfg.getfloat('TTS', 'temperature', fallback=0.8),
        'top_p': cfg.getfloat('TTS', 'top_p', fallback=0.95),
        'top_k': cfg.getint('TTS', 'top_k', fallback=50),
        'max_new_tokens': cfg.getint('TTS', 'max_new_tokens', fallback=1024),
        'retry_max_new_tokens': cfg.getint('TTS', 'retry_max_new_tokens', fallback=2000),
        'greedy': cfg.getboolean('TTS', 'greedy', fallback=False),
        'seed': cfg.getint('TTS', 'seed', fallback=42),
        'max_chars': cfg.getint('TTS', 'max_chars', fallback=150),
        'batch_chunks': cfg.getint('TTS', 'batch_chunks', fallback=4),
        'inter_chunk_silence_ms': cfg.getint('TTS', 'inter_chunk_silence_ms', fallback=120),
        'trim_silence': cfg.getboolean('TTS', 'trim_silence', fallback=True),
        'copy_to': _normalize_copy_path(cfg.get('TTS', 'copy_to', fallback='')),
        'copy_enabled': cfg.getboolean('TTS', 'copy_enabled', fallback=True),
    }


def _write_audio8_ini(**values):
    cfg = configparser.ConfigParser()
    cfg.read(AUDIO8_INI)
    if not cfg.has_section('TTS'):
        cfg.add_section('TTS')
    for key, value in values.items():
        if value is None:
            continue
        if key == 'copy_to':
            value = _normalize_copy_path(value)
        if isinstance(value, bool):
            cfg.set('TTS', key, 'true' if value else 'false')
        else:
            cfg.set('TTS', key, str(value))
    with open(AUDIO8_INI, 'w') as f:
        cfg.write(f)


AUDIO_EXTS = ('.wav', '.flac', '.mp3', '.m4a', '.ogg', '.opus')


def _safe_audio_name(name):
    """Sanitize an uploaded reference-voice filename; None when unusable."""
    base = os.path.basename((name or '').strip())
    stem, ext = os.path.splitext(base)
    ext = ext.lower()
    if ext not in AUDIO_EXTS:
        return None
    stem = re.sub(r'[^A-Za-z0-9._-]+', '_', stem).strip('._-') or 'reference'
    return f'{stem}{ext}'


def _reference_abs_path(value):
    """Resolve a reference-voice setting to an existing absolute path."""
    value = (value or '').strip()
    if not value:
        return None
    candidates = [value] if os.path.isabs(value) else [
        os.path.join(PROJECT_ROOT, value),
        os.path.join(PROJECT_ROOT, 'tts', 'Audio8_TTS', value),
    ]
    for candidate in candidates:
        candidate = os.path.normpath(candidate)
        if os.path.isfile(candidate):
            return candidate
    return None
def create(sm):
    cfg = settings_store.load_config()

    # ------------------------------------------------------------------ header
    ui.label('Text-to-Speech').classes('text-2xl font-bold')
    with ui.row().classes('items-center gap-4'):
        active_label = ui.label(
            f'Active engine: {ENGINES.get(cfg.TTS_ENGINE, cfg.TTS_ENGINE)}'
        ).classes('text-sm font-bold text-slate-200')
        status_label = ui.label('Status: checking...').classes('text-sm text-slate-400')

    # ------------------------------------------------------------------ tabs
    with ui.tabs().classes('w-full').props('mobile-arrows no-caps') as tabs:
        tab_general = ui.tab('General')
        tab_styletts = ui.tab('StyleTTS2')
        tab_pocket = ui.tab('Pocket')
        tab_vibevoice = ui.tab('VibeVoice')
        tab_qwen = ui.tab('Qwen3')
        tab_ming = ui.tab('Ming 3.0')
        tab_audio8 = ui.tab('Audio 8')
        tab_test = ui.tab('Test')

    url_inputs = {}
    save_button = None

    with ui.tab_panels(tabs, value=tab_general).classes('w-full'):

        # ------------------------------------------------------------ General
        with ui.tab_panel(tab_general):
            with ui.card().classes('w-full'):
                ui.label('General').classes('text-lg font-bold')
                engine_select = ui.select(
                    ENGINES,
                    value=cfg.TTS_ENGINE,
                    label='Active engine',
                ).classes('w-56')
                ui.label('This is the engine main.py uses for speech.').classes(
                    'text-xs text-slate-400'
                )
                with ui.row().classes('gap-8 items-start flex-wrap mt-3'):
                    with ui.column().classes('gap-2'):
                        tts_enabled = ui.switch('Enable TTS', value=cfg.TTS_ENABLED)
                        send_chat = ui.switch(
                            'Send responses to chat (disable for TTS-only)',
                            value=cfg.SEND_RESPONSES_TO_CHAT,
                        )
                        audio_player = ui.switch(
                            'Enable Audio Player (disable when using Neurosync)',
                            value=cfg.AUDIO_PLAYER_ENABLED,
                        )
                ui.label(
                    'The Save button below writes every engine tab in one go.'
                ).classes('text-xs text-slate-400 mt-2')
                save_button = ui.button('Save TTS settings', icon='save')

        # ----------------------------------------------------------- StyleTTS2
        with ui.tab_panel(tab_styletts):
            with ui.card().classes('w-full'):
                with ui.row().classes('w-full items-center justify-between'):
                    ui.label('StyleTTS2').classes('text-lg font-bold')
                    ui.button('Start StyleTTS2', icon='play_arrow',
                              on_click=lambda: _launch_engine('styletts2')).props('flat dense outline')
                with ui.column().classes('gap-1 min-w-[280px]'):
                    ui.label('Server URL').classes('text-sm text-slate-400')
                    url_inputs['styletts2'] = ui.input(
                        value=getattr(cfg, URL_KEYS['styletts2'], '')
                    ).classes('w-full')

                def slider_row(label_text, min_, max_, step_, value, fmt):
                    with ui.row().classes('w-full items-center gap-3'):
                        ui.label(label_text).classes('w-40 text-sm')
                        s = ui.slider(min=min_, max=max_, step=step_, value=value).classes('grow')
                        v = ui.label(fmt.format(value)).classes('w-16 text-xs text-right text-slate-400')
                        s.on_value_change(lambda e, f=fmt, lbl=v: lbl.set_text(f.format(e.value)))
                        return s

                diffusion = slider_row('Diffusion steps', 5, 50, 1,
                                       int(cfg.TTS_DIFFUSION_STEPS), '{:.0f}')
                embedding = slider_row('Embedding scale', 0.5, 1.5, 0.05,
                                       float(cfg.TTS_EMBEDDING_SCALE), '{:.1f}')
                alpha = slider_row('Alpha (timbre)', 0.0, 1.0, 0.05,
                                   float(cfg.TTS_ALPHA), '{:.2f}')
                beta = slider_row('Beta (prosody)', 0.0, 1.0, 0.05,
                                  float(cfg.TTS_BETA), '{:.2f}')
                ui.label(
                    'Diffusion steps: higher = better quality but slower. '
                    'Embedding scale: higher = stronger text conditioning.'
                ).classes('text-xs text-slate-500 mt-1')
                ui.label(
                    'Alpha (timbre): 0 = reference voice, 1 = model-predicted. '
                    'Beta (prosody): 0 = reference rhythm, 1 = text-driven/expressive.'
                ).classes('text-xs text-slate-500 mt-1')
                ui.label('Reference voice').classes('text-sm text-slate-400 mt-2')
                reference_voice = ui.input(value=cfg.TTS_REFERENCE_VOICE).classes('w-full')
                ui.label('Copy audio to (network share, empty = disabled)').classes(
                    'text-sm text-slate-400 mt-2'
                )
                copy_to = ui.input(value=cfg.TTS_COPY_TO).classes('w-full')

        # --------------------------------------------------------------- Pocket
        with ui.tab_panel(tab_pocket):
            with ui.card().classes('w-full'):
                with ui.row().classes('w-full items-center justify-between'):
                    ui.label('Pocket TTS').classes('text-lg font-bold')
                    ui.button('Start Pocket', icon='play_arrow',
                              on_click=lambda: _launch_engine('pocket')).props('flat dense outline')
                ui.label('Server URL').classes('text-sm text-slate-400')
                url_inputs['pocket'] = ui.input(
                    value=getattr(cfg, URL_KEYS['pocket'], '')
                ).classes('w-full')

                pocket_device, pocket_speed = _read_pocket_ini()

                def save_device(e):
                    _write_pocket_ini(device=e.value)
                    ui.notify(f'Pocket device set to {e.value} (applies on restart)')

                ui.label('Device').classes('text-sm text-slate-400 mt-2')
                device_toggle = ui.toggle({'cpu': 'CPU', 'cuda': 'GPU (CUDA)'},
                                          value=pocket_device)
                device_toggle.on_value_change(save_device)

                with ui.row().classes('w-full items-center gap-3 mt-2'):
                    ui.label('Speech speed').classes('w-28 text-sm')
                    speed_slider = ui.slider(min=0.5, max=2.0, step=0.05,
                                             value=pocket_speed).classes('grow')
                    speed_label = ui.label(f'{pocket_speed:.2f}x').classes(
                        'w-16 text-xs text-slate-400'
                    )
                    speed_slider.on_value_change(
                        lambda e: speed_label.set_text(f'{e.value:.2f}x')
                    )
                    ui.button(
                        'Save speed',
                        on_click=lambda: (
                            _write_pocket_ini(speed=speed_slider.value),
                            ui.notify('Pocket speed saved (applies on restart)'),
                        ),
                    ).props('flat dense')

        # ------------------------------------------------------------ VibeVoice
        with ui.tab_panel(tab_vibevoice):
            with ui.card().classes('w-full'):
                with ui.row().classes('w-full items-center justify-between'):
                    ui.label('VibeVoice').classes('text-lg font-bold')
                    ui.button('Start VibeVoice', icon='play_arrow',
                              on_click=lambda: _launch_engine('vibevoice')).props('flat dense outline')
                ui.label('Server URL').classes('text-sm text-slate-400')
                url_inputs['vibevoice'] = ui.input(
                    value=getattr(cfg, URL_KEYS['vibevoice'], '')
                ).classes('w-full')
                vibevoice_model = ui.input('Model', value=cfg.VIBEVOICE_MODEL).classes('w-full mt-2')
                with ui.row().classes('w-full items-center gap-3 mt-2'):
                    ui.label('Inference steps (lower = faster)').classes('w-48 text-sm')
                    steps_slider = ui.slider(min=1, max=20, step=1,
                                             value=int(cfg.VIBEVOICE_INFERENCE_STEPS)).classes('grow')
                    steps_label = ui.label(str(int(cfg.VIBEVOICE_INFERENCE_STEPS))).classes(
                        'w-8 text-xs text-slate-400'
                    )
                    steps_slider.on_value_change(
                        lambda e: steps_label.set_text(str(int(e.value)))
                    )

        # ---------------------------------------------------------------- Qwen3
        with ui.tab_panel(tab_qwen):
            with ui.card().classes('w-full'):
                with ui.row().classes('w-full items-center justify-between'):
                    ui.label('Qwen3-TTS').classes('text-lg font-bold')
                    ui.button('Start Qwen3', icon='play_arrow',
                              on_click=lambda: _launch_engine('qwen')).props('flat dense outline')
                ui.label('Server URL').classes('text-sm text-slate-400')
                url_inputs['qwen'] = ui.input(
                    value=getattr(cfg, URL_KEYS['qwen'], '')
                ).classes('w-full')

        # ----------------------------------------------------------------- Ming
        with ui.tab_panel(tab_ming):
            with ui.card().classes('w-full'):
                with ui.row().classes('w-full items-center justify-between'):
                    ui.label('Ming 3.0-tts-0.5B').classes('text-lg font-bold')
                    ui.button('Start Ming', icon='play_arrow',
                              on_click=lambda: _launch_engine('ming')).props('flat dense outline')
                ui.label('Server URL').classes('text-sm text-slate-400')
                url_inputs['ming'] = ui.input(
                    value=getattr(cfg, URL_KEYS['ming'], '')
                ).classes('w-full')

                ming = _read_ming_ini()

                with ui.row().classes('w-full gap-8 items-start flex-wrap mt-3'):
                    with ui.column().classes('gap-2 min-w-[300px] grow'):
                        ui.label('Voice').classes('text-sm font-semibold text-slate-300')
                        ui.label('Device (restart required)').classes('text-xs text-slate-400')
                        ming_device = ui.toggle({'cuda:0': 'GPU (CUDA)', 'cpu': 'CPU'},
                                                value=ming['device'])
                        ui.label('Reference voice').classes('text-xs text-slate-400')
                        ming_reference = ui.input(value=ming['reference_voice']).classes('w-full')
                        ui.label('Speaker embedding (recomputed when reference changes)').classes(
                            'text-xs text-slate-400'
                        )
                        ming_spk = ui.input(value=ming['spk_emb_path']).classes('w-full')
                        ming_language = ui.select(
                            ['English', 'Chinese', 'German', 'Spanish', 'French',
                             'Korean', 'Japanese'],
                            value=ming['language'],
                            label='Language',
                        ).classes('w-56')

                    with ui.column().classes('gap-2 min-w-[300px] grow'):
                        ui.label('Quality').classes('text-sm font-semibold text-slate-300')
                        with ui.row().classes('gap-3'):
                            ming_cfg = ui.number('CFG', value=ming['cfg'],
                                                 min=0, max=5, step=0.1).classes('w-24')
                            ming_sigma = ui.number('Sigma', value=ming['sigma'],
                                                   min=0, max=1, step=0.05).classes('w-24')
                            ming_temperature = ui.number(
                                'Temperature', value=ming['temperature'],
                                min=0, max=1.5, step=0.05,
                            ).classes('w-32')
                        with ui.row().classes('gap-3'):
                            ming_max_length = ui.number(
                                'Max text length', value=ming['max_length'],
                                min=8, max=80, step=1,
                            ).classes('w-32')
                            ming_steps = ui.number(
                                'Max decode steps', value=ming['max_decode_steps'],
                                min=100, max=4000, step=100,
                            ).classes('w-36')
                            ming_seed = ui.number(
                                'Seed (-1 = random)', value=ming['seed'],
                                min=-1, max=2147483647, step=1,
                            ).classes('w-36')
                        with ui.row().classes('gap-6'):
                            ming_raw_text = ui.switch('Raw text (single pass)',
                                                      value=ming['raw_text'])
                            ming_trim = ui.switch('Trim silence',
                                                  value=ming['trim_silence'])
                        ui.label(
                            'CFG/sigma/temperature change delivery; max decode steps is the '
                            'main speed knob. Text normalization is off (no pynini).'
                        ).classes('text-xs text-slate-500')

                    with ui.column().classes('gap-2 min-w-[300px] grow'):
                        ui.label('Delivery').classes('text-sm font-semibold text-slate-300')
                        ui.label('Copy audio to').classes('text-xs text-slate-400')
                        ming_copy_to = ui.input(value=ming['copy_to']).classes('w-full')
                        ming_copy_enabled = ui.switch('Copy enabled',
                                                      value=ming['copy_enabled'])
                        ui.label(
                            'Model: tts/Ming-3.0-tts/Ming-3.0-tts-0.5b · TTS task only.'
                        ).classes('text-xs text-slate-500')

                with ui.row().classes('w-full items-center gap-2 mt-3'):
                    ming_activate_btn = ui.button(
                        'Use Ming as active engine', icon='check_circle'
                    ).props('flat')
                with ui.row().classes('w-full items-center gap-2 mt-2'):
                    ming_test_input = ui.input(
                        placeholder='Test text for the Ming server'
                    ).classes('grow')
                    ming_test_btn = ui.button('Test Ming server', icon='volume_up')

        # --------------------------------------------------------------- Audio 8
        with ui.tab_panel(tab_audio8):
            with ui.card().classes('w-full'):
                with ui.row().classes('w-full items-center justify-between'):
                    ui.label('Audio 8 TTS (Realistic 0.6B)').classes('text-lg font-bold')
                    ui.button('Start Audio 8', icon='play_arrow',
                              on_click=lambda: _launch_engine('audio8')).props('flat dense outline')
                ui.label('Server URL').classes('text-sm text-slate-400')
                url_inputs['audio8'] = ui.input(
                    value=getattr(cfg, URL_KEYS['audio8'], '')
                ).classes('w-full')

                audio8 = _read_audio8_ini()

                with ui.row().classes('w-full gap-8 items-start flex-wrap mt-3'):
                    # ---- voice / reference
                    with ui.column().classes('gap-2 min-w-[340px] grow'):
                        ui.label('Voice').classes('text-sm font-semibold text-slate-300')
                        ui.label('Device (restart required)').classes('text-xs text-slate-400')
                        audio8_device = ui.toggle(
                            {'auto': 'Auto', 'cuda:0': 'GPU (CUDA)', 'cpu': 'CPU'},
                            value=audio8['device'] if audio8['device'] in
                            ('auto', 'cuda:0', 'cpu') else 'auto',
                        )
                        ui.label('Reference voice').classes('text-xs text-slate-400')
                        audio8_reference = ui.input(
                            value=audio8['reference_audio'],
                            placeholder='tts/reference_voices/voice.wav',
                        ).classes('w-full')
                        audio8_upload = ui.upload(
                            label='Browse…', auto_upload=True,
                            max_file_size=200 * 1024 * 1024,
                        ).props('accept=.wav,.flac,.mp3,.m4a,.ogg,.opus').classes('w-full')

                        ui.label(
                            'Transcribe the reference clip (faster-whisper)'
                        ).classes('text-xs text-slate-400 mt-1')
                        with ui.row().classes('w-full items-center gap-2'):
                            audio8_stt_model = ui.select(
                                ['base.en', 'base', 'small.en', 'medium.en', 'large-v3'],
                                value=getattr(cfg, 'STT_WHISPER_MODEL', 'base.en')
                                if getattr(cfg, 'STT_WHISPER_MODEL', 'base.en') in
                                ('base.en', 'base', 'small.en', 'medium.en', 'large-v3')
                                else 'base.en',
                                label='Whisper model',
                            ).classes('w-36')
                            audio8_stt_lang = ui.select(
                                ['auto', 'en', 'th', 'ja', 'ko', 'zh', 'es', 'fr', 'de'],
                                value='auto', label='Language',
                            ).classes('w-32')
                            audio8_transcribe = ui.button(
                                'Transcribe', icon='graphic_eq'
                            ).props('flat dense')
                        ui.label(
                            'small.en / medium.en / large-v3 download on first use and are slower.'
                        ).classes('text-xs text-slate-500')

                        ui.label('Reference transcript (must match the clip word-for-word)').classes(
                            'text-xs text-slate-400'
                        )
                        audio8_reference_text = ui.textarea(
                            value=audio8['reference_text'], placeholder='Words spoken in the clip'
                        ).classes('w-full').props('rows=3 autogrow')

                    # ---- quality
                    with ui.column().classes('gap-2 min-w-[320px] grow'):
                        ui.label('Quality').classes('text-sm font-semibold text-slate-300')
                        with ui.row().classes('gap-3'):
                            audio8_temp = ui.number('Temperature', value=audio8['temperature'],
                                                    min=0.05, max=2, step=0.05).classes('w-32')
                            audio8_top_p = ui.number('Top-p', value=audio8['top_p'],
                                                     min=0.01, max=1, step=0.01).classes('w-24')
                            audio8_top_k = ui.number('Top-k', value=audio8['top_k'],
                                                     min=0, max=200, step=5).classes('w-24')
                        with ui.row().classes('gap-3'):
                            audio8_max_new = ui.number(
                                'Max new tokens', value=audio8['max_new_tokens'],
                                min=128, max=2048, step=1,
                            ).classes('w-36')
                            audio8_retry = ui.number(
                                'Retry tokens', value=audio8['retry_max_new_tokens'],
                                min=128, max=3000, step=1,
                            ).classes('w-32')
                            audio8_seed = ui.number('Seed (-1 = random)', value=audio8['seed'],
                                                    min=-1, max=2147483647, step=1).classes('w-36')
                        with ui.row().classes('gap-3'):
                            audio8_max_chars = ui.number(
                                'Max chars / chunk', value=audio8['max_chars'],
                                min=40, max=400, step=10,
                            ).classes('w-36')
                            audio8_gap = ui.number(
                                'Chunk gap (ms)', value=audio8['inter_chunk_silence_ms'],
                                min=0, max=1000, step=10,
                            ).classes('w-32')
                            audio8_batch = ui.number(
                                'Batch chunks', value=audio8['batch_chunks'],
                                min=1, max=8, step=1,
                            ).classes('w-32')
                        with ui.row().classes('gap-6'):
                            audio8_greedy = ui.switch('Greedy (faster, flatter)',
                                                      value=audio8['greedy'])
                            audio8_trim = ui.switch('Trim silence', value=audio8['trim_silence'])
                        ui.label(
                            'Text is split at ~max chars (the model is trained on short '
                            'inputs) and joined with the chunk gap. Batch chunks runs that many '
                            'chunks in one GPU pass — 4 is ~2.8x faster than 1; 8 is fastest but '
                            'peaks around 7.8 GB VRAM. Greedy is a smaller speed knob.'
                        ).classes('text-xs text-slate-500')

                    # ---- delivery
                    with ui.column().classes('gap-2 min-w-[300px] grow'):
                        ui.label('Delivery').classes('text-sm font-semibold text-slate-300')
                        ui.label('Copy audio to').classes('text-xs text-slate-400')
                        audio8_copy_to = ui.input(value=audio8['copy_to']).classes('w-full')
                        audio8_copy_enabled = ui.switch('Copy enabled',
                                                        value=audio8['copy_enabled'])
                        ui.label(
                            'Model: Edge0/Audio8-TTS-Realistic-0.6b · 44.1 kHz · zero-shot cloning '
                            'is used only when both the reference clip and transcript are set.'
                        ).classes('text-xs text-slate-500')

                with ui.row().classes('w-full items-center gap-2 mt-3'):
                    audio8_save_btn = ui.button(
                        'Save Audio 8 settings', icon='save'
                    ).props('flat')
                    audio8_activate_btn = ui.button(
                        'Use Audio 8 as active engine', icon='check_circle'
                    ).props('flat')
                with ui.row().classes('w-full items-center gap-2 mt-2'):
                    audio8_test_input = ui.input(
                        placeholder='Test text for the Audio 8 server'
                    ).classes('grow')
                    audio8_test_btn = ui.button('Test Audio 8', icon='volume_up')

        # ----------------------------------------------------------------- Test
        with ui.tab_panel(tab_test):
            with ui.card().classes('w-full'):
                ui.label('Test TTS').classes('text-lg font-bold')
                with ui.row().classes('w-full items-center gap-2'):
                    test_input = ui.input(placeholder='Text to speak').classes('grow')
                    speak_btn = ui.button('Speak', icon='volume_up')

    # ------------------------------------------------------------------ save
    async def save():
        engine = engine_select.value or 'styletts2'
        values = {
            'TTS_ENABLED': tts_enabled.value,
            'TTS_ENGINE': engine,
            'TTS_URL': url_inputs['styletts2'].value.strip(),
            'POCKET_TTS_URL': url_inputs['pocket'].value.strip(),
            'VIBEVOICE_TTS_URL': url_inputs['vibevoice'].value.strip(),
            'QWEN_TTS_URL': url_inputs['qwen'].value.strip(),
            'MING_TTS_URL': url_inputs['ming'].value.strip(),
            'AUDIO8_TTS_URL': url_inputs['audio8'].value.strip(),
            'VIBEVOICE_MODEL': vibevoice_model.value.strip(),
            'VIBEVOICE_INFERENCE_STEPS': int(steps_slider.value),
            'TTS_DIFFUSION_STEPS': int(diffusion.value),
            'TTS_EMBEDDING_SCALE': round(float(embedding.value), 1),
            'TTS_ALPHA': round(float(alpha.value), 2),
            'TTS_BETA': round(float(beta.value), 2),
            'TTS_REFERENCE_VOICE': reference_voice.value.strip(),
            'TTS_COPY_TO': copy_to.value.strip(),
            'SEND_RESPONSES_TO_CHAT': send_chat.value,
            'AUDIO_PLAYER_ENABLED': audio_player.value,
        }
        ming_values = {
            'device': ming_device.value,
            'reference_voice': ming_reference.value.strip(),
            'spk_emb_path': ming_spk.value.strip(),
            'language': ming_language.value or 'English',
            'cfg': float(ming_cfg.value if ming_cfg.value is not None else 2.0),
            'sigma': float(ming_sigma.value if ming_sigma.value is not None else 0.25),
            'temperature': float(
                ming_temperature.value if ming_temperature.value is not None else 0.0
            ),
            'max_length': int(ming_max_length.value or 24),
            'max_decode_steps': int(ming_steps.value or 1000),
            'raw_text': bool(ming_raw_text.value),
            'trim_silence': bool(ming_trim.value),
            'seed': int(ming_seed.value if ming_seed.value is not None else -1),
            'copy_to': ming_copy_to.value.strip(),
            'copy_enabled': bool(ming_copy_enabled.value),
        }
        ming_ok = False
        ming_restart = []
        try:
            _write_ming_ini(**ming_values)
            ming_url = url_inputs['ming'].value.strip()
            if ming_url:
                base = ming_url.replace('/tts', '').rstrip('/')
                async with httpx.AsyncClient(timeout=60.0) as client:
                    r = await client.post(f'{base}/settings', json=ming_values)
                    ming_ok = r.status_code == 200
                    if ming_ok:
                        ming_restart = r.json().get('restart_required', []) or []
        except Exception as exc:
            print(f"[PANEL-TTS] Ming settings sync failed: {exc}", flush=True)
        audio8_values = {
            'model': audio8['model'],
            'device': audio8_device.value or 'auto',
            'dtype': audio8['dtype'],
            'reference_audio': audio8_reference.value.strip(),
            'reference_text': (audio8_reference_text.value or '').strip(),
            'temperature': float(audio8_temp.value if audio8_temp.value is not None else 0.8),
            'top_p': float(audio8_top_p.value if audio8_top_p.value is not None else 0.95),
            'top_k': int(audio8_top_k.value if audio8_top_k.value is not None else 50),
            'max_new_tokens': int(audio8_max_new.value or 1024),
            'retry_max_new_tokens': int(audio8_retry.value or 2000),
            'greedy': bool(audio8_greedy.value),
            'seed': int(audio8_seed.value if audio8_seed.value is not None else 42),
            'max_chars': int(audio8_max_chars.value or 150),
            'batch_chunks': int(audio8_batch.value or 4),
            'inter_chunk_silence_ms': int(audio8_gap.value or 0),
            'trim_silence': bool(audio8_trim.value),
            'copy_to': audio8_copy_to.value.strip(),
            'copy_enabled': bool(audio8_copy_enabled.value),
        }
        audio8_ok = False
        audio8_restart = []
        try:
            _write_audio8_ini(**audio8_values)
            audio8_url = url_inputs['audio8'].value.strip()
            if audio8_url:
                base = audio8_url.replace('/tts', '').rstrip('/')
                async with httpx.AsyncClient(timeout=30.0) as client:
                    r = await client.post(f'{base}/settings', json=audio8_values)
                    audio8_ok = r.status_code == 200
                    if audio8_ok:
                        audio8_restart = r.json().get('restart_required', []) or []
        except Exception as exc:
            print(f"[PANEL-TTS] Audio 8 settings sync failed: {exc}", flush=True)
        file_ok, pushed = await asyncio.to_thread(settings_store.save, values)
        # Push StyleTTS2 params to the StyleTTS2 server directly (live)
        styletts_ok = False
        if engine == 'styletts2':
            try:
                base = url_inputs['styletts2'].value.strip().replace('/tts', '')
                async with httpx.AsyncClient(timeout=5.0) as client:
                    r = await client.post(f'{base}/settings', json={
                        'diffusion_steps': int(diffusion.value),
                        'embedding_scale': round(float(embedding.value), 1),
                        'alpha': round(float(alpha.value), 2),
                        'beta': round(float(beta.value), 2),
                        'reference_voice': reference_voice.value.strip(),
                        'copy_to': copy_to.value.strip(),
                    })
                    styletts_ok = r.status_code == 200
            except Exception:
                pass
        if file_ok:
            extra = ['styletts2'] if styletts_ok else []
            if ming_ok:
                extra.append('ming')
            if audio8_ok:
                extra.append('audio8')
            names = list(pushed.keys()) + extra
            print(
                f"[PANEL-TTS] save engine={engine} "
                f"ming_url={url_inputs['ming'].value.strip()!r} "
                f"ming_live={ming_ok} ming_restart={ming_restart} "
                f"audio8_url={url_inputs['audio8'].value.strip()!r} "
                f"audio8_live={audio8_ok} audio8_restart={audio8_restart} "
                f"pushed={names}",
                flush=True,
            )
            suffix = ''
            if ming_restart:
                suffix += f' · Ming restart required: {", ".join(ming_restart)}'
            if audio8_restart:
                suffix += f' · Audio 8 restart required: {", ".join(audio8_restart)}'
            ui.notify(
                f'Saved engine={ENGINES.get(engine, engine)} '
                f'(pushed live to: {", ".join(names) or "no running services"})'
                f'{suffix}',
                type='positive',
            )
            await refresh_status()
        else:
            ui.notify('Failed to write config.py', type='negative')

    save_button.on_click(save)

    async def use_ming():
        engine_select.value = 'ming'
        await save()

    ming_activate_btn.on_click(use_ming)

    async def use_audio8():
        engine_select.value = 'audio8'
        await save()

    audio8_activate_btn.on_click(use_audio8)
    audio8_save_btn.on_click(save)

    async def test_ming():
        text = (ming_test_input.value or '').strip()
        url = (url_inputs['ming'].value or '').strip()
        if not text or not url:
            ui.notify('Enter text and a Ming server URL first', type='warning')
            return
        ming_test_btn.props('loading')
        started = time.time()
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                r = await client.post(url, json={'text': text})
            elapsed = time.time() - started
            if r.status_code == 200:
                ui.notify(
                    f'Ming OK: {len(r.content)} bytes in {elapsed:.1f}s '
                    f'({r.headers.get("content-type", "?")})',
                    type='positive',
                )
            else:
                ui.notify(
                    f'Ming failed HTTP {r.status_code} in {elapsed:.1f}s: '
                    f'{r.text[:180]}',
                    type='negative',
                )
        except Exception as exc:
            ui.notify(f'Ming server unreachable: {exc}', type='negative')
        finally:
            ming_test_btn.props(remove='loading')

    ming_test_btn.on_click(test_ming)

    # ------------------------------------------------------------- Audio 8 I/O
    async def upload_reference(event):
        try:
            filename = _safe_audio_name(event.file.name)
            if filename is None:
                ui.notify('Use .wav, .flac, .mp3, .m4a, .ogg or .opus', type='negative')
                return
            data = await event.file.read()
            os.makedirs(REFERENCE_DIR, exist_ok=True)
            destination = os.path.join(REFERENCE_DIR, filename)

            def _write():
                with open(destination, 'wb') as handle:
                    handle.write(data)

            await asyncio.to_thread(_write)
            relative = os.path.relpath(destination, PROJECT_ROOT).replace(os.sep, '/')
            audio8_reference.value = relative
            ui.notify(
                f'Uploaded {relative} — click Transcribe to fill the transcript',
                type='positive',
            )
        except Exception as exc:
            ui.notify(f'Reference upload failed: {exc}', type='negative')

    audio8_upload.on_upload(upload_reference)

    async def transcribe_reference():
        path = _reference_abs_path(audio8_reference.value)
        if path is None:
            ui.notify('Pick a reference audio file first (or fix the path)', type='warning')
            return
        if not os.path.isfile(TRANSCRIBE_SCRIPT):
            ui.notify('clients/transcribe_audio.py is missing', type='negative')
            return
        model = audio8_stt_model.value or 'base.en'
        language = audio8_stt_lang.value or 'auto'
        args = [
            sys.executable, TRANSCRIBE_SCRIPT, path,
            '--json', '--model', str(model), '--language', str(language),
        ]
        audio8_transcribe.props('loading')
        ui.notify(f'Transcribing with {model} ({language})…')
        try:
            proc = await asyncio.to_thread(
                subprocess.run, args, capture_output=True, text=True, timeout=600,
            )
            stdout = (proc.stdout or '').strip()
            payload = {}
            if stdout:
                try:
                    payload = json.loads(stdout.splitlines()[-1])
                except json.JSONDecodeError:
                    payload = {}
            if proc.returncode != 0 or 'error' in payload:
                detail = payload.get('error') or (proc.stderr or stdout)[-300:]
                ui.notify(f'Transcription failed: {detail}', type='negative')
                return
            text = (payload.get('text') or '').strip()
            if not text:
                ui.notify('Whisper heard nothing in that clip', type='warning')
                return
            audio8_reference_text.value = text
            ui.notify(
                f'Transcribed {payload.get("duration", 0)}s of audio '
                f'({payload.get("language") or "?"}, {payload.get("elapsed_s", 0)}s)',
                type='positive',
            )
        except subprocess.TimeoutExpired:
            ui.notify('Transcription timed out after 10 minutes', type='negative')
        except Exception as exc:
            ui.notify(f'Transcription failed: {exc}', type='negative')
        finally:
            audio8_transcribe.props(remove='loading')

    audio8_transcribe.on_click(transcribe_reference)

    async def test_audio8():
        text = (audio8_test_input.value or '').strip()
        url = (url_inputs['audio8'].value or '').strip()
        if not text or not url:
            ui.notify('Enter text and an Audio 8 server URL first', type='warning')
            return
        audio8_test_btn.props('loading')
        started = time.time()
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                r = await client.post(url, json={'text': text})
            elapsed = time.time() - started
            if r.status_code == 200:
                ui.notify(
                    f'Audio 8 OK: {len(r.content)} bytes in {elapsed:.1f}s '
                    f'({r.headers.get("content-type", "?")})',
                    type='positive',
                )
                await refresh_status()
            else:
                ui.notify(
                    f'Audio 8 failed HTTP {r.status_code} in {elapsed:.1f}s: {r.text[:180]}',
                    type='negative',
                )
        except Exception as exc:
            ui.notify(f'Audio 8 server unreachable: {exc}', type='negative')
        finally:
            audio8_test_btn.props(remove='loading')

    audio8_test_btn.on_click(test_audio8)

    # ------------------------------------------------------------ live status
    async def refresh_status():
        engine = engine_select.value or 'styletts2'
        active_label.text = f'Active engine: {ENGINES.get(engine, engine)}'
        element = url_inputs.get(engine)
        url = (element.value or '').strip() if element is not None else ''
        if not url:
            status_label.text = f'Status: ● No URL configured ({ENGINES.get(engine, engine)})'
            status_label.classes(replace='text-sm text-slate-400')
            return
        base = url.replace('/tts', '').rstrip('/')
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                await client.get(base + '/')
            status_label.text = f'Status: ● Connected ({ENGINES.get(engine, engine)})'
            status_label.classes(replace='text-sm text-green-400')
        except Exception:
            status_label.text = f'Status: ● Offline ({ENGINES.get(engine, engine)})'
            status_label.classes(replace='text-sm text-red-400')

    async def on_engine_change(event):
        await refresh_status()

    engine_select.on_value_change(on_engine_change)
    ui.timer(5.0, refresh_status, immediate=True)

    # ------------------------------------------------------------------ test
    async def test():
        text = (test_input.value or '').strip()
        if not text:
            return
        speak_btn.props('loading')
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(
                    f'{settings_store.MAIN_URL}/api/tts', json={'text': text}
                )
            ui.notify(
                'TTS test sent' if r.status_code == 200
                else f'TTS test failed: {r.text[:120]}',
                type='positive' if r.status_code == 200 else 'negative',
            )
        except Exception as e:
            ui.notify(f'MCP server not running: {e}', type='negative')
        speak_btn.props(remove='loading')

    speak_btn.on_click(test)
