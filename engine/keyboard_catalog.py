"""Standard keyboard keys, using canonical names accepted by the key parser."""

from .keys import KEY_ALIASES, parse_keys


def keyboard_catalog() -> list[dict[str, str]]:
    groups = [
        (list("ABCDEFGHIJKLMNOPQRSTUVWXYZ"), "Letter"),
        (list("1234567890"), "Number"),
        (["SPACE", "ENTER", "TAB", "ESC", "BACKSPACE", "DELETE", "INSERT",
          "HOME", "END", "PAGEUP", "PAGEDOWN", "LEFT", "RIGHT", "UP", "DOWN"], "Navigation"),
        (["MINUS", "EQUAL", "LEFTBRACE", "RIGHTBRACE", "BACKSLASH", "SEMICOLON",
          "APOSTROPHE", "GRAVE", "COMMA", "DOT", "SLASH", "102ND"], "Punctuation"),
        ([f"F{i}" for i in range(1, 25)], "Function"),
        (["LEFTSHIFT", "RIGHTSHIFT", "LEFTCTRL", "RIGHTCTRL", "LEFTALT", "RIGHTALT",
          "LEFTMETA", "RIGHTMETA", "CAPSLOCK", "NUMLOCK", "SCROLLLOCK", "SYSRQ",
          "PAUSE", "COMPOSE"], "Modifier / system"),
        ([f"KP{i}" for i in range(10)] + ["KPDOT", "KPENTER", "KPPLUS", "KPMINUS",
          "KPASTERISK", "KPSLASH", "KPEQUAL", "KPCOMMA"], "Keypad"),
    ]
    labels = {
        "ENTER": "Enter / Return", "ESC": "Escape", "LEFTBRACE": "Left bracket",
        "RIGHTBRACE": "Right bracket", "DOT": "Period / Dot", "102ND": "ISO extra key",
        "LEFTMETA": "Left Super / Meta", "RIGHTMETA": "Right Super / Meta",
        "LEFTCTRL": "Left Ctrl", "RIGHTCTRL": "Right Ctrl", "LEFTSHIFT": "Left Shift",
        "RIGHTSHIFT": "Right Shift", "LEFTALT": "Left Alt", "RIGHTALT": "Right Alt",
        "SYSRQ": "Print screen / SysRq", "KPENTER": "Keypad Enter",
    }
    labels.update({"PAGEUP": "Page up", "PAGEDOWN": "Page down", "CAPSLOCK": "Caps lock",
        "NUMLOCK": "Num lock", "SCROLLLOCK": "Scroll lock", "BACKSPACE": "Backspace",
        "GRAVE": "Backtick / Tilde", "EQUAL": "Equal / Plus", "BACKSLASH": "Backslash",
        "KPDOT": "Keypad decimal", "KPPLUS": "Keypad plus", "KPMINUS": "Keypad minus",
        "KPASTERISK": "Keypad multiply", "KPSLASH": "Keypad divide", "KPEQUAL": "Keypad equal",
        "KPCOMMA": "Keypad comma", "LEFTBRACE": "Left bracket", "RIGHTBRACE": "Right bracket"})
    labels.update({f"KP{i}": f"Keypad {i}" for i in range(10)})
    result = []
    for names, group in groups:
        for name in names:
            # The catalog and free-form field share one parser, so every
            # offered key remains usable regardless of alias additions.
            parse_keys(name)
            title = labels.get(name, name.title())
            aliases = [alias for alias, target in KEY_ALIASES.items() if target == name]
            result.append({"value": name, "keys": name, "actionDescription": title,
                           "description": " · ".join([group, name, *aliases]), "label": title})
    return result
