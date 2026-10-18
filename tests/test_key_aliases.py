"""Key parser regressions. Never open a keyboard or input device."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine._codes import KEY_CODES
from engine.keys import KeyParseError, parse_keys, resolve_key


ADDITIONS = {
    "bracketleft": "LEFTBRACE",
    "bracketright": "RIGHTBRACE",
    "XF86AudioPause": "PAUSECD",
    "XF86Calculator": "CALC",
    "XF86Eject": "EJECTCD",
    "XF86KbdBrightnessDown": "KBDILLUMDOWN",
    "XF86KbdBrightnessUp": "KBDILLUMUP",
    "XF86KbdLightOnOff": "KBDILLUMTOGGLE",
    "XF86PowerOff": "POWER",
    "XF86TouchpadOff": "TOUCHPAD_OFF",
    "XF86TouchpadOn": "TOUCHPAD_ON",
    "XF86TouchpadToggle": "TOUCHPAD_TOGGLE",
}


class TestKeyAliases(unittest.TestCase):
    def test_new_spellings_resolve_to_linux_codes(self):
        for spelling, target in ADDITIONS.items():
            with self.subTest(spelling=spelling):
                self.assertEqual(resolve_key(spelling), KEY_CODES[target])
                self.assertEqual(resolve_key(spelling.swapcase()), KEY_CODES[target])

    def test_new_spellings_compose_with_modifiers(self):
        for spelling, target in ADDITIONS.items():
            with self.subTest(spelling=spelling):
                self.assertEqual(parse_keys(f"Super+Ctrl+Shift+{spelling}"), [
                    KEY_CODES["LEFTMETA"], KEY_CODES["LEFTCTRL"],
                    KEY_CODES["LEFTSHIFT"], KEY_CODES[target],
                ])

    def test_existing_aliases_keep_their_meaning(self):
        baseline = {
            "SUPER": "LEFTMETA", "META": "LEFTMETA", "WIN": "LEFTMETA",
            "CMD": "LEFTMETA", "MOD": "LEFTMETA", "CTRL": "LEFTCTRL",
            "CONTROL": "LEFTCTRL", "ALT": "LEFTALT", "OPT": "LEFTALT",
            "SHIFT": "LEFTSHIFT", "RETURN": "ENTER", "CR": "ENTER",
            "ESCAPE": "ESC", "DEL": "DELETE", "PGUP": "PAGEUP",
            "PGDN": "PAGEDOWN", "PRINT": "SYSRQ", "PRTSC": "SYSRQ",
            "PRINTSCREEN": "SYSRQ", "PERIOD": "DOT", "PLUS": "EQUAL",
            "RETURN_KP": "KPENTER", "XF86AUDIORAISEVOLUME": "VOLUMEUP",
            "XF86AUDIOLOWERVOLUME": "VOLUMEDOWN", "XF86AUDIOMUTE": "MUTE",
            "XF86AUDIOMICMUTE": "MICMUTE", "XF86AUDIOPLAY": "PLAYPAUSE",
            "XF86AUDIONEXT": "NEXTSONG", "XF86AUDIOPREV": "PREVIOUSSONG",
            "XF86MONBRIGHTNESSUP": "BRIGHTNESSUP",
            "XF86MONBRIGHTNESSDOWN": "BRIGHTNESSDOWN",
        }
        for alias, target in baseline.items():
            with self.subTest(alias=alias):
                self.assertEqual(resolve_key(alias), KEY_CODES[target])
        self.assertEqual(parse_keys("SUPER+RETURN"), [125, 28])
        self.assertEqual(resolve_key("KEY_A"), KEY_CODES["A"])

    def test_invalid_names_still_fail(self):
        for spelling in ("", "XF86NotARealKey", "bracketmiddle", "KEY_NO_SUCH_KEY"):
            with self.subTest(spelling=spelling):
                with self.assertRaises(KeyParseError):
                    resolve_key(spelling)
        with self.assertRaises(KeyParseError):
            parse_keys("Super+NotARealKey")
        with self.assertRaises(KeyParseError):
            parse_keys("")


if __name__ == "__main__":
    unittest.main()
