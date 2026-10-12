"""Keep auxiliary handheld keys opt-in while accepting explicit device names."""
import unittest
from unittest.mock import patch

from engine.devices import DeviceInfo, DeviceScanner
from engine.buttons import button_for_key_code, parse_combo


def device(name, keys):
    info = DeviceInfo.__new__(DeviceInfo)
    info.name = name
    info.key_codes = keys
    return info


class PortalDeviceSelection(unittest.TestCase):
    def test_dedicated_back_does_not_alias_select(self):
        self.assertEqual(button_for_key_code(278), "BACK_BUTTON")
        self.assertEqual(parse_combo("BACK_BUTTON"), ("BACK_BUTTON",))
        self.assertEqual(button_for_key_code(314), "SELECT")
        self.assertEqual(button_for_key_code(316), "MODE")

    def setUp(self):
        self.pad = device("AYN Odin2 Gamepad", [304])
        self.volume = device("gpio-keys", [115])
        self.keyboard = device("External Keyboard", [30])
        self.touch = device("Touchscreen", [330])

    def test_default_filter_only_reads_gamepad(self):
        with patch.object(DeviceScanner, "scan", return_value=[self.pad, self.volume, self.keyboard, self.touch]):
            self.assertEqual(DeviceScanner().find_pads([]), [self.pad])

    def test_named_media_node_is_accepted(self):
        with patch.object(DeviceScanner, "scan", return_value=[self.pad, self.volume, self.keyboard, self.touch]):
            self.assertEqual(DeviceScanner().find_pads(["gpio-keys"]), [self.volume])
            self.assertEqual(DeviceScanner().find_pads(["gpio-keys"], allow_keyboard=False), [])


if __name__ == "__main__":
    unittest.main()
