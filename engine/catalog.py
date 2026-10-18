"""Read-only editor catalogs. Importing or browsing never opens input devices."""

from __future__ import annotations

import json
import os
import subprocess

from .keys import KeyParseError, parse_keys


class CatalogError(Exception):
    """The current compositor's bindings could not be read."""


def shortcut_catalog(binds: list[dict]) -> list[dict[str, str]]:
    """Keep ordinary, globally available keyboard shortcuts we can replay.

    The value is a key chord, never a cached dispatcher or shell command.
    XKB keysyms are accepted only when the existing key parser understands
    them. This is intentionally conservative about special bind semantics.
    """
    descriptions: dict[str, list[str]] = {}
    for bind in binds:
        if not isinstance(bind, dict):
            continue
        if any(bind.get(flag) for flag in (
            "mouse", "release", "longPress", "locked", "catch_all",
            "catchAll", "submap", "ignore_mods", "ignoreMods",
            "multiKey", "click", "drag", "devices",
        )):
            continue
        if bind.get("enabled") is False:
            continue
        keycode = bind.get("keycode", 0)
        if isinstance(keycode, bool) or not isinstance(keycode, int) or keycode != 0:
            continue
        key = bind.get("key")
        mask = bind.get("modmask")
        if not isinstance(key, str) or not key.strip():
            continue
        if isinstance(mask, bool) or not isinstance(mask, int) or mask < 0 or mask & ~77:
            continue
        # Do not turn raw keycodes or pointer tokens into a keyboard shortcut.
        if ":" in key or "+" in key or "," in key:
            continue
        modifiers = [name for bit, name in ((64, "SUPER"), (4, "CTRL"),
                                             (8, "ALT"), (1, "SHIFT")) if mask & bit]
        keys = "+".join(modifiers + [key.strip().upper()])
        try:
            parse_keys(keys)
        except KeyParseError:
            continue
        description = bind.get("description")
        if not isinstance(description, str) or not description.strip():
            # Dispatch arguments may contain private data; don't expose them
            # as fallback labels or copy them into executable actions.
            description = "Keyboard shortcut"
        description = description.strip()
        names = descriptions.setdefault(keys, [])
        if description not in names:
            names.append(description)
    return [
        {"value": keys, "keys": keys, "label": f"{'; '.join(names)} · {keys}",
         "description": "; ".join(names)}
        for keys, names in sorted(descriptions.items())
    ]


def live_shortcuts() -> list[dict[str, str]]:
    """Read one explicit/current Hyprland session using its public JSON API."""
    env = os.environ.copy()

    def read(*args: str):
        try:
            output = subprocess.check_output(
                ["hyprctl", *args], text=True, env=env, timeout=5,
                stderr=subprocess.DEVNULL,
            )
            return json.loads(output)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise CatalogError("Cannot read Hyprland shortcuts; check the active session.") from exc

    if not env.get("HYPRLAND_INSTANCE_SIGNATURE"):
        instances = read("instances", "-j")
        if not isinstance(instances, list) or len(instances) != 1:
            raise CatalogError("Select a Hyprland session with HYPRLAND_INSTANCE_SIGNATURE.")
        instance = instances[0]
        if not isinstance(instance, dict) or not isinstance(instance.get("instance"), str) or not instance["instance"]:
            raise CatalogError("Hyprland did not report an active session.")
        env["HYPRLAND_INSTANCE_SIGNATURE"] = instance["instance"]
    binds = read("-j", "binds")
    if not isinstance(binds, list):
        raise CatalogError("Hyprland returned an invalid shortcut list.")
    return shortcut_catalog(binds)
