"""Memory (Cognee) tab for the NiceGUI control panel.

Cognee's settings live in its OWN .env (served by cognee_server.py on :8011),
not config.py — so this tab talks to the Cognee server directly: /health for
status, GET/POST /settings for config, and /recall for a memory test (which
works without the MCP server). Saving settings requires a Cognee restart to
take effect (it rewrites the .env).
"""

import asyncio
from urllib.parse import urlparse

import httpx
from nicegui import ui

from panel import settings_store


def create(sm):
    cfg = settings_store.load_config()
    cog_url = getattr(cfg, 'COGNEE_SERVER_URL', 'http://127.0.0.1:8011')

    # ------------------------------------------------------------------ header
    ui.label('Memory (Cognee)').classes('text-2xl font-bold')
    status_label = ui.label('Status: checking...').classes('text-sm text-slate-400')

    state = {'loaded': False}
    cog_port = urlparse(cog_url).port or 8011

    async def _cognee_port_open():
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection('127.0.0.1', cog_port), timeout=1.0
            )
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return True
        except Exception:
            return False

    # --------------------------------------------------------------- settings
    llm_model = ui.input('LLM model').classes('w-full')
    llm_endpoint = ui.input('LLM endpoint').classes('w-full')
    embedding_model = ui.input('Embedding model').classes('w-full')
    embedding_endpoint = ui.input('Embedding endpoint').classes('w-full')
    embedding_dimensions = ui.input('Embedding dimensions').classes('w-full')
    caching = ui.switch('Caching (session memory)')
    auto_feedback = ui.switch('Auto feedback')
    improve_scheduler = ui.switch('Off-peak self-improvement scheduler')
    improve_start = ui.number('Off-peak start hour', min=0, max=23, step=1).classes('w-28')
    improve_end = ui.number('Off-peak end hour', min=0, max=23, step=1).classes('w-28')
    improve_interval = ui.number('Minimum interval (hours)', min=1, step=1).classes('w-40')
    data_dir = ui.label('—').classes('text-xs text-slate-400')
    system_dir = ui.label('—').classes('text-xs text-slate-400')

    async def load_settings():
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(f'{cog_url}/settings')
                if r.status_code != 200:
                    return False
                d = r.json()
            llm_model.value = d.get('llm_model', '')
            llm_endpoint.value = d.get('llm_endpoint', '')
            embedding_model.value = d.get('embedding_model', '')
            embedding_endpoint.value = d.get('embedding_endpoint', '')
            embedding_dimensions.value = d.get('embedding_dimensions', '')
            caching.value = str(d.get('caching', '')).lower() == 'true'
            auto_feedback.value = str(d.get('auto_feedback', '')).lower() == 'true'
            improve_scheduler.value = str(d.get('improve_scheduler_enabled', '')).lower() in (
                'true', '1'
            )
            improve_start.value = int(d.get('improve_off_peak_start') or 3)
            improve_end.value = int(d.get('improve_off_peak_end') or 6)
            improve_interval.value = float(d.get('improve_min_interval_hours') or 24)
            data_dir.text = d.get('data_root_directory') or '—'
            system_dir.text = d.get('system_root_directory') or '—'
            return True
        except Exception:
            return False

    async def check_status():
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                r = await client.get(f'{cog_url}/health')
            if r.status_code == 200 and r.json().get('status') == 'ok':
                initialized = bool(r.json().get('initialized'))
                status_label.text = (
                    'Status: ● Connected' if initialized
                    else 'Status: ● Connected (initializing)'
                )
                status_label.classes(replace='text-sm text-green-400')
                if not state['loaded']:
                    state['loaded'] = await load_settings()
            else:
                status_label.text = 'Status: ● Initializing...'
                status_label.classes(replace='text-sm text-orange-400')
        except Exception:
            # /health can time out while Cognee loads its model; the port being
            # open still means the service is up.
            if await _cognee_port_open():
                status_label.text = 'Status: ● Connected (initializing)'
                status_label.classes(replace='text-sm text-green-400')
                return
            status_label.text = 'Status: ● Disconnected (start Cognee from the top bar)'
            status_label.classes(replace='text-sm text-red-400')
    ui.timer(5.0, check_status, immediate=True)

    async def run_improve():
        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                r = await client.post(f'{cog_url}/improve')
            if r.status_code == 200:
                ui.notify('Self-improvement batch completed', type='positive')
            else:
                ui.notify(f'Improve failed: {r.text[:120]}', type='negative')
        except Exception:
            ui.notify('Cognee server not running', type='negative')

    # --------------------------------------------------------------- settings card
    with ui.card().classes('w-full'):
        with ui.row().classes('w-full justify-between items-center'):
            ui.label('Cognee Settings').classes('text-lg font-bold')
            ui.button('Reload', icon='refresh', on_click=lambda: load_settings()).props('flat')

        with ui.row().classes('w-full gap-6 items-start flex-wrap'):
            with ui.column().classes('gap-2 min-w-[280px] grow'):
                ui.label('LLM configuration').classes('text-sm text-slate-400')
                llm_model
                llm_endpoint
            with ui.column().classes('gap-2 min-w-[280px] grow'):
                ui.label('Embedding configuration').classes('text-sm text-slate-400')
                embedding_model
                embedding_endpoint
                embedding_dimensions
        with ui.row().classes('w-full gap-6 items-start flex-wrap mt-2'):
            with ui.column().classes('gap-2 min-w-[280px] grow'):
                ui.label('Storage').classes('text-sm text-slate-400')
                ui.label('Data directory:').classes('text-xs text-slate-500')
                data_dir
                ui.label('System directory:').classes('text-xs text-slate-500')
                system_dir
            with ui.column().classes('gap-2 min-w-[280px] grow'):
                ui.label('Behavior').classes('text-sm text-slate-400')
                caching
                auto_feedback
            with ui.column().classes('gap-2 min-w-[280px] grow'):
                ui.label('Self-improvement').classes('text-sm text-slate-400')
                improve_scheduler
                with ui.row().classes('items-center gap-2'):
                    improve_start
                    improve_end
                improve_interval
                ui.button('Run improve now', icon='auto_awesome',
                          on_click=run_improve).props('flat')
                ui.label(
                    'remember() no longer rebuilds the graph; improve() runs as a '
                    'batch during the off-peak window.'
                ).classes('text-xs text-slate-500')

        async def save():
            payload = {
                'llm_model': llm_model.value.strip(),
                'llm_endpoint': llm_endpoint.value.strip(),
                'embedding_model': embedding_model.value.strip(),
                'embedding_endpoint': embedding_endpoint.value.strip(),
                'embedding_dimensions': embedding_dimensions.value.strip(),
                'caching': 'true' if caching.value else 'false',
                'auto_feedback': 'true' if auto_feedback.value else 'false',
                'improve_scheduler_enabled': 'true' if improve_scheduler.value else 'false',
                'improve_off_peak_start': str(int(improve_start.value or 3)),
                'improve_off_peak_end': str(int(improve_end.value or 6)),
                'improve_min_interval_hours': str(float(improve_interval.value or 24)),
            }
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.post(f'{cog_url}/settings', json=payload)
                if r.status_code == 200:
                    ui.notify('Cognee settings saved — restart Cognee to apply', type='positive')
                else:
                    ui.notify(f'Save failed: {r.text[:120]}', type='negative')
            except Exception:
                ui.notify('Cognee server not running', type='negative')
        with ui.row().classes('w-full justify-end'):
            ui.button('Save Cognee settings', icon='save', on_click=save)

    # ---------------------------------------------------------------- test recall
    with ui.card().classes('w-full'):
        ui.label('Test Memory Recall').classes('text-lg font-bold')
        with ui.row().classes('w-full items-center gap-2'):
            query_input = ui.input(placeholder='Query (e.g. Alice123)').classes('grow')
            recall_btn = ui.button('Recall', icon='search')

        results = ui.textarea().classes('w-full h-48').props('readonly outlined')

        async def recall():
            query = (query_input.value or '').strip()
            if not query:
                return
            recall_btn.props('loading')
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    r = await client.post(f'{cog_url}/recall',
                                          json={'query': query, 'top_k': 5})
                if r.status_code == 200:
                    items = r.json().get('results', [])
                    results.value = '\n\n'.join(f'• {it}' for it in items) if items \
                        else 'No memories found.'
                else:
                    results.value = f'Recall error: {r.text[:200]}'
            except Exception as e:
                results.value = f'Recall failed: {e}'
            recall_btn.props(remove='loading')
        recall_btn.on_click(recall)