"""Speech-to-Text (STT) tab for the NiceGUI control panel.

Whisper microphone listener settings: whisper model, VAD aggressiveness,
silence threshold, pre-buffer, and the min-dB input gate, plus a Start
Listener button. Settings load from config.py and push live to a running MCP.
"""

import asyncio
import os
import subprocess

import httpx
from nicegui import ui

from panel import settings_store

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CREATE_NEW_CONSOLE = 0x00000010


def start_listener():
    bat = os.path.join(PROJECT_ROOT, 'start_scripts', 'start_listen.bat')
    if not os.path.exists(bat):
        ui.notify('STT listener start script not found', type='negative')
        return
    subprocess.Popen(['cmd', '/c', bat], creationflags=CREATE_NEW_CONSOLE, cwd=PROJECT_ROOT)
    ui.notify('Starting STT listener...')


def create(sm):
    cfg = settings_store.load_config()

    ui.label('Speech-to-Text (STT)').classes('text-2xl font-bold')
    ui.label('Listens to your microphone, transcribes speech with Whisper, and '
             'sends it to the MCP.').classes('text-sm text-slate-400')
    ui.button('Start STT Listener', icon='play_arrow', on_click=start_listener).classes('mt-2')

    with ui.card().classes('w-full'):
        ui.label('Whisper model').classes('text-sm text-slate-400')
        model = ui.input(value=cfg.STT_WHISPER_MODEL).classes('w-full')

    with ui.card().classes('w-full'):
        ui.label('Voice Activity Detection').classes('text-lg font-bold')

        with ui.row().classes('w-full items-center gap-3'):
            ui.label('VAD aggressiveness (0-3)').classes('w-48 text-sm')
            vad = ui.slider(min=0, max=3, step=1, value=int(cfg.STT_VAD_AGGRESSIVENESS)).classes('grow')
            vad_label = ui.label(str(int(cfg.STT_VAD_AGGRESSIVENESS))).classes('w-8 text-xs text-slate-400')
            vad.on_value_change(lambda e: vad_label.set_text(str(int(e.value))))

        with ui.row().classes('w-full items-center gap-3 mt-2'):
            ui.label('Min input level (dB gate)').classes('w-48 text-sm')
            min_db = ui.slider(min=-70.0, max=-20.0, step=1.0, value=float(cfg.STT_MIN_DB)).classes('grow')
            min_db_label = ui.label(f'{float(cfg.STT_MIN_DB):.1f} dB') \
                .classes('w-16 text-xs text-slate-400')
            min_db.on_value_change(lambda e: min_db_label.set_text(f'{e.value:.1f} dB'))

        with ui.row().classes('w-full gap-6 items-end mt-2'):
            with ui.column().classes('grow'):
                ui.label('Silence threshold (seconds)').classes('text-sm text-slate-400')
                silence = ui.number(value=float(cfg.STT_SILENCE_THRESHOLD_S), step=0.1, min=0.1)
            with ui.column().classes('grow'):
                ui.label('Pre-buffer (seconds)').classes('text-sm text-slate-400')
                prebuf = ui.number(value=float(cfg.STT_PRE_BUFFER_S), step=0.1, min=0.0)

    async def save():
        values = {
            'STT_WHISPER_MODEL': model.value.strip(),
            'STT_VAD_AGGRESSIVENESS': int(vad.value),
            'STT_SILENCE_THRESHOLD_S': float(silence.value or 2.0),
            'STT_PRE_BUFFER_S': float(prebuf.value or 0.5),
            'STT_MIN_DB': float(min_db.value),
        }
        file_ok, pushed = await asyncio.to_thread(settings_store.save, values)
        ui.notify(f'Saved (pushed live to: {", ".join(pushed) or "no running services"})',
                  type='positive' if file_ok else 'negative')
    ui.button('Save STT settings', icon='save', on_click=save).classes('mt-2')