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
from panel.tabs import (audio_tab, browser_tab, extras_tab, games_tab, idle_tab,
                        llm_tab, memory_tab, music_tab, neurosync_tab, osc_tab,
                        ssn_tab, stt_tab, tts_tab, twitch_tab, vision_tab)

service_manager = ServiceManager()


def page_shell():
    """Shared layout: header with service chips + left drawer navigation."""
    with ui.header().classes('items-center gap-4 bg-slate-800 px-4'):
        ui.link('Gem Control Panel', '/').classes('text-lg font-bold text-white no-underline hover:text-blue-300')
        ui.space()
        service_manager.render_header()
    with ui.left_drawer().classes('bg-slate-900 p-3'):
        ui.label('TABS').classes('text-xs text-slate-400 tracking-widest')
        ui.link('LLM', '/llm').classes('text-base text-slate-200 no-underline hover:text-white')
        ui.link('Memory', '/memory').classes('text-base text-slate-200 no-underline hover:text-white')
        ui.link('TTS', '/tts').classes('text-base text-slate-200 no-underline hover:text-white')
        ui.link('Vision', '/vision').classes('text-base text-slate-200 no-underline hover:text-white')
        ui.link('Audio', '/audio').classes('text-base text-slate-200 no-underline hover:text-white')
        ui.link('Games', '/games').classes('text-base text-slate-200 no-underline hover:text-white')
        ui.link('Extras', '/extras').classes('text-base text-slate-200 no-underline hover:text-white')
        ui.link('Idle', '/idle').classes('text-base text-slate-200 no-underline hover:text-white')
        ui.link('Neurosync', '/neurosync').classes('text-base text-slate-200 no-underline hover:text-white')
        ui.link('Music', '/music').classes('text-base text-slate-200 no-underline hover:text-white')
        ui.link('Browser', '/browser').classes('text-base text-slate-200 no-underline hover:text-white')
        ui.link('OSC', '/osc').classes('text-base text-slate-200 no-underline hover:text-white')
        ui.link('SSN', '/ssn').classes('text-base text-slate-200 no-underline hover:text-white')
        ui.link('STT', '/stt').classes('text-base text-slate-200 no-underline hover:text-white')
        ui.link('Twitch', '/twitch').classes('text-base text-slate-200 no-underline hover:text-white')
        ui.separator().classes('bg-slate-700')
        ui.label('More tabs migrate here as the old gui.py is phased out') \
            .classes('text-xs text-slate-500')


@ui.page('/llm')
def llm_page():
    page_shell()
    with ui.column().classes('w-full max-w-[1200px] mx-auto p-4 gap-4'):
        llm_tab.create(service_manager)


@ui.page('/memory')
def memory_page():
    page_shell()
    with ui.column().classes('w-full max-w-[1200px] mx-auto p-4 gap-4'):
        memory_tab.create(service_manager)


@ui.page('/tts')
def tts_page():
    page_shell()
    with ui.column().classes('w-full max-w-[1200px] mx-auto p-4 gap-4'):
        tts_tab.create(service_manager)


@ui.page('/vision')
def vision_page():
    page_shell()
    with ui.column().classes('w-full max-w-[1200px] mx-auto p-4 gap-4'):
        vision_tab.create(service_manager)


@ui.page('/games')
def games_page():
    page_shell()
    with ui.column().classes('w-full max-w-[1200px] mx-auto p-4 gap-4'):
        games_tab.create(service_manager)


@ui.page('/extras')
def extras_page():
    page_shell()
    with ui.column().classes('w-full max-w-[1200px] mx-auto p-4 gap-4'):
        extras_tab.create(service_manager)


@ui.page('/audio')
def audio_page():
    page_shell()
    with ui.column().classes('w-full max-w-[1200px] mx-auto p-4 gap-4'):
        audio_tab.create(service_manager)


@ui.page('/idle')
def idle_page():
    page_shell()
    with ui.column().classes('w-full max-w-[1200px] mx-auto p-4 gap-4'):
        idle_tab.create(service_manager)


@ui.page('/neurosync')
def neurosync_page():
    page_shell()
    with ui.column().classes('w-full max-w-[1200px] mx-auto p-4 gap-4'):
        neurosync_tab.create(service_manager)


@ui.page('/music')
def music_page():
    page_shell()
    with ui.column().classes('w-full max-w-[1200px] mx-auto p-4 gap-4'):
        music_tab.create(service_manager)


@ui.page('/browser')
def browser_page():
    page_shell()
    with ui.column().classes('w-full max-w-[1200px] mx-auto p-4 gap-4'):
        browser_tab.create(service_manager)


@ui.page('/osc')
def osc_page():
    page_shell()
    with ui.column().classes('w-full max-w-[1200px] mx-auto p-4 gap-4'):
        osc_tab.create(service_manager)


@ui.page('/ssn')
def ssn_page():
    page_shell()
    with ui.column().classes('w-full max-w-[1200px] mx-auto p-4 gap-4'):
        ssn_tab.create(service_manager)


@ui.page('/stt')
def stt_page():
    page_shell()
    with ui.column().classes('w-full max-w-[1200px] mx-auto p-4 gap-4'):
        stt_tab.create(service_manager)


@ui.page('/twitch')
def twitch_page():
    page_shell()
    with ui.column().classes('w-full max-w-[1200px] mx-auto p-4 gap-4'):
        twitch_tab.create(service_manager)


@ui.page('/')
def index():
    page_shell()
    with ui.column().classes('w-full max-w-[1200px] mx-auto p-4 gap-4 items-center mt-10'):
        ui.label('Gem Control Panel').classes('text-3xl font-bold')
        ui.image('panel/images/Gem_V2.PNG').classes('w-80')
        ui.element('iframe').props('src="http://localhost:8089/index_1.html" sandbox="allow-same-origin allow-scripts allow-popups allow-forms allow-top-navigation"').classes('w-full h-[calc(100vh-3em)]')


ui.run(title='Gem Control Panel', port=8080, dark=True, reload=False, show=True)