"""Read existing compositor mappings; never rewrite bindings outside the mapper.

Inspired by TechLuddite's MIT Luddite Gestures read-before-write approach.
This is an original implementation for evdev/keybind identities, not gestures.
"""
import json
import os
import subprocess
from .buttons import button_for_key_code, GAMEPAD_BUTTONS
from .keys import resolve_key, KeyParseError


def external_bindings(binds, devices):
    result = []
    for bind in binds:
        key = str(bind.get('key', ''))
        try:
            if key.startswith('mouse:'):
                code = int(key.partition(':')[2])
                token = button_for_key_code(code)
            elif bind.get('keycode', 0):
                # Hyprland's code: binding uses XKB keycodes (evdev + 8).
                token = button_for_key_code(int(bind['keycode']) - 8)
            else:
                token = button_for_key_code(resolve_key(key))
        except (ValueError, KeyParseError):
            continue
        # Display the handheld's hardware controls and gamepad-related binds,
        # rather than the full keyboard shortcut catalogue already next to it.
        if token not in GAMEPAD_BUTTONS and token not in {'KEY_POWER', 'KEY_SLEEP', 'KEY_VOLUMEUP', 'KEY_VOLUMEDOWN', 'KEY_BACK'}:
            continue
        result.append(dict(token=token, description=bind.get('description') or bind.get('dispatcher') or 'OS binding',
                           modifiers=int(bind.get('modmask', 0)), kind='compositor'))
    if any('odin2-gamepad' in d.get('name', '') for d in devices.get('mice', [])):
        result.append(dict(token='BACK_BUTTON', description='Native mouse Back / application navigation',
                           modifiers=0, kind='native pointer'))
    return result


def main():
    try:
        env = os.environ.copy()
        if not env.get('HYPRLAND_INSTANCE_SIGNATURE'):
            instances = json.loads(subprocess.check_output(['hyprctl', 'instances', '-j'], text=True, timeout=3))
            if len(instances) != 1:
                raise RuntimeError('Select the active desktop session')
            env['HYPRLAND_INSTANCE_SIGNATURE'] = instances[0]['instance']
        def read(name):
            return json.loads(subprocess.check_output(['hyprctl', '-j', name], env=env, text=True, timeout=3))
        print(json.dumps(dict(available=True, bindings=external_bindings(read('binds'), read('devices')))))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        print(json.dumps(dict(available=False, bindings=[])))


if __name__ == '__main__':
    main()
