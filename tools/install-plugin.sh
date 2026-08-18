#!/usr/bin/env bash
# Install (or re-install) this working tree as an Omarchy shell plugin.
#
# Omarchy refuses symlinks inside a plugin folder, so a checkout cannot simply
# be linked into place -- it has to be copied. This mirrors what
# `omarchy plugin add <git-url>` would drop there, minus the VCS metadata.
set -euo pipefail

id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["id"])' \
      "$(dirname "$0")/../manifest.json")"
src="$(cd "$(dirname "$0")/.." && pwd)"
dest="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/$id"

if [ -L "$dest" ]; then
  rm -f "$dest"
fi

mkdir -p "$dest"
rsync -a --delete \
  --exclude '.git/' \
  --exclude '.gitignore' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.venv/' \
  "$src/" "$dest/"

omarchy plugin validate "$dest"
echo "installed $id -> $dest"

if ! omarchy plugin list 2>/dev/null | grep -q "$id"; then
  echo "note: enable it with 'omarchy plugin enable $id'"
fi

# Pick up the new code without restarting the whole shell.
omarchy-shell shell rescanPlugins >/dev/null 2>&1 || true
echo "shell rescanned"
