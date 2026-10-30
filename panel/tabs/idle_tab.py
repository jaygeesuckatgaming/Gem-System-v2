"""Idle Actions & Talks tab for the NiceGUI control panel.

Controls the autonomous idle monologues (IdleManager): enable/disable, timing,
OSC state/action values, topics and the monologue prompt. Settings are written
to config.py and pushed live to main.py via POST /api/settings (no restart).
Also shows live idle state and can trigger a monologue for testing.
"""

import asyncio

import httpx
from nicegui import ui

from panel import settings_store

MAIN_URL = settings_store.MAIN_URL


def create(sm):
    cfg = settings_store.load_config()

    ui.label('Idle Actions & Talks').classes('text-2xl font-bold')
    status_label = ui.label('Status: checking...').classes('text-sm text-slate-400')

    # ---------------------------------------------------------------- live state
    idle_state = ui.label('—').classes('text-lg font-bold')
    speaking_state = ui.label('—').classes('text-sm text-slate-400')
    activity_state = ui.label('—').classes('text-sm text-slate-400')
    suppression_state = ui.label('—').classes('text-sm text-slate-400')

    async def refresh_status():
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f'{MAIN_URL}/api/idle/status')
            if r.status_code != 200:
                raise RuntimeError(f'HTTP {r.status_code}')
            d = r.json()
            status_label.text = 'Status: ● Connected'
            status_label.classes(replace='text-sm text-green-400')

            idle_state.text = (
                '● Daydreaming' if d.get('is_idle')
                else ('● Speaking' if d.get('is_speaking') else '● Active')
            )
            speaking_state.text = (
                'Monologue playing' if d.get('is_speaking') else 'Not speaking'
            )
            activity_state.text = (
                f"Last chat activity: {d.get('seconds_since_activity', 0):.0f}s ago • "
                f"inactivity limit {d.get('inactivity_limit', 0):.0f}s • "
                f"cooldown {d.get('cooldown', 0):.0f}s"
            )
            if d.get('suppress_enabled') and d.get('game_enabled'):
                suppression_state.text = 'Paused while Gem Drive is active'
                suppression_state.classes(replace='text-sm text-amber-300')
            else:
                suppression_state.text = 'Allowed to talk when chat is quiet'
                suppression_state.classes(replace='text-sm text-slate-400')
        except Exception:
            status_label.text = 'Status: ● MCP server not running'
            status_label.classes(replace='text-sm text-red-400')
            idle_state.text = '—'
            speaking_state.text = '—'
            activity_state.text = '—'
            suppression_state.text = '—'

    ui.timer(2.0, refresh_status, immediate=True)

    async def trigger_now():
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(f'{MAIN_URL}/api/idle/trigger')
            if r.status_code == 200:
                ui.notify('Idle monologue triggered', type='positive')
            elif r.status_code == 409:
                ui.notify('Already speaking — try again in a moment', type='warning')
            else:
                ui.notify(f'Trigger failed: {r.text[:120]}', type='negative')
        except Exception:
            ui.notify('MCP server not running', type='negative')

    with ui.card().classes('w-full'):
        with ui.row().classes('w-full items-center justify-between'):
            with ui.column().classes('gap-0'):
                ui.label('Live State').classes('text-lg font-bold')
                idle_state
                speaking_state
                activity_state
                suppression_state
            ui.button('Trigger monologue now', icon='record_voice_over',
                      on_click=trigger_now)

    # ---------------------------------------------------------------- settings
    enabled = ui.switch('Enable idle actions', value=cfg.IDLE_ACTIONS_ENABLED)
    suppress = ui.switch(
        'Pause while Gem Drive is running',
        value=getattr(cfg, 'GAME_DRIVE_SUPPRESS_IDLE', True),
    )
    inactivity = ui.number('Inactivity limit (seconds)',
                           value=cfg.IDLE_INACTIVITY_LIMIT,
                           step=10, min=10).classes('w-48')
    cooldown = ui.number('Monologue cooldown (seconds)',
                         value=cfg.IDLE_COOLDOWN,
                         step=10, min=0).classes('w-48')

    state_addr = ui.input('OSC state address',
                          value=cfg.IDLE_OSC_STATE_ADDRESS).classes('w-full')
    action_addr = ui.input('OSC action address',
                           value=cfg.IDLE_OSC_ACTION_ADDRESS).classes('w-full')
    bored_val = ui.input('Bored value', value=cfg.IDLE_OSC_BORED_VALUE).classes('w-40')
    normal_val = ui.input('Normal value', value=cfg.IDLE_OSC_NORMAL_VALUE).classes('w-40')
    talk_val = ui.input('Talk value', value=cfg.IDLE_OSC_TALK_VALUE).classes('w-40')
    idle_val = ui.input('Idle value', value=cfg.IDLE_OSC_IDLE_VALUE).classes('w-40')

    topics = ui.textarea(
        'Monologue topics (one per line)',
        value='\n'.join(cfg.IDLE_TOPICS),
    ).classes('w-full').props('outlined autogrow')

    prompt = ui.textarea(
        'Monologue prompt (use {topic})',
        value=cfg.IDLE_MONOLOGUE_PROMPT,
    ).classes('w-full').props('outlined autogrow')

    async def save():
        values = {
            'IDLE_ACTIONS_ENABLED': enabled.value,
            'GAME_DRIVE_SUPPRESS_IDLE': suppress.value,
            'IDLE_INACTIVITY_LIMIT': int(inactivity.value or 120),
            'IDLE_COOLDOWN': int(cooldown.value or 0),
            'IDLE_OSC_STATE_ADDRESS': state_addr.value.strip(),
            'IDLE_OSC_ACTION_ADDRESS': action_addr.value.strip(),
            'IDLE_OSC_BORED_VALUE': bored_val.value.strip(),
            'IDLE_OSC_NORMAL_VALUE': normal_val.value.strip(),
            'IDLE_OSC_TALK_VALUE': talk_val.value.strip(),
            'IDLE_OSC_IDLE_VALUE': idle_val.value.strip(),
            'IDLE_TOPICS': [
                line.strip() for line in (topics.value or '').splitlines()
                if line.strip()
            ],
            'IDLE_MONOLOGUE_PROMPT': prompt.value or '',
        }
        file_ok, pushed = await asyncio.to_thread(settings_store.save, values)
        ui.notify(
            'Idle settings saved' + (
                f' (pushed live to: {", ".join(pushed)})' if pushed else ''
            ),
            type='positive' if file_ok else 'negative',
        )

    with ui.card().classes('w-full'):
        ui.label('Settings').classes('text-lg font-bold')
        with ui.row().classes('gap-8 items-start flex-wrap'):
            with ui.column().classes('gap-2 min-w-[280px]'):
                enabled
                suppress
                inactivity
                cooldown
            with ui.column().classes('gap-2 min-w-[280px] grow'):
                state_addr
                action_addr
                with ui.row().classes('items-center gap-2 flex-wrap'):
                    bored_val
                    normal_val
                    talk_val
                    idle_val
        ui.label(
            'Timing changes apply live. The OSC idle value may be left empty to '
            'skip sending that action.'
        ).classes('text-xs text-slate-400 mt-2')
        topics
        prompt
        with ui.row().classes('w-full justify-end'):
            ui.button('Save idle settings', icon='save', on_click=save)
