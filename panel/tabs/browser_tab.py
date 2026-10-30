"""Browser Use tab for the NiceGUI control panel.

Mirrors the tkinter Browser Use tab: enable toggle, LLM provider (Ollama /
OpenAI), per-provider model + API key, headless toggle, viewport size, and
window position with a monitor picker that auto-fills X/Y. Settings load from
config.py; the monitor list comes from a running MCP server.
"""

import asyncio

import httpx
from nicegui import ui

from panel import settings_store

MAIN = settings_store.MAIN_URL


def create(sm):
    cfg = settings_store.load_config()

    ui.label('Browser Use').classes('text-2xl font-bold')
    status_label = ui.label('Status: checking...').classes('text-sm text-slate-400')

    monitors = {}

    async def check_status():
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                r = await client.get(f'{MAIN}/api/status')
            if r.status_code == 200:
                br = r.json().get('browser', {})
                connected = br.get('connected', False)
                status_label.text = 'Status: ● Connected' if connected else 'Status: ● Not connected'
                status_label.classes(replace='text-sm ' + ('text-green-400' if connected else 'text-orange-400'))
            else:
                status_label.text = 'Status: ● MCP unreachable'
                status_label.classes(replace='text-sm text-orange-400')
        except Exception:
            status_label.text = 'Status: ● Disconnected (start MCP)'
            status_label.classes(replace='text-sm text-red-400')
    ui.timer(5.0, check_status, immediate=True)

    with ui.card().classes('w-full'):
        ui.label('Browser Use').classes('text-lg font-bold')
        enabled = ui.switch('Enable browser use', value=cfg.BROWSER_ENABLED)
        headless = ui.switch('Headless (no visible window)', value=cfg.BROWSER_HEADLESS)

    with ui.card().classes('w-full'):
        ui.label('LLM').classes('text-lg font-bold')
        provider = ui.toggle({'ollama': 'Ollama', 'openai': 'OpenAI'}, value=cfg.BROWSER_LLM_PROVIDER)
        with ui.column().classes('gap-2 mt-2 w-full'):
            ui.label('Ollama model (empty = chat model)').classes('text-sm text-slate-400')
            ollama_model = ui.input(value=cfg.BROWSER_OLLAMA_MODEL).classes('w-full')
            ui.label('OpenAI model').classes('text-sm text-slate-400')
            openai_model = ui.input(value=cfg.BROWSER_OPENAI_MODEL).classes('w-full')
            ui.label('OpenAI API key (openai provider only)').classes('text-sm text-slate-400')
            api_key = ui.input(value=cfg.BROWSER_OPENAI_API_KEY, password=True,
                               password_toggle_button=True).classes('w-full')

    with ui.card().classes('w-full'):
        ui.label('Viewport & Position').classes('text-lg font-bold')
        with ui.row().classes('w-full gap-4 items-end'):
            with ui.column().classes('w-32'):
                ui.label('Width').classes('text-xs text-slate-400')
                viewport_w = ui.number(value=int(cfg.BROWSER_VIEWPORT_WIDTH), step=1, min=100)
            with ui.column().classes('w-32'):
                ui.label('Height').classes('text-xs text-slate-400')
                viewport_h = ui.number(value=int(cfg.BROWSER_VIEWPORT_HEIGHT), step=1, min=100)
            with ui.column().classes('w-28'):
                ui.label('Window X').classes('text-xs text-slate-400')
                window_x = ui.number(value=int(cfg.BROWSER_WINDOW_X), step=1, min=-100000)
            with ui.column().classes('w-28'):
                ui.label('Window Y').classes('text-xs text-slate-400')
                window_y = ui.number(value=int(cfg.BROWSER_WINDOW_Y), step=1, min=-100000)

        ui.label('Open on monitor (auto-fills X/Y)').classes('text-sm text-slate-400 mt-3')
        monitor_select = ui.select([], with_input=True).classes('w-full')
        monitor_status = ui.label('').classes('text-xs text-slate-400')

        async def refresh_monitors():
            monitors.clear()
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    r = await client.get(f'{MAIN}/api/browser/monitors')
                ms = r.json().get('monitors', []) if r.status_code == 200 else []
                labels = []
                for i, m in enumerate(ms):
                    monitors[i] = m
                    star = ' (primary)' if m.get('is_primary') else ''
                    labels.append(f"{i}: {m['width']}x{m['height']} @ ({m['x']},{m['y']}){star}")
                monitor_select.options = labels
                if labels:
                    monitor_select.value = labels[0]
                    monitor_status.text = f'{len(labels)} monitor(s) found'
                    monitor_status.classes(replace='text-xs text-green-400')
                else:
                    monitor_status.text = 'No monitors found'
                    monitor_status.classes(replace='text-xs text-orange-400')
            except Exception:
                monitor_status.text = 'MCP server not running'
                monitor_status.classes(replace='text-xs text-red-400')

        def on_monitor(e):
            choice = e.value or ''
            try:
                idx = int(choice.split(':', 1)[0].strip())
            except (ValueError, IndexError):
                return
            m = monitors.get(idx)
            if m:
                window_x.value = int(m['x'])
                window_y.value = int(m['y'])
        monitor_select.on_value_change(on_monitor)

        ui.button('Refresh monitors', icon='refresh', on_click=refresh_monitors).props('flat')
        ui.timer(15.0, refresh_monitors, immediate=True)

    async def save():
        values = {
            'BROWSER_ENABLED': enabled.value,
            'BROWSER_LLM_PROVIDER': provider.value,
            'BROWSER_OLLAMA_MODEL': ollama_model.value.strip(),
            'BROWSER_OPENAI_MODEL': openai_model.value.strip(),
            'BROWSER_OPENAI_API_KEY': api_key.value.strip(),
            'BROWSER_HEADLESS': headless.value,
            'BROWSER_VIEWPORT_WIDTH': int(viewport_w.value or 1280),
            'BROWSER_VIEWPORT_HEIGHT': int(viewport_h.value or 720),
            'BROWSER_WINDOW_X': int(window_x.value or 0),
            'BROWSER_WINDOW_Y': int(window_y.value or 0),
        }
        file_ok, pushed = await asyncio.to_thread(settings_store.save, values)
        ui.notify(f'Saved (pushed live to: {", ".join(pushed) or "no running services"})',
                  type='positive' if file_ok else 'negative')
    ui.button('Save browser settings', icon='save', on_click=save).classes('mt-2')