"""Resolve stored '[ID] Name' audio device strings against the CURRENT device
list. Windows re-enumerates audio devices — with Voicemeeter installed the
indices shift between boots — so a stored ID alone can silently point at the
WRONG device. The name is the stable identity: an ID is only trusted when the
device at that index still matches the stored name.
"""

import sounddevice as sd


def parse_device_string(s):
    """'[12] Some Name' -> (12, 'Some Name'); plain name -> (None, name)."""
    if not s:
        return None, ''
    if s.startswith('[') and ']' in s:
        try:
            idx = int(s.split(']', 1)[0].strip('['))
            name = s.split('] ', 1)[1] if '] ' in s else ''
            return idx, name
        except ValueError:
            pass
    return None, s


def _name_matches(a, b):
    """Truncation-tolerant comparison. sounddevice truncates names at ~31
    chars, so one side may be a prefix of the other — startswith in both
    directions covers every truncation case. No looser fallback: devices like
    'Voicemeeter Out B1' vs 'Voicemeeter Out A3' must NOT match."""
    a, b = (a or '').strip(), (b or '').strip()
    if not a or not b:
        return False
    return a.startswith(b) or b.startswith(a)


def _usable(dev, want_input):
    if want_input is None:
        return True
    return dev['max_input_channels'] > 0 if want_input else dev['max_output_channels'] > 0


def resolve_device(stored, want_input=None, devices=None):
    """Find the CURRENT device dict matching a stored '[ID] Name' string.

    The stored ID is trusted only if the name at that index still matches;
    otherwise the device is located by name (truncation-tolerant).
    want_input: True for capture devices, False for playback, None for any.
    Returns the device dict or None if no match.
    """
    if not stored:
        return None
    idx, name = parse_device_string(stored)
    if not name:
        return None
    if devices is None:
        devices = sd.query_devices()

    # 1) Stored ID is only valid if the name there still matches
    if idx is not None:
        for d in devices:
            if d['index'] == idx:
                if _name_matches(d['name'], name) and _usable(d, want_input):
                    return d
                break  # index now holds a different device — fall through
    # 2) Find by name
    for d in devices:
        if _name_matches(d['name'], name) and _usable(d, want_input):
            return d
    return None


def device_to_option(d):
    """Device dict -> the '[ID] Name' option string format."""
    return f"[{d['index']}] {d['name']}"