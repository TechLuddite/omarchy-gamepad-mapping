"""Loading, validating and saving the controller-control config."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .buttons import format_combo, parse_combo

CONFIG_VERSION = 1

XDG_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
CONFIG_DIR = XDG_CONFIG / "controller-control"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULT_SETTINGS: dict = {
    # How long to wait for more buttons before deciding a chord is complete.
    # Only applied when a longer binding could still match, so unambiguous
    # presses stay instant.
    "combo_window_ms": 45,
    # How long a "hold" binding must be held before it fires.
    "hold_ms": 450,
    # Auto-repeat timing for bindings marked "repeat".
    "repeat_delay_ms": 400,
    "repeat_interval_ms": 110,
    # Fraction of full travel at which an analog trigger/stick counts as pressed.
    "trigger_threshold": 0.45,
    "stick_threshold": 0.65,
    # Seconds between rescans of /dev/input for hotplugged pads.
    "rescan_interval_s": 2.0,
}

DEFAULT_DEVICE: dict = {
    # Name substrings to match, case-insensitive. Empty list = any gamepad,
    # which is the default so the plugin works on first run whatever you own.
    # Narrow it (e.g. ["8bitdo"]) when you have more than one pad and only want
    # one of them driving the desktop.
    #
    # Note that an empty list also means keyboard-mode pads are ignored: a
    # keyboard-shaped device is only ever considered when you name it
    # explicitly, so this can never latch onto your actual keyboard.
    "match": [],
    # Take the pad away from every other application (games, Steam, browsers).
    "exclusive": False,
    # "nintendo" makes displayed labels match the plastic on 8BitDo pads.
    "layout": "nintendo",
}

# Shipped starter bindings, all built on stock Omarchy keybindings.
#
# The d-pad is bound twice on purpose. Most pads report it as a hat axis
# (DPAD_*), but 8BitDo pads in D-input mode send it on the left-stick axes
# instead (LSTICK_*). Binding both means the defaults work on either without
# the user having to know which kind they own.
DEFAULT_BINDINGS: list[dict] = [
    {"combo": "A", "keys": "SUPER+RETURN", "description": "Terminal"},
    {"combo": "B", "keys": "SUPER+F", "description": "Full screen"},
    {"combo": "X", "keys": "SUPER+SHIFT+RETURN", "description": "Browser"},
    {"combo": "Y", "keys": "SUPER+SHIFT+F", "description": "File manager"},
    {"combo": "START", "keys": "SUPER+SPACE", "description": "Omarchy menu"},
    {"combo": "SELECT", "keys": "SUPER+K", "description": "Keybindings"},
    {"combo": "L", "keys": "SUPER+SHIFT+TAB", "description": "Previous workspace"},
    {"combo": "R", "keys": "SUPER+TAB", "description": "Next workspace"},
    {"combo": "DPAD_LEFT", "keys": "SUPER+LEFT", "description": "Focus left window"},
    {"combo": "DPAD_RIGHT", "keys": "SUPER+RIGHT", "description": "Focus right window"},
    {"combo": "DPAD_UP", "keys": "VOLUMEUP", "repeat": True, "description": "Volume up"},
    {
        "combo": "DPAD_DOWN",
        "keys": "VOLUMEDOWN",
        "repeat": True,
        "description": "Volume down",
    },
    {
        "combo": "LSTICK_LEFT",
        "keys": "SUPER+LEFT",
        "description": "Focus left window",
    },
    {
        "combo": "LSTICK_RIGHT",
        "keys": "SUPER+RIGHT",
        "description": "Focus right window",
    },
    {
        "combo": "LSTICK_UP",
        "keys": "VOLUMEUP",
        "repeat": True,
        "description": "Volume up",
    },
    {
        "combo": "LSTICK_DOWN",
        "keys": "VOLUMEDOWN",
        "repeat": True,
        "description": "Volume down",
    },
    {
        "combo": "L + R",
        "exec": "omarchy capture screenshot fullscreen",
        "description": "Screenshot",
    },
    # Locking is on a hold so a pocket press cannot fire it.
    {
        "combo": "SELECT + START",
        "keys": "SUPER+CTRL+L",
        "hold": True,
        "description": "Lock system",
    },
]


class ConfigError(Exception):
    """Raised when a config file cannot be understood."""


class Binding:
    """One combo -> action mapping."""

    __slots__ = ("combo", "keys", "exec", "description", "repeat", "hold", "enabled")

    def __init__(self, raw: dict, index: int):
        where = f"bindings[{index}]"
        if not isinstance(raw, dict):
            raise ConfigError(f"{where} must be an object")

        combo_spec = raw.get("combo")
        if not isinstance(combo_spec, str) or not combo_spec.strip():
            raise ConfigError(f"{where} is missing a 'combo'")
        try:
            self.combo = parse_combo(combo_spec)
        except ValueError as exc:
            raise ConfigError(f"{where}: {exc}") from exc

        self.keys = raw.get("keys")
        self.exec = raw.get("exec")
        if self.keys is not None and not isinstance(self.keys, str):
            raise ConfigError(f"{where}: 'keys' must be a string")
        if self.exec is not None and not isinstance(self.exec, str):
            raise ConfigError(f"{where}: 'exec' must be a string")
        if not self.keys and not self.exec:
            raise ConfigError(f"{where}: needs either 'keys' or 'exec'")

        self.description = str(raw.get("description") or "")
        self.repeat = bool(raw.get("repeat", False))
        self.hold = bool(raw.get("hold", False))
        self.enabled = bool(raw.get("enabled", True))

        if self.repeat and self.hold:
            raise ConfigError(f"{where}: 'repeat' and 'hold' are mutually exclusive")

    @property
    def key(self) -> tuple[str, ...]:
        return self.combo

    def label(self, layout: str = "auto") -> str:
        return format_combo(self.combo, layout)

    def action_summary(self) -> str:
        if self.keys:
            return f"keys {self.keys}"
        return f"exec {self.exec}"

    def to_dict(self) -> dict:
        out: dict = {"combo": " + ".join(self.combo)}
        if self.keys:
            out["keys"] = self.keys
        if self.exec:
            out["exec"] = self.exec
        if self.description:
            out["description"] = self.description
        if self.repeat:
            out["repeat"] = True
        if self.hold:
            out["hold"] = True
        if not self.enabled:
            out["enabled"] = False
        return out


class Config:
    def __init__(self, raw: dict | None = None, path: Path | None = None):
        raw = raw or {}
        self.path = path or CONFIG_PATH

        version = raw.get("version", CONFIG_VERSION)
        if version != CONFIG_VERSION:
            raise ConfigError(
                f"unsupported config version {version!r} "
                f"(this build understands {CONFIG_VERSION})"
            )

        self.device = {**DEFAULT_DEVICE, **(raw.get("device") or {})}
        self.settings = {**DEFAULT_SETTINGS, **(raw.get("settings") or {})}

        match = self.device.get("match")
        if isinstance(match, str):
            match = [match]
        if match is None:
            match = []
        if not isinstance(match, list) or any(not isinstance(m, str) for m in match):
            raise ConfigError("device.match must be a string or list of strings")
        self.device["match"] = [m.lower() for m in match]

        raw_bindings = raw.get("bindings")
        if raw_bindings is None:
            raw_bindings = DEFAULT_BINDINGS
        if not isinstance(raw_bindings, list):
            raise ConfigError("'bindings' must be a list")

        self.bindings: list[Binding] = []
        seen: dict[tuple[str, ...], int] = {}
        for index, item in enumerate(raw_bindings):
            binding = Binding(item, index)
            if binding.combo in seen:
                raise ConfigError(
                    f"bindings[{index}]: combo {binding.label()!r} is already "
                    f"bound at bindings[{seen[binding.combo]}]"
                )
            seen[binding.combo] = index
            self.bindings.append(binding)

    # -- accessors ----------------------------------------------------------

    @property
    def layout(self) -> str:
        return str(self.device.get("layout", "auto"))

    @property
    def exclusive(self) -> bool:
        return bool(self.device.get("exclusive", False))

    def setting(self, name: str) -> float:
        return float(self.settings.get(name, DEFAULT_SETTINGS[name]))

    def active_bindings(self) -> list[Binding]:
        return [b for b in self.bindings if b.enabled]

    def find(self, combo: tuple[str, ...]) -> Binding | None:
        for binding in self.bindings:
            if binding.combo == combo:
                return binding
        return None

    def remove(self, combo: tuple[str, ...]) -> bool:
        before = len(self.bindings)
        self.bindings = [b for b in self.bindings if b.combo != combo]
        return len(self.bindings) != before

    def upsert(self, binding: Binding) -> bool:
        """Add or replace a binding. Returns True when it replaced an existing one."""
        for index, existing in enumerate(self.bindings):
            if existing.combo == binding.combo:
                self.bindings[index] = binding
                return True
        self.bindings.append(binding)
        return False

    # -- serialisation ------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "version": CONFIG_VERSION,
            "device": self.device,
            "settings": self.settings,
            "bindings": [b.to_dict() for b in self.bindings],
        }

    def save(self, path: Path | None = None) -> Path:
        target = Path(path or self.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), indent=2) + "\n"
        # Write atomically so a crash mid-save can never truncate the config.
        handle, tmp_name = tempfile.mkstemp(
            dir=str(target.parent), prefix=".config-", suffix=".json"
        )
        try:
            with os.fdopen(handle, "w") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, target)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        return target


def load(path: Path | None = None, *, create: bool = False) -> Config:
    target = Path(path or CONFIG_PATH)
    if not target.exists():
        config = Config({}, path=target)
        if create:
            config.save()
        return config
    try:
        raw = json.loads(target.read_text())
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{target}: invalid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{target}: top level must be an object")
    return Config(raw, path=target)
