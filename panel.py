"""Gem-System v2 — NiceGUI Control Panel.

Run with:  python panel.py   (or start_scripts/start_panel.bat)
Opens at:  http://localhost:8080

Replaces the tkinter gui.py incrementally, tab by tab. Phase 1: Vision.
- All settings load from config.py directly — no services need to be running.
- Start/Stop buttons launch the same start_scripts/*.bat consoles; status is
  health-polled, so manually closed consoles update the status automatically.
- Saving settings writes config.py AND pushes live updates to running
  services (no restarts needed).
"""

from nicegui import ui

from panel.service_manager import ServiceManager
from panel.tabs import audio_tab, vision_tab

service_manager = ServiceManager()


def page_shell():
    """Shared layout: header with service chips + left drawer navigation."""
    with ui.header().classes('items-center gap-4 bg-slate-800 px-4'):
        ui.label('Gem Control Panel').classes('text-lg font-bold')
        ui.space()
        service_manager.render_header()
    with ui.left_drawer().classes('bg-slate-900 p-3'):
        ui.label('TABS').classes('text-xs text-slate-400 tracking-widest')
        ui.link('Vision', '/vision').classes('text-base text-slate-200 no-underline hover:text-white')
        ui.link('Audio', '/audio').classes('text-base text-slate-200 no-underline hover:text-white')
        ui.separator().classes('bg-slate-700')
        ui.label('More tabs migrate here as the old gui.py is phased out') \
            .classes('text-xs text-slate-500')


@ui.page('/vision')
def vision_page():
    page_shell()
    with ui.column().classes('w-full max-w-[1200px] mx-auto p-4 gap-4'):
        vision_tab.create(service_manager)


@ui.page('/audio')
def audio_page():
    page_shell()
    with ui.column().classes('w-full max-w-[1200px] mx-auto p-4 gap-4'):
        audio_tab.create(service_manager)


@ui.page('/')
def index():
    page_shell()
    with ui.column().classes('w-full max-w-[1200px] mx-auto p-4 gap-4 items-center mt-10'):
        ui.label('Gem Control Panel').classes('text-3xl font-bold')
        ui.label('Settings are read from config.py — nothing needs to be running.') \
            .classes('text-slate-400')
        ui.link('Open the Vision tab →', '/vision').classes('text-xl text-blue-400 no-underline')


ui.run(title='Gem Control Panel', port=8080, dark=True, reload=False, show=True)