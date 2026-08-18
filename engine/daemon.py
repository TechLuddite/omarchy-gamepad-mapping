"""The long-running listener.

Watches for matching controllers, feeds their events through the chord
recogniser, and runs the bound actions. Emits one JSON object per line on
stdout so the Omarchy shell plugin can show live state.
"""

from __future__ import annotations

import json
import select
import signal
import sys
import time

from .actions import ActionRunner
from .buttons import format_combo
from .combos import ComboEngine
from .config import Config, ConfigError, load
from .devices import DeviceGone, DeviceScanner, Gamepad


class Daemon:
    def __init__(
        self,
        config: Config,
        *,
        dry_run: bool = False,
        emit_buttons: bool = True,
        stream=None,
    ):
        self.config = config
        self.dry_run = dry_run
        self.emit_buttons = emit_buttons
        self.stream = stream or sys.stdout
        self.pads: dict[str, Gamepad] = {}
        self.scanner = DeviceScanner()
        self.engine = ComboEngine(config.active_bindings(), config.settings)
        self.runner = ActionRunner(dry_run=dry_run)
        self.running = False
        self._reload_requested = False
        self._last_scan = 0.0

    # -- output -------------------------------------------------------------

    def emit(self, event: str, **fields) -> None:
        payload = {"event": event, "t": round(time.time(), 3), **fields}
        try:
            self.stream.write(json.dumps(payload) + "\n")
            self.stream.flush()
        except (BrokenPipeError, ValueError):
            self.running = False

    def emit_state(self) -> None:
        self.emit(
            "state",
            connected=bool(self.pads),
            devices=[
                {"path": pad.path, "name": pad.name, "grabbed": pad.grabbed}
                for pad in self.pads.values()
            ],
            bindings=len(self.config.active_bindings()),
            exclusive=self.config.exclusive,
        )

    # -- device management --------------------------------------------------

    def rescan(self) -> None:
        self._last_scan = time.monotonic()
        patterns = self.config.device["match"]
        wanted = {info.path: info for info in self.scanner.find_pads(patterns)}

        changed = False
        for path in list(self.pads):
            if path not in wanted:
                self._drop_pad(path, "disconnected")
                changed = True

        for path, info in wanted.items():
            if path in self.pads:
                continue
            try:
                pad = Gamepad(info, self.config.settings, self.config.exclusive)
            except OSError as exc:
                self.emit("error", message=f"cannot open {path}: {exc}")
                continue
            self.pads[path] = pad
            changed = True
            self.emit(
                "connected",
                path=path,
                name=pad.name,
                grabbed=pad.grabbed,
                buttons=info.button_tokens,
            )
            if self.config.exclusive and not pad.grabbed:
                self.emit(
                    "error",
                    message=f"exclusive grab refused for {pad.name}; sharing instead",
                )

        if changed:
            self.engine.reset()
            self.emit_state()

    def _drop_pad(self, path: str, reason: str) -> None:
        pad = self.pads.pop(path, None)
        if pad is None:
            return
        name = pad.name
        pad.close()
        self.engine.reset()
        self.emit("disconnected", path=path, name=name, reason=reason)

    # -- config -------------------------------------------------------------

    def request_reload(self) -> None:
        self._reload_requested = True

    def _apply_reload(self) -> None:
        self._reload_requested = False
        try:
            new_config = load(self.config.path)
        except ConfigError as exc:
            self.emit("error", message=f"reload failed: {exc}")
            return
        was_exclusive = self.config.exclusive
        was_match = self.config.device["match"]
        self.config = new_config
        self.engine.set_bindings(new_config.active_bindings(), new_config.settings)
        self.engine.reset()
        self._warn_about_bad_actions()
        # Re-open pads when the matching rules or grab mode changed.
        if new_config.exclusive != was_exclusive or new_config.device["match"] != was_match:
            for path in list(self.pads):
                self._drop_pad(path, "reconfigured")
        self.emit("reloaded", bindings=len(new_config.active_bindings()))
        self.rescan()

    def _warn_about_bad_actions(self) -> None:
        for binding in self.config.active_bindings():
            problem = self.runner.validate(binding)
            if problem:
                self.emit(
                    "error",
                    message=f"binding {binding.label()}: {problem}",
                    combo=list(binding.combo),
                )

    # -- main loop ----------------------------------------------------------

    def _fire(self, activation) -> None:
        binding = activation.binding
        ok, detail = self.runner.run(binding)
        self.emit(
            "fire",
            combo=list(binding.combo),
            label=format_combo(binding.combo, self.config.layout),
            description=binding.description,
            action=binding.action_summary(),
            reason=activation.reason,
            ok=ok,
            detail=detail,
        )

    def _pump(self, pad: Gamepad, now: float) -> None:
        try:
            events = pad.read()
        except DeviceGone:
            self._drop_pad(pad.path, "vanished")
            self.emit_state()
            return
        except OSError as exc:
            self.emit("error", message=f"read error on {pad.path}: {exc}")
            self._drop_pad(pad.path, "read-error")
            self.emit_state()
            return

        for token, pressed in events:
            activations = (
                self.engine.press(token, now)
                if pressed
                else self.engine.release(token, now)
            )
            # Emitted after the state change, so `held` on a release no longer
            # contains the button that was just let go.
            if self.emit_buttons:
                self.emit(
                    "button",
                    button=token,
                    label=format_combo([token], self.config.layout),
                    pressed=pressed,
                    held=sorted(self.engine.held),
                )
            for activation in activations:
                self._fire(activation)

    def run(self) -> int:
        self.running = True
        self._install_signal_handlers()
        self.emit(
            "started",
            pid=__import__("os").getpid(),
            config=str(self.config.path),
            dry_run=self.dry_run,
        )
        self._warn_about_bad_actions()
        self.rescan()

        rescan_interval = self.config.setting("rescan_interval_s")

        while self.running:
            if self._reload_requested:
                self._apply_reload()
                rescan_interval = self.config.setting("rescan_interval_s")

            now = time.monotonic()
            deadline = self.engine.next_deadline()
            timeout = rescan_interval - (now - self._last_scan)
            if deadline is not None:
                timeout = min(timeout, max(0.0, deadline - now))
            timeout = max(0.0, min(timeout, rescan_interval))

            fds = [pad.fileno() for pad in self.pads.values()]
            try:
                ready, _, _ = select.select(fds, [], [], timeout)
            except InterruptedError:
                continue
            except OSError:
                ready = []

            now = time.monotonic()
            by_fd = {pad.fileno(): pad for pad in self.pads.values()}
            for fd in ready:
                pad = by_fd.get(fd)
                if pad is not None:
                    self._pump(pad, now)

            for activation in self.engine.tick(time.monotonic()):
                self._fire(activation)

            if time.monotonic() - self._last_scan >= rescan_interval:
                self.rescan()

        self.shutdown()
        return 0

    def _install_signal_handlers(self) -> None:
        def stop(_signum, _frame):
            self.running = False

        def reload_config(_signum, _frame):
            self._reload_requested = True

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, stop)
            except (ValueError, OSError):
                pass
        try:
            signal.signal(signal.SIGHUP, reload_config)
        except (ValueError, OSError):
            pass

    def shutdown(self) -> None:
        for path in list(self.pads):
            pad = self.pads.pop(path)
            pad.close()
        self.runner.close()
        self.emit("stopped")
