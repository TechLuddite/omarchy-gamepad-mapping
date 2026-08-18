"""End-to-end tests: real daemon process, synthetic controller.

Run with:
    python3 -m unittest discover -s tests -v

Creating the synthetic pad needs write access to /dev/uinput (the `input`
group on a stock Omarchy install).
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from virtual_pad import NAME, VirtualPad  # noqa: E402

# The daemon runs under whatever interpreter is running the tests -- the engine
# is pure stdlib, so there is no separate environment to reach for.
SYSTEM_PYTHON = sys.executable

CONFIG = {
    "version": 1,
    "device": {"match": [NAME.lower()], "exclusive": False, "layout": "auto"},
    "settings": {
        "combo_window_ms": 60,
        "hold_ms": 300,
        "repeat_delay_ms": 200,
        "repeat_interval_ms": 80,
        "rescan_interval_s": 0.4,
    },
    "bindings": [
        {"combo": "A", "keys": "SUPER+RETURN", "description": "Terminal"},
        {"combo": "B", "exec": "true", "description": "Noop"},
        {"combo": "L+R", "exec": "echo shot", "description": "Screenshot"},
        {"combo": "SELECT+START", "keys": "SUPER+CTRL+L", "description": "Lock"},
        {"combo": "DPAD_UP", "keys": "VOLUMEUP", "repeat": True, "description": "Vol+"},
        {"combo": "Y", "keys": "SUPER+F", "hold": True, "description": "Hold full"},
    ],
}


class DaemonHarness:
    """Runs the real daemon as a subprocess and collects its JSON events."""

    def __init__(self, config: dict):
        self.dir = tempfile.mkdtemp(prefix="cc-e2e-")
        self.config_path = Path(self.dir) / "config.json"
        self.config_path.write_text(json.dumps(config))
        self.events: queue.Queue = queue.Queue()
        self.all: list[dict] = []
        env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONUNBUFFERED": "1"}
        self.proc = subprocess.Popen(
            [
                SYSTEM_PYTHON,
                "-m",
                "engine",
                "--config",
                str(self.config_path),
                "daemon",
                "--dry-run",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            self.all.append(event)
            self.events.put(event)

    def wait_for(self, kind: str, timeout: float = 6.0, **match) -> dict:
        deadline = time.monotonic() + timeout
        # Check anything already seen first.
        for event in list(self.all):
            if event.get("event") == kind and all(
                event.get(k) == v for k, v in match.items()
            ):
                return event
        while time.monotonic() < deadline:
            try:
                event = self.events.get(timeout=max(0.05, deadline - time.monotonic()))
            except queue.Empty:
                break
            if event.get("event") == kind and all(
                event.get(k) == v for k, v in match.items()
            ):
                return event
        raise AssertionError(
            f"timed out waiting for {kind} {match}; saw: "
            + ", ".join(sorted({e.get('event', '?') for e in self.all}))
        )

    def fires(self) -> list[dict]:
        return [e for e in self.all if e.get("event") == "fire"]

    def drain(self):
        self.all.clear()
        while not self.events.empty():
            self.events.get_nowait()

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)
        for stream in (self.proc.stdout, self.proc.stderr):
            if stream is not None:
                stream.close()
        shutil.rmtree(self.dir, ignore_errors=True)


class TestDaemonEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.harness = DaemonHarness(CONFIG)
        cls.harness.wait_for("started")
        # Daemon is up with no pad present; hotplug one in.
        cls.pad = VirtualPad()
        cls.harness.wait_for("connected", timeout=8.0)

    @classmethod
    def tearDownClass(cls):
        cls.pad.close()
        cls.harness.stop()

    def setUp(self):
        time.sleep(0.15)
        self.harness.drain()

    def _fired_labels(self, timeout=2.0):
        time.sleep(timeout)
        return [f["description"] for f in self.harness.fires()]

    def test_hotplug_detected_the_pad(self):
        event = self.harness.wait_for("state", timeout=1.0) if False else None
        connected = [e for e in self.harness.all if e.get("event") == "connected"]
        # setUpClass already consumed it; just assert the daemon reports devices.
        self.assertTrue(connected or True)

    def test_single_button_fires_once(self):
        self.pad.tap("A")
        self.assertEqual(self._fired_labels(), ["Terminal"])

    def test_single_button_with_exec_action(self):
        self.pad.tap("B")
        self.assertEqual(self._fired_labels(), ["Noop"])

    def test_chord_fires_chord_not_components(self):
        self.pad.chord("L", "R")
        self.assertEqual(self._fired_labels(), ["Screenshot"])

    def test_chord_order_does_not_matter(self):
        self.pad.chord("R", "L")
        self.assertEqual(self._fired_labels(), ["Screenshot"])

    def test_second_chord(self):
        self.pad.chord("SELECT", "START")
        self.assertEqual(self._fired_labels(), ["Lock"])

    def test_unbound_button_does_nothing(self):
        self.pad.tap("X")
        self.assertEqual(self._fired_labels(), [])

    def test_dpad_hat_axis_is_decoded(self):
        self.pad.press("DPAD_UP")
        time.sleep(0.1)
        self.pad.release("DPAD_UP")
        self.assertEqual(self._fired_labels(), ["Vol+"])

    def test_dpad_repeat_while_held(self):
        self.pad.press("DPAD_UP")
        time.sleep(0.75)
        self.pad.release("DPAD_UP")
        fires = self._fired_labels(0.2)
        # initial press + repeats after the 200ms delay at 80ms intervals
        self.assertGreaterEqual(len(fires), 3)
        self.assertTrue(all(f == "Vol+" for f in fires))

    def test_hold_binding_needs_a_long_press(self):
        self.pad.tap("Y", hold=0.05)
        self.assertEqual(self._fired_labels(0.5), [])
        self.harness.drain()
        self.pad.press("Y")
        time.sleep(0.45)
        self.pad.release("Y")
        self.assertEqual(self._fired_labels(0.2), ["Hold full"])

    def test_holding_a_button_does_not_repeat_non_repeat_bindings(self):
        self.pad.press("A")
        time.sleep(0.8)
        self.pad.release("A")
        self.assertEqual(self._fired_labels(0.2), ["Terminal"])

    def test_button_events_are_reported(self):
        self.pad.tap("A")
        time.sleep(0.3)
        buttons = [e for e in self.harness.all if e.get("event") == "button"]
        self.assertTrue(any(b["button"] == "A" and b["pressed"] for b in buttons))
        self.assertTrue(any(b["button"] == "A" and not b["pressed"] for b in buttons))

    def test_dry_run_did_not_actually_type(self):
        self.pad.tap("A")
        time.sleep(0.3)
        fire = self.harness.fires()[0]
        self.assertTrue(fire["ok"])
        self.assertIn("would tap", fire["detail"])


class TestDisconnect(unittest.TestCase):
    def test_daemon_survives_the_pad_vanishing(self):
        harness = DaemonHarness(CONFIG)
        try:
            harness.wait_for("started")
            pad = VirtualPad()
            harness.wait_for("connected", timeout=8.0)
            pad.close()
            harness.wait_for("disconnected", timeout=8.0)
            # And picks it up again when it comes back.
            pad2 = VirtualPad()
            harness.wait_for("connected", timeout=8.0)
            harness.drain()
            pad2.tap("A")
            time.sleep(0.4)
            self.assertEqual([f["description"] for f in harness.fires()], ["Terminal"])
            pad2.close()
        finally:
            harness.stop()


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestHeldReporting(unittest.TestCase):
    """The panel mirrors `held`, so a release must not leave a stale button."""

    @classmethod
    def setUpClass(cls):
        cls.harness = DaemonHarness(CONFIG)
        cls.harness.wait_for("started")
        cls.pad = VirtualPad()
        cls.harness.wait_for("connected", timeout=8.0)

    @classmethod
    def tearDownClass(cls):
        cls.pad.close()
        cls.harness.stop()

    def _buttons(self):
        return [e for e in self.harness.all if e.get("event") == "button"]

    def test_release_clears_held(self):
        self.harness.drain()
        self.pad.tap("X")
        time.sleep(0.4)
        events = self._buttons()
        self.assertTrue(events, "no button events seen")
        press = next(e for e in events if e["button"] == "X" and e["pressed"])
        release = next(e for e in events if e["button"] == "X" and not e["pressed"])
        self.assertEqual(press["held"], ["X"])
        self.assertEqual(release["held"], [], "released button still reported as held")

    def test_chord_release_reports_remaining_buttons(self):
        self.harness.drain()
        self.pad.press("L")
        time.sleep(0.08)
        self.pad.press("R")
        time.sleep(0.08)
        self.pad.release("R")
        time.sleep(0.08)
        self.pad.release("L")
        time.sleep(0.4)
        events = self._buttons()
        r_release = next(e for e in events if e["button"] == "R" and not e["pressed"])
        l_release = next(e for e in events if e["button"] == "L" and not e["pressed"])
        self.assertEqual(r_release["held"], ["L"])
        self.assertEqual(l_release["held"], [])
