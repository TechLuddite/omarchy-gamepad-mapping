"""Standard keyboard keys, using the same names as the mapper's key parser."""
import json
from .keys import parse_keys


def catalog():
    groups = [
        (list('ABCDEFGHIJKLMNOPQRSTUVWXYZ'), 'Letter'),
        (list('1234567890'), 'Number'),
        (['SPACE', 'ENTER', 'TAB', 'ESC', 'BACKSPACE', 'DELETE', 'INSERT',
          'HOME', 'END', 'PAGEUP', 'PAGEDOWN', 'LEFT', 'RIGHT', 'UP', 'DOWN'], 'Navigation'),
        (['MINUS', 'EQUAL', 'LEFTBRACE', 'RIGHTBRACE', 'BACKSLASH', 'SEMICOLON',
          'APOSTROPHE', 'GRAVE', 'COMMA', 'DOT', 'SLASH', '102ND'], 'Punctuation'),
        ([f'F{i}' for i in range(1, 25)], 'Function'),
        (['LEFTSHIFT', 'RIGHTSHIFT', 'LEFTCTRL', 'RIGHTCTRL', 'LEFTALT', 'RIGHTALT',
          'LEFTMETA', 'RIGHTMETA', 'CAPSLOCK', 'NUMLOCK', 'SCROLLLOCK', 'SYSRQ',
          'PAUSE', 'COMPOSE'], 'Modifier / system'),
        ([f'KP{i}' for i in range(10)] + ['KPDOT', 'KPENTER', 'KPPLUS', 'KPMINUS',
          'KPASTERISK', 'KPSLASH', 'KPEQUAL', 'KPCOMMA'], 'Keypad'),
    ]
    result = []
    for names, group in groups:
        for name in names:
            parse_keys(name)
            result.append(dict(value=name, keys=name, description=name.title(),
                               label=f'{name.title()} · {group}'))
    return result


if __name__ == '__main__':
    print(json.dumps(catalog()))
