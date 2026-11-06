"""Games tab for the NiceGUI control panel.

Controls the optional Gem Drive process (chat-driven 3D highway, port 5010):
start/stop, live state + leaderboard, streamer controls (pause/reset/spawn/
crash), and the GAME_DRIVE_* settings.
"""

import asyncio
import os
import subprocess
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx
import psutil
from nicegui import ui

from drive_game import assets
from panel import m8_audio_sync, settings_store
from panel.service_manager import M8_ROOT

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODELS_DIR = PROJECT_ROOT / "models" / "cars"
PLAYERS_DIR = MODELS_DIR / "players"

OLLAMA_URL = os.environ.get('OLLAMA_URL', 'http://127.0.0.1:11434').rstrip('/')
CREATE_NEW_CONSOLE = 0x00000010

# The Half-Life m8 mod (hlsdk-mate) and the game it lives in.
HLSDK_ROOT = Path("C:/Users/jayge/Documents/AI/m8_games/hlsdk-portable")
HALF_LIFE_ROOT = Path("C:/Program Files (x86)/Steam/steamapps/common/Half-Life")
HL_MOD_ROOT = HALF_LIFE_ROOT / "hlm8"
HL_MODEL_OPTIONS = {
    "models/barney.mdl": "Barney (security guard)",
    "models/scientist.mdl": "Scientist",
    "models/hgrunt.mdl": "HECU grunt",
    "models/gman.mdl": "G-Man",
}

# m8's own OpenCE patch (the Gem companion).
M8_HALO_DIR = Path(M8_ROOT).parent / 'OpenCE' / 'build' / 'windows'
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

    # m8 TTS (the Breeze-API bridge to StyleTTS2) and the m8 brain, as buttons
    # beside the game launch controls
    with ui.row().classes('gap-2 items-center flex-wrap'):
        ui.label('m8 companion:').classes('text-sm text-slate-400')
        m8tts_btn = ui.button('Start m8 TTS adapter', icon='play_arrow',
                              on_click=lambda: toggle_m8_service('m8_tts'))
        m8_btn = ui.button('Start m8', icon='play_arrow',
                           on_click=lambda: toggle_m8_service('m8'))

    async def toggle_m8_service(name):
        if await sm.is_running(name):
            sm.stop(name)
        else:
            sm.start(name)
        await asyncio.sleep(1.0)
        await refresh_m8_services()

    async def refresh_m8_services():
        m8tts_running = await sm.is_running('m8_tts')
        m8_running = await sm.is_running('m8')
        m8tts_btn.text = 'Stop m8 TTS adapter' if m8tts_running else 'Start m8 TTS adapter'
        m8_btn.text = 'Stop m8' if m8_running else 'Start m8'

    ui.timer(3.0, refresh_m8_services, immediate=True)

    with ui.tabs().classes('w-full').props('mobile-arrows no-caps') as tabs:
        drive_tab = ui.tab('Gem Drive')
        iso_tab = ui.tab('Isometric Game')
        gem_tab = ui.tab(f'm8 - {m8_audio_sync.companion_name()}')
        hl_tab = ui.tab('Half-Life')
    with ui.tab_panels(tabs, value=gem_tab).classes('w-full'):
        with ui.tab_panel(drive_tab):
            _gem_drive_tab(sm)
        with ui.tab_panel(iso_tab):
            _iso_game_tab(sm, settings_store.load_config())
        with ui.tab_panel(gem_tab):
            _m8_gem_tab(sm)
        with ui.tab_panel(hl_tab):
            _halflife_tab(sm)


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

    def mark_offline():
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

    async def drive_up() -> bool:
        parsed = urlparse(game_url)
        host = parsed.hostname or '127.0.0.1'
        port = parsed.port or 80
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=0.3)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return True
        except Exception:
            return False

    async def refresh_state():
        # Gem Drive is optional: don't poll (or log) while it is stopped
        if not await drive_up():
            mark_offline()
            return

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
            mark_offline()

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


def _m8_gem_tab(sm):
    companion = m8_audio_sync.companion_name()
    ui.label(f'm8 - {companion}').classes('text-2xl font-bold')
    ui.label(
        'The demo companion: Laya decides the action, Ollama writes the line, StyleTTS2 voices '
        f'it, Whisper hears you, and the m8-patched OpenCE gives {companion} their body.'
    ).classes('text-sm text-slate-400 max-w-3xl')

    # -------------------------------------------------------------- mic routing
    cfg = settings_store.load_config()
    stt_url = getattr(cfg, 'STT_SERVER_URL', 'http://127.0.0.1:13310').rstrip('/')
    current_route = str(getattr(cfg, 'MIC_ROUTE', 'gem')).lower()
    with ui.card().classes('w-full'):
        ui.label('Mic routing').classes('text-lg font-bold')
        ui.label(
            'One shared Whisper server hears the microphone. This picks who receives the '
            'transcripts: Gem System (chat) or the m8 adapter (OpenCE). The other side gets '
            'empty text and stays quiet — switch back instantly, no restarts.'
        ).classes('text-sm text-slate-400 max-w-3xl')
        route_toggle = ui.toggle(
            {'gem': 'Gem System', 'm8': f'm8 Adapter ({companion})'},
            value=current_route if current_route in ('gem', 'm8') else 'gem',
        )
        route_status = ui.label('').classes('text-sm text-slate-400')

        async def refresh_route():
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    response = await client.get(f'{stt_url}/health')
                live = response.json().get('route', '?')
                route_status.text = f'Whisper {stt_url}: up · live route: {live}'
                route_status.classes(replace='text-sm text-green-400')
            except Exception:
                route_status.text = f'Whisper {stt_url}: unreachable (start it above)'
                route_status.classes(replace='text-sm text-orange-400')

        async def save_route():
            value = route_toggle.value or 'gem'
            file_ok, _pushed = await asyncio.to_thread(settings_store.save, {'MIC_ROUTE': value})
            live_ok = False
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.post(f'{stt_url}/route', json={'route': value})
                live_ok = response.status_code == 200
            except Exception:
                pass
            target = 'Gem System' if value == 'gem' else f'the m8 adapter ({companion})'
            ui.notify(
                f'Microphone now goes to {target}'
                + ('' if live_ok else ' · Whisper not running; applies when it starts'),
                type='positive' if file_ok else 'negative',
            )
            await refresh_route()

        ui.button('Apply mic routing', icon='swap_horiz', on_click=save_route)
        ui.timer(5.0, refresh_route, immediate=True)

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
                ('whisper', 'Whisper (shared)'),
                ('stt', 'Gem mic listener'),
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
                ('vision', 'Vision model'),
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
                ('stt', 'stt'),
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
            tiles['vision'].text = (current.get('vision') or current.get('model') or '-')

            ready = all(states.values()) and game_running
            overall.text = 'READY' if ready else 'ATTENTION'
            overall.props['color'] = 'green' if ready else 'orange'

            laya_button.text = 'Stop Laya' if states['laya'] else 'Start Laya'
            tts_button.text = 'Stop StyleTTS2' if states['tts'] else 'Start StyleTTS2'
            whisper_button.text = ('Stop Whisper' if states['whisper']
                                   else 'Start Whisper (shared)')
            listener_button.text = ('Stop mic listener' if states['stt']
                                    else 'Start Gem mic listener')
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
            whisper_button = ui.button('Start Whisper (shared)', icon='graphic_eq',
                                       on_click=lambda: toggle_service('whisper'))
            listener_button = ui.button('Start Gem mic listener', icon='mic',
                                        on_click=lambda: toggle_service('stt'))
            game_button = ui.button('Launch OpenCE', icon='sports_esports',
                                    on_click=toggle_game)
            ui.button('Refresh', icon='refresh', on_click=refresh).props('flat')

        ui.timer(2.0, refresh, immediate=True)

    with ui.card().classes('w-full'):
        ui.label('Companion').classes('text-lg font-bold')
        name_input = ui.input('Name', value=companion).classes('w-full max-w-md')
        ui.label(
            'Written to m8.toml [mate] name (the prompts and the voice) and the game\'s '
            'config.toml [companion] name (the words in its state and events). '
            'Restart m8 and OpenCE to apply.'
        ).classes('text-xs text-slate-500')

        def save_name():
            result = m8_audio_sync.set_companion_name(name_input.value)
            name_input.value = result['name']
            ui.notify(f'Saved {result["name"]}; restart m8 and OpenCE to apply')

        ui.button('Save name', icon='save', on_click=save_name).props('flat')

    with ui.card().classes('w-full'):
        ui.label('Models').classes('text-lg font-bold')

        def base_from_url(url: str) -> str:
            url = (url or '').strip().rstrip('/')
            for suffix in ('/v1/chat/completions', '/chat/completions', '/v1'):
                if url.endswith(suffix):
                    return url[: -len(suffix)]
            return url or OLLAMA_URL

        base_input = ui.input(
            'Ollama base URL',
            value=base_from_url(m8_audio_sync.current().get('url', '')),
        ).classes('w-full max-w-md')
        ui.label(
            'm8 calls <base>/v1/chat/completions; the model list uses <base>/api/tags.'
        ).classes('text-xs text-slate-500')

        model_select = ui.select({}, label='Dialogue model', with_input=True).classes('w-full max-w-md')
        vision_select = ui.select(
            {'': '(same as dialogue)'},
            label='Vision model for look (needs image support)',
            with_input=True,
        ).classes('w-full max-w-md')
        ui.label(
            'The vision model is used only for Gem’s look; blank falls back to the dialogue model.'
        ).classes('text-xs text-slate-500')

        reply_input = ui.number(
            'Reply length (tokens)',
            value=float(m8_audio_sync.current().get('max_tokens') or 200),
            min=20, max=1000, step=10,
        ).classes('w-full max-w-md')
        ui.label(
            'The longest a spoken line may get (about 3-4 characters a token). Too low cuts '
            'the voice off mid-word; 200 is a long paragraph. Restart m8 to apply.'
        ).classes('text-xs text-slate-500')

        async def load_models():
            base = base_from_url(base_input.value)
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(f'{base}/api/tags')
                names = sorted({model['name'] for model in response.json().get('models', [])})
                model_select.options = {name: name for name in names}
                vision_select.options = {'': '(same as dialogue)', **{name: name for name in names}}
                current = m8_audio_sync.current()
                dialogue = current.get('model')
                vision = current.get('vision') or ''
                model_select.value = dialogue if dialogue in names else (names[0] if names else None)
                vision_select.value = vision if vision in names else ''
                ui.notify(f'{len(names)} Ollama model(s)')
            except Exception as exc:
                ui.notify(f'Could not list Ollama models: {exc}', type='negative')

        async def restart_m8():
            # (runs as a background task: no UI updates here; the refresh timer does that)
            sm.stop('m8')
            await asyncio.sleep(1.0)
            sm.start('m8')

        async def save_model(restart: bool):
            dialogue = model_select.value
            vision = vision_select.value or ''
            base = base_from_url(base_input.value)
            if not dialogue:
                return
            m8_audio_sync.set_section_value(m8_audio_sync.M8_TOML, 'llm', 'url',
                                            f'{base}/v1/chat/completions')
            m8_audio_sync.set_section_value(m8_audio_sync.M8_TOML, 'llm', 'model', dialogue)
            m8_audio_sync.set_section_value(m8_audio_sync.M8_TOML, 'llm', 'vision_model', vision)
            reply_tokens = max(20, min(1000, int(reply_input.value or 200)))
            m8_audio_sync.set_section_literal(m8_audio_sync.M8_TOML, 'llm', 'max_tokens',
                                              str(reply_tokens))
            detail = f'vision {vision}' if vision else 'vision uses the dialogue model'
            ui.notify(f'Saved {base} · dialogue {dialogue} · reply ≤{reply_tokens} tokens; {detail}' + (
                '; restarting m8' if restart else '; restart m8 to apply'))
            if restart:
                await restart_m8()

        async def save_models_only():
            await save_model(False)

        async def save_models_restart():
            await save_model(True)

        with ui.row().classes('gap-2 items-center flex-wrap'):
            ui.button('Refresh models', icon='refresh', on_click=load_models).props('flat')
            ui.button('Save models', icon='save', on_click=save_models_only).props('flat')
            ui.button('Save + restart m8', icon='restart_alt',
                      on_click=save_models_restart)
            ui.timer(0.2, load_models, once=True)

    with ui.card().classes('w-full'):
        ui.label('Memory').classes('text-lg font-bold')
        memory = m8_audio_sync.memory_settings()
        memory_status = ui.label('Cognee: checking…').classes('text-sm text-slate-400')
        source = memory['source']
        ui.label(
            'm8 writes each play session to the same Cognee memory the stream uses '
            f'(entries read "[{source}] Gem: …"), and recalls past sessions at the '
            'start of a game. Restart m8 to apply a change.'
        ).classes('text-xs text-slate-500')
        memory_switch = ui.switch('Remember play sessions', value=memory['enabled'])
        memory_hits = ui.label('').classes('text-xs text-slate-400 whitespace-pre-wrap')

        async def check_memory():
            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    response = await client.get(f"{memory['url'].rstrip('/')}/health")
                ok = response.status_code == 200
                memory_status.text = f"Cognee: {response.status_code}"
                memory_status.classes(replace='text-sm ' + (
                    'text-green-400' if ok else 'text-orange-400'))
            except Exception:
                memory_status.text = f"Cognee: unreachable ({memory['url']})"
                memory_status.classes(replace='text-sm text-red-400')

        def save_memory():
            result = m8_audio_sync.set_memory_enabled(bool(memory_switch.value))
            ui.notify(('Memory on' if result['enabled'] else 'Memory off')
                      + '; restart m8 to apply')

        async def test_recall():
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        f"{memory['url'].rstrip('/')}/recall",
                        json={'query': 'Gem played Halo', 'top_k': 5},
                    )
                results = response.json().get('results', [])
            except Exception as exc:
                ui.notify(f'Recall failed: {exc}', type='negative')
                return
            ui.notify(f'{len(results)} memory line(s)')
            memory_hits.text = ('\n'.join(f'• {item}' for item in results[:4])
                                if results else '(nothing about Halo yet)')

        with ui.row().classes('gap-2 items-center flex-wrap'):
            ui.button('Check Cognee', icon='refresh', on_click=check_memory).props('flat')
            ui.button('Save', icon='save', on_click=save_memory).props('flat')
            ui.button('Test recall', icon='search', on_click=test_recall).props('flat')
        ui.timer(8.0, check_memory, immediate=True)

    with ui.card().classes('w-full'):
        with ui.row().classes('w-full items-center justify-between'):
            ui.label("Gem's eyes").classes('text-lg font-bold')
            ui.link('open in a new tab', 'http://127.0.0.1:8090/eyes', new_tab=True)
        ui.element('iframe').props(
            'src="http://127.0.0.1:8090/eyes" sandbox="allow-same-origin allow-scripts"'
        ).classes('w-full h-[260px] rounded-lg border-0 bg-slate-950')
        ui.label(
            "Live: the player's view as the vision model gets it, about once a second "
            '(m8 page :8090). Add http://127.0.0.1:8090/eyes to OBS as a Browser Source.'
        ).classes('text-xs text-slate-500')

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
            'The mic goes to m8; the game plays Gem through the output device. '
            'Restart m8 and OpenCE after changing the Audio tab.'
        ).classes('text-xs text-slate-500')

    with ui.card().classes('w-full'):
        with ui.row().classes('w-full items-center justify-between'):
            ui.label('m8 control panel').classes('text-lg font-bold')
            ui.link('open in a new tab', 'http://127.0.0.1:8090', new_tab=True)
        ui.element('iframe').props(
            'src="http://127.0.0.1:8090/" '
            'sandbox="allow-same-origin allow-scripts allow-popups allow-forms allow-top-navigation"'
        ).classes('w-full h-[70vh] rounded-lg border-0 bg-slate-950')

    with ui.card().classes('w-full'):
        ui.label('Quick start').classes('text-lg font-bold')
        for number, step in enumerate((
            'Ollama must be up at the base URL on the Models card — the panel does not start it.',
            'Laya (decisions) — Start Laya above.',
            'StyleTTS2 (voice engine) — Start StyleTTS2 above.',
            'm8 TTS adapter (Games toolbar) — start it before m8: m8 reads its sample rate '
            'when it starts.',
            'Whisper (shared) — start it once above. Gem\'s mic listener and the companion '
            'both use this one server.',
            'm8 (Games toolbar).',
            'Set Mic routing to m8 Adapter, then Launch OpenCE above and just talk: only the '
            'companion hears you. Switch it back to Gem System to talk to Gem again.',
        ), 1):
            ui.label(f'{number}. {step}').classes('text-sm text-slate-300')
        ui.label(
            f'Laya picks do/which/speak, Ollama writes what {companion} says, StyleTTS2 voices it, '
            'one shared Whisper hears you, and OpenCE (with m8\'s patch) gives them a body. '
            'Cognee (Memory tab) is optional: it stores each play session and what they remember.'
        ).classes('text-xs text-slate-500 mt-1')
        with ui.row().classes('gap-3 items-center flex-wrap mt-2'):
            ui.link('m8 brain page', 'http://127.0.0.1:8090', new_tab=True)
            ui.link('Laya health', 'http://127.0.0.1:5002/health', new_tab=True)
            ui.link('Whisper health', 'http://127.0.0.1:13310/health', new_tab=True)
            ui.link('Cognee health', f"{m8_audio_sync.memory_settings()['url'].rstrip('/')}/health",
                    new_tab=True)
            ui.button('Open m8 folder', icon='folder_open',
                      on_click=lambda: _open_folder(Path(M8_ROOT))).props('flat')


def _run_hl_bat(name: str):
    path = HLSDK_ROOT / name
    if not path.exists():
        ui.notify(f'Missing {path}', type='negative')
        return
    subprocess.Popen(['cmd', '/c', str(path)], cwd=str(HLSDK_ROOT),
                     creationflags=CREATE_NEW_CONSOLE)


def _stop_hl():
    subprocess.run(['taskkill', '/IM', 'hl.exe', '/F'], capture_output=True)
    ui.notify('Half-Life stopped')


def _halflife_tab(sm):
    ui.label('Half-Life').classes('text-2xl font-bold')
    ui.label(
        'The m8 companion in GoldSrc: the hlsdk-mate mod (a follower that talks, follows and '
        'fights), beside the m8 brain.'
    ).classes('text-sm text-slate-400 max-w-3xl')

    with ui.card().classes('w-full'):
        ui.label('Status').classes('text-lg font-bold')
        with ui.row().classes('gap-6 items-center flex-wrap'):
            hl_status = ui.label('Half-Life: …').classes('text-sm text-slate-300')
            mod_status = ui.label('Mod: …').classes('text-sm text-slate-300')
            link_status = ui.label('m8 link: …').classes('text-sm text-slate-300')
        with ui.row().classes('gap-2 items-center flex-wrap mt-1'):
            ui.button('Build', icon='build',
                      on_click=lambda: _run_hl_bat('build_hlm8.bat')).props('flat')
            ui.button('Install', icon='download',
                      on_click=lambda: _run_hl_bat('install_hlm8.bat')).props('flat')
            ui.button('Launch Half-Life', icon='play_arrow',
                      on_click=lambda: _run_hl_bat('start_hlm8.bat'))
            ui.button('Stop', icon='stop', on_click=_stop_hl).props('flat')
            ui.button('Open mod folder', icon='folder_open',
                      on_click=lambda: os.startfile(HL_MOD_ROOT)).props('flat')

    with ui.card().classes('w-full'):
        ui.label('Companion').classes('text-lg font-bold')
        companion_state = ui.label('Not connected.').classes('text-sm text-slate-300 max-w-3xl')
        companion_actions = ui.label('').classes('text-xs text-slate-500')
        ui.label(
            'Say "Gem, stay here", "Gem, follow me" or "Gem, attack" on the mic. '
            'm8 needs to run, and the m8 TTS adapter before it.'
        ).classes('text-xs text-slate-500 mt-1')
        with ui.row().classes('gap-3 items-center flex-wrap mt-1'):
            ui.link('m8 brain page', 'http://127.0.0.1:8090', new_tab=True)
            ui.link("Gem's eyes", 'http://127.0.0.1:8090/eyes', new_tab=True)

    with ui.card().classes('w-full'):
        ui.label('Companion model').classes('text-lg font-bold')

        def current_model():
            try:
                text = (HL_MOD_ROOT / 'mate_model.txt').read_text(encoding='utf-8').strip()
                return text or 'models/barney.mdl'
            except Exception:
                return 'models/barney.mdl'

        def apply_model():
            model = (model_input.value or 'models/barney.mdl').strip()
            try:
                HL_MOD_ROOT.mkdir(parents=True, exist_ok=True)
                (HL_MOD_ROOT / 'mate_model.txt').write_text(model + '\n', encoding='utf-8')
                (HL_MOD_ROOT / 'mate_respawn.txt').write_text(str(time.time()), encoding='utf-8')
                ui.notify(f'Model set to {model}')
            except Exception as exc:
                ui.notify(f'Could not save: {exc}', type='negative')

        def model_choices():
            choices = dict(HL_MODEL_OPTIONS)
            models = HL_MOD_ROOT / 'models'
            try:
                for path in sorted(models.glob('*.mdl')):
                    stem = path.stem
                    if stem.lower().endswith(('01', '02', '03', '04', 't')):
                        continue
                    choices[f'models/{path.name}'] = f'{stem} (mod)'
            except Exception:
                pass
            if (models / 'Barniel.mdl').exists():
                choices['models/Barniel.mdl'] = 'Barniel (female Barney)'
            current = current_model()
            if current not in choices:
                choices[current] = f'{current} (custom)'
            return choices

        model_input = ui.input('Model path', value=current_model()).classes('w-full max-w-md')
        model_options = model_choices()
        with ui.row().classes('gap-2 items-center flex-wrap'):
            ui.select(model_options, label='Built-in',
                      on_change=lambda e: setattr(model_input, 'value', e.value) if e.value else None
                      ).classes('w-64')
            ui.button('Apply model', icon='check', on_click=apply_model)
        ui.label(
            'Pick an installed NPC body (Barniel is the female Barney) or type another NPC model '
            'path. Apply respawns her with it; a newly added custom model needs the map reloaded '
            'once, because precaching happens at map load.'
        ).classes('text-xs text-slate-500')

    with ui.card().classes('w-full'):
        ui.label('Voice output (in-game)').classes('text-lg font-bold')

        def output_names():
            try:
                import sounddevice as sd
                return [d['name'] for d in sd.query_devices() if d['max_output_channels'] > 0]
            except Exception:
                return []

        def current_device():
            try:
                return (HL_MOD_ROOT / 'mate_audio_device.txt').read_text(encoding='utf-8').strip()
            except Exception:
                return ''

        def apply_device():
            name = (device_input.value or '').strip()
            try:
                HL_MOD_ROOT.mkdir(parents=True, exist_ok=True)
                (HL_MOD_ROOT / 'mate_audio_device.txt').write_text(name + '\n', encoding='utf-8')
                ui.notify(f'In-game voice: {name or "system default"}')
            except Exception as exc:
                ui.notify(f'Could not save: {exc}', type='negative')

        options = {'': 'System default'}
        for name in output_names():
            options[name] = name
        device_input = ui.input('Device (or part of its name)', value=current_device()).classes('w-full max-w-md')
        with ui.row().classes('gap-2 items-center flex-wrap'):
            ui.select(options, label='Device',
                      on_change=lambda e: setattr(device_input, 'value', e.value) if e.value is not None else None
                      ).classes('w-72')
            ui.button('Apply device', icon='check', on_click=apply_device)
        ui.label(
            'The game plays Gem through waveOut; it applies to the next line. Names match as a '
            'substring, so "Voicemeeter AUX" is enough. Empty means the system default.'
        ).classes('text-xs text-slate-500')

    with ui.card().classes('w-full'):
        ui.label('Game audio output').classes('text-lg font-bold')

        def game_device():
            try:
                text = (HL_MOD_ROOT / 'config.cfg').read_text(encoding='utf-8', errors='replace')
            except Exception:
                return ''
            import re
            found = re.search(r'^\s*snd_device\s+"([^"]*)"', text, re.M)
            return found.group(1) if found else ''

        def set_game_device(name):
            path = HL_MOD_ROOT / 'config.cfg'
            try:
                lines = (path.read_text(encoding='utf-8', errors='replace').splitlines()
                         if path.exists() else [])
            except Exception:
                lines = []
            line = (f'snd_device "{name}"'
                    if name and name.lower() != 'default' else 'snd_device "Default"')
            for index, existing in enumerate(lines):
                if existing.strip().startswith('snd_device'):
                    lines[index] = line
                    break
            else:
                lines.append(line)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('\n'.join(lines) + '\n', encoding='utf-8')

        def apply_game_device():
            name = (game_input.value or '').strip()
            try:
                set_game_device(name)
                ui.notify(f'Game audio: {name or "Default"}; restart Half-Life')
            except Exception as exc:
                ui.notify(f'Could not save: {exc}', type='negative')

        game_options = {'': 'System default'}
        for name in output_names():
            game_options[name] = name
        game_input = ui.input('Sound device (exact name)', value=game_device()).classes('w-full max-w-md')
        with ui.row().classes('gap-2 items-center flex-wrap'):
            ui.select(game_options, label='Device',
                      on_change=lambda e: setattr(game_input, 'value', e.value) if e.value is not None else None
                      ).classes('w-72')
            ui.button('Apply game audio', icon='check', on_click=apply_game_device)
        ui.label(
            "This is the engine's own sound (gunfire, ambience), written to hlm8/config.cfg as "
            'snd_device. It needs Half-Life restarted, and the exact device name.'
        ).classes('text-xs text-slate-500')

    async def refresh():
        try:
            running = any((process.info.get('name') or '').lower() == 'hl.exe'
                          for process in psutil.process_iter(['name']))
        except Exception:
            running = False
        hl_status.text = 'Half-Life: running' if running else 'Half-Life: stopped'
        hl_status.classes(replace='text-sm ' +
                          ('text-green-400' if running else 'text-slate-300'))

        installed_dll = HL_MOD_ROOT / 'dlls' / 'hl.dll'
        installed_client = HL_MOD_ROOT / 'cl_dlls' / 'client.dll'
        built_dll = HLSDK_ROOT / 'build' / 'dlls' / 'Release' / 'hl.dll'
        if installed_dll.exists() and installed_client.exists():
            installed_at = min(installed_dll.stat().st_mtime, installed_client.stat().st_mtime)
            when = time.strftime('%Y-%m-%d %H:%M', time.localtime(installed_at))
            stale = built_dll.exists() and built_dll.stat().st_mtime > installed_at
            mod_status.text = f'Mod: installed {when}' + (' · newer build, install it' if stale else '')
            mod_status.classes(replace='text-sm ' +
                               ('text-amber-300' if stale else 'text-green-400'))
        else:
            mod_status.text = 'Mod: not installed'
            mod_status.classes(replace='text-sm text-red-400')

        state = {}
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                trace = (await client.get('http://127.0.0.1:8090/trace?since=0')).json()
            state = trace.get('state') or {}
        except Exception:
            state = {}
        if state.get('game') == 'Half-Life':
            link_status.text = f"m8 link: {state.get('level', '?')}"
            link_status.classes(replace='text-sm text-green-400')
            companion_state.text = state.get('state') or ''
            names = [action.get('name', '') for action in state.get('actions', [])]
            companion_actions.text = ('Actions offered: ' + ', '.join(names)) if names else ''
        else:
            link_status.text = 'm8 link: no Half-Life state'
            link_status.classes(replace='text-sm text-slate-400')
            companion_state.text = 'Launch Half-Life above, with m8 running.'
            companion_actions.text = ''

    ui.timer(3.0, refresh, immediate=True)
