"""Extras tab — run the standalone scripts in `extras/` from the panel.

Window apps (overlays, monitors) open in their own titled console and can be
stopped here; one-shot scripts run to completion and print their output in the
card. The list lives in panel/extras.py.
"""

from __future__ import annotations

import asyncio
import os

from nicegui import ui

from panel import extras


def _open_extras_folder():
    os.startfile(os.path.join(extras.PROJECT_ROOT, 'extras'))


def _card(item: dict, pids: dict, refreshers: list) -> None:
    with ui.card().classes('w-full'):
        with ui.row().classes('w-full items-start justify-between'):
            with ui.column().classes('gap-0'):
                ui.label(item['title']).classes('text-lg font-bold')
                ui.label(item['desc']).classes('text-xs text-slate-400 max-w-2xl')
                if extras.exists(item):
                    ui.label(item.get('bat') or item['script']).classes(
                        'text-xs text-slate-500 font-mono')
                else:
                    ui.label(f"missing: {extras.script_path(item)}").classes(
                        'text-xs text-red-400 font-mono')
            with ui.row().classes('gap-2 items-center'):
                status = ui.label('stopped').classes('text-sm text-slate-500')
                action = ui.button('Start', icon='play_arrow').props('flat dense')
                stop = ui.button('Stop', icon='stop').props('flat dense')

        output = ui.label('').classes('text-xs text-slate-300 whitespace-pre-wrap font-mono')

        def refresh():
            running = extras.alive(pids.get(item['id']))
            status.text = 'running' if running else 'stopped'
            status.classes(replace='text-sm ' + (
                'text-green-400' if running else 'text-slate-500'))
            action.set_enabled(not running and extras.exists(item))
            stop.set_enabled(running)

        def start_window():
            try:
                pids[item['id']] = extras.launch(item)
                ui.notify(f"Started {item['title']}")
            except FileNotFoundError as exc:
                ui.notify(f'Missing script: {exc}', type='negative')
            except Exception as exc:
                ui.notify(f'Could not start: {exc}', type='negative')
            refresh()

        def stop_window():
            pid = pids.pop(item['id'], None)
            if pid:
                extras.stop(pid)
                ui.notify(f"Stopped {item['title']}")
            refresh()

        async def run_script():
            output.text = 'running…'
            action.set_enabled(False)
            result = await asyncio.to_thread(extras.run_once, item)
            output.text = result['output']
            action.set_enabled(True)
            ui.notify('Finished' if result['ok'] else 'Failed (see output)',
                      type='positive' if result['ok'] else 'negative')

        if item['kind'] == 'window':
            action.on_click(start_window)
            stop.on_click(stop_window)
            refreshers.append(refresh)
            refresh()
        else:
            action.text = 'Run once'
            action.props('icon=terminal')
            stop.set_visibility(False)
            status.set_visibility(False)
            action.on_click(run_script)


def create(sm):
    ui.label('Extras').classes('text-2xl font-bold')
    ui.label(
        'Standalone helper scripts from extras/. Window apps (overlays, monitors) open in '
        'their own titled console and can be stopped here; one-shot scripts run in the page '
        'and show their output.'
    ).classes('text-sm text-slate-400 max-w-3xl')

    with ui.card().classes('w-full'):
        ui.label('Notes').classes('text-lg font-bold')
        ui.label(
            'extras/PyTapo.py and extras/zeep_test_1.py keep their camera credentials in '
            'plain text and are untracked — keep them out of git.'
        ).classes('text-xs text-amber-300 max-w-3xl')
        with ui.row().classes('gap-2 items-center flex-wrap mt-1'):
            ui.button('Open extras folder', icon='folder_open',
                      on_click=_open_extras_folder).props('flat')
        ui.label(
            'Add a script by adding one entry to panel/extras.py EXTRAS.'
        ).classes('text-xs text-slate-500')

    pids = {}
    refreshers = []
    for item in extras.EXTRAS:
        _card(item, pids, refreshers)

    if refreshers:
        ui.timer(2.0, lambda: [refresh() for refresh in refreshers])
