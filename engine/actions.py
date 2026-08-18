"""Running the action attached to a binding."""

from __future__ import annotations

import signal
import subprocess

from .keys import KeyParseError, VirtualKeyboard, parse_keys


class ActionRunner:
    def __init__(self, dry_run: bool = False, keyboard: VirtualKeyboard | None = None):
        self.dry_run = dry_run
        self.keyboard = keyboard or VirtualKeyboard()
        self._key_cache: dict[str, list[int]] = {}
        if not dry_run:
            # Fire-and-forget children; never leave zombies behind.
            try:
                signal.signal(signal.SIGCHLD, signal.SIG_IGN)
            except (ValueError, OSError):
                pass

    def close(self) -> None:
        self.keyboard.close()

    def codes_for(self, spec: str) -> list[int]:
        cached = self._key_cache.get(spec)
        if cached is None:
            cached = parse_keys(spec)
            self._key_cache[spec] = cached
        return cached

    def validate(self, binding) -> str | None:
        """Return an error message if the binding's action cannot run."""
        if binding.keys:
            try:
                self.codes_for(binding.keys)
            except KeyParseError as exc:
                return str(exc)
        return None

    def run(self, binding) -> tuple[bool, str]:
        """Execute a binding. Returns (ok, detail)."""
        if binding.keys:
            try:
                codes = self.codes_for(binding.keys)
            except KeyParseError as exc:
                return False, str(exc)
            if self.dry_run:
                return True, f"would tap {binding.keys}"
            try:
                self.keyboard.tap(codes)
            except OSError as exc:
                return False, f"uinput write failed: {exc}"
            return True, f"tapped {binding.keys}"

        command = binding.exec
        if self.dry_run:
            return True, f"would run {command}"
        try:
            subprocess.Popen(
                ["/bin/sh", "-c", command],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            return False, f"spawn failed: {exc}"
        return True, f"ran {command}"
