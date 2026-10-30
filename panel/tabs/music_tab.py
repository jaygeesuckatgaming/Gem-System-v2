"""Music tab for the NiceGUI control panel (Music Requests + Music Gen merged).

Music requests: download song, song queue, karaoke library, background music
player (set/stop/pause, progress, volume). Music generation: ComfyUI + YuE2
settings. Settings load from config.py; the operational controls talk to a
running MCP server (which owns the music client).
"""

import asyncio

import httpx
from nicegui import ui

from panel import settings_store

MAIN = settings_store.MAIN_URL


def _fmt_time(seconds):
    seconds = int(seconds)
    return f'{seconds // 60}:{seconds % 60:02d}'


def create(sm):
    cfg = settings_store.load_config()

    ui.label('Music').classes('text-2xl font-bold')
    ui.label('Operational controls (download/queue/library/background) need the MCP server '
             'running; settings load from config.py.').classes('text-sm text-slate-400')

    # ------------------------------------------------------------ download song
    with ui.card().classes('w-full'):
        ui.label('Download Song').classes('text-lg font-bold')
        dl_status = ui.label('Status: idle').classes('text-xs text-slate-400')
        with ui.row().classes('w-full items-center gap-2'):
            dl_input = ui.input(placeholder='Song name or YouTube URL').classes('grow')
            dl_btn = ui.button('Download', icon='download')

        async def download():
            query = (dl_input.value or '').strip()
            if not query:
                return
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.post(f'{MAIN}/api/music/download', json={'query': query})
                if r.status_code == 200:
                    dl_status.text = f"Downloading '{query}'..."
                    dl_input.value = ''
                else:
                    dl_status.text = f'Download failed: {r.text[:120]}'
            except Exception:
                dl_status.text = 'MCP server not running'
        dl_btn.on_click(download)

    # ------------------------------------------------------------ song queue
    with ui.card().classes('w-full'):
        with ui.row().classes('w-full justify-between items-center'):
            ui.label('Song Queue').classes('text-lg font-bold')
            with ui.row().classes('gap-2'):
                ui.button('Refresh', icon='refresh', on_click=lambda: refresh_queue()).props('flat')
                ui.button('Clear', icon='delete', on_click=lambda: clear_queue()).props('flat')
        queue_box = ui.textarea().classes('w-full h-32').props('readonly outlined')

        async def refresh_queue():
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    r = await client.get(f'{MAIN}/api/music/queue')
                if r.status_code == 200:
                    q = r.json().get('queue', [])
                    queue_box.value = '\n'.join(f'{i}. {s}' for i, s in enumerate(q, 1)) \
                        if q else 'Queue is empty'
            except Exception:
                queue_box.value = '(MCP server not running)'

        async def clear_queue():
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.delete(f'{MAIN}/api/music/queue')
                await refresh_queue()
            except Exception:
                pass
        ui.timer(5.0, refresh_queue, immediate=True)

    # ------------------------------------------------------------ library
    with ui.card().classes('w-full'):
        ui.label('Song Library (Karaoke)').classes('text-lg font-bold')
        lib_status = ui.label('').classes('text-xs text-slate-400')
        with ui.row().classes('w-full items-center gap-2'):
            lib_select = ui.select([], with_input=True).classes('grow')
            ui.button('Refresh', icon='refresh', on_click=lambda: refresh_library()).props('flat')
            play_btn = ui.button('Play', icon='play_arrow')

        async def refresh_library():
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    r = await client.get(f'{MAIN}/api/music/songs')
                songs = r.json().get('songs', []) if r.status_code == 200 else []
                lib_select.options = songs
                if songs and not lib_select.value:
                    lib_select.value = songs[0]
                lib_status.text = f'{len(songs)} song(s)' if songs else 'No songs in library'
                lib_status.classes(replace='text-xs ' + ('text-green-400' if songs else 'text-slate-400'))
            except Exception:
                lib_status.text = 'MCP server not running'
                lib_status.classes(replace='text-xs text-red-400')

        async def play_selected():
            song = lib_select.value
            if not song:
                return
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    r = await client.post(f'{MAIN}/api/music/play', json={'song': song})
                ui.notify(f'Playing: {song}' if r.status_code == 200 else 'Play failed')
            except Exception:
                ui.notify('MCP server not running', type='negative')
        play_btn.on_click(play_selected)
        ui.timer(10.0, refresh_library, immediate=True)

    # ------------------------------------------------------------ background music
    with ui.card().classes('w-full'):
        ui.label('Background Music').classes('text-lg font-bold')
        bg_status = ui.label('Background: None').classes('text-xs text-slate-400')
        with ui.row().classes('w-full items-center gap-2'):
            bg_select = ui.select(['No background songs'], value='No background songs',
                                  with_input=True).classes('grow')
            ui.button('Refresh', icon='refresh', on_click=lambda: refresh_bg()).props('flat')
            set_btn = ui.button('Set', icon='music_note').props('flat')
            ui.button('Stop', icon='stop', on_click=lambda: stop_bg()).props('flat')

        pause_btn = ui.button('Pause', icon='pause').props('flat')
        progress = ui.linear_progress(value=0.0, show_value=False).classes('w-full')
        time_label = ui.label('0:00 / 0:00').classes('text-xs text-slate-400')
        with ui.row().classes('w-full items-center gap-3'):
            ui.label('Volume').classes('w-16 text-sm')
            volume_slider = ui.slider(min=0.0, max=1.0, step=0.05,
                                      value=float(cfg.BACKGROUND_VOLUME)).classes('grow')
            volume_label = ui.label(f'{float(cfg.BACKGROUND_VOLUME):.2f}').classes('w-10 text-xs text-slate-400')

        async def refresh_bg():
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    r = await client.get(f'{MAIN}/api/music/background')
                d = r.json() if r.status_code == 200 else {}
                songs = d.get('songs', [])
                current = d.get('current')
                bg_select.options = songs if songs else ['No background songs']
                bg_select.value = current if current in (songs or []) else (songs[0] if songs else 'No background songs')
                bg_status.text = f'Background: {current}' if current else 'Background: None'
                bg_status.classes(replace='text-xs text-slate-400')
            except Exception:
                bg_status.text = 'MCP server not running'
                bg_status.classes(replace='text-xs text-red-400')

        async def set_bg():
            song = bg_select.value
            if not song or song == 'No background songs':
                return
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    r = await client.post(f'{MAIN}/api/music/background', json={'song': song})
                if r.status_code == 200:
                    bg_status.text = f'Background: {song}'
            except Exception:
                ui.notify('MCP server not running', type='negative')
        set_btn.on_click(set_bg)

        async def stop_bg():
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.post(f'{MAIN}/api/music/background/stop')
                bg_status.text = 'Background: None'
            except Exception:
                pass

        async def toggle_pause():
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    r = await client.post(f'{MAIN}/api/music/background/pause',
                                          json={} if pause_btn.text == 'Pause' else {'resume': True})
                if r.status_code == 200:
                    pause_btn.text = 'Resume' if pause_btn.text == 'Pause' else 'Pause'
            except Exception:
                pass
        pause_btn.on_click(toggle_pause)

        def on_volume(e):
            volume_label.set_text(f'{e.value:.2f}')
            try:
                httpx.post(f'{MAIN}/api/music/background/volume',
                           json={'volume': e.value}, timeout=3.0)
            except Exception:
                pass
        volume_slider.on_value_change(on_volume)

        async def poll_progress():
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    r = await client.get(f'{MAIN}/api/music/background/status')
                d = r.json() if r.status_code == 200 else {}
                pos, dur, paused = d.get('position', 0), d.get('duration', 0), d.get('paused', False)
                progress.value = min(1.0, pos / dur) if dur > 0 else 0.0
                time_label.text = f'{_fmt_time(pos)} / {_fmt_time(dur)}'
                pause_btn.text = 'Resume' if paused else 'Pause'
            except Exception:
                pass
        ui.timer(0.5, poll_progress)
        ui.timer(15.0, refresh_bg, immediate=True)

    # ------------------------------------------------------------ music gen
    with ui.card().classes('w-full'):
        ui.label('Music Generation (ComfyUI + YuE2)').classes('text-lg font-bold')
        gen_enabled = ui.switch('Enable music generation', value=cfg.MUSIC_GEN_ENABLED)
        gen_url = ui.input('ComfyUI URL', value=cfg.MUSIC_GEN_COMFYUI_URL).classes('w-full')
        gen_workflow = ui.input('Workflow file', value=cfg.MUSIC_GEN_WORKFLOW_FILE).classes('w-full')
        gen_node = ui.input('Text node ID', value=cfg.MUSIC_GEN_TEXT_NODE_ID).classes('w-full')

    # ------------------------------------------------------------------ save
    async def save():
        values = {
            'BACKGROUND_VOLUME': round(float(volume_slider.value), 2),
            'MUSIC_GEN_ENABLED': gen_enabled.value,
            'MUSIC_GEN_COMFYUI_URL': gen_url.value.strip(),
            'MUSIC_GEN_WORKFLOW_FILE': gen_workflow.value.strip(),
            'MUSIC_GEN_TEXT_NODE_ID': gen_node.value.strip(),
        }
        file_ok, pushed = await asyncio.to_thread(settings_store.save, values)
        ui.notify(f'Saved (pushed live to: {", ".join(pushed) or "no running services"})',
                  type='positive' if file_ok else 'negative')
    ui.button('Save music settings', icon='save', on_click=save).classes('mt-2')