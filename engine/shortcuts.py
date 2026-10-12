"""Read Omarchy's current shortcut menu without opening it or firing actions."""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import shlex
import subprocess
import sys

from .keys import KeyParseError, parse_keys


def parse_catalog(text: str, records: dict[str, tuple[str, str]], launcher: str) -> list[dict]:
    options = []
    seen = set()
    for row in text.splitlines():
        combo, arrow, description = row.partition("→")
        if not arrow or not description.strip():
            continue
        combo, description = combo.strip(), description.strip()
        identity = row.strip()
        if identity in seen:
            continue
        seen.add(identity)
        option = {"value": identity, "label": f"{description} · {combo}", "description": description}
        keys = "+".join(combo.replace("+", " ").split())
        try:
            parse_keys(keys)
            option["keys"] = keys
        except KeyParseError:
            # Wheel shortcuts cannot be replayed through a virtual keyboard.
            # Resolve their current dispatch metadata each time they run.
            dispatcher, arg = records.get(identity, ("", ""))
            if dispatcher not in ("lua", "exec", "sendshortcut") or not arg:
                continue
            option["exec"] = shlex.join([launcher, "run", identity])
        options.append(option)
    return options


def live_catalog() -> tuple[list[dict], dict[str, tuple[str, str]]]:
    env = os.environ.copy()
    env.setdefault("OMARCHY_PATH", "/usr/share/omarchy")
    if not env.get("HYPRLAND_INSTANCE_SIGNATURE"):
        instances = json.loads(subprocess.check_output(["hyprctl", "instances", "-j"], text=True, env=env, timeout=5))
        if len(instances) != 1:
            raise RuntimeError("Select the active Hyprland session before reading shortcuts")
        env["HYPRLAND_INSTANCE_SIGNATURE"] = instances[0]["instance"]
    os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = env["HYPRLAND_INSTANCE_SIGNATURE"]
    text = subprocess.check_output(["omarchy", "menu", "keybindings", "--print"], text=True, env=env, timeout=20)
    # The menu refreshes these records from the active compositor and Lua
    # configuration. Only rows in the freshly printed menu are accepted.
    cache = Path(env.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "omarchy"
    devices = subprocess.check_output(["hyprctl", "devices"], text=True, env=env, timeout=5)
    binds = subprocess.check_output(["hyprctl", "binds"], text=True, env=env, timeout=5)
    # Same cache identity as the installed Omarchy menu, including the active
    # keyboard layout. Never borrow dispatch data from another session/cache.
    keymap = "".join(line + "\n" for line in devices.splitlines() if "active keymap:" in line)
    digest = hashlib.sha256(("v11\n" + keymap + binds).encode()).hexdigest()
    path = cache / f"keybindings-{digest}.records"
    records = {}
    if path.exists():
        for row in path.read_text().splitlines():
            fields = row.split("\t", 2)
            if len(fields) == 3:
                records[fields[0].strip()] = (fields[1], fields[2])
    launcher = str(Path(__file__).resolve().parent.parent / "bin/omarchy-shortcuts")
    return parse_catalog(text, records, launcher), records


def main() -> int:
    try:
        options, records = live_catalog()
        if len(sys.argv) == 1 or sys.argv[1:] == ["list"]:
            print(json.dumps(options))
            return 0
        if len(sys.argv) != 3 or sys.argv[1] != "run":
            raise RuntimeError("Usage: omarchy-shortcuts [list | run <shortcut>]")
        identity = sys.argv[2]
        if not any(o["value"] == identity for o in options):
            raise RuntimeError("This shortcut is no longer configured; choose it again")
        dispatcher, arg = records.get(identity, ("", ""))
        if dispatcher == "lua":
            command = ["hyprctl", "dispatch", arg]
        elif dispatcher in ("exec", "sendshortcut"):
            command = ["hyprctl", "dispatch", dispatcher, arg]
        else:
            raise RuntimeError("No current action is available for this shortcut")
        return subprocess.run(command, check=False, env=os.environ.copy()).returncode
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
