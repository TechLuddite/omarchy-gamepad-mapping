import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.config import Config
from engine.daemon import Daemon
from engine.keyboard_catalog import catalog
from engine.keys import parse_keys
from engine.mode_gate import allowed
from engine.conflicts import external_bindings


class ModesAndCatalog(unittest.TestCase):
    def test_standard_keys_are_unique_and_parse(self):
        options = catalog()
        self.assertEqual(len(options), len({o['value'] for o in options}))
        for o in options:
            self.assertEqual(len(parse_keys(o['keys'])), 1)
        self.assertTrue({'A','0','F24','KPENTER','SLASH','RIGHTCTRL','ENTER'} <= {o['value'] for o in options})

    def test_optional_gate_preserves_generic_plugin(self):
        self.assertTrue(allowed(None))

    def test_gate_fails_closed_and_expires(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'mode.json'
            self.assertFalse(allowed(p, 10))
            for state in ({}, {'updated':9,'mapper_allowed':False}, {'updated':5,'mapper_allowed':True}, {'updated':11,'mapper_allowed':True}):
                p.write_text(json.dumps(state))
                self.assertFalse(allowed(p, 10))
            p.write_text(json.dumps({'updated':9,'mapper_allowed':True}))
            self.assertTrue(allowed(p,10))
            self.assertFalse(allowed(p,12))
            link = Path(d)/'link';link.symlink_to(p)
            self.assertFalse(allowed(link,10))

    def test_daemon_cannot_fire_with_missing_mode_state(self):
        with tempfile.TemporaryDirectory() as d:
            daemon=Daemon(Config({'device':{'mode_gate':str(Path(d)/'missing')}, 'bindings':[{'combo':'BACK_BUTTON','keys':'F9'}]}),stream=io.StringIO())
            self.assertFalse(daemon.firing)
            with patch.object(daemon.runner,'run') as run:
                daemon._fire(daemon.engine.press('BACK_BUTTON',1)[0])
                run.assert_not_called()

    def test_daemon_reports_all_three_external_modes(self):
        for mode in ('game', 'os', 'pointer'):
            stream = io.StringIO()
            daemon = Daemon(Config({'device': {'mode_gate': '/unused'}}), stream=stream)
            state = {'mode': mode, 'os_mode': mode != 'game', 'mapper_allowed': mode == 'os'}
            with patch('engine.daemon.mode_snapshot', return_value=state), patch('engine.daemon.mode_allowed', return_value=mode == 'os'):
                daemon.emit_state()
            emitted = json.loads(stream.getvalue())
            self.assertEqual(emitted['input_mode'], mode)
            self.assertEqual(emitted['mode_suppressed'], mode != 'os')

    def test_external_os_and_native_back_are_distinct(self):
        r=external_bindings([
            {'key':'XF86AudioRaiseVolume','description':'Volume up','modmask':0},
            {'key':'XF86PowerOff','description':'Power menu','modmask':0},
            {'key':'mouse:278','description':'Custom Back','modmask':64},
        ],{'mice':[{'name':'ayn-odin2-gamepad'}]})
        self.assertEqual([x['token'] for x in r],['KEY_VOLUMEUP','KEY_POWER','BACK_BUTTON','BACK_BUTTON'])
        self.assertEqual(r[2]['modifiers'],64)
        self.assertEqual(r[-1]['kind'],'native pointer')

    def test_keycode_identity_uses_evdev_offset(self):
        r=external_bindings([{'keycode':123,'description':'Volume','modmask':0}],{})
        self.assertEqual(r[0]['token'],'KEY_VOLUMEUP')
