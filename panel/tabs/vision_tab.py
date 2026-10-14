"""Vision tab for the NiceGUI control panel.

Mirrors the tkinter Vision tab (plus live-updating settings): camera/NDI
source picker, camera preview with drag-to-select face area (SVG overlay,
zero flicker), face enrollment with region restriction, Scan Now with deep
fallback, enrolled people table with per-row delete, and every vision/face
setting — saved to config.py and pushed live to running services.
"""

import asyncio
import base64
import io

import httpx
from nicegui import ui
from PIL import Image

from panel import settings_store

VISION_URL = settings_store.VISION_URL


def create(sm):
    cfg = settings_store.load_config()

    # ------------------------------------------------------------------ header
    ui.label('Vision').classes('text-2xl font-bold')
    vision_status = ui.label().classes('text-sm text-slate-400')

    async def refresh_status():
        running = await sm.is_running('vision')
        vision_status.text = '● Running' if running else '● Stopped — use the Start button in the top bar'
        vision_status.classes(replace='text-sm ' + ('text-green-400' if running else 'text-slate-400'))
    ui.timer(3.0, refresh_status, immediate=True)

    # ------------------------------------------------------- settings section
    with ui.card().classes('w-full'):
        ui.label('Vision Settings').classes('text-lg font-bold')

        with ui.row().classes('w-full gap-6 items-start flex-wrap'):
            with ui.column().classes('gap-2 min-w-[280px] grow'):
                ui.label('Image source').classes('text-xs text-slate-400')
                src_toggle = ui.toggle({'cam': 'Camera', 'ndi': 'NDI'}, value=cfg.VISION_IMAGE_SOURCE)

                with ui.row().classes('items-center gap-2 w-full'):
                    camera_input = ui.number('Camera index', value=cfg.VISION_CAMERA_INDEX,
                                             step=1, min=0, max=9)
                    camera_result = ui.label().classes('text-xs text-slate-400')

                    async def scan_cameras():
                        camera_result.text = 'scanning...'
                        found = await asyncio.to_thread(_scan_cameras)
                        camera_input.props(f'max={max(found) if found else 9}')
                        camera_result.text = f'found: {found}' if found else 'no cameras found'
                        camera_result.classes(replace='text-xs ' + ('text-green-400' if found else 'text-orange-400'))
                    ui.button('Scan cameras', on_click=scan_cameras).props('flat dense')

                saved_ndi = cfg.VISION_NDI_SOURCE_NAME or None
                ndi_select = ui.select([saved_ndi] if saved_ndi else [], label='NDI source',
                                       with_input=True, value=saved_ndi).classes('w-full')
                ndi_result = ui.label().classes('text-xs text-slate-400')

                async def scan_ndi():
                    ndi_result.text = 'scanning...'
                    try:
                        async with httpx.AsyncClient(timeout=10.0) as client:
                            r = await client.get(f'{VISION_URL}/ndi/sources')
                            sources = r.json().get('sources', []) if r.status_code == 200 else []
                        if sources:
                            ndi_select.options = sources
                            if not ndi_select.value:
                                ndi_select.value = sources[0]
                            ndi_result.text = f'{len(sources)} source(s) found'
                            ndi_result.classes(replace='text-xs text-green-400')
                        else:
                            ndi_result.text = 'no NDI sources (is OBS running?)'
                            ndi_result.classes(replace='text-xs text-orange-400')
                    except Exception:
                        ndi_result.text = 'vision service not running'
                        ndi_result.classes(replace='text-xs text-orange-400')
                ui.button('Scan NDI', on_click=scan_ndi).props('flat dense')

                watch_input = ui.input('Watch label (auto = Gem looks at the frame)',
                                       value=cfg.VISION_WATCH_LABEL).classes('w-full')
                frame_edge_input = ui.number('Frame max edge (px)', value=cfg.VISION_FRAME_MAX_EDGE,
                                              step=10, min=320, max=1920).classes('w-40')

            with ui.column().classes('gap-2 min-w-[280px] grow'):
                scan_url_input = ui.input('Vision scan URL', value=cfg.VISION_SCAN_URL).classes('w-full')
                image_url_input = ui.input('Vision get-image URL', value=cfg.VISION_GET_IMAGE_URL).classes('w-full')
                triggers_input = (ui.textarea('Trigger words (comma separated)',
                                               value=', '.join(cfg.VISION_TRIGGER_WORDS))
                                  .classes('w-full'))
                enabled_switch = ui.switch('Vision enabled (chat trigger)', value=cfg.VISION_ENABLED)

        with ui.row().classes('w-full justify-end'):
            async def save_settings():
                values = {
                    'VISION_ENABLED': enabled_switch.value,
                    'VISION_IMAGE_SOURCE': src_toggle.value,
                    'VISION_CAMERA_INDEX': int(camera_input.value or 0),
                    'VISION_NDI_SOURCE_NAME': ndi_select.value or '',
                    'VISION_SCAN_URL': scan_url_input.value,
                    'VISION_GET_IMAGE_URL': image_url_input.value,
                    'VISION_TRIGGER_WORDS': [w.strip() for w in triggers_input.value.split(',') if w.strip()],
                    'VISION_WATCH_LABEL': watch_input.value.strip() or 'auto',
                    'VISION_FRAME_MAX_EDGE': int(frame_edge_input.value or 1280),
                }
                file_ok, pushed = await asyncio.to_thread(settings_store.save, values)
                if file_ok:
                    ui.notify(f'Saved to config.py (pushed live to: {", ".join(pushed) or "no running services"})',
                              type='positive')
                else:
                    ui.notify('Failed to write config.py', type='negative')
            ui.button('Save vision settings', icon='save', on_click=save_settings)

    # ------------------------------------------------ face recognition settings
    with ui.card().classes('w-full'):
        ui.label('Face Recognition').classes('text-lg font-bold')

        with ui.row().classes('w-full gap-6 items-start flex-wrap'):
            with ui.column().classes('gap-2 min-w-[280px] grow'):
                face_enabled = ui.switch('Recognize people on stream', value=cfg.VISION_FACE_RECOGNITION_ENABLED)
                face_greet = ui.switch('Greet recognized people', value=cfg.VISION_FACE_GREET_ENABLED)
                face_report = ui.switch('Mention unknown people', value=cfg.VISION_FACE_REPORT_UNKNOWN)

            with ui.column().classes('gap-2 min-w-[280px] grow'):
                with ui.row().classes('gap-4'):
                    scan_interval = ui.number('Scan interval (s)', value=cfg.VISION_FACE_SCAN_INTERVAL_S,
                                              step=0.5, min=1.0).classes('w-32')
                    greet_cooldown = ui.number('Greet cooldown (s)', value=cfg.VISION_FACE_GREET_COOLDOWN_S,
                                               step=30, min=0).classes('w-40')
                    absence_reset = ui.number('Absence reset (s)', value=cfg.VISION_FACE_ABSENCE_RESET_S,
                                              step=10, min=10).classes('w-40')
                with ui.row().classes('gap-4'):
                    match_threshold = ui.number('Match threshold', value=cfg.VISION_FACE_MATCH_THRESHOLD,
                                                step=0.01, min=0.0, max=1.0).classes('w-40')
                    det_threshold = ui.number('Detection threshold', value=cfg.VISION_FACE_DETECTION_THRESHOLD,
                                              step=0.05, min=0.05, max=1.0).classes('w-40')
                    min_width = ui.number('Min face width (px)', value=cfg.VISION_FACE_MIN_WIDTH_PX,
                                          step=1, min=0, max=500).classes('w-40')
                ignore_input = ui.input('Ignore names (comma separated)',
                                        value=', '.join(cfg.VISION_FACE_IGNORE_NAMES)).classes('w-full')

        with ui.row().classes('w-full justify-end'):
            async def save_face_settings():
                values = {
                    'VISION_FACE_RECOGNITION_ENABLED': face_enabled.value,
                    'VISION_FACE_GREET_ENABLED': face_greet.value,
                    'VISION_FACE_REPORT_UNKNOWN': face_report.value,
                    'VISION_FACE_SCAN_INTERVAL_S': float(scan_interval.value or 5.0),
                    'VISION_FACE_GREET_COOLDOWN_S': float(greet_cooldown.value or 900),
                    'VISION_FACE_ABSENCE_RESET_S': float(absence_reset.value or 120),
                    'VISION_FACE_MATCH_THRESHOLD': float(match_threshold.value or 0.45),
                    'VISION_FACE_DETECTION_THRESHOLD': float(det_threshold.value or 0.45),
                    'VISION_FACE_MIN_WIDTH_PX': int(min_width.value or 30),
                    'VISION_FACE_IGNORE_NAMES': [n.strip() for n in ignore_input.value.split(',') if n.strip()],
                }
                file_ok, pushed = await asyncio.to_thread(settings_store.save, values)
                if file_ok:
                    ui.notify(f'Saved (pushed live to: {", ".join(pushed) or "no running services"})',
                              type='positive')
                else:
                    ui.notify('Failed to write config.py', type='negative')
            ui.button('Save face settings', icon='save', on_click=save_face_settings)

    # ------------------------------------------------------- preview + enrollment
    with ui.card().classes('w-full'):
        with ui.row().classes('w-full items-center justify-between'):
            ui.label('Camera Preview').classes('text-lg font-bold')
            ui.label('Drag on the preview to select a face area — Enroll uses only faces inside it') \
                .classes('text-xs text-slate-400')

        # Selection state: region kept in SOURCE-IMAGE pixel coordinates
        sel = {'start': None, 'region': None, 'frame_size': (1280, 720)}
        img = ui.interactive_image(source='', events=['mousedown', 'mousemove', 'mouseup'],
                                   on_mouse=lambda e: _on_mouse(e, sel, img))
        img.classes('w-full max-w-[960px] rounded-lg bg-slate-900')

        async def refresh_preview():
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    r = await client.get(f'{VISION_URL}/get_image')
                    b64 = r.json().get('image_base64') if r.status_code == 200 else None
                if b64:
                    pil = Image.open(io.BytesIO(base64.b64decode(b64)))
                    sel['frame_size'] = pil.size
                    img.set_source(pil)
            except Exception:
                pass  # vision not running; header status shows that
        ui.timer(0.5, refresh_preview)

        # --- Enrollment controls
        with ui.row().classes('w-full items-end gap-2 flex-wrap'):
            name_input = ui.input('Name').classes('w-48')
            enroll_result = ui.label().classes('text-sm')

            async def enroll():
                name = (name_input.value or '').strip()
                if not name:
                    enroll_result.text = 'Enter a name first'
                    enroll_result.classes(replace='text-sm text-orange-400')
                    return
                payload = {'name': name}
                r = sel['region']
                if r:
                    fw, fh = sel['frame_size']
                    x0, y0, x1, y1 = r
                    payload['region'] = [x0 / fw, y0 / fh, x1 / fw, y1 / fh]
                try:
                    async with httpx.AsyncClient(timeout=20.0) as client:
                        resp = await client.post(f'{VISION_URL}/faces/enroll', json=payload)
                    if resp.status_code == 200:
                        enroll_result.text = f"✓ Enrolled '{name}'"
                        enroll_result.classes(replace='text-sm text-green-400')
                        await refresh_table()
                    else:
                        enroll_result.text = resp.json().get('error', 'Enrollment failed')
                        enroll_result.classes(replace='text-sm text-orange-400')
                except Exception:
                    enroll_result.text = 'Vision service not running'
                    enroll_result.classes(replace='text-sm text-orange-400')
            ui.button('Enroll from camera', icon='person_add', on_click=enroll)

            def clear_area():
                sel['region'] = None
                _update_selection_overlay(sel, img)
                enroll_result.text = 'Face area cleared'
                enroll_result.classes(replace='text-sm text-slate-400')
            ui.button('Clear area', on_click=clear_area).props('flat')

            async def scan_now():
                enroll_result.text = 'scanning...'
                try:
                    async with httpx.AsyncClient(timeout=20.0) as client:
                        resp = await client.post(f'{VISION_URL}/faces/scan')
                        faces = resp.json().get('faces', []) if resp.status_code == 200 else []
                    prefix = 'Scan'
                    if not faces:
                        resp = await _deep_scan()
                        faces = resp or []
                        prefix = 'Deep scan'
                        faces = [f for f in faces if f.get('width', 0) >= 20 or f.get('detection', 0) >= 0.15]
                    if not faces:
                        enroll_result.text = f'{prefix}: no faces detected at all'
                        enroll_result.classes(replace='text-sm text-orange-400')
                    else:
                        parts = [f"{'?' if f['name'] == 'unknown' else f['name']} [det {f.get('detection', 0):.2f}]"
                                 for f in faces[:5]]
                        enroll_result.text = f'{prefix}: ' + ', '.join(parts)
                        enroll_result.classes(replace='text-sm ' +
                                              ('text-green-400' if prefix == 'Scan' else 'text-orange-400'))
                except Exception:
                    enroll_result.text = 'Vision service not running'
                    enroll_result.classes(replace='text-sm text-orange-400')
            ui.button('Scan now', icon='radar', on_click=scan_now).props('flat')

    # ------------------------------------------------------------- enrolled list
    with ui.card().classes('w-full'):
        with ui.row().classes('w-full items-center justify-between'):
            ui.label('Enrolled People').classes('text-lg font-bold')
            refresh_btn = ui.button('Refresh list', icon='refresh', on_click=lambda: refresh_table()).props('flat')

        table = ui.table(
            columns=[{'name': 'name', 'label': 'Person', 'field': 'name', 'align': 'left'},
                     {'name': 'samples', 'label': 'Samples', 'field': 'samples'},
                     {'name': 'actions', 'label': '', 'field': 'actions'}],
            rows=[], row_key='name',
        ).classes('w-full')
        table.add_slot('body-cell-actions', '''
            <q-td :props="props" auto-width>
                <q-btn @click="$parent.$emit('delete', props.row.name)"
                       icon="delete" flat dense color="red" />
            </q-td>
        ''')

        async def delete_person(name):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    await client.post(f'{VISION_URL}/faces/delete', json={'name': name})
                ui.notify(f"Deleted '{name}'")
                await refresh_table()
            except Exception:
                ui.notify('Vision service not running', type='negative')
        table.on('delete', lambda e: delete_person(e.args))

        async def refresh_table():
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    # Process any new photos in the drop folder, then list everyone
                    await client.post(f'{VISION_URL}/faces/refresh')
                    r = await client.get(f'{VISION_URL}/faces/list')
                    people = r.json().get('people', []) if r.status_code == 200 else []
                table.rows = [{'name': p.get('name', '?'), 'samples': p.get('samples', '?')}
                              for p in people]
                if not people:
                    table.rows = [{'name': '(nobody enrolled yet)', 'samples': ''}]
            except Exception:
                table.rows = [{'name': '(vision service not running)', 'samples': ''}]
        ui.timer(5.0, refresh_table, immediate=True)

    ui.label('Tip: you can also drop a <name>.jpg photo into models/faces/photos/ and click Refresh list') \
        .classes('text-xs text-slate-400')


# ---------------------------------------------------------------------- helpers

def _on_mouse(e, sel, img):
    """Drag-to-select on the preview (image pixel coordinates via SVG overlay)."""
    if e.type == 'mousedown' and e.button == 0:
        sel['start'] = (e.image_x, e.image_y)
        sel['region'] = None
        _update_selection_overlay(sel, img)
    elif e.type == 'mousemove' and sel['start'] is not None:
        sel['region'] = _norm_box(sel['start'], (e.image_x, e.image_y))
        _update_selection_overlay(sel, img)
    elif e.type == 'mouseup' and sel['start'] is not None:
        sel['region'] = _norm_box(sel['start'], (e.image_x, e.image_y))
        sel['start'] = None
        x0, y0, x1, y1 = sel['region']
        if (x1 - x0) < 8 or (y1 - y0) < 8:
            sel['region'] = None  # accidental click = clear
        _update_selection_overlay(sel, img)


def _norm_box(p0, p1):
    x0, x1 = sorted((p0[0], p1[0]))
    y0, y1 = sorted((p0[1], p1[1]))
    return (int(x0), int(y0), int(x1), int(y1))


def _update_selection_overlay(sel, img):
    r = sel['region']
    fw, fh = sel['frame_size']
    if r:
        x0, y0, x1, y1 = r
        img.content = (f'<svg width="100%" height="100%" viewBox="0 0 {fw} {fh}" '
                       f'preserveAspectRatio="none">'
                       f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" '
                       f'fill="rgba(255,60,60,0.15)" stroke="#ff3c3c" stroke-width="4"/></svg>')
    else:
        img.content = ''


async def _deep_scan():
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(f'{VISION_URL}/faces/scan?threshold=0.05')
            if r.status_code == 200:
                return r.json().get('faces', [])
    except Exception:
        pass
    return []


def _scan_cameras():
    """Local camera enumeration (open indices 0-9 briefly)."""
    import cv2
    found = []
    for index in range(10):
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if cap.isOpened():
            found.append(index)
            cap.release()
    return found