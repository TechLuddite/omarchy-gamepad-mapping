# Omarchy Gamepad Mapping — agent context

This is the existing Omarchy plugin, forked from Parminder Klair's Controller
Control. It is not an OpenCode extension. Read README.md, PORTAL.md and CREDITS.md
before changing it; inspect git status and the latest commit and preserve user work.
Keep the plugin ID `co.klair.controller-control` and existing binding JSON format.

- Editor: Panel.qml and ShortcutDropdown.qml; both shortcut and standard-key
  catalogs use full-window Back/search/list panels. Selecting one action clears
  the other. Do not automatically show the keyboard when opening a picker.
- Catalogs: engine/keyboard_catalog.py and existing Omarchy shortcut reader.
  The standard catalog contains 119 unique parseable keys.
- Conflicts: engine/conflicts.py reads external compositor/native Back mappings.
  Report conflicts or read failure; do not rewrite unrelated OS bindings.
- Optional gate: engine/mode_gate.py suppresses OS actions when an opted-in
  runtime lease is missing, stale or disallows mapping. Generic installs without
  a gate keep existing behavior. Service.qml exposes mode/suppression separately
  from the user's enabled/paused switches.
- Run `python3 -m unittest discover -s tests -v` and check QML parsing/rendering
  for relevant edits. Current host/ARM suite: 58 tests. Physical game input,
  Back suppression, printed button labels, hold timing and rear paddles remain
  separate from synthetic input tests.

The native AYN Odin 2 **Portal** broker, five-second A + R1 toggle, Hyprland
pointer policy, stock OSK and status dashboard belong to the parent project,
not a generic installation of this plugin. On the maintenance host the parent
is `/srv/projects/odin2-omarchy`; its AGENTS.md and docs/bugs-controls.md record
device access, installation, rollback, preferences and physical acceptance.
Preserve live user-edited bindings; do not restore the old Home/Back/L1 snapshot.
Use user-owned plugin paths, never edit packaged `/usr/share/omarchy/` assets.
If plugin rescanning retains old QML, a shell restart through the real graphical
user manager was required on this Portal; verify the actual editor afterward.

Parent and mapper have independent indexes/commits. For a local checkpoint,
audit the exact staged mapper tree, commit it first, then update the parent's
gitlink/source pin and audit/commit the parent. A prepared index is not a new
commit. The parent `scripts/audit-mapper-tree.py --history` checks this entire
index/history and parent known secrets, allowing only four exact, pinned,
already-public upstream sample/helper entries. Its local pre-commit hook runs
the staged-tree check; do not bypass it or use blanket image/tools exemptions.
Keep raw captures, input/session data, backups and credentials out of Git;
preserve original MIT notices. No push, issue, comment or PR is authorized by
context maintenance or local commit preparation.
