"""Games tab for the NiceGUI control panel.

Controls the optional Gem Drive process (chat-driven 3D highway, port 5010):
start/stop, live state + leaderboard, streamer controls (pause/reset/spawn/
crash), and the GAME_DRIVE_* settings.
"""

import asyncio
import os
import subprocess
from pathlib import Path
from typing import Optional

import httpx
from nicegui import ui

from drive_game import assets
from panel import m8_audio_sync, settings_store
from panel.service_manager import CHASM_ROOT, M8_ROOT

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODELS_DIR = PROJECT_ROOT / "models" / "cars"
PLAYERS_DIR = MODELS_DIR / "players"

# --- chasm / OpenCE -------------------------------------------------------
OPEN_CE_DIR = Path(os.environ.get(
    'OPENCE_DIR',
    r'C:\Users\jayge\Documents\AI\xbox\OpenCE\build\windows',
))
OPEN_CE_EXE = OPEN_CE_DIR / 'halo.exe'
CHASM_URL = os.environ.get('CHASM_URL', 'http://127.0.0.1:7341').rstrip('/')
OLLAMA_URL = os.environ.get('OLLAMA_URL', 'http://127.0.0.1:11434').rstrip('/')
OPEN_CE_MODEL = 'gemma3:4b-it-qat'
CREATE_NEW_CONSOLE = 0x00000010

# m8's own OpenCE patch (the Kevin companion), separate from the chasm build.
M8_HALO_DIR = Path(M8_ROOT) / 'halo' / 'build' / 'windows'
M8_HALO_EXE = M8_HALO_DIR / 'halo.exe'


async def save_uploaded_model(upload, target_dir: Path, project_root: Path = PROJECT_ROOT) -> Optional[Path]:
    """Write a NiceGUI UploadFile to target_dir with a sanitized name."""
    filename = assets.safe_filename(upload.name)
    if filename is None:
        return None
    data = await upload.read()
    target_dir.mkdir(parents=True, exist_ok=True)
    destination = target_dir / filename
    await asyncio.to_thread(destination.write_bytes, data)
    return destination


def create(sm):
    ui.label('Games').classes('text-2xl font-bold')
    with ui.tabs().classes('w-full').props('mobile-arrows no-caps') as tabs:
        drive_tab = ui.tab('Gem Drive')
        iso_tab = ui.tab('Isometric Game')
        opence_tab = ui.tab('Chasm - OpenCE')
        kevin_tab = ui.tab('m8 - Kevin')
    with ui.tab_panels(tabs, value=drive_tab).classes('w-full'):
        with ui.tab_panel(drive_tab):
            _gem_drive_tab(sm)
        with ui.tab_panel(iso_tab):
            _iso_game_tab(sm, settings_store.load_config())
        with ui.tab_panel(opence_tab):
            _chasm_opence_tab(sm)
        with ui.tab_panel(kevin_tab):
            _m8_kevin_tab(sm)


def _gem_drive_tab(sm):
    cfg = settings_store.load_config()
    game_url = getattr(cfg, 'GAME_DRIVE_URL', 'http://127.0.0.1:5010').rstrip('/')

    ui.label('Gem Drive').classes('text-2xl font-bold')
    status_label = ui.label('● Checking...').classes('text-sm text-slate-400')

    async def refresh_status():
        running = await sm.is_running('drive_game')
        status_label.text = '● Running' if running else '● Stopped'
        status_label.classes(
            replace='text-sm ' + ('text-green-400' if running else 'text-slate-400')
        )
        start_btn.text = 'Stop game' if running else 'Start game'

    async def toggle_game():
        if await sm.is_running('drive_game'):
            sm.stop('drive_game')
        else:
            sm.start('drive_game')
        await asyncio.sleep(1.0)
        await refresh_status()

    with ui.card().classes('w-full'):
        with ui.row().classes('w-full items-center justify-between'):
            with ui.column().classes('gap-0'):
                ui.label('Gem Drive — chat highway').classes('text-lg font-bold')
                ui.label(
                    'Slow-paced 3D highway where viewers drive with ! commands. '
                    'Windowed Ursina app, captured by OBS.'
                ).classes('text-sm text-slate-400 max-w-2xl')
            with ui.row().classes('items-center gap-2'):
                start_btn = ui.button('Start game', icon='play_arrow', on_click=toggle_game)
                ui.timer(3.0, refresh_status, immediate=True)

        with ui.row().classes('gap-4 items-center mt-2'):
            ui.label('Chat:').classes('text-xs text-slate-400')
            for command in ('!l left', '!r right', '!f faster', '!s slower',
                            '!b brake', '!j join', '!q leave', '!sc score'):
                ui.badge(command).props('outline').classes('text-xs')

    # ---------------------------------------------------------------- demo mode
    with ui.card().classes('w-full'):
        with ui.row().classes('w-full items-center justify-between'):
            with ui.column().classes('gap-0'):
                ui.label('Demo Mode').classes('text-lg font-bold')
                ui.label(
                    'Spawns auto-driving cars (Demo 1…N) so you can test models, '
                    'camera and tuning without waiting for chat. Demo crashes do not '
                    'trigger Gem commentary.'
                ).classes('text-sm text-slate-400 max-w-2xl')
            with ui.row().classes('items-center gap-2'):
                demo_switch = ui.switch('Enable', value=False)
                demo_count = ui.number('Demo cars', value=6, min=1, max=12).classes('w-24')
                demo_status = ui.label('● Demo off').classes('text-sm text-slate-400')

        async def apply_demo():
            await post_control(
                'demo',
                enabled=bool(demo_switch.value),
                cars=int(demo_count.value or 6),
            )

        ui.button('Apply demo mode', icon='smart_toy', on_click=apply_demo).props('flat')

    # ---------------------------------------------------------------- live state
    state = {'data': None}
    with ui.card().classes('w-full'):
        with ui.row().classes('w-full items-center justify-between'):
            ui.label('Live State').classes('text-lg font-bold')
            state_badge = ui.badge('offline').props('outline')

        with ui.row().classes('gap-3 flex-wrap'):
            stat_labels = {}
            for key, title in (('cars', 'Cars'), ('traffic', 'Traffic'),
                               ('tick', 'Tick'), ('speed', 'Avg speed')):
                with ui.card().classes('bg-slate-800 px-4 py-2 min-w-[120px]'):
                    ui.label(title).classes('text-xs text-slate-400')
                    stat_labels[key] = ui.label('-').classes('text-xl font-bold')

        table = ui.table(
            columns=[
                {'name': 'user', 'label': 'Driver', 'field': 'user', 'align': 'left'},
                {'name': 'best', 'label': 'Best', 'field': 'best', 'align': 'right'},
                {'name': 'run', 'label': 'Run', 'field': 'run', 'align': 'right'},
                {'name': 'status', 'label': 'Status', 'field': 'status', 'align': 'left'},
            ],
            rows=[],
            row_key='user',
        ).classes('w-full').props('flat dense dark')

    async def refresh_state():
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(f'{game_url}/api/state')
            if response.status_code != 200:
                raise RuntimeError(f'HTTP {response.status_code}')
            data = response.json()
            state['data'] = data
            state_badge.text = 'PAUSED' if data.get('paused') else 'RUNNING'
            state_badge.props['color'] = 'orange' if data.get('paused') else 'green'
            if data.get('demo_enabled'):
                demo_status.text = f"● Demo: {data.get('demo_cars', 0)} cars"
                demo_status.classes(replace='text-sm text-cyan-300')
            else:
                demo_status.text = '● Demo off'
                demo_status.classes(replace='text-sm text-slate-400')
            stat_labels['cars'].text = f"{data.get('active_cars', 0)}/12"
            stat_labels['traffic'].text = str(len(data.get('traffic', [])))
            stat_labels['tick'].text = str(data.get('tick', 0))
            speeds = [p.get('speed', 0) for p in data.get('players', [])]
            stat_labels['speed'].text = (
                f'{sum(speeds) / len(speeds):.0f} u/s' if speeds else '—'
            )
            table.rows = [
                {
                    'user': row['user'],
                    'best': f"{row.get('best', 0)} m",
                    'run': f"{row.get('score', 0)} m",
                    'status': 'driving' if row.get('alive') else 'crashed',
                }
                for row in data.get('leaderboard', [])
            ]
            table.update()
        except Exception as exc:
            print(
                f"[games] state refresh failed ({game_url}): "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
            state['data'] = None
            state_badge.text = 'offline'
            state_badge.props['color'] = 'grey'
            demo_status.text = '● Demo off'
            demo_status.classes(replace='text-sm text-slate-400')
            for label in stat_labels.values():
                label.text = '—'
            if table.rows:
                table.rows = []
                table.update()

    ui.timer(2.0, refresh_state, immediate=True)

    # ---------------------------------------------------------------- controls
    async def post_control(action, **extra):
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.post(
                    f'{game_url}/api/control', json={'action': action, **extra}
                )
            if response.status_code == 200:
                ui.notify(f'Game: {action}', type='positive')
            else:
                ui.notify(f'Game returned HTTP {response.status_code}', type='negative')
        except Exception:
            ui.notify('Gem Drive is not running', type='negative')
        await refresh_state()

    with ui.card().classes('w-full'):
        ui.label('Streamer Controls').classes('text-lg font-bold')
        with ui.row().classes('items-center gap-2 flex-wrap'):
            ui.button('Pause', icon='pause',
                      on_click=lambda: post_control('pause')).props('flat')
            ui.button('Resume', icon='play_arrow',
                      on_click=lambda: post_control('resume')).props('flat')
            ui.button('Reset race', icon='restart_alt',
                      on_click=lambda: post_control('reset')).props('flat')
            ui.button('Spawn traffic', icon='traffic',
                      on_click=lambda: post_control('spawn_traffic', count=3)).props('flat')
            crash_user = ui.input(placeholder='viewer name').classes('w-40')
            ui.button('Force crash', icon='car_crash',
                      on_click=lambda: post_control(
                          'force_crash', user=(crash_user.value or '').strip())).props('flat')

    # ---------------------------------------------------------------- settings
    with ui.card().classes('w-full'):
        ui.label('Settings').classes('text-lg font-bold')
        with ui.row().classes('gap-8 items-start flex-wrap'):
            with ui.column().classes('gap-2 min-w-[280px]'):
                enabled = ui.switch('Enable Gem Drive (! commands)', value=cfg.GAME_DRIVE_ENABLED)
                suppress_idle = ui.switch(
                    'Pause idle AI talk while the game is running',
                    value=getattr(cfg, 'GAME_DRIVE_SUPPRESS_IDLE', True),
                )
                commentary = ui.switch('Gem commentary on crashes/leader changes',
                                        value=cfg.GAME_DRIVE_COMMENTARY_ENABLED)
                use_llm = ui.switch('Use LLM for commentary (canned fallback)',
                                    value=cfg.GAME_DRIVE_COMMENTARY_USE_LLM)
            with ui.column().classes('gap-2 min-w-[280px]'):
                cooldown = ui.number('Commentary cooldown (s)',
                                     value=cfg.GAME_DRIVE_COMMENTARY_COOLDOWN_S,
                                     step=5, min=0).classes('w-48')
                max_cars = ui.number('Max cars', value=cfg.GAME_DRIVE_MAX_CARS,
                                     step=1, min=1, max=20).classes('w-48')
                demo_reserved = ui.number(
                    'Demo reserved slots',
                    value=getattr(cfg, 'GAME_DRIVE_DEMO_RESERVED_SLOTS', 2),
                    step=1, min=0, max=20,
                ).classes('w-48')
                ttl = ui.number('Inactive car TTL (s)', value=cfg.GAME_DRIVE_CAR_TTL_S,
                                step=30, min=30).classes('w-48')
                command_cd = ui.number('Per-viewer command cooldown (s)',
                                       value=cfg.GAME_DRIVE_COMMAND_COOLDOWN_S,
                                       step=0.5, min=0.5).classes('w-48')
                traffic_density = ui.select(
                    ['off', 'sparse', 'normal', 'dense'],
                    value=getattr(cfg, 'GAME_DRIVE_TRAFFIC_DENSITY', 'sparse'),
                    label='Traffic density',
                ).classes('w-48')

        ui.label(
            'Traffic density applies live. Max cars, demo reserved slots, TTL '
            'and command cooldown apply when the game restarts.'
        ).classes('text-xs text-slate-400 mt-2')

        async def save_settings():
            values = {
                'GAME_DRIVE_ENABLED': enabled.value,
                'GAME_DRIVE_SUPPRESS_IDLE': suppress_idle.value,
                'GAME_DRIVE_COMMENTARY_ENABLED': commentary.value,
                'GAME_DRIVE_COMMENTARY_USE_LLM': use_llm.value,
                'GAME_DRIVE_COMMENTARY_COOLDOWN_S': float(cooldown.value or 45.0),
                'GAME_DRIVE_MAX_CARS': int(max_cars.value or 12),
                'GAME_DRIVE_DEMO_RESERVED_SLOTS': int(demo_reserved.value or 2),
                'GAME_DRIVE_CAR_TTL_S': float(ttl.value or 180),
                'GAME_DRIVE_COMMAND_COOLDOWN_S': float(command_cd.value or 2.0),
                'GAME_DRIVE_TRAFFIC_DENSITY': traffic_density.value or 'sparse',
            }
            file_ok, pushed = await asyncio.to_thread(settings_store.save, values)
            if file_ok and await sm.is_running('drive_game'):
                await post_control(
                    'traffic_density',
                    density=traffic_density.value or 'sparse',
                )
            ui.notify(
                'Saved to config.py' + (
                    f' (pushed live to: {", ".join(pushed)})' if pushed else ''
                ),
                type='positive' if file_ok else 'negative',
            )

        with ui.row().classes('w-full justify-end'):
            ui.button('Save game settings', icon='save', on_click=save_settings)

    # ---------------------------------------------------------------- camera
    with ui.card().classes('w-full'):
        ui.label('Camera').classes('text-lg font-bold')
        ui.label(
            'Fixed is a constant rig that follows the pack: no zoom, orbit or '
            'camera switching. Offsets and look-at are relative to the pack centre; '
            'negative Z puts the camera behind. Restart Gem Drive to apply.'
        ).classes('text-sm text-slate-400')

        with ui.row().classes('gap-8 items-start flex-wrap w-full'):
            with ui.column().classes('gap-2 min-w-[280px]'):
                camera_mode = ui.select(
                    ['fixed', 'wide'],
                    value=getattr(cfg, 'GAME_DRIVE_CAMERA_MODE', 'fixed'),
                    label='Camera mode',
                ).classes('w-48')
                ui.label('Position offset (X / Y / Z)').classes('text-xs text-slate-400')
                with ui.row().classes('gap-2'):
                    camera_x = ui.number(value=cfg.GAME_DRIVE_CAMERA_OFFSET_X,
                                         step=5).classes('w-24')
                    camera_y = ui.number(value=cfg.GAME_DRIVE_CAMERA_OFFSET_Y,
                                         step=5).classes('w-24')
                    camera_z = ui.number(value=cfg.GAME_DRIVE_CAMERA_OFFSET_Z,
                                         step=5).classes('w-24')
            with ui.column().classes('gap-2 min-w-[280px]'):
                ui.label('Look-at offset (X / Y / Z)').classes('text-xs text-slate-400')
                with ui.row().classes('gap-2'):
                    look_x = ui.number(value=cfg.GAME_DRIVE_CAMERA_LOOK_X,
                                       step=5).classes('w-24')
                    look_y = ui.number(value=cfg.GAME_DRIVE_CAMERA_LOOK_Y,
                                       step=5).classes('w-24')
                    look_z = ui.number(value=cfg.GAME_DRIVE_CAMERA_LOOK_Z,
                                       step=5).classes('w-24')

        async def save_camera():
            values = {
                'GAME_DRIVE_CAMERA_MODE': camera_mode.value or 'fixed',
                'GAME_DRIVE_CAMERA_OFFSET_X': float(camera_x.value or 0.0),
                'GAME_DRIVE_CAMERA_OFFSET_Y': float(camera_y.value or 32.0),
                'GAME_DRIVE_CAMERA_OFFSET_Z': float(camera_z.value or -100.0),
                'GAME_DRIVE_CAMERA_LOOK_X': float(look_x.value or 0.0),
                'GAME_DRIVE_CAMERA_LOOK_Y': float(look_y.value or 1.0),
                'GAME_DRIVE_CAMERA_LOOK_Z': float(look_z.value or 30.0),
            }
            file_ok, _ = await asyncio.to_thread(settings_store.save, values)
            ui.notify(
                'Camera settings saved. Restart Gem Drive to apply.'
                if file_ok else 'Failed to write config.py',
                type='positive' if file_ok else 'negative',
            )

        with ui.row().classes('w-full justify-end'):
            ui.button('Save camera settings', icon='save', on_click=save_camera)

    # ---------------------------------------------------------------- models
    def ensure_model_dirs():
        PLAYERS_DIR.mkdir(parents=True, exist_ok=True)

    async def save_upload(event, target: Path, label: str):
        try:
            destination = await save_uploaded_model(event.file, target)
        except Exception as exc:
            ui.notify(f"{label} upload failed: {exc}", type='negative')
            return None
        if destination is None:
            ui.notify(
                f"{label}: use .glb, .gltf, .obj or .bam (export .blend first)",
                type='negative',
            )
            return None
        return destination.relative_to(PROJECT_ROOT).as_posix()

    with ui.card().classes('w-full'):
        ui.label('Car Models').classes('text-lg font-bold')
        ui.label(
            'Drop GLB/GLTF/OBJ/BAM files in models/cars/. '
            'Export .blend files from Blender to GLB or OBJ first.'
        ).classes('text-sm text-slate-400')

        with ui.row().classes('gap-8 items-start flex-wrap w-full'):
            with ui.column().classes('gap-2 min-w-[320px] grow'):
                car_model_input = ui.input(
                    'Default player model',
                    value=cfg.GAME_DRIVE_CAR_MODEL,
                    placeholder='models/cars/default.glb',
                ).classes('w-full')
                traffic_model_input = ui.input(
                    'Traffic model',
                    value=cfg.GAME_DRIVE_TRAFFIC_MODEL,
                    placeholder='models/cars/traffic.glb',
                ).classes('w-full')
                player_dir_input = ui.input(
                    'Per-viewer model folder',
                    value=cfg.GAME_DRIVE_PLAYER_MODEL_DIR,
                ).classes('w-full')
                ui.label(
                    'Per-viewer files use the chat name, e.g. models/cars/players/JayGeeAiForFun.glb'
                ).classes('text-xs text-slate-400')

            with ui.column().classes('gap-2 min-w-[280px]'):
                model_scale = ui.number(
                    'Model scale (0 = auto-fit)',
                    value=cfg.GAME_DRIVE_MODEL_SCALE,
                    step=0.1, min=0,
                ).classes('w-56')
                model_yaw = ui.number(
                    'Model yaw (degrees)',
                    value=cfg.GAME_DRIVE_MODEL_YAW,
                    step=15,
                ).classes('w-56')
                model_y_offset = ui.number(
                    'Y offset',
                    value=cfg.GAME_DRIVE_MODEL_Y_OFFSET,
                    step=0.05,
                ).classes('w-56')

        with ui.row().classes('gap-4 items-end flex-wrap w-full'):
            with ui.column().classes('gap-1'):
                ui.label('Default car upload').classes('text-xs text-slate-400')
                car_upload = ui.upload(
                    label='Upload car',
                    auto_upload=True,
                    max_file_size=100 * 1024 * 1024,
                ).props('accept=.glb,.gltf,.obj,.bam').classes('w-56')
            with ui.column().classes('gap-1'):
                ui.label('Traffic upload').classes('text-xs text-slate-400')
                traffic_upload = ui.upload(
                    label='Upload traffic',
                    auto_upload=True,
                    max_file_size=100 * 1024 * 1024,
                ).props('accept=.glb,.gltf,.obj,.bam').classes('w-56')
            with ui.column().classes('gap-1'):
                ui.label('Per-viewer upload').classes('text-xs text-slate-400')
                player_name = ui.input(placeholder='viewer chat name').classes('w-56')
                player_upload = ui.upload(
                    label='Upload player car',
                    auto_upload=True,
                    max_file_size=100 * 1024 * 1024,
                ).props('accept=.glb,.gltf,.obj,.bam').classes('w-56')

        async def upload_car(event):
            relative = await save_upload(event, MODELS_DIR, 'Default car')
            if relative:
                car_model_input.value = relative
                file_ok, _ = await asyncio.to_thread(
                    settings_store.save, {'GAME_DRIVE_CAR_MODEL': relative}
                )
                ui.notify(
                    f'Uploaded {relative} and saved. Restart Gem Drive to apply.'
                    if file_ok else 'Uploaded, but failed to write config.py',
                    type='positive' if file_ok else 'negative',
                )

        async def upload_traffic(event):
            relative = await save_upload(event, MODELS_DIR, 'Traffic')
            if relative:
                traffic_model_input.value = relative
                file_ok, _ = await asyncio.to_thread(
                    settings_store.save, {'GAME_DRIVE_TRAFFIC_MODEL': relative}
                )
                ui.notify(
                    f'Uploaded {relative} and saved. Restart Gem Drive to apply.'
                    if file_ok else 'Uploaded, but failed to write config.py',
                    type='positive' if file_ok else 'negative',
                )

        async def upload_player(event):
            name = (player_name.value or '').strip()
            if not name:
                ui.notify('Enter the viewer chat name first', type='negative')
                return
            target_dir = assets.resolve_model_dir(
                player_dir_input.value or 'models/cars/players', PROJECT_ROOT
            )
            try:
                destination = await save_uploaded_model(event.file, target_dir)
            except Exception as exc:
                ui.notify(f'Upload failed: {exc}', type='negative')
                return
            if destination is None:
                ui.notify('Use .glb, .gltf, .obj or .bam (export .blend first)', type='negative')
                return
            try:
                shown = destination.relative_to(PROJECT_ROOT).as_posix()
            except ValueError:
                shown = str(destination)
            ui.notify(f'Uploaded {shown}', type='positive')

        car_upload.on_upload(upload_car)
        traffic_upload.on_upload(upload_traffic)
        player_upload.on_upload(upload_player)

        def open_models_folder():
            ensure_model_dirs()
            try:
                os.startfile(str(MODELS_DIR))
            except Exception as exc:
                ui.notify(f'Could not open folder: {exc}', type='negative')

        async def save_models():
            values = {
                'GAME_DRIVE_CAR_MODEL': (car_model_input.value or '').strip(),
                'GAME_DRIVE_TRAFFIC_MODEL': (traffic_model_input.value or '').strip(),
                'GAME_DRIVE_PLAYER_MODEL_DIR': (player_dir_input.value or 'models/cars/players').strip(),
                'GAME_DRIVE_MODEL_SCALE': float(model_scale.value or 0.0),
                'GAME_DRIVE_MODEL_YAW': float(model_yaw.value or 0.0),
                'GAME_DRIVE_MODEL_Y_OFFSET': float(model_y_offset.value or 0.0),
            }
            file_ok, _ = await asyncio.to_thread(settings_store.save, values)
            ui.notify(
                'Model settings saved. Restart Gem Drive to apply.'
                if file_ok else 'Failed to write config.py',
                type='positive' if file_ok else 'negative',
            )

        with ui.row().classes('w-full items-center justify-between'):
            ui.button('Open models folder', icon='folder_open',
                      on_click=open_models_folder).props('flat')
            ui.button('Save model settings', icon='save', on_click=save_models)


def _iso_game_tab(sm, cfg):
    main_url = settings_store.MAIN_URL

    ui.label('Isometric Game').classes('text-2xl font-bold')
    ui.label(
        'Unreal Engine isometric game driven by OSC. Add exact chat phrases; when a '
        'viewer sends that exact message (or !phrase), the OSC command is sent and '
        'the message does not go to the LLM.'
    ).classes('text-sm text-slate-400 max-w-3xl')

    with ui.card().classes('w-full'):
        with ui.row().classes('w-full items-center gap-6 flex-wrap'):
            enabled = ui.switch('Enable isometric chat commands',
                                value=getattr(cfg, 'ISO_GAME_ENABLED', False))
            with ui.column().classes('gap-0'):
                ui.label('OSC IP').classes('text-xs text-slate-400')
                ip_input = ui.input(value=getattr(cfg, 'ISO_OSC_IP', cfg.OSC_IP)).classes('w-64')
            with ui.column().classes('gap-0'):
                ui.label('OSC port').classes('text-xs text-slate-400')
                port_input = ui.number(
                    value=float(getattr(cfg, 'ISO_OSC_PORT', cfg.OSC_PORT)),
                    step=1, min=1,
                ).classes('w-32')
        ui.label(
            'Phrases are exact matches (case-insensitive). Examples: "left", '
            '"right", "boost", "!brake".'
        ).classes('text-xs text-slate-400 mt-2')

    rows = []

    def test_action(rec):
        address = rec['address'].value.strip()
        value = rec['value'].value.strip()
        if not address:
            ui.notify('No address entered', type='negative')
            return
        # Mirror what chat sends: Unreal expects [chatter]value
        wire_value = f'[JayGeeAiForFun]{value}'
        try:
            r = httpx.post(
                f'{main_url}/api/iso/osc/test',
                json={'address': address, 'value': wire_value},
                timeout=5.0,
            )
            ok = r.status_code == 200
            ui.notify(
                f'Sent {address} = {wire_value}' if ok else f'OSC failed: {r.text[:120]}',
                type='positive' if ok else 'negative',
            )
        except Exception:
            ui.notify('MCP server not running', type='negative')

    def remove_row(rec):
        rec['row'].delete()
        rows.remove(rec)

    def add_row(phrase='', address='', value=''):
        rec = {}
        with list_box:
            with ui.row().classes('w-full items-center gap-2') as row:
                rec['row'] = row
                rec['phrase'] = ui.input(value=phrase, placeholder='Chat phrase').classes('grow')
                rec['address'] = ui.input(value=address, placeholder='/osc/address').classes('grow')
                rec['value'] = ui.input(value=value, placeholder='value').classes('w-32')
                rec['test'] = ui.button(
                    'Test', icon='send', on_click=lambda r=rec: test_action(r)
                ).props('flat dense')
                rec['del'] = ui.button(
                    '✕', on_click=lambda r=rec: remove_row(r)
                ).props('flat dense color=red')
        rows.append(rec)

    with ui.card().classes('w-full'):
        with ui.row().classes('w-full justify-between items-center'):
            ui.label('OSC Commands').classes('text-lg font-bold')
            ui.button('+ Add command', icon='add', on_click=lambda: add_row()).props('flat')
        list_box = ui.column().classes('w-full gap-2')

    async def save():
        actions = [
            {
                'phrase': r['phrase'].value.strip(),
                'address': r['address'].value.strip(),
                'value': r['value'].value.strip(),
            }
            for r in rows
            if r['phrase'].value.strip() and r['address'].value.strip()
        ]
        values = {
            'ISO_GAME_ENABLED': bool(enabled.value),
            'ISO_OSC_IP': ip_input.value.strip(),
            'ISO_OSC_PORT': int(port_input.value or cfg.OSC_PORT),
            'ISO_OSC_ACTIONS': actions,
        }
        file_ok, pushed = await asyncio.to_thread(settings_store.save, values)
        live = False
        if await sm.is_running('mcp'):
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    r = await client.post(
                        f'{main_url}/api/iso/osc_actions',
                        json={
                            'enabled': bool(enabled.value),
                            'ip': ip_input.value.strip(),
                            'port': int(port_input.value or cfg.OSC_PORT),
                            'actions': actions,
                        },
                    )
                    live = r.status_code == 200
            except Exception:
                pass
        if file_ok:
            names = list(pushed.keys()) + (['iso'] if live else [])
            ui.notify(
                f'Saved {len(actions)} command(s) '
                f'(pushed live to: {", ".join(names) or "no running services"})',
                type='positive',
            )
        else:
            ui.notify('Failed to write config.py', type='negative')

    with ui.row().classes('w-full justify-end'):
        ui.button('Save isometric settings', icon='save', on_click=save)

    for action in getattr(cfg, 'ISO_OSC_ACTIONS', []) or []:
        if isinstance(action, dict):
            add_row(
                action.get('phrase', ''),
                action.get('address', ''),
                action.get('value', ''),
            )


def _opence_running() -> bool:
    """Whether halo.exe is alive (the panel may not have started it)."""
    try:
        import psutil

        for process in psutil.process_iter(['name']):
            if (process.info.get('name') or '').lower() == 'halo.exe':
                return True
        return False
    except Exception:
        try:
            output = subprocess.run(
                ['tasklist', '/FI', 'IMAGENAME eq halo.exe'],
                capture_output=True, text=True, timeout=5,
            ).stdout
            return 'halo.exe' in output.lower()
        except Exception:
            return False


def _open_folder(path: Path):
    try:
        os.startfile(str(path))
    except Exception as exc:
        ui.notify(f'Could not open folder: {exc}', type='negative')


def _chasm_opence_tab(sm):
    ui.label('Chasm - OpenCE').classes('text-2xl font-bold')
    ui.label(
        'Halo: Combat Evolved campaign NPCs driven by chasm. chasm runs the LLM, '
        'profile and actions; StyleTTS2 voices the replies; the OpenCE native bridge '
        'reads the NPC, plays the voice positionally and applies the actions.'
    ).classes('text-sm text-slate-400 max-w-3xl')

    tiles = {}

    with ui.card().classes('w-full'):
        with ui.row().classes('w-full items-center justify-between'):
            ui.label('Stack').classes('text-lg font-bold')
            overall = ui.badge('CHECKING').props('outline')
        with ui.row().classes('gap-3 flex-wrap'):
            for key, title in (
                ('chasm', 'chasm backend'),
                ('stt', 'Whisper STT'),
                ('tts', 'StyleTTS2 voice'),
                ('game', 'OpenCE game'),
                ('link', 'Game <-> chasm'),
            ):
                with ui.card().classes('bg-slate-800 px-4 py-2 min-w-[180px]'):
                    ui.label(title).classes('text-xs text-slate-400')
                    tiles[key] = ui.label('-').classes('text-lg font-bold text-slate-500')
        with ui.row().classes('gap-3 flex-wrap mt-2'):
            for key, title in (
                ('llm', 'Ollama model'),
                ('profile', 'Profile'),
                ('heartbeat', 'Heartbeat'),
                ('ttsurl', 'TTS endpoint'),
            ):
                with ui.card().classes('bg-slate-800 px-4 py-2 min-w-[180px]'):
                    ui.label(title).classes('text-xs text-slate-400')
                    tiles[key] = ui.label('-').classes('text-sm text-slate-300')

        def mark(key, running):
            tiles[key].text = 'running' if running else 'stopped'
            tiles[key].classes(replace='text-lg font-bold ' + (
                'text-green-400' if running else 'text-slate-500'))

        async def refresh():
            chasm_running = await sm.is_running('chasm')
            whisper_running = await sm.is_running('whisper')
            tts_running = await sm.is_running('styletts2')
            game_running = await asyncio.to_thread(_opence_running)

            mark('chasm', chasm_running)
            mark('stt', whisper_running)
            mark('tts', tts_running)
            mark('game', game_running)

            connected = False
            phase = 'disconnected'
            last_seen = '-'
            if chasm_running:
                try:
                    async with httpx.AsyncClient(timeout=2.0) as client:
                        response = await client.get(f'{CHASM_URL}/connection/status')
                    data = response.json()
                    connected = bool(data.get('connected'))
                    phase = data.get('phase') or phase
                    seconds = data.get('last_seen_secs')
                    if isinstance(seconds, (int, float)):
                        last_seen = f'{seconds:.1f}s ago'
                except Exception:
                    phase = 'unreachable'

            tiles['link'].text = f'{phase} - {last_seen}' if chasm_running else 'chasm off'
            tiles['link'].classes(replace='text-lg font-bold ' + (
                'text-green-400' if connected else 'text-slate-500'))
            tiles['heartbeat'].text = last_seen if chasm_running else 'chasm off'

            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    response = await client.get(f'{OLLAMA_URL}/api/tags')
                names = [model.get('name', '') for model in response.json().get('models', [])]
                family = OPEN_CE_MODEL.split(':')[0]
                if any(name.startswith(family) for name in names):
                    tiles['llm'].text = OPEN_CE_MODEL
                    tiles['llm'].classes(replace='text-sm text-green-400')
                else:
                    tiles['llm'].text = 'Ollama up - model missing' if names else 'Ollama up - no models'
                    tiles['llm'].classes(replace='text-sm text-orange-300')
            except Exception:
                tiles['llm'].text = 'Ollama offline'
                tiles['llm'].classes(replace='text-sm text-red-400')

            tiles['profile'].text = 'opence'
            tiles['ttsurl'].text = '127.0.0.1:13300/tts'

            ready = chasm_running and whisper_running and tts_running and game_running and connected
            overall.text = 'READY' if ready else 'ATTENTION'
            overall.props['color'] = 'green' if ready else 'orange'

            chasm_button.text = 'Stop chasm' if chasm_running else 'Start chasm'
            stt_button.text = 'Stop Whisper' if whisper_running else 'Start Whisper'
            tts_button.text = 'Stop StyleTTS2' if tts_running else 'Start StyleTTS2'
            game_button.text = 'Stop OpenCE' if game_running else 'Launch OpenCE'

        async def toggle_chasm():
            if await sm.is_running('chasm'):
                sm.stop('chasm')
            else:
                sm.start('chasm')
            await asyncio.sleep(1.2)
            await refresh()

        async def toggle_stt():
            if await sm.is_running('whisper'):
                sm.stop('whisper')
            else:
                sm.start('whisper')
            await asyncio.sleep(1.2)
            await refresh()

        async def toggle_tts():
            if await sm.is_running('styletts2'):
                sm.stop('styletts2')
            else:
                sm.start('styletts2')
            await asyncio.sleep(1.2)
            await refresh()

        def start_game():
            if not OPEN_CE_EXE.exists():
                ui.notify(f'OpenCE not found: {OPEN_CE_EXE}', type='negative')
                return
            try:
                subprocess.Popen(
                    [str(OPEN_CE_EXE)],
                    cwd=str(OPEN_CE_DIR),
                    creationflags=CREATE_NEW_CONSOLE,
                )
                ui.notify('Starting OpenCE')
            except Exception as exc:
                ui.notify(f'Could not start OpenCE: {exc}', type='negative')

        def stop_game():
            subprocess.run(['taskkill', '/F', '/IM', 'halo.exe'], capture_output=True)
            ui.notify('Stopped OpenCE')

        async def toggle_game():
            if await asyncio.to_thread(_opence_running):
                await asyncio.to_thread(stop_game)
            else:
                start_game()
            await asyncio.sleep(1.2)
            await refresh()

        with ui.row().classes('gap-2 items-center flex-wrap mt-3'):
            chasm_button = ui.button('Start chasm', icon='play_arrow', on_click=toggle_chasm)
            stt_button = ui.button('Start Whisper', icon='play_arrow', on_click=toggle_stt)
            tts_button = ui.button('Start StyleTTS2', icon='play_arrow', on_click=toggle_tts)
            game_button = ui.button('Launch OpenCE', icon='sports_esports', on_click=toggle_game)
            ui.button('Refresh', icon='refresh', on_click=refresh).props('flat')

        ui.timer(2.0, refresh, immediate=True)

    with ui.card().classes('w-full'):
        ui.label('Quick start').classes('text-lg font-bold')
        ui.label(
            '1. Start chasm backend.   2. Start Whisper STT.   3. Start StyleTTS2 voice.   '
            '4. Launch OpenCE.   5. In a campaign mission, stand near an NPC and press T '
            'to type, or hold V to speak.'
        ).classes('text-sm text-slate-300')
        ui.label(
            'Push-to-talk is V (controls.push_to_talk): hold it, speak, release. The '
            'transcript and reply appear on the HUD. The game shows Xbox glyphs: '
            'A = Space, B = F (melee) or Escape in menus, X = E (use/pick up), Y = Q.'
        ).classes('text-sm text-slate-400 mt-1')
        ui.label(
            'First run: put an Xbox Halo CE .iso/.xiso next to halo.exe; the game '
            f'extracts maps/ (about 2 GB). chasm settings: '
            f'{Path(CHASM_ROOT) / "chasm.settings.json"}; active profile: opence.'
        ).classes('text-xs text-slate-500 mt-1')

    with ui.card().classes('w-full'):
        ui.label('Paths').classes('text-lg font-bold')
        for title, path in (
            ('OpenCE executable', OPEN_CE_EXE),
            ('OpenCE config', OPEN_CE_DIR / 'config.toml'),
            ('chasm backend', Path(CHASM_ROOT) / 'target' / 'release' / 'chasm.exe'),
            ('chasm profile', Path(CHASM_ROOT) / 'profiles' / 'opence'),
        ):
            exists = path.exists()
            with ui.row().classes('items-center gap-2'):
                ui.icon('check_circle' if exists else 'cancel').classes(
                    'text-green-400' if exists else 'text-red-400')
                ui.label(title).classes('text-sm text-slate-300 w-40')
                ui.label(str(path)).classes('text-xs text-slate-500 break-all')

        with ui.row().classes('gap-2 items-center flex-wrap mt-2'):
            ui.button('Open OpenCE folder', icon='folder_open',
                      on_click=lambda: _open_folder(OPEN_CE_DIR)).props('flat')
            ui.button('Open chasm folder', icon='folder_open',
                      on_click=lambda: _open_folder(Path(CHASM_ROOT))).props('flat')
            ui.link('Open chasm UI', f'{CHASM_URL}/app', new_tab=True)
            ui.link('chasm health', f'{CHASM_URL}/health', new_tab=True)
            ui.link('connection status', f'{CHASM_URL}/connection/status', new_tab=True)


def _m8_kevin_tab(sm):
    ui.label('m8 - Kevin').classes('text-2xl font-bold')
    ui.label(
        'The demo companion: Laya decides the action, Ollama writes the line, StyleTTS2 voices '
        'it, Whisper hears you, and the m8-patched OpenCE gives Kevin his body.'
    ).classes('text-sm text-slate-400 max-w-3xl')

    tiles = {}
    with ui.card().classes('w-full'):
        with ui.row().classes('w-full items-center justify-between'):
            ui.label('Stack').classes('text-lg font-bold')
            overall = ui.badge('CHECKING').props('outline')
        with ui.row().classes('gap-3 flex-wrap'):
            for key, title in (
                ('laya', 'Laya decision'),
                ('tts', 'StyleTTS2'),
                ('m8tts', 'm8 TTS adapter'),
                ('whisper', 'Whisper STT'),
                ('m8', 'm8 brain'),
                ('game', 'OpenCE (m8)'),
            ):
                with ui.card().classes('bg-slate-800 px-4 py-2 min-w-[160px]'):
                    ui.label(title).classes('text-xs text-slate-400')
                    tiles[key] = ui.label('-').classes('text-lg font-bold text-slate-500')
        with ui.row().classes('gap-3 flex-wrap mt-2'):
            for key, title in (
                ('mic', 'Microphone'),
                ('out', 'Game output'),
                ('model', 'Dialogue model'),
            ):
                with ui.card().classes('bg-slate-800 px-4 py-2 min-w-[220px]'):
                    ui.label(title).classes('text-xs text-slate-400')
                    tiles[key] = ui.label('-').classes('text-sm text-slate-300')

        def mark(key, running):
            tiles[key].text = 'running' if running else 'stopped'
            tiles[key].classes(replace='text-lg font-bold ' + (
                'text-green-400' if running else 'text-slate-500'))

        async def refresh():
            states = {}
            for key, name in (
                ('laya', 'laya'),
                ('tts', 'styletts2'),
                ('m8tts', 'm8_tts'),
                ('whisper', 'whisper'),
                ('m8', 'm8'),
            ):
                states[key] = await sm.is_running(name)
                mark(key, states[key])
            game_running = await asyncio.to_thread(_opence_running)
            mark('game', game_running)

            current = m8_audio_sync.current()
            tiles['mic'].text = current.get('input') or '-'
            tiles['out'].text = current.get('output') or '-'
            tiles['model'].text = current.get('model') or '-'

            ready = all(states.values()) and game_running
            overall.text = 'READY' if ready else 'ATTENTION'
            overall.props['color'] = 'green' if ready else 'orange'

            laya_button.text = 'Stop Laya' if states['laya'] else 'Start Laya'
            tts_button.text = 'Stop StyleTTS2' if states['tts'] else 'Start StyleTTS2'
            m8tts_button.text = 'Stop m8 TTS' if states['m8tts'] else 'Start m8 TTS'
            whisper_button.text = 'Stop Whisper' if states['whisper'] else 'Start Whisper'
            m8_button.text = 'Stop m8' if states['m8'] else 'Start m8'
            game_button.text = 'Stop OpenCE' if game_running else 'Launch OpenCE'

        async def toggle_service(name):
            if await sm.is_running(name):
                sm.stop(name)
            else:
                sm.start(name)
            await asyncio.sleep(1.2)
            await refresh()

        def start_game():
            if not M8_HALO_EXE.exists():
                ui.notify(f'm8 OpenCE not found: {M8_HALO_EXE}', type='negative')
                return
            try:
                subprocess.Popen(
                    [str(M8_HALO_EXE)],
                    cwd=str(M8_HALO_DIR),
                    creationflags=CREATE_NEW_CONSOLE,
                )
                ui.notify('Starting m8 OpenCE')
            except Exception as exc:
                ui.notify(f'Could not start m8 OpenCE: {exc}', type='negative')

        def stop_game():
            subprocess.run(['taskkill', '/F', '/IM', 'halo.exe'], capture_output=True)
            ui.notify('Stopped OpenCE')

        async def toggle_game():
            if await asyncio.to_thread(_opence_running):
                await asyncio.to_thread(stop_game)
            else:
                start_game()
            await asyncio.sleep(1.2)
            await refresh()

        with ui.row().classes('gap-2 items-center flex-wrap mt-3'):
            laya_button = ui.button('Start Laya', icon='play_arrow',
                                    on_click=lambda: toggle_service('laya'))
            tts_button = ui.button('Start StyleTTS2', icon='play_arrow',
                                   on_click=lambda: toggle_service('styletts2'))
            m8tts_button = ui.button('Start m8 TTS', icon='play_arrow',
                                     on_click=lambda: toggle_service('m8_tts'))
            whisper_button = ui.button('Start Whisper', icon='play_arrow',
                                       on_click=lambda: toggle_service('whisper'))
            m8_button = ui.button('Start m8', icon='play_arrow',
                                  on_click=lambda: toggle_service('m8'))
            game_button = ui.button('Launch OpenCE', icon='sports_esports',
                                    on_click=toggle_game)
            ui.button('Refresh', icon='refresh', on_click=refresh).props('flat')

        ui.timer(2.0, refresh, immediate=True)

    with ui.card().classes('w-full'):
        ui.label('Dialogue model').classes('text-lg font-bold')
        model_select = ui.select({}, label='Ollama model', with_input=True).classes('w-full max-w-md')

        async def load_models():
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(f'{OLLAMA_URL}/api/tags')
                names = sorted({model['name'] for model in response.json().get('models', [])})
                model_select.options = {name: name for name in names}
                current = m8_audio_sync.current().get('model')
                model_select.value = current if current in names else (names[0] if names else None)
                ui.notify(f'{len(names)} Ollama model(s)')
            except Exception as exc:
                ui.notify(f'Could not list Ollama models: {exc}', type='negative')

        async def restart_m8():
            sm.stop('m8')
            await asyncio.sleep(1.0)
            sm.start('m8')
            await asyncio.sleep(1.5)
            await refresh()

        def save_model(restart: bool):
            model = model_select.value
            if not model:
                return
            m8_audio_sync.set_section_value(m8_audio_sync.M8_TOML, 'llm', 'model', model)
            ui.notify(f'Saved dialogue model {model}' + (
                '; restarting m8' if restart else '; restart m8 to apply'))
            if restart:
                asyncio.create_task(restart_m8())

        with ui.row().classes('gap-2 items-center flex-wrap'):
            ui.button('Refresh models', icon='refresh', on_click=load_models).props('flat')
            ui.button('Save model', icon='save', on_click=lambda: save_model(False)).props('flat')
            ui.button('Save + restart m8', icon='restart_alt',
                      on_click=lambda: save_model(True))
            ui.timer(0.2, load_models, once=True)

    with ui.card().classes('w-full'):
        ui.label('Audio devices').classes('text-lg font-bold')
        audio_label = ui.label().classes('text-sm text-slate-300')

        def refresh_audio():
            current = m8_audio_sync.current()
            audio_label.text = (f"mic: {current.get('input') or '-'}   |   "
                                f"game out: {current.get('output') or '-'}")

        def apply_audio():
            cfg = settings_store.load_config()
            result = m8_audio_sync.apply(cfg.AUDIO_INPUT_DEVICE, cfg.AUDIO_OUTPUT_DEVICE)
            refresh_audio()
            mic = result['input'].split(' (')[0]
            out = result['output'].split(' (')[0]
            ui.notify(f'm8 mic: {mic}; game out: {out} - restart m8 and OpenCE')
            refresh_audio()

        with ui.row().classes('gap-2 items-center flex-wrap'):
            ui.button('Use Audio tab devices', icon='sync_alt', on_click=apply_audio)
            ui.button('Refresh', icon='refresh', on_click=refresh_audio).props('flat')
        refresh_audio()
        ui.label(
            'The mic goes to m8; the game plays Kevin through the output device. '
            'Restart m8 and OpenCE after changing the Audio tab.'
        ).classes('text-xs text-slate-500')

    with ui.card().classes('w-full'):
        ui.label('Quick start').classes('text-lg font-bold')
        ui.label(
            '1. Laya.   2. StyleTTS2.   3. m8 TTS.   4. Whisper.   5. m8.   '
            '6. Launch OpenCE (m8).   Talk to Kevin with the mic.'
        ).classes('text-sm text-slate-300')
        ui.label(
            'Kev is replaced by Laya: Laya picks do/which/speak, Ollama writes the words, '
            'StyleTTS2 speaks them.'
        ).classes('text-xs text-slate-500 mt-1')
        with ui.row().classes('gap-3 items-center flex-wrap mt-2'):
            ui.link('m8 brain page', 'http://127.0.0.1:8090', new_tab=True)
            ui.link('Laya health', 'http://127.0.0.1:5002/health', new_tab=True)
            ui.link('Whisper health', 'http://127.0.0.1:13310/health', new_tab=True)
            ui.button('Open m8 folder', icon='folder_open',
                      on_click=lambda: _open_folder(Path(M8_ROOT))).props('flat')
