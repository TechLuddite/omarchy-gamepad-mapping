"""Pure standard-key catalog tests: no compositor or virtual keyboard."""

import contextlib
import io
import json
import unittest
from unittest.mock import patch

from engine.cli import main
from engine.keyboard_catalog import keyboard_catalog
from engine.keys import parse_keys


class KeyboardCatalogTests(unittest.TestCase):
    def test_every_offered_key_is_unique_and_parses_to_one_keycode(self):
        rows = keyboard_catalog()
        self.assertEqual(len(rows), 119)
        self.assertEqual(len({row["value"] for row in rows}), len(rows))
        for row in rows:
            with self.subTest(row=row["value"]):
                self.assertEqual(row["value"], row["keys"])
                self.assertEqual(len(parse_keys(row["keys"])), 1)
                self.assertNotIn("exec", row)

    def test_covers_navigation_iso_punctuation_keypad_and_function_keys(self):
        names = {row["value"] for row in keyboard_catalog()}
        self.assertTrue({"A", "0", "F24", "KPENTER", "LEFTBRACE", "102ND",
                         "SLASH", "RIGHTCTRL", "ENTER", "SYSRQ"} <= names)

    def test_search_labels_include_friendly_names_and_canonical_names(self):
        rows = {row["value"]: row for row in keyboard_catalog()}
        for name, term in (("ENTER", "Return"), ("LEFTBRACE", "bracket"),
                           ("SYSRQ", "Print screen"), ("LEFTMETA", "Super")):
            with self.subTest(name=name):
                self.assertIn(term, rows[name]["label"])
                self.assertIn(name, rows[name]["description"])

    def test_catalog_does_not_read_compositor_or_config(self):
        out = io.StringIO()
        with patch("subprocess.check_output", side_effect=AssertionError), \
                patch("engine.cli._load", side_effect=AssertionError), \
                contextlib.redirect_stdout(out):
            self.assertEqual(main(["keyboard-keys"]), 0)
        self.assertEqual(len(json.loads(out.getvalue())), 119)


if __name__ == "__main__":
    unittest.main()


class FriendlySearchTests(unittest.TestCase):
    def test_common_spaced_names_and_aliases_are_searchable(self):
        rows = keyboard_catalog()
        for term, expected in [('page up','PAGEUP'),('caps lock','CAPSLOCK'),('keypad 5','KP5'),('backtick','GRAVE'),('tilde','GRAVE'),('plus','EQUAL'),('BRACKETLEFT','LEFTBRACE'),('PGUP','PAGEUP'),('PRINT','SYSRQ')]:
            matches = [r['keys'] for r in rows if term.lower() in (r['label']+' '+r['description']).lower()]
            self.assertIn(expected,matches,term)
