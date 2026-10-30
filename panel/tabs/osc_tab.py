"""OSC tab for the NiceGUI control panel.

Two sections:

* OSC Receiver — the UDP socket (clients/osc_receiver.py) that accepts OSC
  messages *from* Unreal Engine: bind IP, port, and verbose logging.
* OSC Custom Actions — map chat phrases to OSC commands (phrase -> address +
  value), with a dynamic add/remove row editor, per-row test button, and the
  outbound OSC target IP/port.

Everything loads from config.py and saves via the shared writer; the live push
to a running MCP uses /api/settings and the dedicated /api/osc/actions endpoint.
"""

import asyncio

import httpx
from nicegui import ui

from panel import settings_store

MAIN = settings_store.MAIN_URL


def _clamp_port(value, fallback: int) -> int:
    """NiceGUI number inputs don't hard-clamp typed text — sanitize here."""
    try:
        port = int(value)
    except (TypeError, ValueError):
        return fallback
    return port if 1 <= port <= 65535 else fallback


def create(sm):
    cfg = settings_store.load_config()

    ui.label('OSC').classes('text-2xl font-bold')
    ui.label("Receive OSC from Unreal Engine, and map chat phrases to OSC "
             "commands going out.").classes('text-sm text-slate-400')

    # ---------------------------------------------------------- OSC receiver
    with ui.card().classes('w-full'):
        ui.label('OSC Receiver (Unreal → Gem)').classes('text-lg font-bold')
        ui.label('UDP port Gem-System listens on. Point Unreal\'s OSC sender at '
                 'this address — messages arrive as [OSC RX] /address [args].'
                 ).classes('text-sm text-slate-400')
        with ui.row().classes('w-full gap-4 items-end'):
            with ui.column().classes('grow'):
                ui.label('Bind IP').classes('text-xs text-slate-400')
                rx_ip_input = ui.input(
                    value=getattr(cfg, 'OSC_RECEIVE_IP', '0.0.0.0')
                ).props('hint="0.0.0.0 = all interfaces"')
            with ui.column().classes('w-32'):
                ui.label('Port').classes('text-xs text-slate-400')
                rx_port_input = ui.number(
                    value=int(getattr(cfg, 'OSC_RECEIVE_PORT', 9000)),
                    step=1, min=1, max=65535,
                )
            with ui.column().classes('w-48'):
                ui.label('Log every message').classes('text-xs text-slate-400')
                rx_verbose = ui.switch(
                    value=bool(getattr(cfg, 'OSC_RECEIVE_VERBOSE', True))
                )
        ui.label('Bind address applies when the MCP server starts.'
                 ).classes('text-xs text-slate-500')

    # ------------------------------------------------------------ OSC target
    with ui.card().classes('w-full'):
        ui.label('OSC Target').classes('text-lg font-bold')
        with ui.row().classes('w-full gap-4 items-end'):
            with ui.column().classes('grow'):
                ui.label('IP').classes('text-xs text-slate-400')
                ip_input = ui.input(value=cfg.OSC_IP)
            with ui.column().classes('w-28'):
                ui.label('Port').classes('text-xs text-slate-400')
                port_input = ui.number(value=int(cfg.OSC_PORT), step=1, min=1,
                                       max=65535)

    # ------------------------------------------------------------ actions
    rows = []

    def test_action(rec):
        address = rec['address'].value.strip()
        value = rec['value'].value.strip()
        if not address:
            ui.notify('No address entered', type='negative')
            return
        try:
            httpx.post(f'{MAIN}/api/osc/test', json={'address': address, 'value': value},
                       timeout=5.0)
            ui.notify(f'Sent: {address} = {value}', type='positive')
        except Exception:
            ui.notify('MCP server not running', type='negative')

    def remove_row(rec):
        rec['row'].delete()
        rows.remove(rec)

    def add_row(phrase='', address='', value=''):
        rec = {}
        with ui.row().classes('w-full items-center gap-2') as row:
            rec['row'] = row
            rec['phrase'] = ui.input(value=phrase, placeholder='Phrase').classes('grow')
            rec['address'] = ui.input(value=address, placeholder='/address').classes('grow')
            rec['value'] = ui.input(value=value, placeholder='value').classes('w-32')
            rec['test'] = ui.button('Test', icon='send', on_click=lambda r=rec: test_action(r)) \
                .props('flat dense')
            rec['del'] = ui.button('✕', on_click=lambda r=rec: remove_row(r)) \
                .props('flat dense color=red')
        rows.append(rec)

    with ui.card().classes('w-full'):
        with ui.row().classes('w-full justify-between items-center'):
            ui.label('Actions').classes('text-lg font-bold')
            ui.button('+ Add Action', icon='add', on_click=lambda: add_row()).props('flat')

    # ------------------------------------------------------------------ save
    async def save():
        actions = [{'phrase': r['phrase'].value.strip(),
                    'address': r['address'].value.strip(),
                    'value': r['value'].value.strip()}
                   for r in rows
                   if r['phrase'].value.strip() and r['address'].value.strip()]
        values = {
            'OSC_IP': ip_input.value.strip(),
            'OSC_PORT': _clamp_port(port_input.value, 10000),
            'OSC_ACTIONS': actions,
            'OSC_RECEIVE_IP': (rx_ip_input.value or '0.0.0.0').strip(),
            'OSC_RECEIVE_PORT': _clamp_port(rx_port_input.value, 9000),
            'OSC_RECEIVE_VERBOSE': bool(rx_verbose.value),
        }
        file_ok, pushed = await asyncio.to_thread(settings_store.save, values)
        actions_pushed = False
        if await sm.is_running('mcp'):
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    r = await client.post(f'{MAIN}/api/osc/actions', json={'actions': actions})
                    actions_pushed = r.status_code == 200
            except Exception:
                pass
        if file_ok:
            names = list(pushed.keys()) + (['actions'] if actions_pushed else [])
            ui.notify(f'Saved {len(actions)} action(s) (pushed live to: '
                      f'{", ".join(names) or "no running services"})', type='positive')
        else:
            ui.notify('Failed to write config.py', type='negative')
    ui.button('Save OSC settings', icon='save', on_click=save).classes('mt-2')

    # Load existing actions from config.py
    for a in getattr(cfg, 'OSC_ACTIONS', []):
        if isinstance(a, dict):
            add_row(a.get('phrase', ''), a.get('address', ''), a.get('value', ''))