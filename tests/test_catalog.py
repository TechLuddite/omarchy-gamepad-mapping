"""Pure catalog fixtures; no compositor, input devices or action execution."""

import contextlib
import io
import json
import subprocess
import unittest
from unittest.mock import patch

from engine.catalog import CatalogError, live_shortcuts, shortcut_catalog
from engine.cli import main


def binding(key="Return", modmask=64, **kwargs):
    return {"key": key, "modmask": modmask, "description": "Open terminal", **kwargs}


class ShortcutCatalogTests(unittest.TestCase):
    def test_names_and_modifier_order_use_existing_parser(self):
        row = shortcut_catalog([binding(modmask=77)])[0]
        self.assertEqual(row["keys"], "SUPER+CTRL+ALT+SHIFT+RETURN")
        self.assertIn("Open terminal", row["label"])

    def test_duplicate_chords_keep_all_distinct_descriptions(self):
        rows = shortcut_catalog([binding(), binding(), binding(description="Other action")])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["description"], "Open terminal; Other action")

    def test_unknown_keysyms_are_skipped(self):
        self.assertEqual(shortcut_catalog([binding(key="UnsupportedKeysym")]), [])

    def test_special_bind_semantics_are_skipped(self):
        for flag in ("mouse", "release", "longPress", "locked", "catch_all",
                     "catchAll", "ignore_mods", "ignoreMods", "submap",
                     "multiKey", "click", "drag", "devices"):
            with self.subTest(flag=flag):
                self.assertEqual(shortcut_catalog([binding(**{flag: "test"})]), [])
        self.assertEqual(shortcut_catalog([binding(enabled=False)]), [])

    def test_unknown_or_lock_modifier_masks_are_skipped(self):
        for mask in (-1, 2, 16, 32, 128, True, "64", None):
            with self.subTest(mask=mask):
                self.assertEqual(shortcut_catalog([binding(modmask=mask)]), [])

    def test_mouse_keycodes_and_multiple_keys_are_skipped(self):
        for key in ("mouse:272", "code:10", "", "A+B", "A,B", "mouse_up", None):
            with self.subTest(key=key):
                self.assertEqual(shortcut_catalog([binding(key=key)]), [])

    def test_numeric_or_malformed_keycode_cannot_override_a_valid_key_label(self):
        for keycode in (38, -1, True, False, "0", None, []):
            with self.subTest(keycode=keycode):
                self.assertEqual(shortcut_catalog([binding(keycode=keycode)]), [])
        self.assertEqual(len(shortcut_catalog([binding(keycode=0)])), 1)

    def test_no_dispatch_metadata_or_command_is_exposed(self):
        row = shortcut_catalog([binding(description="", dispatcher="exec", arg="private-token")])[0]
        self.assertEqual(row["description"], "Keyboard shortcut")
        self.assertNotIn("private-token", json.dumps(row))
        self.assertNotIn("exec", row)

    def test_invalid_rows_are_ignored(self):
        self.assertEqual(shortcut_catalog([None, "invalid", {}, []]), [])

    @patch.dict("os.environ", {"HYPRLAND_INSTANCE_SIGNATURE": "explicit"}, clear=True)
    @patch("engine.catalog.subprocess.check_output")
    def test_explicit_session_only_reads_binds(self, run):
        run.return_value = json.dumps([binding()])
        self.assertEqual(len(live_shortcuts()), 1)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0], ["hyprctl", "-j", "binds"])
        self.assertEqual(run.call_args.kwargs["env"]["HYPRLAND_INSTANCE_SIGNATURE"], "explicit")

    @patch.dict("os.environ", {}, clear=True)
    @patch("engine.catalog.subprocess.check_output")
    def test_single_session_is_selected_without_mutating_environment(self, run):
        run.side_effect = [json.dumps([{"instance": "only-session"}]), "[]"]
        self.assertEqual(live_shortcuts(), [])
        self.assertEqual(run.call_args.kwargs["env"]["HYPRLAND_INSTANCE_SIGNATURE"], "only-session")
        import os
        self.assertNotIn("HYPRLAND_INSTANCE_SIGNATURE", os.environ)

    @patch.dict("os.environ", {}, clear=True)
    @patch("engine.catalog.subprocess.check_output")
    def test_missing_ambiguous_or_invalid_sessions_fail_clearly(self, run):
        for value in ([], [{"instance": "a"}, {"instance": "b"}], [{}], {}):
            run.return_value = json.dumps(value)
            with self.subTest(value=value), self.assertRaises(CatalogError):
                live_shortcuts()

    @patch.dict("os.environ", {"HYPRLAND_INSTANCE_SIGNATURE": "explicit"}, clear=True)
    @patch("engine.catalog.subprocess.check_output")
    def test_failed_read_is_bounded_and_does_not_expose_stderr(self, run):
        for exc in (FileNotFoundError(), subprocess.TimeoutExpired("hyprctl", 5),
                    subprocess.CalledProcessError(1, "hyprctl")):
            run.side_effect = exc
            with self.subTest(exc=exc), self.assertRaises(CatalogError):
                live_shortcuts()
        self.assertEqual(run.call_args.kwargs["timeout"], 5)

    @patch.dict("os.environ", {"HYPRLAND_INSTANCE_SIGNATURE": "explicit"}, clear=True)
    @patch("engine.catalog.subprocess.check_output")
    def test_invalid_compositor_json_is_an_error(self, run):
        for value in ("not-json", "{}", "null"):
            run.return_value = value
            with self.subTest(value=value), self.assertRaises(CatalogError):
                live_shortcuts()

    @patch("engine.cli.live_shortcuts", return_value=[{"value": "SUPER+RETURN"}])
    def test_cli_outputs_json_without_loading_config_or_daemon(self, _read):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), patch("engine.cli._load", side_effect=AssertionError):
            self.assertEqual(main(["shortcuts"]), 0)
        self.assertEqual(json.loads(out.getvalue()), [{"value": "SUPER+RETURN"}])

    @patch("engine.cli.live_shortcuts", side_effect=CatalogError("Select a session"))
    def test_cli_reports_catalog_failure(self, _read):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(main(["shortcuts"]), 1)
        self.assertIn("Select a session", err.getvalue())


if __name__ == "__main__":
    unittest.main()
