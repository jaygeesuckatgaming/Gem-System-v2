"""Twitch tab for the NiceGUI control panel.

Twitch EventSub settings: enable toggle, client credentials, channel, and the
sub-animation OSC value + duck duration, with a test button. Settings load
from config.py and push live to a running MCP; credentials are masked inputs.
"""

import asyncio

import httpx
from nicegui import ui

from panel import settings_store

MAIN = settings_store.MAIN_URL


def create(sm):
    cfg = settings_store.load_config()

    ui.label('Twitch').classes('text-2xl font-bold')
    status_label = ui.label('Status: checking...').classes('text-sm text-slate-400')

    async def check_status():
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                r = await client.get(f'{MAIN}/api/status')
            if r.status_code == 200:
                enabled = r.json().get('twitch', {}).get('enabled', False)
                status_label.text = 'Status: ● Enabled' if enabled else 'Status: ● Disabled'
                status_label.classes(replace='text-sm ' + ('text-green-400' if enabled else 'text-slate-400'))
            else:
                status_label.text = 'Status: ● MCP unreachable'
                status_label.classes(replace='text-sm text-orange-400')
        except Exception:
            status_label.text = 'Status: ● Disconnected (start MCP)'
            status_label.classes(replace='text-sm text-red-400')
    ui.timer(5.0, check_status, immediate=True)

    with ui.card().classes('w-full'):
        ui.label('EventSub').classes('text-lg font-bold')
        enabled = ui.switch('Enable Twitch EventSub', value=cfg.TWITCH_ENABLED)
        ui.label('Channel').classes('text-sm text-slate-400 mt-3')
        channel = ui.input(value=cfg.TWITCH_CHANNEL).classes('w-full')

    with ui.card().classes('w-full'):
        ui.label('Credentials').classes('text-lg font-bold')
        with ui.column().classes('gap-2 w-full'):
            ui.label('Client ID').classes('text-sm text-slate-400')
            client_id = ui.input(value=cfg.TWITCH_CLIENT_ID).classes('w-full')
            ui.label('Client secret').classes('text-sm text-slate-400')
            client_secret = ui.input(value=cfg.TWITCH_CLIENT_SECRET, password=True,
                                     password_toggle_button=True).classes('w-full')
            ui.label('OAuth token').classes('text-sm text-slate-400')
            oauth = ui.input(value=cfg.TWITCH_OAUTH_TOKEN, password=True,
                             password_toggle_button=True).classes('w-full')
            ui.label('Refresh token').classes('text-sm text-slate-400')
            refresh = ui.input(value=cfg.TWITCH_REFRESH_TOKEN, password=True,
                               password_toggle_button=True).classes('w-full')

    with ui.card().classes('w-full'):
        ui.label('Sub Animation').classes('text-lg font-bold')
        with ui.column().classes('gap-2 w-full'):
            ui.label('OSC value').classes('text-sm text-slate-400')
            sub_anim = ui.input(value=cfg.TWITCH_SUB_ANIMATION).classes('w-full')
            ui.label('Duck duration (seconds)').classes('text-sm text-slate-400')
            duck_s = ui.number(value=float(cfg.TWITCH_SUB_ANIMATION_DUCK_S), step=0.5, min=0.0)
        test_btn = ui.button('Test sub animation (with duck)', icon='celebration')

        async def test_anim():
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    r = await client.post(f'{MAIN}/api/osc/test_animation',
                                          json={'animation': sub_anim.value.strip()})
                ui.notify('Sub animation triggered' if r.status_code == 200 else 'Test failed',
                          type='positive' if r.status_code == 200 else 'negative')
            except Exception:
                ui.notify('MCP server not running', type='negative')
        test_btn.on_click(test_anim)

    async def save():
        values = {
            'TWITCH_ENABLED': enabled.value,
            'TWITCH_CLIENT_ID': client_id.value.strip(),
            'TWITCH_CLIENT_SECRET': client_secret.value.strip(),
            'TWITCH_OAUTH_TOKEN': oauth.value.strip(),
            'TWITCH_REFRESH_TOKEN': refresh.value.strip(),
            'TWITCH_CHANNEL': channel.value.strip(),
            'TWITCH_SUB_ANIMATION': sub_anim.value.strip(),
            'TWITCH_SUB_ANIMATION_DUCK_S': float(duck_s.value or 5.0),
        }
        file_ok, pushed = await asyncio.to_thread(settings_store.save, values)
        ui.notify(f'Saved (pushed live to: {", ".join(pushed) or "no running services"})',
                  type='positive' if file_ok else 'negative')
    ui.button('Save Twitch settings', icon='save', on_click=save).classes('mt-2')