"""Key parser regressions. Never open a keyboard or input device."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.keys import KeyParseError, parse_keys, resolve_key


# Fixed Linux input-event-codes.h ABI values, not the production alias/code
# tables. XKB evdev keycodes are these numbers + 8 (e.g. AudioPause 209).
# https://github.com/torvalds/linux/blob/master/include/uapi/linux/input-event-codes.h
ADDITIONS = {
    "bracketleft": 26,
    "bracketright": 27,
    "XF86AudioPause": 201,
    "XF86Calculator": 140,
    "XF86Eject": 161,
    "XF86KbdBrightnessDown": 229,
    "XF86KbdBrightnessUp": 230,
    "XF86KbdLightOnOff": 228,
    "XF86PowerOff": 116,
    "XF86TouchpadOff": 532,
    "XF86TouchpadOn": 531,
    "XF86TouchpadToggle": 530,
}


class TestKeyAliases(unittest.TestCase):
    def test_new_spellings_resolve_to_linux_codes(self):
        for spelling, code in ADDITIONS.items():
            with self.subTest(spelling=spelling):
                self.assertEqual(resolve_key(spelling), code)
                self.assertEqual(resolve_key(spelling.swapcase()), code)

    def test_new_spellings_compose_with_modifiers(self):
        for spelling, code in ADDITIONS.items():
            with self.subTest(spelling=spelling):
                self.assertEqual(parse_keys(f"Super+Ctrl+Shift+{spelling}"), [
                    125, 29, 42, code,
                ])

    def test_existing_aliases_keep_their_meaning(self):
        baseline = {
            "SUPER": 125, "META": 125, "WIN": 125,
            "CMD": 125, "MOD": 125, "CTRL": 29,
            "CONTROL": 29, "ALT": 56, "OPT": 56,
            "SHIFT": 42, "RETURN": 28, "CR": 28,
            "ESCAPE": 1, "DEL": 111, "PGUP": 104,
            "PGDN": 109, "PRINT": 99, "PRTSC": 99,
            "PRINTSCREEN": 99, "PERIOD": 52, "PLUS": 13,
            "RETURN_KP": 96, "XF86AUDIORAISEVOLUME": 115,
            "XF86AUDIOLOWERVOLUME": 114, "XF86AUDIOMUTE": 113,
            "XF86AUDIOMICMUTE": 248, "XF86AUDIOPLAY": 164,
            "XF86AUDIONEXT": 163, "XF86AUDIOPREV": 165,
            "XF86MONBRIGHTNESSUP": 225,
            "XF86MONBRIGHTNESSDOWN": 224,
        }
        for alias, code in baseline.items():
            with self.subTest(alias=alias):
                self.assertEqual(resolve_key(alias), code)
        self.assertEqual(parse_keys("SUPER+RETURN"), [125, 28])
        self.assertEqual(resolve_key("KEY_A"), 30)

    def test_invalid_names_still_fail(self):
        for spelling in ("", "XF86NotARealKey", "bracketmiddle", "KEY_NO_SUCH_KEY", "code:34", "code:35"):
            with self.subTest(spelling=spelling):
                with self.assertRaises(KeyParseError):
                    resolve_key(spelling)
        with self.assertRaises(KeyParseError):
            parse_keys("Super+NotARealKey")
        with self.assertRaises(KeyParseError):
            parse_keys("")


if __name__ == "__main__":
    unittest.main()
