# Omarchy Gamepad Mapping

A touch-focused Omarchy shortcut mapper, built on **Parminder Klair’s
[Controller Control](https://github.com/perminder-klair/omarchy-controller-control)**.
The shortcut picker uses **David Heinemeier Hansson’s Omarchy UI**. Thanks also to
**Simon Schubert’s mobile Omarchy work** for the handheld environment this is
being developed on. See [CREDITS.md](CREDITS.md) for provenance and licenses.

Record a button or combination, choose an Omarchy action from a searchable
menu, and save. You can do the whole assignment by touch. The action’s name
fills automatically. Search matches names and keys, ignoring spaces and plus
signs; opening the menu does not summon the keyboard until you tap its search
field. Existing shortcuts are read from the running Omarchy configuration.

The normal window leaves the on-screen keyboard accessible. Assignments remain
available while the master switch disables execution, and native gamepad input
continues to reach games by default. Single buttons, chords, analog triggers,
stick directions, hold and repeat actions are supported by the inherited engine.
Hold/repeat and custom commands are available through its CLI and JSON config.
The Odin’s dedicated Back button is separate from Select.

## Install

On Omarchy:

```sh
omarchy plugin add https://github.com/TechLuddite/omarchy-gamepad-mapping.git --enable
```

This compatible fork retains plugin ID `co.klair.controller-control` and the
existing `~/.config/controller-control/config.json`, so existing assignments
survive. Install one version of Controller Control at a time. Back up your
current plugin directory before replacing the original with this fork.

The user must be able to read the selected controller’s `/dev/input/event*`
node and write `/dev/uinput`. On the Odin port, membership in `input` and the
narrow uinput udev rule are provisioned by the native installer. Use the
inherited CLI’s `doctor` command to check access before enabling assignments.
The plugin does not run privileged installation hooks.

Open the editor from the bar widget or:

```sh
omarchy-shell controller open
```

For the Odin’s mobile bar, an application-drawer launcher is installed by the
native port. That integration is tracked in the parent `odin2-omarchy` project.
Bindings and CLI instructions are in [UPSTREAM.md](UPSTREAM.md); its old editor
screens/instructions describe the original upstream form. [PORTAL.md](PORTAL.md)
describes this fork’s handheld adaptations.

## Verified platform and checks

Development device: AYN Odin2 Portal, native ARM64 Linux, Omarchy 4.0.3 with
omarchy-mobile, Hyprland 0.56.2 and Qt 6.12. The initial menu exports all 223
configured shortcuts; installing Voxtype adds Omarchy’s dictation bindings.

52 tests pass on the ARM device: the upstream 44, three Portal device/button
checks, and five shortcut-catalog checks. The integration tests use a synthetic
pad and run actions in dry-run mode. Physical rear paddles and full game
compatibility remain separate hardware checks.

```sh
python3 -m unittest discover -s tests -v
```

Raw device evidence, the complete native port, and hardware bring-up notes stay
in `/srv/projects/odin2-omarchy`. This repository contains reusable mapper code.

## License

MIT. Original engine/QML notices remain in [LICENSE](LICENSE); Omarchy UI’s
notice remains in [OMARCHY-LICENSE](OMARCHY-LICENSE). See [CREDITS.md](CREDITS.md).
