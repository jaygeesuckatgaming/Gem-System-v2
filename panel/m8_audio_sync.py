"""Keep m8 and the m8-patched OpenCE on the devices chosen in the Audio tab.

The Audio tab stores `[id] Name` strings from sounddevice, which truncates
names at ~31 characters. m8 matches a microphone by a case-insensitive
substring, but OpenCE compares SDL device names exactly — so this module asks
the bundled 32-bit `tools/sdl_devices.exe` for the exact SDL names and matches
the stored (possibly truncated) name to them.

Call `apply(stored_input, stored_output)` after saving the Audio tab. It
updates:
  m8/m8.toml                      [mic] device
  m8/halo/build/windows/config.toml  [audio] input_device / output_device
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
M8_ROOT = Path(os.environ.get("M8_ROOT", r"C:\Users\jayge\Documents\AI\m8"))
M8_TOML = M8_ROOT / "m8.toml"
HALO_CONFIG = M8_ROOT / "halo" / "build" / "windows" / "config.toml"
SDL_TOOL = PROJECT_ROOT / "tools" / "sdl_devices.exe"


def _sdl_names() -> tuple[list[str], list[str]]:
    if not SDL_TOOL.exists():
        return [], []
    try:
        output = subprocess.run(
            [str(SDL_TOOL)], capture_output=True, text=True, timeout=15
        ).stdout
    except Exception:
        return [], []

    playback: list[str] = []
    recording: list[str] = []
    section = None
    for line in output.splitlines():
        stripped = line.strip()
        if stripped == "PLAYBACK":
            section = playback
            continue
        if stripped == "RECORDING":
            section = recording
            continue
        if section is not None and "|" in line:
            _, name = line.split("|", 1)
            if name.strip():
                section.append(name.strip())
    return playback, recording


def _stored_name(stored: str) -> str:
    if not stored:
        return ""
    if stored.startswith("[") and "] " in stored:
        return stored.split("] ", 1)[1]
    return stored


def _match(name: str, candidates: list[str]) -> str:
    """Truncation-tolerant match, the same idea as device_utils._name_matches."""
    name = (name or "").strip()
    if not name:
        return ""
    for candidate in candidates:
        if candidate.startswith(name) or name.startswith(candidate):
            return candidate
    for candidate in candidates:
        if name.lower() in candidate.lower():
            return candidate
    return name


def resolve_audio(stored_input: str, stored_output: str) -> tuple[str, str]:
    playback, recording = _sdl_names()
    return (
        _match(_stored_name(stored_input), recording),
        _match(_stored_name(stored_output), playback),
    )


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def set_section_value(path: Path, section: str, key: str, value: str) -> None:
    """Line-based TOML update that keeps the file's comments and other keys."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    start = next((i for i, line in enumerate(lines) if line.strip() == f"[{section}]"), None)

    if start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"[{section}]")
        lines.append(f'{key} = "{_escape(value)}"')
    else:
        end = len(lines)
        for i in range(start + 1, len(lines)):
            if lines[i].strip().startswith("["):
                end = i
                break
        for i in range(start + 1, end):
            if re.match(rf"\s*{re.escape(key)}\s*=", lines[i]):
                lines[i] = f'{key} = "{_escape(value)}"'
                break
        else:
            lines.insert(start + 1, f'{key} = "{_escape(value)}"')

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_section_value(path: Path, section: str, key: str) -> str:
    if not path.exists():
        return ""
    in_section = False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == f"[{section}]":
            in_section = True
            continue
        if in_section and stripped.startswith("["):
            break
        if in_section:
            match = re.match(rf"\s*{re.escape(key)}\s*=\s*\"(.*)\"\s*$", line)
            if match:
                return match.group(1)
    return ""


def apply(stored_input: str, stored_output: str) -> dict:
    input_name, output_name = resolve_audio(stored_input, stored_output)

    if input_name:
        set_section_value(M8_TOML, "mic", "device", input_name)
    if output_name:
        set_section_value(HALO_CONFIG, "audio", "output_device", output_name)
    if input_name:
        set_section_value(HALO_CONFIG, "audio", "input_device", input_name)

    return {
        "input": input_name,
        "output": output_name,
        "m8": str(M8_TOML),
        "halo": str(HALO_CONFIG),
    }


def current() -> dict:
    return {
        "input": read_section_value(M8_TOML, "mic", "device"),
        "output": read_section_value(HALO_CONFIG, "audio", "output_device"),
        "model": read_section_value(M8_TOML, "llm", "model"),
        "vision": read_section_value(M8_TOML, "llm", "vision_model"),
    }
