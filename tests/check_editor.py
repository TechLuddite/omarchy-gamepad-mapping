#!/usr/bin/env python3
"""Run the real editor offscreen with fake CLI/service and no session bus.

The Service subclass disables startup/reloads; its editor loader and IPC are real.
No input device is opened, and the fake CLI rejects any daemon call.
Requires Quickshell and the Omarchy shell UI kit (OMARCHY_SHELL_DIR overrides).
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import sys
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.catalog import shortcut_catalog
from engine.keyboard_catalog import keyboard_catalog

repo = Path(__file__).resolve().parents[1]
kit = Path(os.environ.get('OMARCHY_SHELL_DIR', '/usr/share/omarchy/shell'))
with tempfile.TemporaryDirectory(prefix='controller-editor-check-') as directory:
    root = Path(directory)
    for path in ('home', 'runtime', 'bin', 'config', 'state', 'cache'):
        (root / path).mkdir(mode=0o700)
    for name in ('Panel.qml', 'EditorContent.qml', 'BarWidget.qml', 'Service.qml'):
        shutil.copy2(repo / name, root / name)
    (root / 'Commons').symlink_to(kit / 'Commons', target_is_directory=True)
    shutil.copytree(kit / 'Ui', root / 'Ui')
    # Layer-shell surfaces require a Wayland compositor; replace only that
    # wrapper. The form, FloatingWindow, UI controls and key events are real.
    wayland_socket = os.environ.get('CONTROLLER_TEST_WAYLAND_SOCKET', '')
    if not wayland_socket:
        shutil.copy2(repo / 'tests/editor/KeyboardPanel.qml', root / 'Ui/KeyboardPanel.qml')
    shutil.copy2(repo / 'tests/editor/shell.qml', root / 'shell.qml')
    captured = json.loads((repo / 'tests/fixtures/hyprland-0.56.2-binds.json').read_text())
    catalog_response = json.dumps(shortcut_catalog(captured))
    keyboard_response = json.dumps(keyboard_catalog())
    cli = root / 'bin/controller-control'
    cli.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
with (Path(os.environ['HOME']) / 'calls.jsonl').open('a') as stream:
    stream.write(json.dumps(sys.argv[1:]) + '\\n')
pointer_path = Path(os.environ['HOME']) / 'pointer.json'
pointer_defaults = {'enabled': False, 'pointer_stick': 'left', 'scroll_stick': 'right',
    'speed': 900, 'scroll_speed': 8, 'dead_zone': .18, 'scroll_dead_zone': .35,
    'invert_scroll': False, 'buttons': {'A': 'left', 'X': 'left', 'B': 'right'}}
profile_path = Path(os.environ['HOME']) / 'profiles.json'
def current_config():
    config = {'bindings': [{'combo': 'B', 'keys': 'RETURN'}], 'device': {'layout': 'auto', 'aliases': {'A': 'B', 'B': 'Y'}}}
    state = Path(os.environ['HOME']) / 'mode.json'
    if state.exists(): config['modes'] = json.loads(state.read_text())
    config['pointer'] = json.loads(pointer_path.read_text()) if pointer_path.exists() else pointer_defaults
    if profile_path.exists(): config['profiles'] = json.loads(profile_path.read_text())
    return config
if sys.argv[1:] == ['fixture-snapshot']:
    config = current_config()
    profiles = config.get('profiles', {'active':'Current','items':{'Current':{}}})
    print(json.dumps({'event':'bindings','profiles':{'active':profiles['active'],'names':sorted(profiles['items'])},
                     'modes':config.get('modes',{'enabled':False,'active':'game'}), 'pointer':config['pointer']}))
    raise SystemExit(0)
if sys.argv[1:] == ['profile', 'list', '--json']:
    profiles = current_config().get('profiles', {'active': 'Current', 'items': {'Current': {}}})
    print(json.dumps({'active': profiles['active'], 'names': sorted(profiles['items'])}))
    raise SystemExit(0)
if len(sys.argv) >= 4 and sys.argv[1] == 'profile':
    config = current_config()
    snapshot = {'bindings': config['bindings'], 'pointer': config['pointer']}
    profiles = config.get('profiles', {'active': 'Current', 'items': {'Current': snapshot}})
    profiles['items'][profiles['active']] = snapshot
    operation, name = sys.argv[2], sys.argv[3]
    if operation == 'create':
        if name in profiles['items']:
            print('Profile already exists', file=sys.stderr)
            sys.exit(1)
        profiles['items'][name] = json.loads(json.dumps(snapshot))
        profiles['active'] = name
    elif operation == 'rename':
        renamed = sys.argv[4]
        profiles['items'][renamed] = profiles['items'].pop(name)
        if profiles['active'] == name: profiles['active'] = renamed
    elif operation == 'use':
        profiles['active'] = name
    elif operation == 'delete':
        if name == 'Next':
            print('Fixture refused delete', file=sys.stderr)
            sys.exit(1)
        assert sys.argv[4] == '--switch-to' and profiles['active'] == name
        profiles['active'] = sys.argv[5]
        del profiles['items'][name]
    else:
        raise RuntimeError('Unexpected profile action')
    profile_path.write_text(json.dumps(profiles))
    pointer_path.write_text(json.dumps(profiles['items'][profiles['active']]['pointer']))
    raise SystemExit(0)
if sys.argv[1:] == ['pointer', '--json']:
    print(pointer_path.read_text() if pointer_path.exists() else json.dumps(pointer_defaults))
    raise SystemExit(0)
if len(sys.argv) == 5 and sys.argv[1:3] == ['pointer', '--set'] and sys.argv[4] == '--json':
    update = json.loads(sys.argv[3])
    if update.get('speed') == 1337:
        print('Fixture rejected settings', file=sys.stderr)
        sys.exit(1)
    state = json.loads(pointer_path.read_text()) if pointer_path.exists() else pointer_defaults
    state.update(update)
    pointer_path.write_text(json.dumps(state))
    print(json.dumps(state))
    raise SystemExit(0)
if sys.argv[1:] == ['shortcuts']:
    print(CATALOG_RESPONSE)
    raise SystemExit(0)
if sys.argv[1:] == ['keyboard-keys']:
    marker = Path(os.environ['HOME']) / 'keyboard-read'
    if not marker.exists():
        marker.touch()
        print('unavailable')
        raise SystemExit(1)
    print(KEYBOARD_RESPONSE)
    raise SystemExit(0)
if sys.argv[1:] == ['conflicts', '--json']:
    marker = Path(os.environ['HOME']) / 'mapping-read'
    if not marker.exists():
        marker.touch()
        print(json.dumps({'available': False, 'bindings': [], 'error': 'Fixture unavailable'}))
    else:
        print(json.dumps({'available': True, 'error': '', 'bindings': [
            {'token': 'A', 'code': 304, 'description': 'Raw south action', 'modifiers': 64, 'submap': 'desktop'},
            {'token': 'B', 'code': 305, 'description': 'Raw east action', 'modifiers': 0, 'submap': ''},
            {'token': 'KEY_ENTER', 'code': 28, 'description': 'Keyboard action', 'modifiers': 0, 'submap': ''},
        ]}))
    raise SystemExit(0)
if sys.argv[1] == 'mode':
    path = Path(os.environ['HOME']) / 'mode.json'
    state = json.loads(path.read_text()) if path.exists() else {'enabled': False, 'active': 'game'}
    if sys.argv[2] != '--json':
        state['enabled'] = sys.argv[2] != 'disable'
        if sys.argv[2] in ('game', 'os'): state['active'] = sys.argv[2]
        path.write_text(json.dumps(state))
    print(json.dumps({'modes_enabled': state['enabled'], 'active': state['active']}))
    raise SystemExit(0)
if sys.argv[1] not in ('bind', 'unbind'):
    raise SystemExit('Unexpected CLI command')
if sys.argv[1:3] == ['bind', 'Z']:
    print('fixture mutation failed', file=sys.stderr)
    raise SystemExit(7)
'''.replace('CATALOG_RESPONSE', repr(catalog_response)).replace('KEYBOARD_RESPONSE', repr(keyboard_response)))
    cli.chmod(0o700)
    for name, response in [('hyprctl', '{}'), ('fc-match', 'monospace')]:
        stub = root / 'bin' / name
        stub.write_text('#!/bin/sh\nprintf \'%s\\n\' \'%s\'\n' % ('%s', response))
        stub.chmod(0o700)
    env = os.environ.copy()
    env['CONTROLLER_EDITOR_FIXTURE_PATH'] = str(root / 'shell.qml')
    env.update(PATH=str(root / 'bin') + os.pathsep + env.get('PATH', ''), HOME=str(root / 'home'), XDG_CONFIG_HOME=str(root / 'config'),
               XDG_STATE_HOME=str(root / 'state'), XDG_CACHE_HOME=str(root / 'cache'),
               XDG_RUNTIME_DIR=str(root / 'runtime'), DBUS_SESSION_BUS_ADDRESS='unix:path=/nonexistent',
               QT_QPA_PLATFORM='offscreen', QT_QPA_PLATFORMTHEME='', QT_QUICK_CONTROLS_STYLE='Basic', QT_QUICK_BACKEND='software')
    for name in ('DISPLAY', 'WAYLAND_DISPLAY', 'QS_CONFIG_PATH', 'QS_CONFIG_NAME', 'HYPRLAND_INSTANCE_SIGNATURE', 'SWAYSOCK'):
        env.pop(name, None)
    if wayland_socket:
        assert Path(wayland_socket).is_absolute() and Path(wayland_socket).is_socket()
        env.update(QT_QPA_PLATFORM='wayland', WAYLAND_DISPLAY=wayland_socket)
    result = subprocess.run(['quickshell', '--no-color', '-p', str(root / 'shell.qml')],
                            env=env, text=True, capture_output=True, timeout=45)
    output = result.stdout + result.stderr
    print(output, end='')
    if 'EDITOR CHECK PASS' not in output:
        print((root / 'home/calls.jsonl').read_text() if (root / 'home/calls.jsonl').exists() else 'No fake CLI calls')
    assert result.returncode == 0 and 'EDITOR CHECK PASS' in output, result.returncode
    calls = (root / 'home/calls.jsonl').read_text()
    import json
    calls = [json.loads(line) for line in calls.splitlines()]
    calls = [call for call in calls if call != ["fixture-snapshot"]]
    assert ['bind', 'B', '--keys', 'SUPER+j', '--description', 'custom keys'] in calls, calls
    assert ['bind', 'X', '--exec', "printf 'custom command'", '--description', 'custom command'] in calls, calls
    assert ["shortcuts"] in calls, calls
    assert ["keyboard-keys"] in calls, calls
    assert sum(call == ["conflicts", "--json"] for call in calls) >= 2, calls
    calls = [call for call in calls if call not in (["shortcuts"], ["keyboard-keys"], ["conflicts", "--json"])]
    assert [call for call in calls if call[0] == "mode" and call != ["mode", "--json"]] == [["mode", "game"], ["mode", "os"], ["mode", "disable"], ["mode", "os"], ["mode", "game"], ["mode", "os"], ["mode", "disable"], ["mode", "game"], ["mode", "os"]], calls
    calls = [call for call in calls if call[0] != "mode"]
    pointer_calls = [call for call in calls if call[0] == 'pointer' and '--set' in call]
    assert len(pointer_calls) == 2, pointer_calls
    assert all(call[1] == '--set' and call[3] == '--json' for call in pointer_calls), pointer_calls
    applied = json.loads(pointer_calls[0][2])
    assert applied == {'enabled': True, 'pointer_stick': 'right', 'scroll_stick': 'left',
        'speed': 1450, 'scroll_speed': 12, 'dead_zone': .22, 'scroll_dead_zone': .41,
        'invert_scroll': True, 'buttons': {'X': 'left', 'L2': 'left', 'R2': 'right'}}, applied
    assert json.loads(pointer_calls[1][2])['speed'] == 1337
    assert json.loads((root / 'home/pointer.json').read_text()) == applied
    calls = [call for call in calls if call[0] != "pointer"]
    assert [call for call in calls if call[0] == 'profile' and call != ['profile', 'list', '--json']] == [
        ['profile', 'create', 'Work'], ['profile', 'rename', 'Work', 'Couch'],
        ['profile', 'create', 'Current'], ['profile', 'use', 'Current'],
        ['profile', 'create', 'Next'], ['profile', 'use', 'Current'],
        ['profile', 'use', 'Next'], ['profile', 'delete', 'Next', '--switch-to', 'Couch'],
        ['profile', 'use', 'Couch'], ['profile', 'delete', 'Couch', '--switch-to', 'Current'], ['profile', 'delete', 'Next']], calls
    profiles = json.loads((root / 'home/profiles.json').read_text())
    assert profiles['active'] == 'Current' and set(profiles['items']) == {'Current', 'Next'}, profiles
    calls = [call for call in calls if call[0] != "profile"]
    assert calls == [
        ['bind', 'B', '--keys', 'SUPER+j', '--description', 'custom keys'],
        ['bind', 'X', '--exec', "printf 'custom command'", '--description', 'custom command'],
        ['bind', 'A', '--keys', 'RETURN', '--description', 'repeat flag', '--repeat'],
        ['bind', 'X', '--exec', 'true', '--description', 'hold flag', '--hold'],
        ['bind', 'Z', '--keys', 'RETURN'],
        ['unbind', 'Y'],
    ], calls
    assert not any(marker in output for marker in ('ReferenceError', 'TypeError', 'Unable to assign', 'is not defined')), output
    print('Fake CLI preserved key/command argv and never invoked list/daemon or a reload.')
