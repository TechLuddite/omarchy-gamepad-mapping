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
if sys.argv[1:] == ['shortcuts']:
    print(CATALOG_RESPONSE)
    raise SystemExit(0)
if sys.argv[1:] == ['keyboard-keys']:
    print(KEYBOARD_RESPONSE)
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
                            env=env, text=True, capture_output=True, timeout=20)
    output = result.stdout + result.stderr
    print(output, end='')
    assert result.returncode == 0 and 'EDITOR CHECK PASS' in output, result.returncode
    calls = (root / 'home/calls.jsonl').read_text()
    import json
    calls = [json.loads(line) for line in calls.splitlines()]
    assert ['bind', 'B', '--keys', 'SUPER+j', '--description', 'custom keys'] in calls, calls
    assert ['bind', 'X', '--exec', "printf 'custom command'", '--description', 'custom command'] in calls, calls
    assert ["shortcuts"] in calls, calls
    assert ["keyboard-keys"] in calls, calls
    calls = [call for call in calls if call not in (["shortcuts"], ["keyboard-keys"])]
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
