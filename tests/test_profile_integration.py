"""Profile changes against mocked native ownership/output, never real devices."""
import io
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from engine.config import Config, load
from engine.daemon import Daemon
from engine.pointer import PointerController
from test_native_modes import FakePad


class ProfileModeIntegration(unittest.TestCase):
    def test_profile_creation_waits_for_the_config_lock(self):
        import os
        import subprocess
        import sys
        import tempfile
        import time
        from pathlib import Path
        from engine.config import Binding, editing
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            env = {**os.environ, 'CONTROLLER_CONTROL_PID_FILE': str(Path(directory) / 'absent.pid')}
            with editing(path) as config:
                proc = subprocess.Popen([sys.executable, '-m', 'engine', '--config', str(path), 'profile', 'create', 'Work'], env=env, stdout=subprocess.DEVNULL)
                try:
                    time.sleep(0.15)
                    self.assertIsNone(proc.poll(), 'Profile edit must wait for the config lock')
                    config.upsert(Binding({'combo': 'Z', 'exec': 'true'}, 0))
                    config.save()
                except BaseException:
                    proc.kill(); proc.wait(); raise
            self.assertEqual(proc.wait(timeout=10), 0)
            after = load(path)
            self.assertEqual(after.active_profile, 'Work')
            self.assertIn(('Z',), {b.combo for b in after.bindings})

    def configuration(self, mode='os'):
        config = Config({'modes': {'enabled': True, 'active': mode},
                         'bindings': [], 'pointer': {'enabled': True, 'speed': 900, 'buttons':{'A':'left','B':'right'}}})
        config.profile_create('Media')
        config.pointer['speed'] = 350
        config.profile_use('Current')
        return config

    def test_profile_switch_releases_drag_and_waits_for_new_neutral_snapshot(self):
        current = self.configuration()
        runner, output = Mock(), Mock()
        runner.validate.return_value = None
        with patch('engine.daemon.ActionRunner', return_value=runner):
            daemon = Daemon(current, stream=io.StringIO())
        daemon.pointer = PointerController(current.pointer, output=output)
        old = FakePad()
        daemon.pads[old.path] = old
        daemon._arm_neutral()
        daemon._advance_neutral()
        daemon._tick_pointer(0.)
        old.events = [('A', True)]
        daemon._pump_batch([old], .01)
        self.assertEqual(daemon.pointer._down, {'left'})
        selected = Config(current.to_dict())
        selected.profile_use('Media')
        replacement = FakePad(path='/fake/replacement')
        replacement.held = {'A'}
        replacement.ready = False
        replacement.grabbed = False
        replacement.allow_grab = False
        daemon.scanner = Mock()
        daemon.scanner.find_pads.return_value = [SimpleNamespace(path=replacement.path, button_tokens=[])]
        with patch('engine.daemon.load', return_value=selected), \
                patch('engine.daemon.Gamepad', return_value=replacement), \
                patch('engine.daemon.PointerController', side_effect=lambda settings, output=None: PointerController(settings, output=Mock())):
            daemon._apply_reload()
        output.release_all.assert_called()
        output.close.assert_not_called()
        self.assertTrue(old.closed)
        self.assertFalse(daemon.firing)
        self.assertEqual(daemon.config.active_profile, 'Media')
        self.assertEqual(daemon.pointer.settings.speed, 350)
        self.assertEqual(daemon._mode_state()['active_profile'], 'Media')

    def test_game_uses_passthrough_across_profile_changes(self):
        config = self.configuration('game')
        config.profile_use('Media')
        runner, output = Mock(), Mock()
        with patch('engine.daemon.ActionRunner', return_value=runner):
            daemon = Daemon(config, stream=io.StringIO())
        daemon.pointer = PointerController(config.pointer, output=output)
        pad = FakePad(exclusive=False)
        pad.held = {'A'}
        pad.axes = {0: 1.}
        daemon.pads[pad.path] = pad
        daemon._tick_pointer(1.)
        self.assertFalse(config.effective_exclusive)
        self.assertFalse(daemon.firing)
        output.move.assert_not_called()
        output.set_button.assert_not_called()
        runner.run.assert_not_called()

    def test_profile_snapshots_contain_no_global_mode_or_device_policy(self):
        config = self.configuration()
        config.set_mode('game')
        config.profile_use('Media')
        self.assertEqual(config.input_mode, 'game')
        raw = config.to_dict()
        for item in raw['profiles']['items'].values():
            self.assertEqual(set(item), {'bindings', 'pointer'})
        self.assertEqual(raw['modes'], {'enabled': True, 'active': 'game'})


if __name__ == '__main__':
    unittest.main()
