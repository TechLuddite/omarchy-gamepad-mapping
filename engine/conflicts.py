"""Read-only context for potential overlap with Hyprland input bindings.

Matching an input identity is advisory: modifiers, exclusive grabs, submaps and
application behavior determine whether both actions can actually fire.
"""

from __future__ import annotations

import json
import os
import subprocess

from ._codes import BTN_CODES
from .buttons import button_for_key_code
from .keys import KeyParseError, resolve_key
from .linux_input import KEY_MAX


def _integer(value) -> int:
    # JSON booleans and floats must not become plausible input identities.
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("Expected an integer")
    return int(value)


def external_bindings(binds: list[dict]) -> list[dict]:
    """Translate compositor input identities, retaining modifier context.

    Hyprland's keycodes use XKB numbering (evdev + 8); mouse codes use evdev
    numbering directly. Named keys are best-effort Linux key aliases, so named
    symbol bindings may differ under another keyboard layout.
    """
    result = []
    for bind in binds:
        if not isinstance(bind, dict):
            continue
        key = str(bind.get("key") or "")
        try:
            keycode = _integer(bind.get("keycode") if bind.get("keycode") is not None else 0)
            if key.startswith("mouse:"):
                code = _integer(key.partition(":")[2])
            elif keycode:
                code = keycode - 8
            elif key.startswith("code:"):
                code = _integer(key.partition(":")[2]) - 8
            else:
                code = resolve_key(key)
            modifiers = _integer(bind.get("modmask") if bind.get("modmask") is not None else 0)
        except (ValueError, TypeError, KeyParseError):
            continue
        if not 0 < code <= KEY_MAX or modifiers < 0:
            continue
        # BACK is a legacy config alias for SELECT. Never report raw BTN_BACK
        # as SELECT, even before dedicated BACK_BUTTON support is installed.
        token = "BACK_BUTTON" if code == BTN_CODES["BACK"] else button_for_key_code(code)
        result.append({
            "token": token,
            "code": code,
            "key": key,
            "description": str(bind.get("description") or (bind.get("dispatcher") if bind.get("dispatcher") != "__lua" else "") or f"{key or f'code:{keycode}'} (modifiers {modifiers})"),
            "modifiers": modifiers,
            "submap": str(bind.get("submap") or ""),
            "kind": "compositor",
        })
    return result


def report() -> dict:
    """Read only the inherited active session; never select another session."""
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return {"available": False, "bindings": [], "error": "No active Hyprland session"}
    try:
        data = json.loads(subprocess.check_output(
            ["hyprctl", "-j", "binds"], text=True, timeout=3,
            stderr=subprocess.DEVNULL,
        ))
        if not isinstance(data, list):
            raise ValueError("Unexpected bindings response")
        identified = external_bindings(data)
        return {"available": True, "bindings": identified, "error": "",
                "unidentified": len(data) - len(identified)}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"available": False, "bindings": [], "error": "Could not read compositor bindings"}
