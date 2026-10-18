"""Optional gamepad pointer backend; importing this module never opens devices.

The caller supplies normalized raw ABS axis values and aliased button tokens.
``allowed`` must include the current mode, master switch and capture/pause state.
Saved mappings win: blocked_tokens contains their final button tokens plus raw
LSTICK_*/RSTICK_* directions whose aliases they claim. Claiming any direction
reserves that whole stick. Transitions require neutral before motion resumes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import errno
import fcntl
import math
import os
import re
import struct
import time
from typing import Mapping

from . import linux_input as li
from .buttons import normalize_button

REL_X, REL_Y, REL_HWHEEL, REL_WHEEL = 0, 1, 6, 8
BTN_LEFT, BTN_RIGHT = 0x110, 0x111
UI_SET_RELBIT = li._ioc(li._IOC_WRITE, "U", 102, 4)
_BUTTONS = {"left": BTN_LEFT, "right": BTN_RIGHT}
_STICKS = {"left": (0, 1, "LSTICK_"), "right": (3, 4, "RSTICK_")}


class PointerConfigError(ValueError):
    """An optional pointer setting is invalid."""


@dataclass(frozen=True)
class PointerSettings:
    enabled: bool = False
    pointer_stick: str = "left"
    scroll_stick: str = "right"
    speed: float = 900
    scroll_speed: float = 8
    dead_zone: float = 0.18
    scroll_dead_zone: float = 0.35
    invert_scroll: bool = False
    buttons: Mapping[str, str] = field(default_factory=lambda: {"L2": "left", "R2": "right"})


def validate_pointer(raw=None) -> PointerSettings:
    """Validate a pointer object, independent of config files and input devices.

    Button names use the normal alias vocabulary. Custom single-token alias
    targets are accepted too; chords cannot be pointer buttons. Unknown options
    are rejected, so spelling mistakes cannot silently enable a different policy.
    """
    if raw is None:
        return PointerSettings()
    if not isinstance(raw, dict):
        raise PointerConfigError("pointer must be an object")
    defaults = PointerSettings()
    known = set(defaults.__dataclass_fields__)
    if set(raw) - known:
        raise PointerConfigError("unknown pointer setting: " + ", ".join(sorted(map(str, set(raw) - known))))
    values = {name: raw.get(name, getattr(defaults, name)) for name in known}
    for name in ("enabled", "invert_scroll"):
        if not isinstance(values[name], bool):
            raise PointerConfigError(f"pointer.{name} must be a boolean")
    for name in ("pointer_stick", "scroll_stick"):
        if values[name] not in ("left", "right", "none"):
            raise PointerConfigError(f"pointer.{name} must be left, right or none")
    if values["pointer_stick"] != "none" and values["pointer_stick"] == values["scroll_stick"]:
        raise PointerConfigError("pointer and scroll must use different sticks")
    for name, lower, upper, exclusive in (("speed", 1, 4000, False),
                                           ("scroll_speed", 1, 60, False),
                                           ("dead_zone", 0, .95, True),
                                           ("scroll_dead_zone", 0, .95, True)):
        value = values[name]
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < lower
                or value > upper or (exclusive and value == upper)):
            bound = "<" if exclusive else "<="
            raise PointerConfigError(f"pointer.{name} must satisfy {lower} <= value {bound} {upper}")
    if not isinstance(values["buttons"], dict):
        raise PointerConfigError("pointer.buttons must be an object")
    buttons = {}
    for token, action in values["buttons"].items():
        if not isinstance(token, str) or not token.strip() or "+" in token or "," in token:
            raise PointerConfigError("pointer button must be a single token")
        name = normalize_button(token)
        if not re.fullmatch(r"[A-Z0-9_]+", name):
            raise PointerConfigError("pointer button must be a single token")
        if not isinstance(action, str) or action not in _BUTTONS:
            raise PointerConfigError("pointer button action must be left or right")
        if name in buttons:
            raise PointerConfigError(f"duplicate pointer button alias: {name}")
        buttons[name] = action
    values["buttons"] = buttons
    return PointerSettings(**values)


class NullPointer:
    """Explicit dry-run sink. It never allocates a uinput device."""
    def move(self, dx, dy): pass
    def scroll(self, horizontal, vertical): pass
    def set_button(self, button, pressed): pass
    def release_all(self): pass
    def close(self): pass


class VirtualPointer:
    """Lazy, mouse-only uinput output, with release-before-destroy cleanup."""
    NAME = "controller-control virtual pointer"

    def __init__(self, settle: float = .1):
        self._fd = None
        self._held = set()
        self._settle = settle
        self._ready_at = 0.

    @property
    def active(self):
        return self._fd is not None

    def open(self):
        if self.active:
            return
        fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        try:
            for event_type in (li.EV_SYN, li.EV_KEY, li.EV_REL):
                fcntl.ioctl(fd, li.UI_SET_EVBIT, event_type)
            for code in (REL_X, REL_Y, REL_HWHEEL, REL_WHEEL):
                fcntl.ioctl(fd, UI_SET_RELBIT, code)
            for code in _BUTTONS.values():
                fcntl.ioctl(fd, li.UI_SET_KEYBIT, code)
            setup = struct.pack("HHHH80sI", li.BUS_USB, 0x1D6B, 0xCC02, 1,
                                self.NAME.encode()[:79], 0)
            fcntl.ioctl(fd, li.UI_DEV_SETUP, setup)
            fcntl.ioctl(fd, li.UI_DEV_CREATE)
        except OSError:
            try:
                fcntl.ioctl(fd, li.UI_DEV_DESTROY)
            except OSError:
                pass
            try:
                os.close(fd)
            except OSError:
                pass
            raise
        self._fd = fd
        self._ready_at = time.monotonic() + self._settle

    @property
    def ready(self):
        return self.active and time.monotonic() >= self._ready_at

    def _write(self, event_type, code, value):
        data = li.pack_event(event_type, code, value)
        if os.write(self._fd, data) != len(data):
            raise OSError(errno.EIO, "short uinput event write")

    def _send(self, events):
        try:
            for event_type, code, value in events:
                self._write(event_type, code, value)
            self._write(li.EV_SYN, li.SYN_REPORT, 0)
        except OSError:
            self.close()
            raise

    def move(self, dx, dy):
        if not dx and not dy:
            return
        self.open()
        self._send([(li.EV_REL, code, int(value)) for code, value in
                    ((REL_X, dx), (REL_Y, dy)) if value])

    def scroll(self, horizontal, vertical):
        if not horizontal and not vertical:
            return
        self.open()
        self._send([(li.EV_REL, code, int(value)) for code, value in
                    ((REL_HWHEEL, horizontal), (REL_WHEEL, vertical)) if value])

    def set_button(self, button, pressed):
        code = _BUTTONS[button]
        if pressed:
            self.open()
            if code in self._held:
                return
            # Track even an attempted key-down: cleanup then tries to release
            # it if the write or the following SYN_REPORT fails.
            self._held.add(code)
        elif code not in self._held:
            return
        self._send([(li.EV_KEY, code, int(pressed))])
        if not pressed:
            self._held.discard(code)

    def release_all(self):
        if not self.active or not self._held:
            return
        self._send([(li.EV_KEY, code, 0) for code in sorted(self._held)])
        self._held.clear()

    def close(self):
        if not self.active:
            self._held.clear()
            return
        fd = self._fd
        # Cleanup tries every release even when a previous write failed.
        for code in sorted(self._held):
            try:
                self._write(li.EV_KEY, code, 0)
            except OSError:
                pass
        if self._held:
            try:
                self._write(li.EV_SYN, li.SYN_REPORT, 0)
            except OSError:
                pass
        self._held.clear()
        try:
            fcntl.ioctl(fd, li.UI_DEV_DESTROY)
        except OSError:
            pass
        finally:
            self._fd = None
            try:
                os.close(fd)
            except OSError:
                pass


class PointerController:
    """Time-based motion and click policy, with an injectable output sink.

    tick() must also run on idle timer ticks, not just on axis input events.
    Mode/config/device transitions call reset(); the next allowed tick seeds
    held buttons and neutral guards. Passing allowed=False is always silent,
    releases any drag and closes the output. Use NullPointer for dry-run.
    """
    MAX_DT = .05

    def __init__(self, settings=None, output=None):
        if isinstance(settings, PointerSettings):
            settings = {key: getattr(settings, key) for key in settings.__dataclass_fields__}
        self.settings = validate_pointer(settings)
        self.output = output if output is not None else VirtualPointer()
        self.needs_tick = False
        self._allowed = False
        self._last_time = None
        self._fraction = [0., 0., 0., 0.]
        self._quarantine = set()
        self._down = set()
        self._armed = {"pointer": False, "scroll": False}

    def _clear(self):
        self.needs_tick = False
        self._allowed = False
        self._last_time = None
        self._fraction = [0., 0., 0., 0.]
        self._quarantine.clear()
        self._down.clear()
        self._armed = {"pointer": False, "scroll": False}

    def reset(self):
        try:
            self.output.release_all()
        except Exception:
            try:
                self.output.close()
            except Exception:
                pass
            raise
        finally:
            self._clear()

    def close(self):
        try:
            self.reset()
        finally:
            self.output.close()

    @staticmethod
    def _axis(axes, code):
        value = axes.get(code, 0.)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return 0.
        return max(-1., min(1., value))

    def _velocity(self, role, axes, blocked, dead_zone):
        stick = getattr(self.settings, role + "_stick")
        if stick == "none":
            return (0., 0.)
        xcode, ycode, prefix = _STICKS[stick]
        x, y = self._axis(axes, xcode), self._axis(axes, ycode)
        magnitude = math.hypot(x, y)
        if any(token.startswith(prefix) for token in blocked):
            self._armed[role] = False
            return (0., 0.)
        if magnitude <= max(dead_zone, 0.0001):
            self._armed[role] = True
            return (0., 0.)
        if not self._armed[role]:
            return (0., 0.)
        gain = ((min(1., magnitude) - dead_zone) / (1. - dead_zone)) ** 2
        return (x / magnitude * gain, y / magnitude * gain)

    def tick(self, now, axes, held, blocked_tokens=(), allowed=False):
        try:
            if not isinstance(now, (int, float)) or isinstance(now, bool) or not math.isfinite(now):
                raise ValueError("pointer tick time must be finite")
            held = {normalize_button(token) for token in held}
            blocked = {normalize_button(token) for token in blocked_tokens}
            if not allowed or not self.settings.enabled:
                self.reset()
                return
            if hasattr(self.output, "open"):
                self.output.open()
                if not self.output.ready:
                    self.needs_tick = True
                    return
            if not self._allowed:
                self._allowed = True
                self._last_time = now
                self._quarantine = held.copy()
            dt = max(0., min(self.MAX_DT, now - self._last_time))
            self._last_time = now
            self._quarantine.intersection_update(held)
            self._quarantine.update(held & blocked)
            desired = {action for token, action in self.settings.buttons.items()
                       if token in held and token not in blocked and token not in self._quarantine}
            for action in sorted(self._down - desired):
                self.output.set_button(action, False)
            for action in sorted(desired - self._down):
                self.output.set_button(action, True)
            self._down = desired
            px, py = self._velocity("pointer", axes, blocked, self.settings.dead_zone)
            sx, sy = self._velocity("scroll", axes, blocked, self.settings.scroll_dead_zone)
            sign = -1 if self.settings.invert_scroll else 1
            velocity = (px * self.settings.speed, py * self.settings.speed,
                        sx * self.settings.scroll_speed * sign, -sy * self.settings.scroll_speed * sign)
            self.needs_tick = any(velocity)
            result = []
            for index, value in enumerate(velocity):
                if not value:
                    self._fraction[index] = 0.
                else:
                    self._fraction[index] += value * dt
                integer = math.trunc(self._fraction[index])
                self._fraction[index] -= integer
                result.append(integer)
            if result[0] or result[1]:
                self.output.move(*result[:2])
            if result[2] or result[3]:
                self.output.scroll(*result[2:])
        except Exception:
            # An output failure cannot leave the controller believing a drag
            # remains pressed. Preserve the original failure for the caller.
            try:
                self.close()
            except Exception:
                pass
            raise
