"""A synthetic X-input style gamepad for testing without real hardware.

Built on the same pure-stdlib uinput layer the engine uses, so the test suite
needs nothing installed either. Creating the pad exercises `linux_input`'s
uinput side, and reading it exercises the evdev side.
"""

from __future__ import annotations

import fcntl
import os
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import linux_input as li  # noqa: E402
from engine._codes import ABS_CODES, BTN_CODES  # noqa: E402

# Matches what an 8BitDo Zero 2 exposes in X-input mode.
BUTTONS: dict[str, int] = {
    "A": BTN_CODES["SOUTH"],
    "B": BTN_CODES["EAST"],
    "X": BTN_CODES["NORTH"],
    "Y": BTN_CODES["WEST"],
    "L": BTN_CODES["TL"],
    "R": BTN_CODES["TR"],
    "SELECT": BTN_CODES["SELECT"],
    "START": BTN_CODES["START"],
}

HAT: dict[str, tuple[int, int]] = {
    "DPAD_LEFT": (ABS_CODES["HAT0X"], -1),
    "DPAD_RIGHT": (ABS_CODES["HAT0X"], 1),
    "DPAD_UP": (ABS_CODES["HAT0Y"], -1),
    "DPAD_DOWN": (ABS_CODES["HAT0Y"], 1),
}

# Some pads (8BitDo in D-input) report the d-pad on the left stick axes and
# never use the hat they advertise. Reproduced here so the "stick" d-pad
# source is covered without needing that hardware.
STICK: dict[str, tuple[int, int]] = {
    "DPAD_LEFT": (ABS_CODES["X"], 0),
    "DPAD_RIGHT": (ABS_CODES["X"], 255),
    "DPAD_UP": (ABS_CODES["Y"], 0),
    "DPAD_DOWN": (ABS_CODES["Y"], 255),
}

NAME = "controller-control test pad"


class VirtualPad:
    """A uinput gamepad that presses buttons on demand."""

    def __init__(
        self,
        name: str = NAME,
        settle: float = 0.45,
        dpad_on_stick: bool = False,
        back_button: bool = False,
    ):
        # When True the d-pad is sent on ABS_X/ABS_Y with a 0..255 range,
        # exactly as an 8BitDo does, instead of on the hat.
        self.dpad_on_stick = dpad_on_stick
        self.buttons = dict(BUTTONS)
        if back_button:
            self.buttons["BACK_BUTTON"] = BTN_CODES["BACK"]
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        try:
            fcntl.ioctl(self.fd, li.UI_SET_EVBIT, li.EV_KEY)
            fcntl.ioctl(self.fd, li.UI_SET_EVBIT, li.EV_ABS)
            fcntl.ioctl(self.fd, li.UI_SET_EVBIT, li.EV_SYN)
            for code in self.buttons.values():
                fcntl.ioctl(self.fd, li.UI_SET_KEYBIT, code)
            for axis in (ABS_CODES["HAT0X"], ABS_CODES["HAT0Y"]):
                fcntl.ioctl(self.fd, li.UI_SET_ABSBIT, axis)
                fcntl.ioctl(
                    self.fd, li.UI_ABS_SETUP, li.pack_abs_setup(axis, -1, 1)
                )
            # Advertised whether or not they are used -- 8BitDo advertises a
            # hat it never sends, which is why capability sniffing cannot tell
            # these pads apart and the source has to be configured.
            for axis in (ABS_CODES["X"], ABS_CODES["Y"]):
                fcntl.ioctl(self.fd, li.UI_SET_ABSBIT, axis)
                fcntl.ioctl(
                    self.fd, li.UI_ABS_SETUP, li.pack_abs_setup(axis, 0, 255, value=128)
                )
            setup = struct.pack(
                "HHHH80sI", li.BUS_BLUETOOTH, 0x2DC8, 0x9018, 1, name.encode()[:79], 0
            )
            fcntl.ioctl(self.fd, li.UI_DEV_SETUP, setup)
            fcntl.ioctl(self.fd, li.UI_DEV_CREATE)
        except OSError:
            os.close(self.fd)
            raise
        # Let udev create the node and let listeners notice it.
        time.sleep(settle)

    def _emit(self, ev_type: int, code: int, value: int) -> None:
        os.write(self.fd, li.pack_event(ev_type, code, value))

    def _set(self, button: str, pressed: bool) -> None:
        if button in self.buttons:
            self._emit(li.EV_KEY, self.buttons[button], 1 if pressed else 0)
        elif self.dpad_on_stick and button in STICK:
            axis, value = STICK[button]
            self._emit(li.EV_ABS, axis, value if pressed else 128)
        elif button in HAT:
            axis, value = HAT[button]
            self._emit(li.EV_ABS, axis, value if pressed else 0)
        else:
            raise KeyError(button)
        self._emit(li.EV_SYN, li.SYN_REPORT, 0)

    def press(self, button: str) -> None:
        self._set(button, True)

    def release(self, button: str) -> None:
        self._set(button, False)

    def tap(self, button: str, hold: float = 0.02) -> None:
        self.press(button)
        time.sleep(hold)
        self.release(button)

    def chord(self, *buttons: str, hold: float = 0.05) -> None:
        for button in buttons:
            self.press(button)
            time.sleep(0.005)
        time.sleep(hold)
        for button in reversed(buttons):
            self.release(button)
            time.sleep(0.005)

    def close(self) -> None:
        if self.fd < 0:
            return
        try:
            fcntl.ioctl(self.fd, li.UI_DEV_DESTROY)
        except OSError:
            pass
        try:
            os.close(self.fd)
        finally:
            self.fd = -1

    def __enter__(self) -> VirtualPad:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
