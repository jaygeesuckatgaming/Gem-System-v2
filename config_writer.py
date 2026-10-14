"""Shared config.py regex-rewrite machinery.

Used by BOTH main.py's save_config() and the NiceGUI control panel, so the
rewrite rules for simple keys, multiline prompts, and structured values can
never drift between the two writers.

config.py stays the single source of truth: this module only rewrites the
keys it is given — everything else in the file is left untouched.

Special keys (prompts, lists) are deduplicated: the first assignment in the
file is replaced with the new value and any later duplicate assignments of
the same key are removed. (main.py's old writer appended a new SYSTEM_PROMPT
on every save because its pattern only matched the triple-quoted format,
which is why old config.py files accumulate dozens of copies.)
"""

import re
import pprint


def _quoted_or_triple(key):
    """Pattern matching a KEY assignment in ANY stored format:
    triple-quoted (\"\"\"...\"\"\"), single-quoted repr, or double-quoted."""
    return re.compile(
        rf'^{key}\s*=\s*(?:"{3}.*?"{3}|\'(?:[^\'\\]|\\.)*\'|"(?:[^"\\]|\\.)*")\s*',
        re.MULTILINE | re.DOTALL,
    )


def _bracket_list(key):
    """Pattern matching a KEY assignment holding a [...] literal."""
    return re.compile(rf'^{key}\s*=\s*\[.*?\]\s*', re.MULTILINE | re.DOTALL)


# Special (non-simple) keys: (serializer, pattern)
_SPECIAL_HANDLERS = {
    'SYSTEM_PROMPT': (repr, _quoted_or_triple('SYSTEM_PROMPT')),
    'GAME_AGENT_SYSTEM_PROMPT': (repr, _quoted_or_triple('GAME_AGENT_SYSTEM_PROMPT')),
    'OSC_ACTIONS': (lambda v: pprint.pformat(v, width=120), _bracket_list('OSC_ACTIONS')),
    'LAYA_ANIMATION_MAP': (lambda v: pprint.pformat(v, width=120), _bracket_list('LAYA_ANIMATION_MAP')),
    'LAYA_ANIMATION_OPTIONS': (lambda v: pprint.pformat(v, width=120), _bracket_list('LAYA_ANIMATION_OPTIONS')),
    'BROWSER_BLOCKED_TERMS': (lambda v: pprint.pformat(v, width=120), _bracket_list('BROWSER_BLOCKED_TERMS')),
}


def write_config_values(config_file, updates, special=None):
    """Rewrite config.py in place.

    updates: {KEY: (value, is_string)} — simple single-line assignments.
             is_string=True serializes with repr(str(value)).
    special: optional {KEY: value} for multiline/structured keys
             (SYSTEM_PROMPT, GAME_AGENT_SYSTEM_PROMPT, OSC_ACTIONS,
             LAYA_ANIMATION_MAP, LAYA_ANIMATION_OPTIONS, BROWSER_BLOCKED_TERMS).

    Only the provided keys are rewritten. Returns True on success.
    """
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            content = f.read()

        # --- Simple single-line assignments ---
        for key, (value, is_string) in updates.items():
            if key in _SPECIAL_HANDLERS:
                continue  # routed through `special` instead
            new_value = repr(str(value)) if is_string else str(value)
            # Function replacement avoids escape interpretation in the value
            pattern = re.compile(rf'^{key}\s*=\s*.*$', re.MULTILINE)
            content = pattern.sub(lambda m, kv=f'{key} = {new_value}': kv, content)

        # --- Multiline / structured keys (deduplicated: replace first, drop rest) ---
        for key, value in (special or {}).items():
            handler = _SPECIAL_HANDLERS.get(key)
            if handler is None:
                print(f"config_writer: no handler for special key {key}, skipping")
                continue
            serializer, pattern = handler
            literal = serializer(value)
            state = {'first': True}

            def repl(m, _key=key, _literal=literal, _state=state):
                if _state['first']:
                    _state['first'] = False
                    return f'{_key} = {_literal}'
                return ''  # remove duplicate assignments of the same key

            if pattern.search(content):
                content = pattern.sub(repl, content)
            else:
                content += f'\n{key} = {literal}\n'

        with open(config_file, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    except Exception as e:
        print(f"config_writer: failed to write {config_file}: {e}")
        return False