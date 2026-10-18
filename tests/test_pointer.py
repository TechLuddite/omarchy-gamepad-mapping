"""Pure pointer fixtures. No input devices, compositor or live uinput calls."""
import math
import struct
import unittest
from unittest.mock import patch

from engine import linux_input as li
from engine.pointer import (BTN_LEFT, BTN_RIGHT, REL_HWHEEL, REL_WHEEL,
                            UI_SET_RELBIT, NullPointer, PointerConfigError,
                            PointerController, PointerSettings, VirtualPointer,
                            validate_pointer)


class Output:
    def __init__(self):
        self.moves = []
        self.scrolls = []
        self.buttons = set()
        self.button_events = []
        self.closed = 0
        self.releases = 0

    def move(self, x, y): self.moves.append((x, y))
    def scroll(self, h, v): self.scrolls.append((h, v))
    def set_button(self, button, pressed):
        self.button_events.append((button, pressed))
        (self.buttons.add if pressed else self.buttons.discard)(button)
    def release_all(self):
        for button in sorted(self.buttons):
            self.button_events.append((button, False))
        self.buttons.clear()
        self.releases += 1
    def close(self): self.closed += 1


def controller(**options):
    sink = Output()
    return PointerController({"enabled": True, "buttons":{"A":"left","B":"right"}, **options}, sink), sink


def tick(engine, now, axes=None, held=(), blocked=(), allowed=True):
    engine.tick(now, axes or {}, held, blocked, allowed)


class PointerValidationTests(unittest.TestCase):
    def test_disabled_defaults_and_none_sticks(self):
        self.assertFalse(validate_pointer().enabled)
        self.assertEqual(validate_pointer({"pointer_stick": "none", "scroll_stick": "none"}).speed, 900)
        self.assertEqual(validate_pointer({"buttons": {}}).buttons, {})

    def test_button_aliases_custom_targets_and_duplicates(self):
        self.assertEqual(validate_pointer({"buttons": {"south": "left", "accept": "right"}}).buttons,
                         {"A": "left", "ACCEPT": "right"})
        for value in ({"SOUTH": "left", "A": "right"}, {"A+B": "left"},
                      {"": "left"}, {"A": "middle"}, {"A": []}, {1: "left"}):
            with self.subTest(value=value), self.assertRaises(PointerConfigError):
                validate_pointer({"buttons": value})

    def test_types_ranges_same_stick_and_unknown_options(self):
        cases = [False, [], {"enabled": 1}, {"invert_scroll": "false"},
                 {"speed": True}, {"speed": 0}, {"speed": 4001},
                 {"scroll_speed": 0}, {"scroll_speed": 61}, {"speed": math.inf},
                 {"dead_zone": .95}, {"dead_zone": -.1}, {"dead_zone": math.nan},
                 {"scroll_dead_zone": .95}, {"pointer_stick": "right"},
                 {"scroll_stick": "left"}, {"pointer_stick": "other"},
                 {"buttons": []}, {"sped": 900}]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(PointerConfigError):
                validate_pointer(case)
        validate_pointer({"speed": 4000, "scroll_speed": 60, "dead_zone": 0})


class PointerPolicyTests(unittest.TestCase):
    def test_disabled_and_game_never_open_output(self):
        with patch("engine.pointer.os.open", side_effect=AssertionError("input must stay closed")):
            for engine in (PointerController(), PointerController({"enabled": True})):
                tick(engine, 0, held={"A"}, axes={0: 1}, allowed=False)
                tick(engine, 1, held={"A"}, axes={0: 1}, allowed=False)
                engine.close()
            tick(PointerController(), 0, axes={0: 1}, held={"A"})

    def test_activation_requires_button_release_and_neutral(self):
        engine, sink = controller()
        tick(engine, 0, {0: 1}, {"A"})
        tick(engine, .02, {0: 1}, {"A"})
        self.assertFalse(sink.moves or sink.buttons)
        tick(engine, .03, {}, ())
        tick(engine, .05, {0: 1}, {"SOUTH"})
        self.assertEqual(sink.buttons, {"left"})
        self.assertGreater(sum(x for x, _ in sink.moves), 0)

    def test_motion_total_is_independent_of_tick_partition_and_fractional(self):
        totals = []
        for rate in (50, 100, 200):
            engine, sink = controller(speed=123)
            tick(engine, 0)
            for index in range(1, rate + 1):
                tick(engine, index / rate, {0: 1})
            totals.append(sum(x for x, _ in sink.moves))
        self.assertLessEqual(max(totals) - min(totals), 1)
        self.assertTrue(all(abs(value - 123) <= 1 for value in totals))

    def test_deadzone_radial_acceleration_and_diagonal_speed_limit(self):
        engine, sink = controller(speed=1000)
        tick(engine, 0)
        tick(engine, .02, {0: .1, 1: .1})
        self.assertFalse(sink.moves)
        tick(engine, .04, {0: .5})
        slow = math.hypot(*sink.moves[-1])
        tick(engine, .06, {0: 1})
        fast = math.hypot(*sink.moves[-1])
        self.assertLess(slow, fast)
        tick(engine, .08, {0: 1, 1: 1})
        self.assertLessEqual(math.hypot(*sink.moves[-1]), 20)

    def test_scroll_fraction_direction_inversion_and_stick_swap(self):
        for inverted in (False, True):
            engine, sink = controller(pointer_stick="right", scroll_stick="left",
                                      scroll_speed=10, invert_scroll=inverted)
            tick(engine, 0)
            for index in range(1, 101):
                tick(engine, index / 100, {0: 1, 1: 1})
            h, v = map(sum, zip(*sink.scrolls))
            self.assertGreater(abs(h), 0)
            self.assertEqual(h, -v)
            self.assertEqual(h > 0, not inverted)
            self.assertFalse(sink.moves)

    def test_stall_backward_clock_and_nonfinite_axes_do_not_jump(self):
        engine, sink = controller(speed=1000)
        tick(engine, 1)
        tick(engine, 100, {0: 1})
        self.assertEqual(sink.moves, [(50, 0)])
        tick(engine, 99, {0: 1})
        self.assertEqual(sink.moves, [(50, 0)])
        tick(engine, 99.02, {0: math.nan, 1: math.inf})
        self.assertEqual(sink.moves, [(50, 0)])
        tick(engine, 99.04, held={"A"})
        self.assertTrue(sink.buttons)
        with self.assertRaises(ValueError):
            tick(engine, math.nan)
        self.assertFalse(sink.buttons)

    def test_saved_button_bindings_win_and_held_unblock_needs_release(self):
        engine, sink = controller()
        tick(engine, 0)
        tick(engine, .01, held={"A"}, blocked={"SOUTH"})
        tick(engine, .02, held={"A"})
        self.assertFalse(sink.buttons)
        tick(engine, .03)
        tick(engine, .04, held={"A"})
        self.assertEqual(sink.buttons, {"left"})
        tick(engine, .05, held={"A"}, blocked={"A"})
        self.assertFalse(sink.buttons)

    def test_claimed_direction_reserves_whole_stick_and_requires_center_on_unblock(self):
        engine, sink = controller()
        tick(engine, 0)
        tick(engine, .02, {0: 1}, blocked={"LSTICK_UP"})
        tick(engine, .04, {0: 1})
        self.assertFalse(sink.moves)
        tick(engine, .06)
        tick(engine, .08, {0: 1})
        self.assertTrue(sink.moves)

    def test_disable_releases_drag_and_reenable_requires_new_press(self):
        engine, sink = controller()
        tick(engine, 0)
        tick(engine, .02, held={"A"})
        self.assertEqual(sink.buttons, {"left"})
        tick(engine, .04, held={"A"}, allowed=False)
        self.assertFalse(sink.buttons)
        tick(engine, .06, held={"A"})
        self.assertFalse(sink.buttons)
        tick(engine, .08)
        tick(engine, .1, held={"A"})
        self.assertEqual(sink.buttons, {"left"})
        engine.reset()
        self.assertFalse(sink.buttons)

    def test_two_tokens_for_one_action_do_not_release_until_both_up(self):
        engine, sink = controller(buttons={"A": "left", "X": "left"})
        tick(engine, 0)
        tick(engine, .02, held={"A", "X"})
        tick(engine, .04, held={"X"})
        self.assertEqual(sink.button_events, [("left", True)])
        tick(engine, .06)
        self.assertEqual(sink.button_events[-1], ("left", False))

    def test_output_errors_release_reset_and_reraise(self):
        engine, sink = controller()
        tick(engine, 0)
        tick(engine, .02, held={"A"})
        with patch.object(sink, "move", side_effect=OSError("lost mouse")):
            with self.assertRaisesRegex(OSError, "lost mouse"):
                tick(engine, .04, {0: 1}, {"A"})
        self.assertFalse(sink.buttons)
        tick(engine, .06, {0: 1}, {"A"})
        self.assertFalse(sink.buttons)

    def test_reset_failure_still_closes_and_forgets_activation(self):
        engine, sink = controller()
        tick(engine, 0)
        with patch.object(sink, "release_all", side_effect=OSError("release failed")):
            with self.assertRaisesRegex(OSError, "release failed"):
                engine.reset()
        self.assertEqual(sink.closed, 1)
        tick(engine, .02, held={"A"}, axes={0: 1})
        self.assertFalse(sink.buttons or sink.moves)

    def test_zero_deadzone_accepts_center_quantization(self):
        engine,sink = controller(dead_zone=0)
        tick(engine,0,{0:1/65535,1:1/65535})
        self.assertFalse(engine.needs_tick)
        tick(engine,.02,{0:1.})
        self.assertTrue(engine.needs_tick)
        self.assertTrue(sink.moves)

    def test_idle_does_not_request_frame_ticks(self):
        engine,sink = controller()
        tick(engine,0)
        self.assertFalse(engine.needs_tick)
        tick(engine,.02,{0:1})
        self.assertTrue(engine.needs_tick)
        tick(engine,.04)
        self.assertFalse(engine.needs_tick)

    def test_null_sink_is_explicitly_safe(self):
        with patch("engine.pointer.os.open", side_effect=AssertionError("no uinput")):
            engine = PointerController({"enabled": True}, NullPointer())
            tick(engine, 0)
            tick(engine, .02, {0: 1, 4: 1}, {"A"})
            tick(engine, .04, allowed=False)


class VirtualPointerAbiTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.calls = []
        self.open = patch("engine.pointer.os.open", return_value=41).start()
        self.ioctl = patch("engine.pointer.fcntl.ioctl", side_effect=lambda *args: self.calls.append(args)).start()
        self.close = patch("engine.pointer.os.close", side_effect=lambda fd: self.calls.append(("close", fd))).start()
        self.write = patch("engine.pointer.os.write", side_effect=self.record).start()
        self.addCleanup(patch.stopall)

    def record(self, fd, data):
        event = li.unpack_event(data)[2:]
        self.events.append(event)
        self.calls.append(("write", event))
        return len(data)

    def test_capabilities_are_mouse_only_and_open_is_lazy(self):
        mouse = VirtualPointer(settle=0)
        mouse.move(0, 0)
        mouse.release_all()
        self.open.assert_not_called()
        mouse.move(3, -2)
        self.assertIn((41, li.UI_SET_EVBIT, li.EV_REL), self.calls)
        self.assertNotIn((41, li.UI_SET_EVBIT, li.EV_ABS), self.calls)
        keybits = {args[2] for args in self.calls if len(args) == 3 and args[1] == li.UI_SET_KEYBIT}
        self.assertEqual(keybits, {BTN_LEFT, BTN_RIGHT})
        relbits = {args[2] for args in self.calls if len(args) == 3 and args[1] == UI_SET_RELBIT}
        self.assertEqual(relbits, {0, 1, 6, 8})
        setup = next(args[2] for args in self.calls if len(args) == 3 and args[1] == li.UI_DEV_SETUP)
        self.assertEqual(struct.unpack("HHHH80sI", setup)[4].split(b"\0")[0], mouse.NAME.encode())
        self.assertEqual(self.events, [(li.EV_REL, 0, 3), (li.EV_REL, 1, -2), (li.EV_SYN, 0, 0)])

    def test_wheels_and_drag_release_before_destroy(self):
        mouse = VirtualPointer(settle=0)
        mouse.scroll(2, -1)
        mouse.set_button("left", True)
        mouse.set_button("right", True)
        mouse.set_button("left", True)
        mouse.close()
        self.assertIn((li.EV_REL, REL_HWHEEL, 2), self.events)
        self.assertIn((li.EV_REL, REL_WHEEL, -1), self.events)
        self.assertEqual(self.events[-3:], [(li.EV_KEY, BTN_LEFT, 0), (li.EV_KEY, BTN_RIGHT, 0), (li.EV_SYN, 0, 0)])
        self.assertEqual(self.calls[-2:], [(41, li.UI_DEV_DESTROY), ("close", 41)])
        self.assertLess(self.calls.index(("write", (li.EV_KEY, BTN_LEFT, 0))),
                        self.calls.index((41, li.UI_DEV_DESTROY)))
        self.assertFalse(mouse.active)
        mouse.close()
        self.open.assert_called_once()

    def test_write_error_attempts_release_then_closes(self):
        mouse = VirtualPointer(settle=0)
        mouse.set_button("left", True)
        original = self.write.side_effect
        count = 0
        def failing(fd, data):
            nonlocal count
            count += 1
            if count == 1:
                raise OSError("write failed")
            return original(fd, data)
        self.write.side_effect = failing
        with self.assertRaisesRegex(OSError, "write failed"):
            mouse.move(1, 0)
        self.assertIn((li.EV_KEY, BTN_LEFT, 0), self.events)
        self.assertFalse(mouse.active)
        self.assertIn(("close", 41), self.calls)

    def test_failed_keydown_and_short_write_also_cleanup(self):
        mouse = VirtualPointer(settle=0)
        self.write.side_effect = lambda fd, data: len(data) - 1
        with self.assertRaises(OSError):
            mouse.set_button("right", True)
        self.assertFalse(mouse.active)
        self.assertIn(("close", 41), self.calls)

    def test_settle_never_sleeps_or_blocks_the_input_loop(self):
        mouse=VirtualPointer(settle=.1)
        with patch('engine.pointer.time.monotonic',return_value=2), patch('engine.pointer.time.sleep',side_effect=AssertionError('blocking sleep')):
            mouse.open()
            self.assertFalse(mouse.ready)
        with patch('engine.pointer.time.monotonic',return_value=2.2):
            self.assertTrue(mouse.ready)
        mouse.close()

    def test_setup_failure_closes_descriptor(self):
        self.ioctl.side_effect = OSError("ioctl failed")
        mouse = VirtualPointer(settle=0)
        with self.assertRaisesRegex(OSError, "ioctl failed"):
            mouse.move(1, 0)
        self.assertFalse(mouse.active)
        self.close.assert_called_once_with(41)


if __name__ == "__main__":
    unittest.main()
