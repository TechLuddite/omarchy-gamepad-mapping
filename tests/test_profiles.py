"""Named OS profiles using temporary files and mocked CLI notifications only."""

from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import patch

from engine.cli import main
from engine.config import Binding, Config, ConfigError, load, profile_name
from engine.buttons import parse_combo


def legacy(**extra):
    return {"bindings": [{"combo": "A", "keys": "SUPER+RETURN", "description": "Terminal"},
                         {"combo": "B", "exec": "custom-command", "hold": True},
                         {"combo": "DPAD_UP", "keys": "VOLUMEUP", "repeat": True, "enabled": False}],
            "device": {"match": ["chosen pad"], "exclusive": True, "custom": "device value"},
            "settings": {"hold_ms": 900, "custom": "settings value"},
            "enabled": False, "modes": {"active": "os", "enabled": True},
            "future": {"nested": [1, 2]}, **extra}


def configured():
    config = Config(legacy(pointer={"enabled": True, "speed": 12, "buttons": {"A": "left"}}))
    config.profile_create("Work")
    return config


class ProfileConfigTests(unittest.TestCase):
    def test_legacy_serialization_has_no_profile_or_new_pointer_fields(self):
        config = Config(legacy())
        expected = {"version": 1, "enabled": config.enabled, "device": config.device,
                    "settings": config.settings, "bindings": [b.to_dict() for b in config.bindings],
                    "modes": {"active": "os", "enabled": True}, "future": {"nested": [1, 2]}}
        self.assertEqual(config.to_dict(), expected)
        self.assertEqual(config.active_profile, "Current")
        self.assertEqual(config.profile_names(), ["Current"])
        self.assertNotIn("profiles", config.to_dict())
        self.assertNotIn("pointer", config.to_dict())

    def test_explicit_use_migrates_all_original_bindings_and_pointer(self):
        config = Config(legacy(pointer={"enabled": True, "speed": 12}))
        before = config.to_dict()
        config.profile_use("Current")
        result = config.to_dict()
        self.assertEqual(result["profiles"], {"active": "Current", "mirror_of":"Current", "items": {
            "Current": {"bindings": before["bindings"], "pointer": before["pointer"]}}})
        for key in ("device", "settings", "enabled", "modes", "future"):
            self.assertEqual(result[key], before[key])
        self.assertEqual(set(result["profiles"]["items"]["Current"]), {"bindings", "pointer"})

    def test_create_clones_selects_and_preserves_current_original(self):
        config = configured()
        self.assertEqual(config.active_profile, "Work")
        result = config.to_dict()
        self.assertEqual(result["profiles"]["items"]["Current"], result["profiles"]["items"]["Work"])
        config.pointer["buttons"]["X"] = "right"
        config.remove(parse_combo("B"))
        config.upsert(Binding({"combo": "A", "keys": "F9"}, 0))
        config.to_dict()
        config.profile_use("Current")
        self.assertEqual(config.find(parse_combo("A")).keys, "SUPER+RETURN")
        self.assertIsNotNone(config.find(parse_combo("B")))
        self.assertEqual(config.pointer["buttons"], {"A": "left"})
        config.profile_use("Work")
        self.assertEqual(config.find(parse_combo("A")).keys, "F9")
        self.assertIsNone(config.find(parse_combo("B")))
        self.assertEqual(config.pointer["buttons"], {"A": "left", "X": "right"})

    def test_unknown_top_fields_and_global_mode_never_switch(self):
        config = configured()
        original = config.to_dict()
        config.enabled = True
        config.device["match"] = ["new pad"]
        config.settings["hold_ms"] = 300
        config.profile_use("Current")
        result = config.to_dict()
        self.assertTrue(result["enabled"])
        self.assertEqual(result["device"]["match"], ["new pad"])
        self.assertEqual(result["settings"]["hold_ms"], 300)
        self.assertEqual(result["modes"], original["modes"])
        self.assertEqual(result["future"], original["future"])

    def test_active_rename_and_inactive_delete(self):
        config = configured()
        config.profile_rename("Work", "  Desktop  ")
        self.assertEqual(config.active_profile, "Desktop")
        self.assertEqual(config.profile_names(), ["Current", "Desktop"])
        config.profile_delete("Current")
        self.assertEqual(config.profile_names(), ["Desktop"])
        self.assertEqual(Config(config.to_dict()).active_profile, "Desktop")

    def test_inactive_rename_does_not_change_active(self):
        config = configured()
        config.profile_rename("Current", "Original")
        self.assertEqual(config.active_profile, "Work")
        self.assertEqual(config.profile_names(), ["Original", "Work"])

    def test_active_delete_explicitly_selects_replacement_and_keeps_globals(self):
        config = configured()
        original = deepcopy(config.to_dict())
        config.pointer['speed'] = 40
        config.upsert(Binding({'combo': 'Y', 'keys': 'F9'}, 0))
        config.profile_delete('Work', switch_to='Current')
        result = config.to_dict()
        self.assertEqual(config.active_profile, 'Current')
        self.assertEqual(config.profile_names(), ['Current'])
        self.assertEqual(result['bindings'], original['profiles']['items']['Current']['bindings'])
        self.assertEqual(result['pointer'], original['profiles']['items']['Current']['pointer'])
        for key in ('device', 'settings', 'enabled', 'modes', 'future'):
            self.assertEqual(result[key], original[key])

    def test_bad_or_stale_delete_replacement_does_not_change_state(self):
        for target, replacement in [('Work', 'Work'), ('Work', 'missing'), ('Current', 'Work'), ('Work', '')]:
            config = configured()
            before = deepcopy(config.to_dict())
            with self.subTest(target=target, replacement=replacement), self.assertRaises(ConfigError):
                config.profile_delete(target, switch_to=replacement)
            self.assertEqual(config.to_dict(), before)

    def test_cannot_delete_last_profile_even_with_replacement(self):
        config = Config(legacy())
        before = config.to_dict()
        with self.assertRaisesRegex(ConfigError, 'last profile'):
            config.profile_delete('Current', switch_to='Current')
        self.assertEqual(config.to_dict(), before)

    def test_failed_operations_do_not_migrate_or_change_state(self):
        for config in (Config(legacy()), configured()):
            for operation in (lambda: config.profile_create("Current"),
                              lambda: config.profile_use("missing"),
                              lambda: config.profile_rename("missing", "New"),
                              lambda: config.profile_rename(config.active_profile, "Current"),
                              lambda: config.profile_delete(config.active_profile),
                              lambda: config.profile_delete("missing")):
                before = config.to_dict()
                with self.assertRaises(ConfigError):
                    operation()
                self.assertEqual(config.to_dict(), before)

    def test_names_trim_and_reject_controls_empty_or_overlong(self):
        self.assertEqual(profile_name("  Travel 🦉  "), "Travel 🦉")
        self.assertEqual(profile_name("x" * 64), "x" * 64)
        for name in (None, 1, "", "  ", "x" * 65, "a\nb", " a\t ", "a\x00b", "a\u200bb"):
            config = Config(legacy())
            before = config.to_dict()
            with self.subTest(name=name), self.assertRaises(ConfigError):
                config.profile_create(name)
            self.assertEqual(config.to_dict(), before)

    def test_old_editor_top_mirror_changes_replace_stale_active_snapshot(self):
        raw = configured().to_dict()
        original_other = deepcopy(raw["profiles"]["items"]["Current"])
        raw["bindings"] = [{"combo": "Y", "keys": "F8"}]
        raw["pointer"] = {"speed": 42}
        config = Config(raw)
        self.assertEqual(config.find(parse_combo("Y")).keys, "F8")
        self.assertEqual(config.pointer["speed"],42)
        result = config.to_dict()
        self.assertEqual(result["profiles"]["items"]["Work"], {"bindings": raw["bindings"], "pointer": config.pointer})
        self.assertEqual(result["profiles"]["items"]["Current"], original_other)

    def test_absent_mirrors_fall_back_to_active_snapshot(self):
        raw = configured().to_dict()
        expected = raw["profiles"]["items"]["Work"]
        del raw["bindings"]
        del raw["pointer"]
        result = Config(raw).to_dict()
        self.assertEqual(result["bindings"], expected["bindings"])
        self.assertEqual(result["pointer"], expected["pointer"])

    def test_all_profiles_validated_even_when_inactive_and_mirrors_valid(self):
        for invalid in ({"bindings": "bad", "pointer": {}},
                        {"bindings": [{"combo": "", "keys": "A"}], "pointer": {}},
                        {"bindings": [{"combo": "A", "keys": 123}], "pointer": {}},
                        {"bindings": [{"combo": "A"}], "pointer": {}},
                        {"bindings": [{"combo": "A", "keys": "A", "repeat": True, "hold": True}], "pointer": {}},
                        {"bindings": [], "pointer": []}, {"bindings": []},
                        {"bindings": [], "pointer": {}, "modes": {"current": "game"}}):
            raw = configured().to_dict()
            raw["profiles"]["items"]["Current"] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ConfigError):
                Config(raw)

    def test_duplicate_normalized_combo_rejected_in_inactive_profile(self):
        raw = configured().to_dict()
        raw["profiles"]["items"]["Current"]["bindings"] = [
            {"combo": "L + R", "keys": "A"}, {"combo": "R+L", "keys": "B"}]
        with self.assertRaises(ConfigError):
            Config(raw)

    def test_invalid_profile_structure_and_names_rejected(self):
        for profiles in (None, [], {}, {"active": "Current", "items": {}},
                         {"active": "missing", "items": {"Other": {"bindings": [], "pointer": {}}}},
                         {"active": " Bad", "items": {" Bad": {"bindings": [], "pointer": {}}}},
                         {"active": "Bad\n", "items": {"Bad\n": {"bindings": [], "pointer": {}}}}):
            with self.subTest(profiles=profiles), self.assertRaises(ConfigError):
                Config(legacy(profiles=profiles))

    def test_explicit_malformed_top_mirrors_rejected(self):
        for key, invalid in (("bindings", {}), ("pointer", None), ("pointer", [])):
            raw = configured().to_dict()
            raw[key] = invalid
            with self.subTest(key=key, invalid=invalid), self.assertRaises(ConfigError):
                Config(raw)

    def test_invalid_pointer_policy_rejected_in_active_and_inactive_snapshots(self):
        for name in ("Current", "Work"):
            for pointer in ({"enabled": "yes"}, {"speed": -1}, {"dead_zone": 1},
                            {"buttons": {"A+B": "left"}}, {"pointer_stick": "right"},
                            {"custom": {"values": [1]}}):
                raw = configured().to_dict()
                raw["profiles"]["items"][name]["pointer"] = pointer
                with self.subTest(name=name, pointer=pointer), self.assertRaises(ConfigError):
                    Config(raw)

    def test_invalid_top_pointer_policy_rejected_even_with_valid_active_snapshot(self):
        raw = configured().to_dict()
        raw["pointer"] = {"buttons": {"A": "middle"}}
        with self.assertRaises(ConfigError):
            Config(raw)

    def test_manual_active_change_cannot_overwrite_another_profile(self):
        config=configured()
        config.upsert(Binding({'combo':'A','keys':'F9'},0))
        config.profile_use('Current')
        raw=config.to_dict()
        before=deepcopy(raw['profiles']['items'])
        raw['profiles']['active']='Work'
        with self.assertRaisesRegex(ConfigError,'mirror owner'):
            Config(raw)
        self.assertEqual(raw['profiles']['items'],before)

    def test_ownerless_conflicting_mirrors_are_rejected(self):
        raw=configured().to_dict()
        raw['profiles'].pop('mirror_of')
        raw['bindings']=[{'combo':'X','keys':'SPACE'}]
        with self.assertRaisesRegex(ConfigError,'ambiguous profile mirrors'):
            Config(raw)

    def test_joined_emoji_names_and_null_bindings_match_legacy_policy(self):
        name='Desk 👩\u200d💻'
        self.assertEqual(profile_name(name),name)
        config=Config({'bindings':None})
        config.profile_create(name)
        raw=config.to_dict()
        raw['bindings']=None
        raw['profiles']['items'][name]['bindings']=None
        restored=Config(raw)
        self.assertEqual([b.to_dict() for b in restored.bindings],[b.to_dict() for b in Config({'bindings':None}).bindings])

    def test_saved_snapshots_and_mirrors_roundtrip_together(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            config = configured()
            config.pointer["speed"] = 30
            config.save(path)
            result = load(path)
            self.assertEqual(result.to_dict(), config.to_dict())
            self.assertEqual(result.active_profile, "Work")
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_duplicate_profile_json_keys_rejected_instead_of_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"profiles":{"active":"A","items":{"A":{"bindings":[],"pointer":{}},"A":{"bindings":[],"pointer":{}}}}}')
            with self.assertRaisesRegex(ConfigError, "duplicate JSON field"):
                load(path)

    def test_failed_atomic_replace_preserves_original_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            config = Config(legacy(), path)
            config.save()
            original = path.read_bytes()
            config.profile_create("Work")
            with patch("engine.config.os.replace", side_effect=OSError("fixture failure")), self.assertRaises(OSError):
                config.save()
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(directory).iterdir()), [path])


class ProfileCliTests(unittest.TestCase):
    def test_stale_active_mirror_cannot_be_saved_by_unrelated_cli_edit(self):
        raw=configured().to_dict()
        raw['profiles']['active']='Current'
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.json'
            path.write_text(json.dumps(raw))
            before=path.read_bytes()
            with patch('engine.cli._notify_daemon') as notify, contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                result=main(['--config',str(path),'mode','os'])
            self.assertNotEqual(result,0)
            self.assertEqual(path.read_bytes(),before)
            notify.assert_not_called()


    def invoke(self, config, *arguments):
        output = io.StringIO()
        with patch("engine.cli._load", return_value=config), \
                patch("engine.cli._edit", return_value=contextlib.nullcontext(config)), \
                patch.object(config, "save") as save, \
                patch("engine.cli._notify_daemon", return_value=False) as notify, \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = main(["profile", *arguments])
        return result, output.getvalue(), save, notify

    def test_list_is_read_only_and_does_not_migrate(self):
        config = Config(legacy())
        result, output, save, notify = self.invoke(config, "list", "--json")
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output), {"active": "Current", "names": ["Current"]})
        save.assert_not_called()
        notify.assert_not_called()
        self.assertNotIn("profiles", config.to_dict())

    def test_create_use_rename_delete_save_once_and_notify_sighup(self):
        config = Config(legacy())
        for arguments in (("create", "Work"), ("use", "Current"),
                          ("rename", "Work", "Travel"), ("delete", "Travel")):
            with self.subTest(arguments=arguments):
                result, _output, save, notify = self.invoke(config, *arguments)
                self.assertEqual(result, 0)
                save.assert_called_once_with()
                notify.assert_called_once_with(signal.SIGHUP)

    def test_invalid_action_has_no_file_write_or_signal(self):
        config = Config(legacy())
        before = config.to_dict()
        result, output, save, notify = self.invoke(config, "use", "missing")
        self.assertEqual(result, 1)
        self.assertIn("unknown profile", output)
        save.assert_not_called()
        notify.assert_not_called()
        self.assertEqual(config.to_dict(), before)

    def test_active_delete_is_one_atomic_save_and_one_reload(self):
        config = configured()
        result, _, save, notify = self.invoke(config, 'delete', 'Work', '--switch-to', 'Current')
        self.assertEqual(result, 0)
        self.assertEqual(config.active_profile, 'Current')
        self.assertEqual(config.profile_names(), ['Current'])
        save.assert_called_once_with()
        notify.assert_called_once_with(signal.SIGHUP)

    def test_invalid_delete_replacement_never_writes_or_signals(self):
        config = configured()
        before = deepcopy(config.to_dict())
        result, _, save, notify = self.invoke(config, 'delete', 'Work', '--switch-to', 'missing')
        self.assertEqual(result, 1)
        self.assertEqual(config.to_dict(), before)
        save.assert_not_called()
        notify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
