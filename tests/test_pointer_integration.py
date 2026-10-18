"""Mocked daemon/config/CLI integration; no input nodes or uinput devices."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from engine.cli import main
from engine.config import Config, ConfigError, load
from engine.daemon import Daemon
from engine.pointer import NullPointer, PointerController
from test_native_modes import FakePad


class PointerIntegration(unittest.TestCase):
    def test_pointer_edit_waits_for_the_config_lock(self):
        import os
        import subprocess
        import sys
        import time
        from engine.config import Binding, editing
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            env = {**os.environ, 'CONTROLLER_CONTROL_PID_FILE': str(Path(directory) / 'absent.pid')}
            with editing(path) as config:
                proc = subprocess.Popen([sys.executable, '-m', 'engine', '--config', str(path), 'pointer', '--set', '{"speed":1450}', '--json'], env=env, stdout=subprocess.DEVNULL)
                try:
                    time.sleep(0.15)
                    self.assertIsNone(proc.poll(), 'Pointer edit must wait for the config lock')
                    config.upsert(Binding({'combo': 'Z', 'exec': 'true'}, 0))
                    config.save()
                except BaseException:
                    proc.kill(); proc.wait(); raise
            self.assertEqual(proc.wait(timeout=10), 0)
            after = load(path)
            self.assertEqual(after.pointer['speed'], 1450)
            self.assertIn(('Z',), {b.combo for b in after.bindings})

    def daemon(self, **changes):
        raw = {'modes': {'enabled': True, 'active': 'os'}, 'bindings': [],
               'pointer': {'enabled': True, 'buttons':{'A':'left','B':'right'}}, **changes}
        runner = Mock()
        runner.validate.return_value = None
        runner.run.return_value = (True, 'mock')
        with patch('engine.daemon.ActionRunner', return_value=runner):
            daemon = Daemon(Config(raw), stream=io.StringIO())
        output = Mock()
        daemon.pointer = PointerController(daemon.config.pointer, output=output)
        pad = FakePad(aliases=daemon.config.aliases)
        pad.axes = {0: 0., 1: 0., 3: 0., 4: 0.}
        daemon.pads[pad.path] = pad
        daemon._arm_neutral()
        daemon._advance_neutral()
        daemon._tick_pointer(0.)
        output.reset_mock()
        return daemon, pad, runner, output

    def test_first_pointer_tick_does_not_repeat_the_opening_state(self):
        runner = Mock()
        runner.validate.return_value = None
        with patch('engine.daemon.ActionRunner', return_value=runner):
            daemon = Daemon(Config({'bindings': []}), stream=io.StringIO())
        daemon.emit_state()
        daemon._tick_pointer(0.)
        events = [json.loads(line)['event'] for line in daemon.stream.getvalue().splitlines()]
        self.assertEqual(events.count('state'), 1)

    def test_legacy_and_game_never_allocate_mouse_output(self):
        for modes in ({'enabled': False}, {'enabled': True, 'active': 'game'}):
            daemon, pad, runner, output = self.daemon(modes=modes)
            pad.axes[0] = 1.
            pad.held = {'A'}
            daemon._tick_pointer(1.)
            output.move.assert_not_called()
            output.set_button.assert_not_called()
            runner.run.assert_not_called()

    def test_quick_click_press_and_release_in_one_batch_is_preserved(self):
        daemon, pad, runner, output = self.daemon()
        pad.events = [('A', True), ('A', False)]
        daemon._pump_batch([pad], 1.)
        self.assertEqual(output.set_button.call_args_list,
                         [unittest.mock.call('left', True), unittest.mock.call('left', False)])
        runner.run.assert_not_called()

    def test_saved_alias_and_stick_claims_override_mouse_defaults(self):
        daemon, pad, runner, output = self.daemon(
            device={'aliases': {'A': 'B', 'LSTICK_RIGHT': 'NEXT'}},
            bindings=[{'combo': 'B', 'keys': 'RETURN'}, {'combo': 'NEXT', 'keys': 'TAB'}])
        pad.events = [('A', True)]
        daemon._pump_batch([pad], 1.)
        pad.axes[0] = 1.
        daemon._tick_pointer(1.05)
        runner.run.assert_called_once()
        output.set_button.assert_not_called()
        output.move.assert_not_called()
        self.assertIn('LSTICK_RIGHT', daemon._pointer_claims())

    def test_swapped_button_alias_does_not_reserve_unclaimed_recorded_click(self):
        daemon,pad,runner,output=self.daemon(device={'aliases':{'A':'B','B':'A'}},bindings=[{'combo':'A','keys':'RETURN'}])
        pad.events=[('A',True)]
        daemon._pump_batch([pad],1.)
        output.set_button.assert_called_once_with('right',True)
        runner.run.assert_not_called()
        self.assertEqual(daemon._pointer_claims(),{'A'})

    def test_default_bindings_leave_default_pointer_clicks_available(self):
        from engine.config import DEFAULT_BINDINGS
        daemon,pad,runner,output=self.daemon(bindings=DEFAULT_BINDINGS,pointer={'enabled':True})
        pad.events=[('L2',True)]
        daemon._pump_batch([pad],1.)
        output.set_button.assert_called_once_with('left',True)
        runner.run.assert_not_called()

    def test_reset_release_failure_is_reported_without_stopping_daemon(self):
        daemon,pad,_,output=self.daemon()
        output.release_all.side_effect=OSError('release failed')
        daemon._arm_neutral()
        self.assertEqual(daemon.pointer_status,'error')
        self.assertIn('release failed',daemon.stream.getvalue())
        self.assertFalse(daemon.pointer._down)

    def test_pointer_only_reload_keeps_pad_and_virtual_pointer(self):
        from types import SimpleNamespace
        daemon,pad,runner,output=self.daemon()
        pointer=daemon.pointer
        daemon.scanner=Mock()
        daemon.scanner.find_pads.return_value=[SimpleNamespace(path=pad.path)]
        updated=Config({**daemon.config.to_dict(),'pointer':{'enabled':True,'speed':1400}})
        with patch('engine.daemon.load',return_value=updated), patch('engine.daemon.Gamepad') as reopen:
            daemon._apply_reload()
        reopen.assert_not_called()
        self.assertIs(daemon.pads[pad.path],pad)
        self.assertIs(daemon.pointer,pointer)
        self.assertEqual(pointer.settings.speed,1400)
        output.close.assert_not_called()
        runner.close.assert_not_called()

    def test_saved_pointer_snapshot_is_normalized(self):
        daemon,_,_,_=self.daemon(pointer={'buttons':{'south':'left'}})
        daemon.emit_bindings()
        event=json.loads(daemon.stream.getvalue().splitlines()[-1])
        self.assertEqual(event['pointer']['buttons'],{'A':'left'})
        self.assertEqual(event['pointer']['speed'],900)

    def test_motion_runs_without_new_input_events(self):
        daemon, pad, _, output = self.daemon()
        pad.axes[0] = 1.
        daemon._tick_pointer(.02)
        daemon._tick_pointer(.04)
        self.assertEqual(output.move.call_count, 2)

    def test_pause_releases_drag_and_resume_requires_release(self):
        daemon, pad, _, output = self.daemon()
        pad.events = [('A', True)]
        daemon._pump_batch([pad], .01)
        self.assertIn('left', daemon.pointer._down)
        daemon.paused = True
        daemon._process_safety_changes()
        self.assertEqual(daemon.pointer._down, set())
        output.release_all.assert_called()
        daemon.paused = False
        daemon._process_safety_changes()
        daemon._tick_pointer(.03)
        self.assertFalse(daemon.firing)

    def test_multiple_matching_controllers_require_explicit_narrowing(self):
        daemon, pad, _, output = self.daemon()
        daemon.pads['/fake/second'] = FakePad(path='/fake/second')
        pad.axes[0] = 1.
        daemon._tick_pointer(.02)
        self.assertEqual(daemon.pointer_status, 'select_one_controller')
        output.move.assert_not_called()

    def test_output_error_fails_closed_until_reload(self):
        daemon, pad, _, output = self.daemon()
        output.move.side_effect = OSError('synthetic output failure')
        pad.axes[0] = 1.
        daemon._tick_pointer(.02)
        self.assertEqual(daemon.pointer_status, 'error')
        output.close.assert_called()
        daemon._tick_pointer(.04)
        output.move.assert_called_once()

    def test_dry_run_selects_non_device_sink(self):
        with patch('engine.daemon.ActionRunner'), patch('engine.pointer.os.open', side_effect=AssertionError):
            daemon = Daemon(Config({'pointer': {'enabled': True}}), dry_run=True, stream=io.StringIO())
            self.assertIsInstance(daemon.pointer.output, NullPointer)
            daemon._tick_pointer(0.)

    def test_invalid_pointer_config_is_rejected_before_runtime(self):
        for pointer in (None, [], {'speed': -1}, {'enabled': 1}, {'unknown': True}):
            with self.subTest(pointer=pointer), self.assertRaises(ConfigError):
                Config({'pointer': pointer})
        self.assertNotIn('pointer', Config({}).to_dict())

    def test_pointer_cli_updates_only_pointer_and_inspection_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            original = Config({'bindings': [{'combo': 'X', 'keys': 'RETURN'}]}, path)
            original.save()
            before = path.read_bytes()
            with patch('engine.cli._notify_daemon') as notify, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--config', str(path), 'pointer', '--json']), 0)
                notify.assert_not_called()
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(main(['--config', str(path), 'pointer', '--set', '{"enabled":true,"speed":700}', '--json']), 0)
            notify.assert_called_once()
            restored = load(path)
            self.assertEqual(restored.pointer['speed'], 700)
            self.assertTrue(restored.pointer['enabled'])
            self.assertEqual([b.to_dict() for b in restored.bindings], [b.to_dict() for b in original.bindings])
            self.assertFalse(restored.modes_enabled)


if __name__ == '__main__':
    unittest.main()
