"""The standalone scripts in `extras/`, launched from the Extras tab.

Every entry runs the panel's own Python (the conda env the panel was started
in), with the project root as the working directory:

  * `window` apps open in their own titled console and are stopped by killing
    the process tree (the console closes with the app);
  * `once` scripts run to completion with a timeout and their output is shown
    in the page.

Add a script by adding one dict to EXTRAS. Keep secrets out of this file — the
two camera tests hold their credentials in their own scripts, which are
untracked on purpose.
"""

from __future__ import annotations

import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CREATE_NEW_CONSOLE = 0x00000010

EXTRAS = [
    {
        'id': 'gpu_viz',
        'title': 'GPU / CPU monitor',
        'bat': 'start_scripts/start_GPU_Viz.bat',
        'script': 'extras/gpu_viz.py',
        'kind': 'window',
        'desc': 'Live GPU load and VRAM plus CPU and RAM graphs. Needs pynvml.',
    },
    {
        'id': 'now_playing',
        'title': 'Now Playing overlay',
        'script': 'extras/now_playing.py',
        'kind': 'window',
        'desc': 'Always-on-top now-playing bar, for OBS window capture.',
    },
    {
        'id': 'token_usage',
        'title': 'Token usage overlay',
        'bat': 'start_scripts/start_token_usage.bat',
        'script': 'extras/token_usage.py',
        'kind': 'window',
        'desc': 'Always-on-top LLM token counter. Reads token_usage_state.json.',
    },
    {
        'id': 'text_scroller',
        'title': 'Text scroller',
        'bat': 'start_scripts/start_text_scroller.bat',
        'script': 'extras/text_scroller.py',
        'kind': 'window',
        'desc': 'Rolls a text file up the screen; it asks for the file when it starts.',
    },
    {
        'id': 'pytapo',
        'title': 'Tapo camera test',
        'script': 'extras/PyTapo.py',
        'kind': 'once',
        'timeout': 20,
        'desc': 'Prints the Tapo camera basic info. Needs pytapo and the camera on the LAN.',
    },
    {
        'id': 'zeep_ptz',
        'title': 'ONVIF PTZ test',
        'script': 'extras/zeep_test_1.py',
        'kind': 'once',
        'timeout': 20,
        'desc': 'Starts a continuous PTZ move on the ONVIF camera. Needs zeep + the WSDL files.',
    },
]


def _path(relative: str) -> str:
    return os.path.join(PROJECT_ROOT, relative)


def script_path(item: dict) -> str:
    """The .bat that starts it (with its env and console title), else its script."""
    if item.get('bat'):
        return _path(item['bat'])
    return _path(item['script'])


def exists(item: dict) -> bool:
    return os.path.exists(script_path(item))


def launch(item: dict) -> int:
    """Starts a window entry in its own titled console; returns the cmd PID.

    Entries with a `bat` go through it (it sets the title and the conda env);
    the rest run under the panel's own Python with a title set here.
    """
    path = script_path(item)
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    if item.get('bat'):
        args = ['cmd', '/c', path]
    else:
        args = ['cmd', '/c', f'title Gem Extras: {item["title"]} && "{sys.executable}" -u "{path}"']
    proc = subprocess.Popen(
        args,
        creationflags=CREATE_NEW_CONSOLE,
        cwd=PROJECT_ROOT,
    )
    return proc.pid


def stop(pid: int) -> None:
    subprocess.run(['taskkill', '/T', '/F', '/PID', str(pid)], capture_output=True)


def alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        import psutil
        return psutil.pid_exists(pid)
    except Exception:
        out = subprocess.run(['tasklist', '/FI', f'PID eq {pid}'],
                             capture_output=True, text=True)
        return str(pid) in out.stdout


def run_once(item: dict) -> dict:
    """Runs a one-shot script and returns {'ok': bool, 'output': str}."""
    path = script_path(item)
    if not os.path.exists(path):
        return {'ok': False, 'output': f'Not found: {path}'}
    try:
        result = subprocess.run(
            [sys.executable, '-u', path],
            capture_output=True, text=True,
            timeout=item.get('timeout', 30),
            cwd=PROJECT_ROOT,
        )
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout if isinstance(exc.stdout, str) else ''
        return {'ok': False, 'output': f'Timed out after {exc.timeout}s\n{partial or ""}'.strip()}
    except Exception as exc:
        return {'ok': False, 'output': str(exc)}
    output = (result.stdout or '').strip()
    if result.stderr:
        output = (output + '\n' + result.stderr.strip()).strip()
    return {'ok': result.returncode == 0, 'output': output or '(no output)'}
