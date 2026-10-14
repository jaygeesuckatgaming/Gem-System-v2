"""Audio tab for the NiceGUI control panel.

Mirrors the tkinter Audio tab: output device picker with test tone + VU
meter, separate music output device, input device with live monitor + VU
meter, audio player toggle, and all ducking knobs. Devices are enumerated
locally via sounddevice (works with no services running); saving writes
config.py and pushes live updates to main.py.
"""

import asyncio
import math
import os

import httpx
from nicegui import ui

from panel import settings_store

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MIN_DB = -60.0


def create(sm):
    cfg = settings_store.load_config()

    # ------------------------------------------------------------------ header
    ui.label('Audio').classes('text-2xl font-bold')
    ui.label('Settings load from config.py directly; changes apply live to a running MCP server '
             'when you press Save.').classes('text-sm text-slate-400')

    runtime = {'out_stream': None, 'in_stream': None, 'testing_out': False,
               'monitoring_in': False, 'phase': 0.0, 'samplerate': 48000.0}

    # ------------------------------------------------------------- VU meters
    def make_meter(label_text):
        ui.label(label_text).classes('text-xs text-slate-400 mt-1')
        with ui.element('div').classes('w-full h-3 rounded bg-slate-700 overflow-hidden'):
            fill = ui.element('div').classes('h-3')
            fill.style('width: 0%; background: #4ade80; transition: none;')
        db = ui.label('-60 dB').classes('text-xs text-slate-400')
        return fill, db

    def meter_style(el, db_label, db):
        db = max(db, MIN_DB)  # floor the display at -60 dB
        pct = max(0.0, min(100.0, (db + 60.0) / 60.0 * 100.0))
        color = '#f87171' if db > -6 else ('#fb923c' if db > -18 else '#4ade80')
        el.style(f'width: {pct:.0f}%; background: {color}; transition: none;')
        db_label.set_text(f'{db:.0f} dB')

    levels = {'out': MIN_DB, 'in': MIN_DB}
    out_fill, out_db = make_meter('Output level')
    in_fill, in_db = make_meter('Input level')

    def update_meters():
        meter_style(out_fill, out_db, levels['out'])
        meter_style(in_fill, in_db, levels['in'])
    ui.timer(0.1, update_meters)

    # ---------------------------------------------------------- device helpers
    def query_devices(kind):
        """Enumerate device dicts locally via sounddevice. kind: 'output'|'input'."""
        try:
            import sounddevice as sd
            return [d for d in sd.query_devices()
                    if (d['max_output_channels'] if kind == 'output'
                        else d['max_input_channels']) > 0]
        except Exception as e:
            ui.notify(f'Device enumeration failed: {e}', type='negative')
            return []

    def options_from(devs):
        options = {'': 'System Default'}
        for d in devs:
            label = f"[{d['index']}] {d['name']}"
            options[label] = label
        return options

    def match_option(saved, kind, devs):
        """Find the current option for a saved '[ID] Name' device string, by
        NAME — Windows shifts device indices between boots, so the stored ID
        alone can point at a different device."""
        if not saved:
            return None
        try:
            from device_utils import resolve_device, device_to_option
            dev = resolve_device(saved, want_input=(kind == 'input'), devices=devs)
            return device_to_option(dev) if dev else None
        except Exception:
            return None

    def parse_device_id(selected):
        if not selected or '[' not in selected:
            return None
        try:
            return int(selected.split(']')[0].strip('['))
        except ValueError:
            return None

    # ------------------------------------------------------- output device card
    with ui.card().classes('w-full'):
        ui.label('Output Device').classes('text-lg font-bold')
        out_select = ui.select({'': 'System Default'}, value='', with_input=True).classes('w-full')
        out_result = ui.label().classes('text-xs text-slate-400')

        async def refresh_outputs():
            out_result.text = 'scanning...'
            devs = await asyncio.to_thread(query_devices, 'output')
            out_select.options = options_from(devs)
            matched = match_option(cfg.AUDIO_OUTPUT_DEVICE, 'output', devs)
            if matched:
                out_select.value = matched
            out_result.text = f'{len(devs)} device(s) found'
            out_result.classes(replace='text-xs text-green-400')
        ui.button('Refresh devices', icon='refresh', on_click=refresh_outputs).props('flat')

        test_btn = ui.button('Test', icon='play_arrow').props('flat')

        def out_callback(outdata, frames, time_info, status):
            import numpy as np
            if not runtime['testing_out']:
                outdata.fill(0)
                return
            n = np.arange(frames) + runtime['phase']
            tone = 0.1 * np.sin(2 * math.pi * 440.0 * n / runtime['samplerate'])
            outdata[:, 0] = tone
            runtime['phase'] += frames
            rms = float(np.sqrt(np.mean(tone ** 2)))
            levels['out'] = max(20 * math.log10(rms + 1e-9), levels['out'] - 0.5)

        def stop_output_test():
            runtime['testing_out'] = False
            if runtime['out_stream'] is not None:
                try:
                    runtime['out_stream'].stop()
                    runtime['out_stream'].close()
                except Exception:
                    pass
                runtime['out_stream'] = None
            test_btn.icon = 'play_arrow'
            test_btn.props('color=green')
            levels['out'] = MIN_DB

        async def toggle_output_test():
            if runtime['testing_out']:
                stop_output_test()
                return
            device_id = parse_device_id(out_select.value)
            try:
                import sounddevice as sd
                if device_id is None:
                    device_id = sd.default.device[1]
                runtime['samplerate'] = sd.query_devices(device_id, 'output')['default_samplerate']
                runtime['phase'] = 0.0
                runtime['testing_out'] = True
                runtime['out_stream'] = sd.OutputStream(
                    device=device_id, channels=1, samplerate=runtime['samplerate'],
                    callback=out_callback)
                runtime['out_stream'].start()
                test_btn.icon = 'stop'
                test_btn.props('color=red')
                ui.notify('Playing 440 Hz test tone — press Stop to end')
            except Exception as e:
                runtime['testing_out'] = False
                ui.notify(f'Test failed: {e}', type='negative')
        test_btn.on_click(toggle_output_test)

    # -------------------------------------------------------- music device card
    with ui.card().classes('w-full'):
        ui.label('Music Output Device').classes('text-lg font-bold')
        ui.label('Separate device for music (Voicemeeter VOD splitting). Leave empty to use the '
                 'Output Device.').classes('text-xs text-slate-400')
        music_select = ui.select({'': 'System Default'}, value='', with_input=True).classes('w-full')
        music_result = ui.label().classes('text-xs text-slate-400')

        async def refresh_music():
            music_result.text = 'scanning...'
            devs = await asyncio.to_thread(query_devices, 'output')
            music_select.options = options_from(devs)
            matched = match_option(cfg.MUSIC_OUTPUT_DEVICE, 'output', devs)
            if matched:
                music_select.value = matched
            music_result.text = f'{len(devs)} device(s) found'
            music_result.classes(replace='text-xs text-green-400')
        ui.button('Refresh devices', icon='refresh', on_click=refresh_music).props('flat')

    # -------------------------------------------------------- input device card
    with ui.card().classes('w-full'):
        ui.label('Input Device (Listener)').classes('text-lg font-bold')
        input_select = ui.select({'': 'None'}, value='', with_input=True).classes('w-full')
        input_result = ui.label().classes('text-xs text-slate-400')

        async def refresh_inputs():
            input_result.text = 'scanning...'
            devs = await asyncio.to_thread(query_devices, 'input')
            input_select.options = options_from(devs)
            matched = match_option(cfg.AUDIO_INPUT_DEVICE, 'input', devs)
            if matched:
                input_select.value = matched
            input_result.text = f'{len(devs)} device(s) found'
            input_result.classes(replace='text-xs text-green-400')
        ui.button('Refresh devices', icon='refresh', on_click=refresh_inputs).props('flat')

        monitor_btn = ui.button('Monitor', icon='play_arrow').props('flat')

        def in_callback(indata, frames, time_info, status):
            import numpy as np
            rms = float(np.sqrt(np.mean(indata[:, 0] ** 2))) if indata.size else 0.0
            levels['in'] = max(20 * math.log10(rms + 1e-9), levels['in'] - 0.5)

        def stop_input_monitor():
            runtime['monitoring_in'] = False
            if runtime['in_stream'] is not None:
                try:
                    runtime['in_stream'].stop()
                    runtime['in_stream'].close()
                except Exception:
                    pass
                runtime['in_stream'] = None
            monitor_btn.icon = 'play_arrow'
            monitor_btn.props('color=green')
            levels['in'] = MIN_DB

        async def toggle_input_monitor():
            if runtime['monitoring_in']:
                stop_input_monitor()
                return
            device_id = parse_device_id(input_select.value)
            try:
                import sounddevice as sd
                if device_id is None:
                    device_id = sd.default.device[0]
                runtime['monitoring_in'] = True
                runtime['in_stream'] = sd.InputStream(
                    device=device_id, channels=1, samplerate=48000.0,
                    callback=in_callback)
                runtime['in_stream'].start()
                monitor_btn.icon = 'stop'
                monitor_btn.props('color=red')
                ui.notify('Monitoring input — speak to see the level')
            except Exception as e:
                runtime['monitoring_in'] = False
                ui.notify(f'Monitor failed: {e}', type='negative')
        monitor_btn.on_click(toggle_input_monitor)

    # -------------------------------------------------------------- ducking card
    with ui.card().classes('w-full'):
        ui.label('Audio Ducking').classes('text-lg font-bold')
        duck_enabled = ui.switch('Enable ducking (lower music when TTS speaks)',
                                 value=cfg.AUDIO_DUCKING_ENABLED)

        def slider_row(label_text, min_, max_, step_, value, fmt):
            with ui.row().classes('w-full items-center gap-3'):
                ui.label(label_text).classes('w-40 text-sm')
                s = ui.slider(min=min_, max=max_, step=step_, value=value).classes('grow')
                v = ui.label(fmt.format(value)).classes('w-20 text-xs text-right text-slate-400')
                s.on_value_change(lambda e, f=fmt, lbl=v: lbl.set_text(f.format(e.value)))
                return s

        duck_amount = slider_row('Duck amount', -30, 0, 1, int(cfg.AUDIO_DUCK_AMOUNT), '{:.0f} dB')
        attack = slider_row('Attack time', 0, 1000, 10, int(cfg.AUDIO_DUCK_ATTACK_MS), '{:.0f} ms')
        release = slider_row('Release time', 0, 2000, 10, int(cfg.AUDIO_DUCK_RELEASE_MS), '{:.0f} ms')
        duck_delay = slider_row('Duck delay', 0.0, 10.0, 0.1, float(cfg.AUDIO_DUCK_DELAY_S), '{:.1f} s')
        duck_hold = slider_row('Duck hold', 0.0, 10.0, 0.1, float(cfg.AUDIO_DUCK_HOLD_S), '{:.1f} s')

    # ---------------------------------------------------------- playback toggle
    with ui.card().classes('w-full'):
        ui.label('Playback').classes('text-lg font-bold')
        player_enabled = ui.switch('Audio Player enabled (plays TTS when NOT using Neurosync)',
                                   value=cfg.AUDIO_PLAYER_ENABLED)

    # ------------------------------------------------------------------ save
    async def save():
        values = {
            'AUDIO_PLAYER_ENABLED': player_enabled.value,
            'AUDIO_OUTPUT_DEVICE': out_select.value or '',
            'MUSIC_OUTPUT_DEVICE': music_select.value or '',
            'AUDIO_INPUT_DEVICE': input_select.value or '',
            'AUDIO_DUCKING_ENABLED': duck_enabled.value,
            'AUDIO_DUCK_AMOUNT': int(duck_amount.value),
            'AUDIO_DUCK_ATTACK_MS': int(attack.value),
            'AUDIO_DUCK_RELEASE_MS': int(release.value),
            'AUDIO_DUCK_DELAY_S': round(float(duck_delay.value), 1),
            'AUDIO_DUCK_HOLD_S': round(float(duck_hold.value), 1),
        }
        file_ok, pushed = await asyncio.to_thread(settings_store.save, values)
        # Input device has a dedicated endpoint on main.py
        input_pushed = False
        if await sm.is_running('mcp'):
            try:
                with httpx.Client(timeout=5.0) as client:
                    r = client.post(f'{settings_store.MAIN_URL}/api/audio/input_device',
                                    json={'device': values['AUDIO_INPUT_DEVICE']})
                    input_pushed = r.status_code == 200
            except Exception:
                pass
        if file_ok:
            names = list(pushed.keys()) + (['input_device'] if input_pushed else [])
            ui.notify(f'Saved to config.py (pushed live to: {", ".join(names) or "no running services"})',
                      type='positive')
        else:
            ui.notify('Failed to write config.py', type='negative')
    ui.button('Save audio settings', icon='save', on_click=save).classes('mt-2')

    # --------------------------------------------------- initial state + cleanup
    async def initial_load():
        await refresh_outputs()
        await refresh_music()
        await refresh_inputs()
    ui.timer(0.2, initial_load, once=True)

    def cleanup_streams():
        stop_output_test()
        stop_input_monitor()
    try:
        ui.context.client.on_disconnect(cleanup_streams)
    except Exception:
        pass