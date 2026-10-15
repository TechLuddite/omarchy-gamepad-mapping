# Odin2 Portal adaptation

Based on [Controller Control](https://github.com/perminder-klair/omarchy-controller-control)
at `d5ac4cb41926fc93d2516a4f54bc5ec300d7838e`, by Parminder Klair (MIT).

The original evdev/uinput engine and binding recorder are retained. The editor
is an ordinary window, so the handheld keyboard remains reachable; the service
provides `omarchy-shell controller open` for the application drawer. Relevant
QtQuick imports use API 6.11 to avoid Qt 6.12's Color name collision. Explicit
device filters can select media-key-only hardware nodes as well as gamepads.

Bindings stay in `~/.config/controller-control/config.json`. Recording mutes
existing actions until all captured buttons are released. Press Record combo,
press and release the desired buttons, choose an action from the Step 2 dropdown,
and save. The dropdown reads Omarchy's live keybinding list and fills the action
description automatically. No typing is required. Tap the dropdown’s search
field to filter by action name or key combination; the keyboard opens only
when you tap that field. Keyboard shortcuts use the
virtual keyboard; wheel-based Omarchy shortcuts resolve their current action
from Omarchy's menu metadata. Custom commands remain available through the CLI
and JSON configuration.
The initial Portal configuration has no assigned actions. The master switch
keeps assignments while disabling their execution. Native gamepad input remains
available to games by default.

Hold and repeat options are also available through the CLI (`bind --hold` or
`bind --repeat`) and the JSON configuration. These options are not exposed in
the current form. The native device passes 58 tests: 44 upstream, three Portal
device/button checks, five shortcut-catalog checks and six catalog/mode/conflict checks. The October 14 parent-port check physically correlates left/right paddles with
GPIO57/58 on this Portal. A separate userspace bridge exposes their input;
the mapper does not read GPIOs or ship board policy.

## Later bug-session changes

The editor now offers a second searchable picker for 119 standard keyboard keys
alongside the live Omarchy shortcut picker. Selecting either clears the other;
Clear resets both. They save through the existing `keys`/`exec` configuration.
Both pickers fill the editor window with a Back button, search and a scrolling
list, so bottom-positioned triggers cannot clip their results. The Portal user
confirmed both revised pickers. Restart the shell if rescanning retains old QML.

Existing volume/power compositor bindings and native mouse Back navigation are
shown read-only, with warnings next to intersecting existing and draft mappings.
This follows TechLuddite's MIT Luddite Gestures ownership/conflict design; the
evdev/Hyprland reader is original, not copied gesture code. Reading failure is
shown explicitly rather than claiming that no external mappings exist.

The Portal integration supplies an optional `device.mode_gate` runtime lease.
Missing/stale leases suppress actions; generic installs without that option
retain their previous behavior. The Portal broker defaults to Game Mode and
uses left-paddle hold plus right-paddle taps to cycle Game → OS → Pointer → Game.
OS Mode activates these assignments; Pointer Mode exclusively owns navigation.
A + R1 no longer switches modes. The editor displays all three lease states.
The physical pad is disabled only as a Hyprland mouse so native BTN_BACK cannot
also navigate apps behind the mapper. Separate volume/power devices retain their
OS bindings. Games retain evdev input; physical game acceptance remains separate.
The new split OSK is disabled at the user's request; stock moarchy-keyboard stays
active. See the parent project's docs/bugs-controls.md for tests and rollback.

### Shared Omarchy controls — October 14

The editor and full-window pickers now explicitly import `qs.Ui as Ui`. Back
uses `Ui.Button` with standard hover/focus/press borders; result rows use
`Ui.CursorSurface`, with shared TextField/separator/scrollbar surfaces. Popup
foreground comes from `Color.popups.text`. Preserve live theme bindings and use
actual Omarchy components for new controls. No configuration schema or binding
record changes accompany this styling fix. Parent `docs/themed-ui.md` records
the Portal's additional UI plugin, theme tests and remaining physical checks.
