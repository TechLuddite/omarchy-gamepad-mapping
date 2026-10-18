"""Pure/mocked compositor context checks; no input nodes or commands opened."""

import contextlib
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.conflicts import external_bindings, report


class TestBindingIdentities(unittest.TestCase):
    def test_named_key_preserves_modifiers_description_and_submap(self):
        row = external_bindings([{
            "key": "XF86AudioRaiseVolume", "modmask": 64,
            "description": "Volume up", "submap": "media",
        }])[0]
        self.assertEqual(row, {
            "token": "KEY_VOLUMEUP", "code": 115,
            "key": "XF86AudioRaiseVolume", "description": "Volume up",
            "modifiers": 64, "submap": "media", "kind": "compositor",
        })

    def test_xkb_keycode_is_evdev_plus_eight(self):
        row = external_bindings([{"keycode": 312, "dispatcher": "exec"}])[0]
        self.assertEqual(row["code"], 304)
        self.assertEqual(row["token"], "A")
        self.assertEqual(row["description"], "exec")

    def test_literal_code_prefix_uses_xkb_numbering(self):
        self.assertEqual(external_bindings([{"key": "code:123"}])[0]["token"], "KEY_VOLUMEUP")

    def test_mouse_code_has_no_xkb_offset(self):
        row = external_bindings([{"key": "mouse:272"}])[0]
        self.assertEqual(row["code"], 272)
        self.assertEqual(row["token"], "MOUSE")

    def test_mouse_back_never_confuses_legacy_select_alias(self):
        rows = external_bindings([{"key": "mouse:278"}, {"keycode": 322}])
        self.assertEqual([(row["token"], row["code"]) for row in rows], [
            ("BACK_BUTTON", 278), ("SELECT", 314),
        ])

    def test_unknown_codes_remain_visible_without_invented_button_identity(self):
        row = external_bindings([{"keycode": 775}])[0]
        self.assertEqual(row["token"], "CODE_767")
        self.assertEqual(row["description"], "code:775 (modifiers 0)")

    def test_malformed_rows_are_skipped_without_losing_valid_rows(self):
        rows = external_bindings([
            None, [], {"key": "NotARealKey"}, {"keycode": {}},
            {"keycode": 8}, {"key": "mouse:-1"}, {"keycode": 776},
            {"key": "mouse:no"}, {"key": "a", "modmask": "bad"},
            {"key": "a", "modmask": -1}, {"key": "Return"},
        ])
        self.assertEqual([row["token"] for row in rows], ["KEY_ENTER"])

    def test_different_modifier_contexts_are_retained(self):
        rows = external_bindings([{"key": "a"}, {"key": "a", "modmask": 64}])
        self.assertEqual([row["modifiers"] for row in rows], [0, 64])
        self.assertEqual([row["token"] for row in rows], ["KEY_A", "KEY_A"])

    def test_boolean_and_float_numbers_are_not_input_identities(self):
        for field in ("keycode", "modmask"):
            for value in (True, False, 123.9, 123.0):
                with self.subTest(field=field, value=value):
                    self.assertEqual(external_bindings([{"key": "a", field: value}]), [])

    def test_integer_strings_remain_supported(self):
        row = external_bindings([{"keycode": "123", "modmask": "64"}])[0]
        self.assertEqual((row["token"], row["modifiers"]), ("KEY_VOLUMEUP", 64))


class TestReadOnlyReport(unittest.TestCase):
    def test_real_schema_reports_unidentified_keycodes(self):
        from pathlib import Path
        payload = (Path(__file__).parent / 'fixtures/hyprland-0.56.2-binds.json').read_text()
        with patch.dict("os.environ", {"HYPRLAND_INSTANCE_SIGNATURE":"fixture"}), patch("engine.conflicts.subprocess.check_output", return_value=payload):
            result = report()
        self.assertGreater(result['unidentified'],0)
        self.assertIn('KEY_VOLUMEUP',{r['token'] for r in result['bindings']})


    def test_binding_snapshot_carries_the_applied_device_aliases(self):
        from engine.config import Config
        from engine.daemon import Daemon
        from unittest.mock import Mock
        daemon = Daemon.__new__(Daemon)
        daemon.config = Config({"device": {"aliases": {"A": "B", "B": "Y"}}})
        daemon.emit = Mock()
        daemon.emit_bindings()
        self.assertEqual(daemon.emit.call_args.kwargs["aliases"], {"A": "B", "B": "Y"})

    def test_missing_session_does_not_run_a_command(self):
        with patch.dict("os.environ", {}, clear=True), patch("engine.conflicts.subprocess.check_output") as run:
            result = report()
        run.assert_not_called()
        self.assertFalse(result["available"])
        self.assertTrue(result["error"])

    def test_active_session_only_reads_binds(self):
        with patch.dict("os.environ", {"HYPRLAND_INSTANCE_SIGNATURE": "test"}), patch(
            "engine.conflicts.subprocess.check_output", return_value='[{"key":"a"}]',
        ) as run:
            result = report()
        run.assert_called_once_with(["hyprctl", "-j", "binds"], text=True, timeout=3, stderr=subprocess.DEVNULL)
        self.assertTrue(result["available"])
        self.assertEqual(result["bindings"][0]["token"], "KEY_A")
        self.assertEqual(result["error"], "")

    def test_successful_empty_result_differs_from_read_failure(self):
        with patch.dict("os.environ", {"HYPRLAND_INSTANCE_SIGNATURE": "test"}), patch(
            "engine.conflicts.subprocess.check_output", return_value="[]",
        ):
            self.assertEqual(report(), {"available": True, "bindings": [], "error": "", "unidentified": 0})

    def test_command_and_response_failures_are_explicit(self):
        failures = [
            FileNotFoundError(), PermissionError(),
            subprocess.TimeoutExpired("hyprctl", 3),
            subprocess.CalledProcessError(1, "hyprctl"),
        ]
        with patch.dict("os.environ", {"HYPRLAND_INSTANCE_SIGNATURE": "test"}):
            for failure in failures:
                with self.subTest(failure=type(failure).__name__), patch(
                    "engine.conflicts.subprocess.check_output", side_effect=failure,
                ):
                    self.assertEqual(report(), {
                        "available": False, "bindings": [], "error": "Could not read compositor bindings",
                    })
            for response in ("invalid json", "{}", "null"):
                with self.subTest(response=response), patch(
                    "engine.conflicts.subprocess.check_output", return_value=response,
                ):
                    self.assertFalse(report()["available"])

    def test_main_cli_json_path_never_loads_config_or_scans_input(self):
        from engine.cli import build_parser

        for available in (True, False):
            expected = {"available": available, "bindings": [], "error": "" if available else "test"}
            output = io.StringIO()
            with self.subTest(available=available), patch("engine.conflicts.report", return_value=expected), patch(
                "engine.cli._load", side_effect=AssertionError("Must not load/write config"),
            ), patch("engine.cli.scan", side_effect=AssertionError("Must not scan input")), contextlib.redirect_stdout(output):
                args = build_parser().parse_args(["conflicts", "--json"])
                self.assertEqual(args.func(args), 0)
            self.assertEqual(json.loads(output.getvalue()), expected)


if __name__ == "__main__":
    unittest.main()
