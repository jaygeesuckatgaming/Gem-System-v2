"""Neurosync tab for the NiceGUI control panel.

Mirrors the tkinter Neurosync tab: blendshape intensity sliders, OSC + LiveLink
config, talking-animation delays, the watcher audio path, quick emote test
buttons, and a Start Neurosync button (launches the merged Local API +
watcher_to_face .bat). Saving writes config.py + pushes live to a running MCP.
"""

import asyncio
import os
import subprocess

import httpx
from nicegui import ui

from panel import settings_store

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CREATE_NEW_CONSOLE = 0x00000010


def start_neurosync():
    bat = os.path.join(PROJECT_ROOT, 'start_scripts', 'start_merged_watcher_to_face.bat')
    if not os.path.exists(bat):
        ui.notify('Neurosync start script not found', type='negative')
        return
    subprocess.Popen(['cmd', '/c', bat], creationflags=CREATE_NEW_CONSOLE, cwd=PROJECT_ROOT)
    ui.notify('Starting Neurosync (Local API + watcher_to_face)...')


def create(sm):
    cfg = settings_store.load_config()

    # ------------------------------------------------------------------ header
    ui.label('Neurosync').classes('text-2xl font-bold')
    ui.button('Start Neurosync', icon='play_arrow', on_click=start_neurosync)
    ui.label('Launches the merged Local API + watcher_to_face pipeline (audio -> '
             'LiveLink blendshapes).').classes('text-xs text-slate-500')

    # ------------------------------------------------------ watcher audio path
    with ui.card().classes('w-full'):
        ui.label('Watcher Audio File Path').classes('text-lg font-bold')
        watcher_path = ui.input(value=cfg.TTS_OUTPUT_PATH).classes('w-full')

    # ------------------------------------------------------ blendshape sliders
    def slider_row(label_text, min_, max_, step_, value, fmt):
        with ui.row().classes('w-full items-center gap-3'):
            ui.label(label_text).classes('w-40 text-sm')
            s = ui.slider(min=min_, max=max_, step=step_, value=value).classes('grow')
            v = ui.label(fmt.format(value)).classes('w-16 text-xs text-right text-slate-400')
            s.on_value_change(lambda e, f=fmt, lbl=v: lbl.set_text(f.format(e.value)))
            return s

    with ui.card().classes('w-full'):
        ui.label('Blendshape Intensity').classes('text-lg font-bold')
        ui.label('Adjust facial expression intensity (values > 1.0 are clamped to 1.0).') \
            .classes('text-xs text-slate-500')
        mouth = slider_row('Mouth', 0.5, 2.0, 0.05, float(cfg.BLENDSHAPE_MOUTH_SCALE), '{:.2f}')
        eye = slider_row('Eye', 0.5, 2.0, 0.05, float(cfg.BLENDSHAPE_EYE_SCALE), '{:.2f}')
        eyebrow = slider_row('Eyebrow', 0.3, 1.5, 0.05, float(cfg.BLENDSHAPE_EYEBROW_SCALE), '{:.2f}')
        eyewide = slider_row('EyeWide', 0.1, 1.0, 0.05, float(cfg.BLENDSHAPE_EYEWIDE_SCALE), '{:.2f}')
        eyesquint = slider_row('EyeSquint', 0.5, 2.0, 0.05, float(cfg.BLENDSHAPE_EYESQUINT_SCALE), '{:.2f}')

    # ------------------------------------------------------ OSC + LiveLink + delays
    with ui.card().classes('w-full'):
        ui.label('OSC (Unreal)').classes('text-lg font-bold')
        with ui.row().classes('w-full gap-4 items-end'):
            with ui.column().classes('grow'):
                ui.label('IP').classes('text-xs text-slate-400')
                osc_ip = ui.input(value=cfg.OSC_IP)
            with ui.column().classes('w-28'):
                ui.label('Port').classes('text-xs text-slate-400')
                osc_port = ui.number(value=int(cfg.OSC_PORT), step=1, min=1)
            with ui.column().classes('grow'):
                ui.label('Address').classes('text-xs text-slate-400')
                osc_address = ui.input(value=cfg.OSC_ADDRESS)

        ui.label('LiveLink (Unreal Engine)').classes('text-lg font-bold mt-4')
        with ui.row().classes('w-full gap-4 items-end'):
            with ui.column().classes('grow'):
                ui.label('IP').classes('text-xs text-slate-400')
                livelink_ip = ui.input(value=cfg.LIVELINK_IP)
            with ui.column().classes('w-28'):
                ui.label('Port').classes('text-xs text-slate-400')
                livelink_port = ui.number(value=int(cfg.LIVELINK_PORT), step=1, min=1)

        ui.label('Talking Animation Delays').classes('text-lg font-bold mt-4')
        start_delay = slider_row('Start delay', 0.0, 10.0, 0.1, float(cfg.AVATAR_TALK_START_DELAY_S), '{:.1f} s')
        stop_delay = slider_row('Stop delay', 0.0, 10.0, 0.1, float(cfg.AVATAR_TALK_STOP_DELAY_S), '{:.1f} s')

    # ------------------------------------------------------------------ save
    async def save():
        values = {
            'TTS_OUTPUT_PATH': watcher_path.value.strip(),
            'BLENDSHAPE_MOUTH_SCALE': round(float(mouth.value), 2),
            'BLENDSHAPE_EYE_SCALE': round(float(eye.value), 2),
            'BLENDSHAPE_EYEBROW_SCALE': round(float(eyebrow.value), 2),
            'BLENDSHAPE_EYEWIDE_SCALE': round(float(eyewide.value), 2),
            'BLENDSHAPE_EYESQUINT_SCALE': round(float(eyesquint.value), 2),
            'OSC_IP': osc_ip.value.strip(),
            'OSC_PORT': int(osc_port.value or 10000),
            'OSC_ADDRESS': osc_address.value.strip(),
            'LIVELINK_IP': livelink_ip.value.strip(),
            'LIVELINK_PORT': int(livelink_port.value or 11111),
            'AVATAR_TALK_START_DELAY_S': round(float(start_delay.value), 1),
            'AVATAR_TALK_STOP_DELAY_S': round(float(stop_delay.value), 1),
        }
        file_ok, pushed = await asyncio.to_thread(settings_store.save, values)
        if file_ok:
            ui.notify(f'Saved (pushed live to: {", ".join(pushed) or "no running services"})',
                      type='positive')
        else:
            ui.notify('Failed to write config.py', type='negative')
    ui.button('Save Neurosync settings', icon='save', on_click=save).classes('mt-2')

    # ------------------------------------------------------ quick emotes
    with ui.card().classes('w-full'):
        ui.label('Quick Emotes (test OSC)').classes('text-lg font-bold')
        status = ui.label().classes('text-sm text-slate-400')

        async def send_emote(emote):
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    r = await client.post(f'{settings_store.MAIN_URL}/api/osc/emote',
                                          json={'emote': emote})
                status.text = f"✓ Sent emote: '{emote}'"
                status.classes(replace='text-sm text-green-400')
            except Exception as e:
                status.text = f'Failed (MCP not running?): {e}'
                status.classes(replace='text-sm text-red-400')

        emotes = ['Wave', 'Hello', 'Yes', 'No', 'Happy', 'Sad', 'Angry', 'Surprised']
        with ui.row().classes('gap-2 flex-wrap'):
            for e in emotes:
                ui.button(e, on_click=lambda em=e: send_emote(em)).props('flat outline')
        with ui.row().classes('items-center gap-2 mt-2'):
            custom = ui.input(placeholder='Custom emote').classes('w-48')
            ui.button('Send', on_click=lambda: send_emote(custom.value.strip())).props('flat')