"""LLM tab for the NiceGUI control panel.

Mirrors the tkinter LLM tab: Ollama connection status, model name, system
prompt, wake words, and voice speaker name. The connection check hits
Ollama directly (works with no MCP server running); saving writes config.py
and pushes live to a running MCP (model swaps apply without restart).
"""

import asyncio

import httpx
from nicegui import ui

from panel import settings_store


def create(sm):
    cfg = settings_store.load_config()

    # ------------------------------------------------------------------ header
    ui.label('LLM Configuration').classes('text-2xl font-bold')
    status_label = ui.label('Status: checking...').classes('text-sm text-slate-400')

    base_url = getattr(cfg, 'OLLAMA_BASE_URL', 'http://localhost:11434')

    async def check_connection():
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f'{base_url}/api/version')
            if r.status_code == 200:
                status_label.text = f'Status: ● Connected — model "{cfg.OLLAMA_MODEL}"'
                status_label.classes(replace='text-sm text-green-400')
            else:
                status_label.text = 'Status: ● Not reachable'
                status_label.classes(replace='text-sm text-orange-400')
        except Exception:
            status_label.text = 'Status: ● Disconnected (is Ollama running?)'
            status_label.classes(replace='text-sm text-red-400')
    ui.timer(5.0, check_connection, immediate=True)

    # ------------------------------------------------------------------ fields
    with ui.card().classes('w-full'):
        ui.label('Model').classes('text-sm text-slate-400')
        model_input = ui.input(value=cfg.OLLAMA_MODEL, placeholder='e.g. gemma4:31b-cloud') \
            .classes('w-full')
        ui.label('Base URL').classes('text-sm text-slate-400 mt-3')
        base_url_input = ui.input(value=base_url).classes('w-full')

    with ui.card().classes('w-full'):
        ui.label('System Prompt').classes('text-lg font-bold')
        prompt_input = ui.textarea(value=cfg.SYSTEM_PROMPT).classes('w-full h-64')

    with ui.card().classes('w-full'):
        with ui.row().classes('w-full gap-6 items-start flex-wrap'):
            with ui.column().classes('gap-1 min-w-[260px] grow'):
                ui.label('Wake words (comma separated)').classes('text-sm text-slate-400')
                wake_input = ui.input(value=', '.join(cfg.WAKE_WORDS)).classes('w-full')
            with ui.column().classes('gap-1 min-w-[260px] grow'):
                ui.label('Voice speaker name (for memory)').classes('text-sm text-slate-400')
                speaker_input = ui.input(value=cfg.VOICE_SPEAKER_NAME).classes('w-full')

    # ------------------------------------------------------------------ save
    async def save():
        values = {
            'SYSTEM_PROMPT': prompt_input.value,
            'WAKE_WORDS': [w.strip() for w in wake_input.value.split(',') if w.strip()],
            'OLLAMA_MODEL': model_input.value.strip(),
            'VOICE_SPEAKER_NAME': speaker_input.value.strip(),
        }
        # Base URL is consumed by main.py via a separate live path; write it too
        values['OLLAMA_BASE_URL'] = base_url_input.value.strip()
        file_ok, pushed = await asyncio.to_thread(settings_store.save, values)
        if file_ok:
            ui.notify(f'Saved to config.py (pushed live to: {", ".join(pushed) or "no running services"})',
                      type='positive')
        else:
            ui.notify('Failed to write config.py', type='negative')
    ui.button('Save LLM settings', icon='save', on_click=save).classes('mt-2')