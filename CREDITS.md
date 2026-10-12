# Credits and provenance

This mapper exists because of the projects below. Preserve their notices when
copying or redistributing the code, and add credits as further work is reused.

- **Parminder Klair**, [Controller Control](https://github.com/perminder-klair/omarchy-controller-control),
  pinned at `d5ac4cb41926fc93d2516a4f54bc5ec300d7838e`: the Python evdev/uinput
  engine, combo matching, recording service, original QML editor and upstream
  tests. MIT notice retained in `LICENSE`.
- **David Heinemeier Hansson and Omarchy contributors**,
  [Omarchy](https://github.com/basecamp/omarchy), pinned at
  `0534987009061cbe2dacdde4ad564092ab698d12`: the shell/plugin API and theme UI.
  `ShortcutDropdown.qml` adapts `Ui/SearchableDropdown.qml`, adding direct touch
  selection, optional search focus and a popup height limit. MIT notice retained
  in `OMARCHY-LICENSE` and the source header.
- **Simon Schubert**, [omarchy-mobile](https://github.com/SimonSchubert/omarchy-mobile)
  and [moarchy-keyboard](https://github.com/SimonSchubert/moarchy-keyboard): the
  mobile shell and on-screen keyboard used to develop and test this editor.
  They remain separate dependencies, not bundled copies in this repository.
- **Linux input, Qt and Quickshell contributors**: the kernel input interfaces,
  rendering toolkit and shell runtime this plugin uses.

**TechLuddite’s adaptation** adds the touch workflow, searchable live shortcut
catalog, automatic descriptions, dedicated Odin Back-button token, compatibility
with Qt 6.12, and native device verification. The parent `odin2-omarchy` project
records the broader kernel, bootloader, firmware, hardware and application work.
