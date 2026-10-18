"""Native ownership and recovery checks using mocked input I/O only.

Never run a daemon loop or open an input node/virtual device in these tests.
"""
import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from engine import linux_input as li
from engine.cli import main
from engine.combos import Activation
from engine.config import Config, ConfigError, load
from engine.daemon import Daemon
from engine.devices import Gamepad


def configuration(mode='os', **kw):
    return Config({'modes': {'enabled': True, 'active': mode},
                   'bindings': [{'combo': 'A', 'keys': 'RETURN', 'repeat': True}], **kw})


class ConfigModeTests(unittest.TestCase):
    def test_legacy_serialization_does_not_gain_modes(self):
        for exclusive in (False, True):
            config = Config({'device': {'exclusive': exclusive}, 'enabled': False})
            self.assertFalse(config.modes_enabled)
            self.assertEqual(config.input_mode, 'legacy')
            self.assertEqual(config.effective_exclusive, exclusive)
            self.assertNotIn('modes', config.to_dict())

    def test_explicit_modes_defaults_and_validation(self):
        config = Config({'modes': {}})
        self.assertEqual(config.to_dict()['modes'], {'enabled': False, 'active': 'game'})
        for modes in (None, [], True, {'enabled': 'yes'}, {'enabled': 1}, {'active': 'pointer'}, {'other': True}):
            with self.subTest(modes=modes), self.assertRaises(ConfigError):
                Config({'modes': modes})

    def test_game_is_passthrough_and_master_disable_releases_os(self):
        self.assertFalse(configuration('game', device={'exclusive': True}).effective_exclusive)
        self.assertTrue(configuration('os').effective_exclusive)
        self.assertFalse(configuration('os', enabled=False).effective_exclusive)

    def test_mode_enable_disable_retains_active_choice(self):
        config = Config({})
        config.set_mode('enable')
        self.assertEqual(config.input_mode, 'game')
        config.set_mode('os')
        config.set_mode('disable')
        self.assertEqual(config.input_mode, 'legacy')
        self.assertEqual(config.modes['active'], 'os')
        config.set_mode('enable')
        self.assertEqual(config.input_mode, 'os')

    def test_cli_inspection_never_saves_or_signals(self):
        out = io.StringIO()
        with patch('engine.cli._load', return_value=Config({})), patch('engine.cli._notify_daemon') as signal, patch.object(Config, 'save') as save, contextlib.redirect_stdout(out):
            self.assertEqual(main(['mode', '--json']), 0)
        save.assert_not_called()
        signal.assert_not_called()
        self.assertEqual(json.loads(out.getvalue())['input_mode'], 'legacy')

    def test_cli_mode_changes_preserve_bindings_through_atomic_save(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            config = Config({'device': {'exclusive': True}, 'bindings': [{'combo': 'B', 'exec': 'custom command'}]}, path=path)
            config.save()
            before = config.to_dict()
            with patch('engine.cli._notify_daemon') as signal, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--config', str(path), 'mode', 'game', '--json']), 0)
            signal.assert_called_once()
            after = load(path).to_dict()
            self.assertEqual(after.pop('modes'), {'enabled': True, 'active': 'game'})
            self.assertEqual(before, after)
            self.assertEqual(list(Path(directory).glob('.config-*')), [])


class MaintainerIntegrationTests(unittest.TestCase):
    def test_legacy_disconnect_preserves_another_pads_pending_hold(self):
        config = Config({'bindings': [{'combo': 'X', 'keys': 'RETURN', 'hold': True}]})
        with patch('engine.daemon.ActionRunner'):
            daemon = Daemon(config, stream=io.StringIO())
        daemon.pads = {path: FakePad(path=path) for path in ('/fake/a', '/fake/b')}
        daemon._feed('/fake/a', 'A', True, 0)
        daemon._feed('/fake/b', 'X', True, 0)
        daemon._drop_pad('/fake/a', 'fixture')
        self.assertEqual(daemon.engine.held, {'X'})
        self.assertEqual([a.binding.combo for a in daemon.engine.tick(10)], [('X',)])

    def test_mode_change_waits_for_locked_config_edit(self):
        import os
        import subprocess
        import sys
        import time
        from engine.config import Binding, editing
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            env = {**os.environ, 'CONTROLLER_CONTROL_PID_FILE': str(Path(directory) / 'absent.pid')}
            with editing(path) as config:
                proc = subprocess.Popen([sys.executable, '-m', 'engine', '--config', str(path), 'mode', 'os', '--json'], env=env, stdout=subprocess.DEVNULL)
                try:
                    time.sleep(0.15)
                    self.assertIsNone(proc.poll(), 'Mode mutation must wait for the config lock')
                    config.upsert(Binding({'combo': 'Z', 'exec': 'true'}, 0))
                    config.save()
                except BaseException:
                    proc.kill()
                    proc.wait()
                    raise
            self.assertEqual(proc.wait(timeout=10), 0)
            after = load(path)
            self.assertEqual(after.input_mode, 'os')
            self.assertIn(('Z',), {b.combo for b in after.bindings})


class SnapshotTests(unittest.TestCase):
    def test_eviocgkey_uses_current_state_bitmap_and_propagates_failure(self):
        def ioctl(fd, request, buf):
            self.assertEqual((fd, request), (999, li.EVIOCGKEY(96)))
            for code in (30, 304, 767):
                buf[code // 8] |= 1 << (code % 8)
        with patch('engine.linux_input.fcntl.ioctl', side_effect=ioctl):
            self.assertEqual({c for c in range(li.KEY_CNT) if li.bit_is_set(li.read_key_state(999, strict=True), c)}, {30, 304, 767})
        with patch('engine.linux_input.fcntl.ioctl', side_effect=OSError('denied')):
            with self.assertRaises(OSError):
                li.read_key_state(999, strict=True)

    def pad(self, keys=(), axes=None, aliases=None, guarded=True):
        axes = axes or {}
        info = SimpleNamespace(path='/fake/event0', name='Mock pad', abs_codes=list(axes), abs_info={code: {'value': 1000, 'min': -1000, 'max': 1000} for code in axes})
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch('engine.devices.li.open_event_device', return_value=999))
        self.grab = self.stack.enter_context(patch('engine.devices.li.grab', return_value=True))
        self.stack.enter_context(patch('engine.devices.os.close'))
        self.read = self.stack.enter_context(patch('engine.devices.os.read', side_effect=BlockingIOError))
        self.keys = self.stack.enter_context(patch('engine.devices.li.read_key_state', return_value=self.bitmap(keys)))
        self.abs = self.stack.enter_context(patch('engine.devices.li.read_abs_info', side_effect=lambda fd, code: axes[code]))
        return Gamepad(info, {}, exclusive=True, aliases=aliases, guarded=guarded)

    @staticmethod
    def bitmap(keys):
        return bytes(sum(1 << (c % 8) for c in keys if c // 8 == i) for i in range((li.KEY_CNT + 7) // 8))

    def events(self, *events):
        self.read.side_effect = [b''.join(li.pack_event(*event) for event in events), BlockingIOError(), BlockingIOError()]

    def test_held_start_is_not_ready_and_raw_identity_is_unaliased(self):
        pad = self.pad(keys={304}, aliases={'A': 'B'})
        self.assertFalse(pad.ready)
        self.assertFalse(pad.grabbed)
        self.grab.assert_not_called()
        self.assertEqual(pad.held, {'A'})
        self.keys.return_value = self.bitmap(set())
        self.events((li.EV_KEY, 304, 0))
        self.assertEqual(pad.read(), [])
        self.assertTrue(pad.ready)
        self.events((li.EV_KEY, 304, 1))
        self.assertEqual(pad.read(), [('B', True)])
        self.assertEqual(pad.held, {'A'})

    def test_press_racing_acquisition_releases_grab_for_original_consumer(self):
        pad = self.pad()
        pad.grabbed = False
        self.grab.reset_mock()
        self.keys.side_effect = [self.bitmap(set()), self.bitmap({304})]
        self.assertFalse(pad.retry_grab(True))
        self.assertEqual(self.grab.call_args_list, [unittest.mock.call(999, True), unittest.mock.call(999, False)])
        self.assertFalse(pad.grabbed)
        self.assertFalse(pad.ready)
        self.assertEqual(pad.held, {'A'})

    def test_malformed_key_values_do_not_release_held_input(self):
        pad = self.pad()
        self.events((li.EV_KEY, 304, 1))
        self.assertEqual(pad.read(), [('A', True)])
        for value in (-1, 2, 3):
            self.events((li.EV_KEY, 304, value))
            self.assertEqual(pad.read(), [])
            self.assertEqual(pad.held, {'A'})
        self.events((li.EV_KEY, 304, 0))
        self.assertEqual(pad.read(), [('A', False)])
        self.assertEqual(pad.held, set())

    def test_two_raw_buttons_aliased_to_one_token_preserve_held_identity(self):
        pad = self.pad(aliases={'A': 'X', 'B': 'X'})
        self.events((li.EV_KEY, 304, 1), (li.EV_KEY, 305, 1))
        self.assertEqual(pad.read(), [('X', True)])
        self.events((li.EV_KEY, 304, 0))
        self.assertEqual(pad.read(), [])
        self.assertEqual(pad.held, {'B'})
        self.events((li.EV_KEY, 305, 0))
        self.assertEqual(pad.read(), [('X', False)])

    def test_axis_snapshot_is_fresh_normalized_and_neutral_guarded(self):
        pad = self.pad(axes={0: {'value': 50, 'min': -100, 'max': 100}, 2: {'value': 0, 'min': 0, 'max': 255}})
        self.assertEqual(pad.axes, {0: 0.5, 2: 0.0})
        self.assertTrue(pad.ready)
        self.assertTrue(pad.neutral)
        self.assertFalse(pad.acquisition_neutral)
        self.assertFalse(pad.grabbed)
        self.assertIn("axis 0=0.500", pad.safety_error)
        self.assertEqual(pad.info.abs_info[0]['max'], 100)
        self.abs.side_effect = lambda fd, code: {'value': 0, 'min': -100 if code == 0 else 0, 'max': 100}
        self.assertTrue(pad.resync())
        self.assertEqual(pad.axes[0], 0.0)

    def test_game_can_capture_while_sticks_drift_below_mapping_threshold(self):
        pad = self.pad(axes={0:{'value':20,'min':-100,'max':100}})
        self.assertTrue(pad.ready)
        self.assertFalse(pad.grabbed)
        self.events((li.EV_KEY,304,1))
        self.assertEqual(pad.read(),[('A',True)])
        self.events((li.EV_KEY,304,0))
        self.assertEqual(pad.read(),[('A',False)])

    def test_snapshot_failure_is_not_neutral(self):
        pad = self.pad()
        self.keys.side_effect = OSError('denied')
        self.assertFalse(pad.resync())
        self.assertFalse(pad.ready)
        self.assertIn('snapshot failed', pad.safety_error)

    def test_overflow_discards_until_syn_report_and_resnapshots(self):
        pad = self.pad()
        self.events((li.EV_KEY, 304, 1), (li.EV_SYN, li.SYN_DROPPED, 0), (li.EV_KEY, 305, 1))
        self.assertEqual(pad.read(), [])
        self.assertFalse(pad.ready)
        self.keys.return_value = self.bitmap({305})
        self.events((li.EV_KEY, 304, 0), (li.EV_SYN, li.SYN_REPORT, 0), (li.EV_KEY, 304, 1))
        self.assertEqual(pad.read(), [])
        self.assertEqual(pad.held, {'B'})
        self.assertFalse(pad.ready)
        self.keys.return_value = self.bitmap(set())
        self.events((li.EV_KEY, 305, 0))
        self.assertEqual(pad.read(), [])
        self.assertTrue(pad.ready)

    def test_stale_queued_press_is_discarded_on_transition(self):
        pad = self.pad()
        self.events((li.EV_KEY, 304, 1), (li.EV_KEY, 304, 0))
        self.assertTrue(pad.resync())
        self.assertEqual(pad.held, set())

    def test_rescan_can_finish_overflow_recovery_at_syn_report(self):
        pad = self.pad()
        pad._sync_dropped = True
        pad.ready = False
        self.events((li.EV_SYN, li.SYN_REPORT, 0))
        self.assertTrue(pad.resync())
        self.assertFalse(pad._sync_dropped)

    def test_legacy_does_not_snapshot_keys_or_discard_input(self):
        pad = self.pad(guarded=False)
        self.keys.assert_not_called()
        self.read.assert_not_called()
        self.events((li.EV_KEY, 304, 1))
        self.assertEqual(pad.read(), [('A', True)])


class FakePad:
    def __init__(self, info=None, settings=None, exclusive=True, aliases=None, guarded=True, path='/fake/0'):
        self.path = info.path if info else path
        self.name = 'Mock pad'
        self.aliases = aliases or {}
        self.grabbed = exclusive
        self.ready = True
        self.held = set()
        self.axes = {}
        self.resync_generation = 0
        self.events = []
        self.allow_grab = True
        self.closed = False
        self.safety_error = ''

    @property
    def neutral(self):
        return not self.held

    @property
    def acquisition_neutral(self):
        return self.neutral and not any(abs(v) > 0.15 for v in self.axes.values())

    def apply(self, settings, aliases):
        self.aliases = aliases

    def read(self):
        was_ready = self.ready
        events, self.events = self.events, []
        for token, pressed in events:
            if pressed:
                self.held.add(token)
            else:
                self.held.discard(token)
        if not was_ready:
            self.resync()
            return []
        return [(self.aliases.get(token, token), pressed) for token, pressed in events]

    def resync(self):
        self.resync_generation += 1
        self.ready = self.neutral
        self.events = []
        return self.ready

    def retry_grab(self, exclusive):
        if self.allow_grab or not exclusive:
            self.grabbed = exclusive
        return self.grabbed == exclusive

    def close(self):
        self.grabbed = False
        self.closed = True


class DaemonModeTests(unittest.TestCase):
    def daemon(self, mode='os', pads=1, config=None):
        runner = Mock()
        runner.validate.return_value = None
        runner.run.return_value = (True, 'mock')
        with patch('engine.daemon.ActionRunner', return_value=runner):
            daemon = Daemon(config or configuration(mode), stream=io.StringIO())
        for index in range(pads):
            pad = FakePad(path=f'/fake/{index}', exclusive=mode == 'os')
            daemon.pads[pad.path] = pad
        daemon._arm_neutral()
        daemon._advance_neutral()
        return daemon, runner

    def press(self, daemon, pad, token='A', pressed=True):
        pad.events = [(token, pressed)]
        daemon._pump(pad, 1.0)

    def test_game_never_runs_desktop_actions_even_direct_fire(self):
        daemon, runner = self.daemon('game')
        self.assertFalse(daemon.firing)
        self.assertEqual(daemon.input_status, 'passthrough')
        daemon._fire(Activation(daemon.config.bindings[0], 'press'))
        self.press(daemon, next(iter(daemon.pads.values())))
        runner.run.assert_not_called()

    def test_pending_reload_or_safety_reset_blocks_actions_immediately(self):
        for flag in ('_reload_requested', '_safety_reset_requested'):
            with self.subTest(flag=flag):
                daemon, runner = self.daemon()
                setattr(daemon, flag, True)
                self.assertFalse(daemon.safe_ready)
                daemon._fire(Activation(daemon.config.bindings[0], 'press'))
                self.press(daemon, next(iter(daemon.pads.values())))
                runner.run.assert_not_called()

    def test_os_grab_failure_blocks_and_recovers(self):
        daemon, runner = self.daemon()
        pad = next(iter(daemon.pads.values()))
        pad.grabbed = False
        pad.allow_grab = False
        self.assertEqual(daemon.input_status, 'waiting_grab')
        self.press(daemon, pad)
        runner.run.assert_not_called()
        pad.held.clear()
        pad.allow_grab = True
        daemon.scanner = Mock()
        daemon.scanner.find_pads.return_value = [SimpleNamespace(path=pad.path)]
        daemon.rescan()
        self.assertEqual(daemon.input_status, 'ready')
        self.press(daemon, pad)
        runner.run.assert_called_once()

    def test_held_reconnect_requires_all_inputs_neutral(self):
        daemon, runner = self.daemon(pads=2)
        first, second = daemon.pads.values()
        second.held = {'B'}
        daemon._arm_neutral()
        self.press(daemon, first)
        self.assertEqual(daemon.input_status, 'waiting_neutral')
        runner.run.assert_not_called()
        self.press(daemon, first, pressed=False)
        self.press(daemon, second, token='B', pressed=False)
        self.assertEqual(daemon.input_status, 'ready')
        self.press(daemon, first)
        runner.run.assert_called_once()

    def test_same_token_on_two_pads_is_reference_counted(self):
        daemon, runner = self.daemon(pads=2)
        first, second = daemon.pads.values()
        self.press(daemon, first)
        self.press(daemon, second)
        runner.run.assert_called_once()
        self.press(daemon, first, pressed=False)
        self.assertEqual(daemon.engine.held, {'A'})
        self.press(daemon, second, pressed=False)
        self.assertEqual(daemon.engine.held, set())

    def test_disconnect_does_not_forget_other_pad_is_physically_held(self):
        daemon, runner = self.daemon(pads=2)
        first, second = daemon.pads.values()
        self.press(daemon, second)
        runner.run.reset_mock()
        daemon._drop_pad(first.path, 'mock-disconnect')
        self.assertFalse(daemon.firing)
        self.assertEqual(second.held, {'A'})
        self.press(daemon, second, pressed=False)
        self.press(daemon, second)
        runner.run.assert_called_once()

    def test_pause_resume_resets_outputs_and_drops_repeat(self):
        daemon, runner = self.daemon()
        pad = next(iter(daemon.pads.values()))
        self.press(daemon, pad)
        runner.run.reset_mock()
        before = runner.close.call_count
        daemon.paused = True
        daemon._process_safety_changes()
        self.assertEqual(runner.close.call_count, before)
        self.assertEqual(daemon.engine.tick(100), [])
        daemon.paused = False
        daemon._process_safety_changes()
        self.assertEqual(daemon.input_status, 'waiting_neutral')
        runner.run.assert_not_called()
        self.press(daemon, pad, pressed=False)
        self.press(daemon, pad)
        runner.run.assert_called_once()

    def test_resync_generation_change_clears_pending_output(self):
        daemon, runner = self.daemon()
        pad = next(iter(daemon.pads.values()))
        self.press(daemon, pad)
        runner.run.reset_mock()
        def overflow():
            pad.resync_generation += 1
            pad.ready = False
            pad.held = {'B'}
            return []
        pad.read = overflow
        daemon._pump(pad, 2)
        self.assertEqual(daemon.engine.tick(100), [])
        self.assertFalse(daemon.firing)
        runner.run.assert_not_called()

    def test_overflow_on_second_pad_blocks_first_pad_in_same_ready_batch(self):
        daemon, runner = self.daemon(pads=2)
        first, second = daemon.pads.values()
        first.events = [('A', True)]
        def overflow():
            second.resync_generation += 1
            second.ready = False
            second.held = {'B'}
            return []
        second.read = overflow
        daemon._pump_batch([first, second], 1)
        runner.run.assert_not_called()
        self.assertFalse(daemon.firing)

    def test_neutral_barrier_resnapshots_every_pad_before_output(self):
        daemon, runner = self.daemon(pads=2)
        first, second = daemon.pads.values()
        daemon._neutral_required = True
        original = second.resync
        def raced_press():
            second.held = {'B'}
            return original()
        second.resync = raced_press
        daemon._advance_neutral()
        self.assertTrue(daemon._neutral_required)
        self.press(daemon, first)
        runner.run.assert_not_called()

    def test_master_disable_reload_releases_grab_and_keyboard(self):
        daemon, runner = self.daemon()
        old_pad = next(iter(daemon.pads.values()))
        new_config = configuration(enabled=False)
        daemon.scanner = Mock()
        daemon.scanner.find_pads.return_value = [SimpleNamespace(path='/fake/new', button_tokens=['A'])]
        with patch('engine.daemon.load', return_value=new_config), patch('engine.daemon.Gamepad', side_effect=FakePad):
            daemon._apply_reload()
        self.assertTrue(old_pad.closed)
        self.assertFalse(next(iter(daemon.pads.values())).grabbed)
        self.assertEqual(daemon.input_status, 'disabled')
        runner.close.assert_not_called()
        runner.run.assert_not_called()

    def test_mode_reload_releases_grab_game_and_rearms_os(self):
        daemon, runner = self.daemon()
        daemon.scanner = Mock()
        daemon.scanner.find_pads.return_value = [SimpleNamespace(path='/fake/new', button_tokens=['A'])]
        with patch('engine.daemon.load', return_value=configuration('game')), patch('engine.daemon.Gamepad', side_effect=FakePad):
            daemon._apply_reload()
        self.assertFalse(next(iter(daemon.pads.values())).grabbed)
        self.assertEqual(daemon.input_status, 'passthrough')
        with patch('engine.daemon.load', return_value=configuration('os')), patch('engine.daemon.Gamepad', side_effect=FakePad):
            daemon._apply_reload()
        self.assertTrue(next(iter(daemon.pads.values())).grabbed)
        self.assertEqual(daemon.input_status, 'ready')

    def test_status_exposes_requested_and_effective_ownership(self):
        daemon, _ = self.daemon()
        daemon.emit_state()
        state = json.loads(daemon.stream.getvalue().splitlines()[-1])
        self.assertEqual((state['input_mode'], state['input_status'], state['input_ready']), ('os', 'ready', True))
        self.assertTrue(state['requested_exclusive'])
        self.assertTrue(state['effective_exclusive'])

    def test_bindings_only_reload_keeps_pad_and_prepared_keyboard(self):
        daemon, runner = self.daemon()
        pad = next(iter(daemon.pads.values()))
        daemon.scanner = Mock()
        daemon.scanner.find_pads.return_value = [SimpleNamespace(path=pad.path)]
        updated = configuration(bindings=[{'combo':'B','keys':'SPACE'}])
        with patch('engine.daemon.load', return_value=updated), patch('engine.daemon.Gamepad') as reopen:
            daemon._apply_reload()
        reopen.assert_not_called()
        self.assertIs(daemon.pads[pad.path], pad)
        self.assertFalse(pad.closed)
        runner.close.assert_not_called()
        runner.prepare.assert_called_once()
        self.assertEqual(daemon.engine.held,set())

    def test_fast_retry_only_for_enabled_connected_waiting_grab(self):
        daemon, _ = self.daemon(pads=0)
        self.assertFalse(daemon._waiting_for_grab())
        pad = FakePad(exclusive=False)
        daemon.pads[pad.path] = pad
        self.assertTrue(daemon._waiting_for_grab())
        daemon.config.enabled = False
        self.assertFalse(daemon._waiting_for_grab())
        daemon.config.enabled = True
        daemon.paused = True
        self.assertFalse(daemon._waiting_for_grab())
        daemon.paused = False
        pad.grabbed = True
        self.assertFalse(daemon._waiting_for_grab())

    def test_drift_after_grab_does_not_block_os_actions(self):
        daemon, runner = self.daemon()
        pad = next(iter(daemon.pads.values()))
        pad.axes[0] = 0.2
        daemon._arm_neutral()
        daemon._advance_neutral()
        self.assertTrue(daemon.firing)
        self.press(daemon,pad)
        runner.run.assert_called_once()

    def test_saved_modes_are_in_authoritative_bindings_snapshot(self):
        daemon, _ = self.daemon('game')
        daemon.emit_bindings()
        event = json.loads(daemon.stream.getvalue().splitlines()[-1])
        self.assertEqual(event['modes'],{'enabled':True,'active':'game'})

    def test_legacy_fire_and_sharing_are_unchanged(self):
        daemon, runner = self.daemon(config=Config({'bindings': [{'combo': 'A', 'keys': 'RETURN'}]}))
        self.assertEqual(daemon.input_status, 'legacy')
        daemon._pump(next(iter(daemon.pads.values())), 1)
        self.press(daemon, next(iter(daemon.pads.values())))
        runner.run.assert_called_once()


if __name__ == '__main__':
    unittest.main()
