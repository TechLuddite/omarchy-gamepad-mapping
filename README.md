# Controller Control

Map game controller button combos to desktop shortcuts and commands, as an
Omarchy shell plugin.

Press `L + R` to take a screenshot. Press `START` to open the Omarchy menu.
Hold `SELECT + START` to lock the screen. Any chord, any action.

Built for an **8BitDo Zero 2**, but it works with any pad the kernel exposes —
Xbox, DualSense, generic USB gamepads.

## Why it exists

Omarchy already has 200+ keybindings. This does not try to replace them: a
binding can simply *type* an existing shortcut, so `A -> SUPER+RETURN` opens a
terminal through the keybinding you already have. Nothing is duplicated.

## Install

```bash
omarchy plugin add https://github.com/perminder-klair/omarchy-controller-control.git --enable
```

From a local checkout instead:

```bash
./tools/install-plugin.sh
omarchy plugin enable co.klair.controller-control
```

There is nothing to compile and nothing to `pip install` — the engine is pure
Python standard library, which is also why the plugin needs no install hook.

### Requirements

- Your user must be in the `input` group (stock on Omarchy) to read
  `/dev/input`. Check with `id`.
- `/dev/uinput` must be writable for `keys` actions. `controller-control
  doctor` verifies both.

## Pairing an 8BitDo Zero 2

The Zero 2 boots into whichever mode you last used. For Bluetooth on Linux,
use **D-input**:

| Hold on power-on | Mode | Linux over Bluetooth |
|---|---|---|
| `START + B` | D-input | works — pairs as "8BitDo Zero 2 gamepad" |
| `START + X` | X-input | intended for the 2.4G dongle / Windows |
| `START + A` | macOS | works |
| `START + Y` | Switch | works |

Pair it once with `bluetoothctl`, then `trust` it so it reconnects on its own.

## Usage

The bar widget shows a controller glyph — solid when a pad is connected, dim
when not, and it pulses whenever a binding fires. Click it to open the
bindings panel, where **Record combo** captures whatever you press next.

Everything is also available from the CLI:

```bash
controller-control doctor          # check permissions, config, and the pad
controller-control devices         # what the kernel sees
controller-control monitor         # print button tokens as you press them
controller-control learn           # record one combo and print its token
controller-control list            # show configured bindings
controller-control bind "L + R" --keys SUPER+RETURN --description Terminal
controller-control bind START --exec 'omarchy menu'
controller-control unbind "L + R"
controller-control test "L + R"    # run a binding's action now
```

The binary lives inside the plugin folder; add it to your `PATH` with:

```bash
export PATH="$HOME/.config/omarchy/plugins/co.klair.controller-control/bin:$PATH"
```

## Button names

Buttons are named by the Linux/evdev convention, which follows the Xbox
layout: `A` is the south face button, `B` east, `X` north, `Y` west. Also
available: `L`, `R`, `L2`, `R2`, `SELECT`, `START`, `MODE`, `THUMBL`,
`THUMBR`, `DPAD_UP/DOWN/LEFT/RIGHT`, and stick directions such as
`LSTICK_LEFT`.

8BitDo pads use the Nintendo *physical* layout, where A sits on the right and
B on the bottom — the opposite of where evdev expects them. In practice their
D-input firmware is **label-faithful**: a Zero 2 sends the code for `A` when
you press the button printed "A", so the tokens match the plastic and nothing
needs swapping. Other pads and other firmware modes are not guaranteed to do
this.

So: don't reason about it, measure it. `controller-control learn` (or the
panel's **Record combo**) reports exactly what your pad sends. If your pad
turns out to be position-faithful instead, set `device.layout` to `"nintendo"`
to relabel the face buttons in the UI so they match the plastic.

D-pads arrive as a hat axis and analog triggers as an axis; both are
translated into ordinary button tokens for you.

> **8BitDo in D-input mode:** the d-pad is reported on the *left stick* axes
> rather than the hat, so it arrives as `LSTICK_UP/DOWN/LEFT/RIGHT` and not
> `DPAD_*`. The shipped defaults bind both, so they work either way — but if
> you write your own d-pad binding and it never fires, run `monitor` and check
> which one your pad actually sends.

## Configuration

`~/.config/controller-control/config.json`:

```json
{
  "version": 1,
  "device": {
    "match": ["8bitdo"],
    "exclusive": false,
    "layout": "nintendo"
  },
  "settings": {
    "combo_window_ms": 45,
    "hold_ms": 450,
    "repeat_delay_ms": 400,
    "repeat_interval_ms": 110
  },
  "bindings": [
    { "combo": "START", "keys": "SUPER+SPACE", "description": "Omarchy menu" },
    { "combo": "L + R", "exec": "omarchy capture screenshot" },
    { "combo": "DPAD_UP", "keys": "VOLUMEUP", "repeat": true },
    { "combo": "SELECT + START", "keys": "SUPER+CTRL+L", "hold": true }
  ]
}
```

**Bindings** take either `keys` (typed on a virtual keyboard, so Hyprland
handles it exactly like a real shortcut) or `exec` (a shell command). Options:

- `repeat` — fire again while held, for volume and brightness.
- `hold` — only fire after a long press, for anything destructive.
- `enabled: false` — keep a binding around without it firing.

**`device.match`** is a list of case-insensitive substrings matched against
the device name. It defaults to empty, which matches any gamepad — narrow it
when you own several pads and only want one of them driving the desktop. A
keyboard-shaped device (an 8BitDo in keyboard mode) is only picked up when you
name it explicitly, so an empty list can never latch onto your real keyboard. **`device.exclusive`**
grabs the pad so nothing else — games, Steam, the browser — sees it.

The daemon reloads on `SIGHUP`, which is what the panel and
`omarchy-shell controller reload` use, so edits apply without dropping the
Bluetooth connection.

## How chords are resolved

- Bindings fire on **press**, never on release, so letting go of `L + R`
  cannot also trigger `R`.
- When the buttons held could still grow into a longer binding, the decision
  waits `combo_window_ms`. When no longer binding could match, it fires
  instantly — single presses have no added latency.
- A binding that has fired is latched until one of its own buttons is
  released, so holding a chord does not retrigger it.

This means `A` and `A + B` can coexist: tapping `A` fires `A`, and pressing
both fires only `A + B`.

## IPC

```bash
omarchy-shell controller status    # JSON: running, connected, device, bindings
omarchy-shell controller reload    # re-read the config
omarchy-shell controller restart   # bounce the daemon
```

## Architecture

```
omarchy-shell (Quickshell)
├── Service.qml      runs the daemon, parses its JSON event stream, IPC
├── BarWidget.qml    connection glyph, pulses on fire
└── Panel.qml        bindings editor with press-to-record capture
        │
        └── bin/controller-control daemon
                └── engine/   pure-stdlib evdev reader + chord recogniser
```

The daemon reads `/dev/input/event*` directly and emits one JSON object per
line, which is what the QML layer consumes. `keys` actions are typed on a
uinput virtual keyboard, so the compositor treats them as a real keyboard.

Device inspection is cached per device node: opening an input node blocks for
around 20ms in the kernel, so re-inspecting every node to spot a hotplug would
stall the daemon's timers. Listing the nodes is a sub-millisecond glob, and
only genuinely new nodes are opened.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

33 tests, no dependencies. The end-to-end suite fabricates a synthetic gamepad
over uinput and drives the real daemon process against it, so chord
resolution, hotplug, disconnect, repeat, and hold are all covered without
touching real hardware.

## License

MIT
