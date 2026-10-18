"""Parsing key combos and typing them on a virtual keyboard.

Actions of the form {"keys": "SUPER+RETURN"} work by creating a uinput
keyboard and tapping the combo on it. The compositor sees an ordinary keyboard,
so every keybinding Omarchy already has keeps working untouched -- there is no
need to re-declare them here.
"""

from __future__ import annotations

import fcntl
import os
import struct
import time

from . import linux_input as li
from ._codes import KEY_CODES

# Friendly spellings accepted in config, mapped onto KEY_* table names.
KEY_ALIASES: dict[str, str] = {
    "SUPER": "LEFTMETA",
    "META": "LEFTMETA",
    "WIN": "LEFTMETA",
    "CMD": "LEFTMETA",
    "MOD": "LEFTMETA",
    "CTRL": "LEFTCTRL",
    "CONTROL": "LEFTCTRL",
    "ALT": "LEFTALT",
    "OPT": "LEFTALT",
    "SHIFT": "LEFTSHIFT",
    "RETURN": "ENTER",
    "CR": "ENTER",
    "ESCAPE": "ESC",
    "DEL": "DELETE",
    "PGUP": "PAGEUP",
    "PGDN": "PAGEDOWN",
    "PRINT": "SYSRQ",
    "PRTSC": "SYSRQ",
    "PRINTSCREEN": "SYSRQ",
    "PERIOD": "DOT",
    "BRACKETLEFT": "LEFTBRACE",
    "BRACKETRIGHT": "RIGHTBRACE",
    "PLUS": "EQUAL",
    "RETURN_KP": "KPENTER",
    # XF86 names, so bindings can be copied straight out of Hyprland config.
    "XF86AUDIORAISEVOLUME": "VOLUMEUP",
    "XF86AUDIOLOWERVOLUME": "VOLUMEDOWN",
    "XF86AUDIOMUTE": "MUTE",
    "XF86AUDIOMICMUTE": "MICMUTE",
    "XF86AUDIOPLAY": "PLAYPAUSE",
    "XF86AUDIOPAUSE": "PAUSECD",
    "XF86AUDIONEXT": "NEXTSONG",
    "XF86AUDIOPREV": "PREVIOUSSONG",
    "XF86MONBRIGHTNESSUP": "BRIGHTNESSUP",
    "XF86MONBRIGHTNESSDOWN": "BRIGHTNESSDOWN",
    "XF86CALCULATOR": "CALC",
    "XF86EJECT": "EJECTCD",
    "XF86KBDBRIGHTNESSDOWN": "KBDILLUMDOWN",
    "XF86KBDBRIGHTNESSUP": "KBDILLUMUP",
    "XF86KBDLIGHTONOFF": "KBDILLUMTOGGLE",
    "XF86POWEROFF": "POWER",
    "XF86TOUCHPADOFF": "TOUCHPAD_OFF",
    "XF86TOUCHPADON": "TOUCHPAD_ON",
    "XF86TOUCHPADTOGGLE": "TOUCHPAD_TOGGLE",
}


class KeyParseError(Exception):
    """Raised for a key combo string that cannot be resolved to key codes."""


def resolve_key(name: str) -> int:
    """Resolve a single key name to its KEY_* code."""
    token = name.strip().upper().replace("-", "_").replace(" ", "_")
    if not token:
        raise KeyParseError("empty key name")
    if token.startswith("KEY_"):
        token = token[4:]
    token = KEY_ALIASES.get(token, token)
    # Bare digits and letters are spelled KEY_1 / KEY_A in the kernel table.
    if token in KEY_CODES:
        return KEY_CODES[token]
    raise KeyParseError(f"unknown key {name!r}")


def parse_keys(spec: str) -> list[int]:
    """Parse "SUPER+SHIFT+RETURN" into an ordered list of key codes.

    Modifiers come first in the returned order, which is also the press order.
    """
    parts = [p for p in spec.replace(",", "+").split("+") if p.strip()]
    if not parts:
        raise KeyParseError("empty key combo")
    return [resolve_key(p) for p in parts]


class VirtualKeyboard:
    """A uinput keyboard used to replay key combos into the compositor."""

    NAME = "controller-control virtual keyboard"
    VENDOR = 0x1D6B  # Linux Foundation
    PRODUCT = 0xCC01

    def __init__(self, settle: float = 0.4):
        self._fd: int | None = None
        self._settle = settle

    @property
    def active(self) -> bool:
        return self._fd is not None

    def open(self) -> None:
        if self._fd is not None:
            return
        fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        try:
            fcntl.ioctl(fd, li.UI_SET_EVBIT, li.EV_KEY)
            fcntl.ioctl(fd, li.UI_SET_EVBIT, li.EV_SYN)
            # Advertise exactly the keyboard keys, so the device is never
            # mistaken for a mouse or a pad.
            for code in sorted(set(KEY_CODES.values())):
                if 0 < code <= li.KEY_MAX:
                    fcntl.ioctl(fd, li.UI_SET_KEYBIT, code)
            setup = struct.pack(
                "HHHH80sI",
                li.BUS_USB,
                self.VENDOR,
                self.PRODUCT,
                1,
                self.NAME.encode()[:79],
                0,
            )
            fcntl.ioctl(fd, li.UI_DEV_SETUP, setup)
            fcntl.ioctl(fd, li.UI_DEV_CREATE)
        except OSError:
            os.close(fd)
            raise
        self._fd = fd
        # Give the compositor a moment to bind the new device, otherwise the
        # very first combo can be delivered before anything is listening.
        if self._settle:
            time.sleep(self._settle)

    def close(self) -> None:
        if self._fd is None:
            return
        try:
            fcntl.ioctl(self._fd, li.UI_DEV_DESTROY)
        except OSError:
            pass
        try:
            os.close(self._fd)
        finally:
            self._fd = None

    def _emit(self, ev_type: int, code: int, value: int) -> None:
        assert self._fd is not None
        os.write(self._fd, li.pack_event(ev_type, code, value))

    def _sync(self) -> None:
        self._emit(li.EV_SYN, li.SYN_REPORT, 0)

    def tap(self, codes: list[int], gap: float = 0.012) -> None:
        """Press the codes in order, then release them in reverse order."""
        if not codes:
            return
        self.open()
        for code in codes:
            self._emit(li.EV_KEY, code, 1)
        self._sync()
        if gap:
            time.sleep(gap)
        for code in reversed(codes):
            self._emit(li.EV_KEY, code, 0)
        self._sync()

    def __enter__(self) -> VirtualKeyboard:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
