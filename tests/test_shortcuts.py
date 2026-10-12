"""Shortcut picker exports actions that the mapper can execute without typing."""
import shlex
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.keys import parse_keys
from engine.shortcuts import parse_catalog


class ShortcutCatalogTests(unittest.TestCase):
    def test_descriptions_and_modifiers_are_preserved(self):
        options = parse_catalog("SUPER SHIFT + RETURN → Browser\nSUPER + I → Toggle keyboard\n", {}, "/plugin/bin/omarchy-shortcuts")
        self.assertEqual(options[0]["keys"], "SUPER+SHIFT+RETURN")
        self.assertEqual(options[0]["description"], "Browser")
        self.assertEqual(options[1]["keys"], "SUPER+I")
        for option in options:
            parse_keys(option["keys"])

    def test_same_action_on_different_keys_stays_distinct(self):
        options = parse_catalog("SUPER + Q → Close\nSUPER + W → Close\nSUPER + Q → Close\n", {}, "/helper")
        self.assertEqual(len(options), 2)
        self.assertNotEqual(options[0]["value"], options[1]["value"])

    def test_brackets_and_media_shortcuts_resolve(self):
        names = ["BRACKETLEFT", "BRACKETRIGHT", "XF86AudioPause", "XF86Calculator", "XF86Eject", "XF86KbdBrightnessDown", "XF86KbdBrightnessUp", "XF86KbdLightOnOff", "XF86PowerOff", "XF86TouchpadOff", "XF86TouchpadOn", "XF86TouchpadToggle"]
        for name in names:
            with self.subTest(name=name):
                option = parse_catalog(f"SHIFT + {name} → Test", {}, "/helper")[0]
                self.assertEqual(len(parse_keys(option["keys"])), 2)

    def test_wheel_action_is_resolved_at_execution_time(self):
        row = "SUPER + mouse_down → Scroll workspace"
        options = parse_catalog(row, {row: ("lua", 'hl.dsp.focus({ workspace = "e+1" })')}, "/path with spaces/helper")
        self.assertEqual(shlex.split(options[0]["exec"]), ["/path with spaces/helper", "run", row])
        self.assertNotIn("keys", options[0])

    def test_missing_or_stale_nonkeyboard_metadata_is_not_used(self):
        row = "SUPER + mouse_down → Scroll workspace"
        self.assertEqual(parse_catalog(row, {"old row": ("lua", "wrong")}, "/helper"), [])
        self.assertEqual(parse_catalog("", {}, "/helper"), [])


if __name__ == "__main__":
    unittest.main()
