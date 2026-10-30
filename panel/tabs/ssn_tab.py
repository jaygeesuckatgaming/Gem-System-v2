"""Social Stream Ninja tab for the NiceGUI control panel.

SSN connection status, API URL, session ID, and target platforms. Session ID
+ targets push live to a running MCP; the API URL is a file-only write
(consumed at SSN client init, needs an MCP restart to apply).
"""

import asyncio

import httpx
from nicegui import ui

from panel import settings_store

MAIN = settings_store.MAIN_URL


def create(sm):
    cfg = settings_store.load_config()

    ui.label('Social Stream Ninja').classes('text-2xl font-bold')
    status_label = ui.label('Status: checking...').classes('text-sm text-slate-400')

    async def check_status():
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                r = await client.get(f'{MAIN}/api/status')
            if r.status_code == 200:
                enabled = r.json().get('ssn', {}).get('enabled', False)
                status_label.text = (
                    'Status: ● Configured — test delivery below'
                    if enabled else 'Status: ● Not configured'
                )
                status_label.classes(replace='text-sm ' + ('text-green-400' if enabled else 'text-orange-400'))
            else:
                status_label.text = 'Status: ● MCP unreachable'
                status_label.classes(replace='text-sm text-orange-400')
        except Exception:
            status_label.text = 'Status: ● Disconnected (start MCP)'
            status_label.classes(replace='text-sm text-red-400')
    ui.timer(5.0, check_status, immediate=True)

    with ui.card().classes('w-full'):
        ui.label('SSN Settings').classes('text-lg font-bold')
        ui.label('API URL').classes('text-sm text-slate-400')
        api_url = ui.input(value=cfg.SSN_API_URL).classes('w-full')
        ui.label('(API URL applies after an MCP restart)').classes('text-xs text-slate-500')
        ui.label('Session ID').classes('text-sm text-slate-400 mt-3')
        session_id = ui.input(value=cfg.SSN_SESSION_ID).classes('w-full')

        ui.label('Target Platforms').classes('text-sm text-slate-400 mt-3')
        targets = cfg.SSN_TARGETS or []
        with ui.row().classes('gap-6'):
            discord = ui.switch('Discord', value='discord' in targets)
            twitch = ui.switch('Twitch', value='twitch' in targets)
            youtube = ui.switch('YouTube', value='youtube' in targets)

    async def save():
        target_list = [name for name, sw in (('discord', discord), ('twitch', twitch),
                                             ('youtube', youtube)) if sw.value]
        values = {
            'SSN_API_URL': api_url.value.strip(),
            'SSN_SESSION_ID': session_id.value.strip(),
            'SSN_TARGETS': target_list,
        }
        file_ok, pushed = await asyncio.to_thread(settings_store.save, values)
        ui.notify(f'Saved (pushed live to: {", ".join(pushed) or "no running services"})',
                  type='positive' if file_ok else 'negative')
    ui.button('Save SSN settings', icon='save', on_click=save).classes('mt-2')

    with ui.card().classes('w-full mt-2'):
        ui.label('Delivery Test').classes('text-lg font-bold')
        ui.label(
            "SSN returns 'failed' when the standalone app is not delivering to that platform."
        ).classes('text-xs text-slate-400')
        with ui.row().classes('w-full items-center gap-2'):
            test_text = ui.input(value='SSN connection test from Gem').classes('grow')
            test_target = ui.select(['youtube', 'twitch', 'discord'],
                                    value='youtube', label='Target').classes('w-32')
            test_btn = ui.button('Send test', icon='send')

        async def test_delivery():
            api = (api_url.value or cfg.SSN_API_URL).rstrip('/')
            sid = (session_id.value or cfg.SSN_SESSION_ID).strip()
            if not sid:
                ui.notify('Session ID is empty', type='negative')
                return
            test_btn.props('loading')
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    r = await client.post(
                        f'{api}/{sid}',
                        json={
                            'action': 'sendChat',
                            'value': test_text.value or 'SSN test',
                            'target': test_target.value,
                        },
                    )
                body = r.text.strip()
                ok = r.status_code == 200 and 'fail' not in body.lower()
                ui.notify(
                    f'SSN HTTP {r.status_code}: {body[:160] or "(empty)"}',
                    type='positive' if ok else 'negative',
                )
            except Exception as exc:
                ui.notify(f'SSN unreachable: {exc}', type='negative')
            finally:
                test_btn.props(remove='loading')

        test_btn.on_click(test_delivery)
