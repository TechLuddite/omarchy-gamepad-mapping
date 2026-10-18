"""The long-running listener.

Watches for matching controllers, feeds their events through the chord
recogniser, and runs the bound actions. Emits one JSON object per line on
stdout so the Omarchy shell plugin can show live state.
"""

from __future__ import annotations

import json
import os
import select
import signal
import sys
import time

from .actions import ActionRunner
from .buttons import STICK_AXES, format_combo, label_overrides
from .combos import ComboEngine
from .config import PID_PATH, Config, ConfigError, load, stamp
from .devices import DeviceGone, DeviceScanner, Gamepad
from .pointer import NullPointer, PointerController, validate_pointer


class Daemon:
    def __init__(
        self,
        config: Config,
        *,
        dry_run: bool = False,
        emit_buttons: bool = True,
        exit_with_stdin: bool = False,
        stream=None,
    ):
        self.config = config
        self.dry_run = dry_run
        self.emit_buttons = emit_buttons
        # The shell plugin holds our stdin open. If the shell dies without
        # stopping us, the pipe closes and we leave too, instead of living on
        # beside the daemon the next shell starts and firing every press twice.
        self.exit_with_stdin = exit_with_stdin
        self.stream = stream or sys.stdout
        self.pads: dict[str, Gamepad] = {}
        # Pads holding each button. Two pads can hold the same one, and it
        # stays down until the last of them lets go.
        self._held_by: dict[str, set[str]] = {}
        self.scanner = DeviceScanner()
        self.engine = ComboEngine(config.active_bindings(), config.settings)
        self.runner = ActionRunner(dry_run=dry_run)
        self.running = False
        # Transient, signal-driven mute. Distinct from config.enabled: the
        # panel pauses firing while it records a combo, so pressing the very
        # buttons you are trying to bind cannot trigger what they are already
        # bound to. It is never persisted.
        self.paused = False
        # Signal handlers must not write to stdout, so a pause change is
        # flagged here and announced from the main loop instead. Without this
        # the UI silently disagrees with the daemon about whether it is muted.
        self._pause_announced = False
        # Self-pipe, so a signal interrupts select() instead of waiting out
        # the rescan interval. Without it a toggle can take a couple of
        # seconds to visibly take effect, which reads as a broken switch.
        self._wake_r = -1
        self._wake_w = -1
        self._reload_requested = False
        self._last_scan = 0.0
        # Hand edits to the file are picked up without needing a SIGHUP.
        self._config_stamp = stamp(config.path)
        self._neutral_required = config.modes_enabled
        self._safety_reset_requested = False
        self._last_config_check = time.monotonic()
        self.pointer = PointerController(config.pointer, output=NullPointer() if dry_run else None)
        self._pointer_error = ""
        self._last_pointer_status = None

    @property
    def firing(self) -> bool:
        if not self.config.modes_enabled:
            return self.config.enabled and not self.paused
        return self.config.input_mode == "os" and self.safe_ready

    @property
    def safe_ready(self) -> bool:
        return (self.config.input_mode == "os" and self.config.enabled and not self.paused and bool(self.pads)
                and not self._reload_requested and not self._safety_reset_requested
                and not self._neutral_required
                and all(pad.ready and pad.grabbed for pad in self.pads.values()))

    @property
    def input_status(self) -> str:
        if not self.config.modes_enabled:
            return "legacy"
        if self.config.input_mode == "game":
            return "passthrough" if self.pads else "disconnected"
        if not self.config.enabled:
            return "disabled"
        if self.paused:
            return "paused"
        if not self.pads:
            return "disconnected"
        if any(not pad.ready or (not pad.grabbed and not pad.acquisition_neutral) for pad in self.pads.values()):
            return "waiting_neutral"
        if not all(pad.grabbed for pad in self.pads.values()):
            return "waiting_grab"
        return "ready" if self.safe_ready else "waiting_neutral"

    def _mode_state(self) -> dict:
        return {"modes_enabled": self.config.modes_enabled,
                "input_mode": self.config.input_mode,
                "input_ready": self.safe_ready if self.config.modes_enabled else bool(self.pads),
                "input_status": self.input_status,
                "input_blocker": "; ".join(filter(None, (p.safety_error or (p.acquisition_blocker if not p.grabbed else "") for p in self.pads.values()))),
                "requested_exclusive": self.config.effective_exclusive,
                "effective_exclusive": bool(self.pads) and all(p.grabbed for p in self.pads.values()),
                "pointer_enabled": self.pointer.settings.enabled,
                "pointer_status": self.pointer_status,
                "active_profile": self.config.active_profile}

    @property
    def pointer_status(self) -> str:
        if not self.pointer.settings.enabled:
            return "disabled"
        if self.config.input_mode != "os":
            return "requires_os"
        if self._pointer_error:
            return "error"
        if len(self.pads) > 1:
            return "select_one_controller"
        return "ready" if self.firing else self.input_status

    def _pointer_claims(self) -> set[str]:
        claimed = {token for binding in self.config.active_bindings() for token in binding.combo}
        raw = set()
        for directions in STICK_AXES.values():
            raw.update(directions)
        return claimed | {token for token in raw if self.config.aliases.get(token, token) in claimed}

    def _tick_pointer(self, now: float, held_override=None) -> None:
        allowed = (self.config.modes_enabled and self.config.input_mode == "os"
                   and self.firing and len(self.pads) == 1 and not self._pointer_error)
        pad = next(iter(self.pads.values())) if allowed else None
        try:
            held = ({pad.aliases.get(token, token) for token in pad.held} if pad else set())
            if pad is not None and held_override is not None:
                held = held_override
            self.pointer.tick(now, pad.axes if pad else {}, held,
                              self._pointer_claims(), allowed=allowed)
        except (OSError, ValueError) as exc:
            self._pointer_error = str(exc)
            self.emit("error", message=f"pointer output unavailable: {exc}; reload settings to retry")
        status = self.pointer_status
        if status != self._last_pointer_status:
            self._last_pointer_status = status
            self.emit_state()

    def _reset_outputs(self) -> None:
        """Transition hook: forget chords; key taps already release their output."""
        self.engine.reset()
        self._held_by.clear()
        self._reset_pointer()

    def _reset_pointer(self, *, close=False):
        try:
            self.pointer.close() if close else self.pointer.reset()
        except (OSError, ValueError) as exc:
            self._pointer_error = str(exc)
            self.emit("error", message=f"pointer release failed: {exc}")

    def _arm_neutral(self, *, resnapshot: bool = True) -> None:
        self._reset_outputs()
        self._neutral_required = True
        for path, pad in self.pads.items():
            if resnapshot:
                pad.resync()
            for token in pad.held:
                self._held_by.setdefault(pad.aliases.get(token, token), set()).add(path)

    def _advance_neutral(self) -> None:
        if self._neutral_required and self.pads and all(p.ready and p.neutral for p in self.pads.values()):
            # Another pad may have queued a press while the first released.
            # Drain and snapshot every participant before lifting the barrier.
            for pad in self.pads.values():
                pad.resync()
            if all(p.ready and p.neutral for p in self.pads.values()):
                self._neutral_required = False
                self.engine.reset()
                self._held_by.clear()

    def _process_safety_changes(self) -> None:
        if self.config.modes_enabled and (self._safety_reset_requested or self.paused != self._pause_announced):
            self._safety_reset_requested = False
            self._arm_neutral()
            self._advance_neutral()
        if self.paused != self._pause_announced:
            self._pause_announced = self.paused
            self.emit_state()

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
                {"path": pad.path, "name": pad.name, "grabbed": pad.grabbed,
                 **({"ready": pad.ready, "safety_error": pad.safety_error} if self.config.modes_enabled else {})}
                for pad in self.pads.values()
            ],
            bindings=len(self.config.active_bindings()),
            exclusive=self.config.effective_exclusive,
            enabled=self.config.enabled,
            paused=self.paused,
            **self._mode_state(),
        )

    def emit_bindings(self) -> None:
        """The whole binding list, so the panel never has to read the file."""
        layout = self.config.layout
        self.emit(
            "bindings",
            layout=layout,
            labels=label_overrides(layout),
            aliases=self.config.aliases,
            modes=self.config.modes or {"enabled": False, "active": "game"},
            pointer=self.config.pointer,
            profiles={"active": self.config.active_profile, "names": self.config.profile_names()},
            bindings=[
                {**b.to_dict(), "label": b.label(layout)} for b in self.config.bindings
            ],
        )

    # -- device management --------------------------------------------------

    def rescan(self) -> None:
        previous_status = self.input_status
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
                if self.config.modes_enabled:
                    pad = self.pads[path]
                    before = pad.grabbed
                    pad.retry_grab(self.config.effective_exclusive)
                    if not pad.ready:
                        pad.resync()
                    if before != pad.grabbed:
                        self._arm_neutral()
                        changed = True
                continue
            try:
                pad = Gamepad(
                    info,
                    self.config.settings,
                    self.config.effective_exclusive,
                    self.config.aliases,
                    **({"guarded": True} if self.config.modes_enabled else {}),
                )
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
            if self.config.effective_exclusive and not pad.grabbed:
                self.emit(
                    "error",
                    message=(f"exclusive grab refused for {pad.name}; waiting without desktop output"
                             if self.config.modes_enabled else
                             f"exclusive grab refused for {pad.name}; sharing instead"),
                )

        if changed:
            if self.config.modes_enabled:
                self._arm_neutral()
                self._advance_neutral()
            self.emit_state()
        elif self.config.modes_enabled:
            self._advance_neutral()
            if previous_status != self.input_status:
                self.emit_state()

    def _drop_pad(self, path: str, reason: str) -> None:
        pad = self.pads.pop(path, None)
        if pad is None:
            return
        name = pad.name
        pad.close()
        if self.config.modes_enabled:
            self._arm_neutral()
        # Let go of whatever only this pad was holding; another pad's buttons
        # and any chord in progress on them carry on.
        for token in [t for t, pads in self._held_by.items() if path in pads]:
            pads = self._held_by[token]
            pads.discard(path)
            if not pads:
                del self._held_by[token]
                self.engine.drop(token)
        self.emit(
            "disconnected",
            path=path,
            name=name,
            reason=reason,
            held=sorted(self.engine.held),
        )

    def _feed(self, path: str, token: str, pressed: bool, now: float, *, activate: bool = True):
        """One pad's button change. None when no button changed overall."""
        pads = self._held_by.get(token)
        if pressed:
            if pads:
                pads.add(path)
                return None
            self._held_by[token] = {path}
            return self.engine.press(token, now) if activate else []
        if not pads or path not in pads:
            return None
        pads.discard(path)
        if pads:
            return None
        del self._held_by[token]
        return self.engine.release(token, now) if activate else []

    # -- config -------------------------------------------------------------

    def request_reload(self) -> None:
        self._reload_requested = True

    def _apply_reload(self) -> None:
        self._reload_requested = False
        # Taken first, so an edit landing mid-load is noticed next time round.
        self._config_stamp = stamp(self.config.path)
        try:
            new_config = load(self.config.path)
        except ConfigError as exc:
            self.emit("error", message=f"reload failed: {exc}")
            return
        was_exclusive = self.config.effective_exclusive
        was_modes = self.config.modes_enabled
        was_match = self.config.device["match"]
        self.config = new_config
        self._reset_pointer()
        self.pointer.settings = validate_pointer(new_config.pointer)
        self._pointer_error = ""
        if was_modes or new_config.modes_enabled:
            self._reset_outputs()
            self._neutral_required = new_config.modes_enabled
        self.engine.set_bindings(new_config.active_bindings(), new_config.settings)
        self.engine.reset()
        self._held_by.clear()
        # Re-open pads when the matching rules or grab mode changed.
        if (was_modes != new_config.modes_enabled or
                new_config.effective_exclusive != was_exclusive or new_config.device["match"] != was_match):
            for path in list(self.pads):
                self._drop_pad(path, "reconfigured")
        for pad in self.pads.values():
            pad.apply(new_config.settings, new_config.aliases)
        if new_config.modes_enabled:
            self._arm_neutral()
            self._advance_neutral()
        # Announced before the warnings below: a client clears old errors on
        # "reloaded", and these belong to the config just loaded.
        self.emit(
            "reloaded",
            bindings=len(new_config.active_bindings()),
            enabled=new_config.enabled,
            **self._mode_state(),
        )
        self.emit_bindings()
        self._warn_about_bad_actions()
        self._prepare_keyboard()
        self.rescan()
        self.emit_state()

    def _prepare_keyboard(self) -> None:
        if not any(b.keys for b in self.config.active_bindings()):
            return
        try:
            self.runner.prepare()
        except OSError as exc:
            self.emit(
                "error",
                message=f"cannot create the virtual keyboard: {exc}; keys bindings will fail",
            )

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
        if not self.firing:
            # Still reported, so the UI can show the combo was recognised.
            self.emit(
                "suppressed",
                combo=list(binding.combo),
                label=format_combo(binding.combo, self.config.layout),
                description=binding.description,
                reason=self.input_status if self.config.modes_enabled else ("paused" if self.paused else "disabled"),
            )
            return
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
        old_generation = getattr(pad, "resync_generation", 0)
        events = self._read_pad(pad)
        if events is None:
            return
        if self.config.modes_enabled:
            self._pump_native(pad, events, now, old_generation)
            return

        for token, pressed in events:
            activations = self._feed(pad.path, token, pressed, now)
            if activations is None:
                continue
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

    def _read_pad(self, pad: Gamepad):
        try:
            return pad.read()
        except DeviceGone:
            self._drop_pad(pad.path, "vanished")
            self.emit_state()
            return
        except OSError as exc:
            self.emit("error", message=f"read error on {pad.path}: {exc}")
            self._drop_pad(pad.path, "read-error")
            self.emit_state()
            return

    def _pump_batch(self, pads, now: float) -> None:
        """Read every ready pad before deciding whether any output is safe."""
        batches = []
        for pad in pads:
            generation = pad.resync_generation
            events = self._read_pad(pad)
            if events is not None:
                batches.append((pad, events, generation))
        if any(not p.ready or p.resync_generation != generation for p, _events, generation in batches):
            self._arm_neutral(resnapshot=False)
        blocked = not self.firing
        for pad, events, generation in batches:
            if pad.path in self.pads:
                self._pump_native(pad, events, now, generation, force_blocked=blocked)

    def _pump_native(self, pad: Gamepad, events, now: float, old_generation: int, *, force_blocked=False) -> None:
        previous_status = self.input_status
        if pad.resync_generation != old_generation or not pad.ready:
            self._arm_neutral(resnapshot=False)
        blocked = force_blocked or not self.firing
        for token, pressed in events:
            activations = self._feed(pad.path, token, pressed, now, activate=not blocked) or []
            held = set(self._held_by)
            if self.emit_buttons:
                self.emit("button", button=token, label=format_combo([token], self.config.layout),
                          pressed=pressed, held=sorted(held))
            for activation in activations:
                self._fire(activation)
            # Preserve quick press/release pairs drained in the same batch.
            self._tick_pointer(now, held)
        self._advance_neutral()
        if previous_status != self.input_status:
            self.emit_state()

    def _write_pid_file(self) -> None:
        try:
            PID_PATH.parent.mkdir(parents=True, exist_ok=True)
            PID_PATH.write_text(f"{os.getpid()}\n")
        except OSError as exc:
            self.emit("error", message=f"cannot write {PID_PATH}: {exc}")

    def _remove_pid_file(self) -> None:
        try:
            if PID_PATH.read_text().strip() == str(os.getpid()):
                PID_PATH.unlink()
        except (OSError, ValueError):
            pass

    def run(self) -> int:
        self.running = True
        self._open_wakeup_pipe()
        self._install_signal_handlers()
        self._write_pid_file()
        try:
            self._loop()
        finally:
            # Also on a crash, so the pad is never left grabbed and the
            # virtual keyboard and pid file do not outlive us.
            self.shutdown()
        return 0

    def _loop(self) -> None:
        self.emit(
            "started",
            pid=os.getpid(),
            config=str(self.config.path),
            dry_run=self.dry_run,
            enabled=self.config.enabled,
            **self._mode_state(),
        )
        self.emit_bindings()
        self._warn_about_bad_actions()
        self.rescan()
        # Always publish an opening snapshot. rescan() only reports when
        # something changed, so a daemon that starts with no pad attached
        # would otherwise leave a client with nothing to render.
        self.emit_state()
        self._prepare_keyboard()

        rescan_interval = self.config.setting("rescan_interval_s")

        self._pause_announced = self.paused

        while self.running:
            if self._reload_requested:
                self._apply_reload()
                rescan_interval = self.config.setting("rescan_interval_s")

            self._process_safety_changes()

            # Seed pointer quarantine while inputs are neutral before waiting
            # for the next event, rather than quarantining the first real click.
            self._tick_pointer(time.monotonic())

            now = time.monotonic()
            deadline = self.engine.next_deadline()
            timeout = rescan_interval - (now - self._last_scan)
            if deadline is not None:
                timeout = min(timeout, max(0.0, deadline - now))
            timeout = max(0.0, min(timeout, rescan_interval))
            if self.pointer.needs_tick and self.firing:
                timeout = min(timeout, 1 / 60)
            if self._waiting_for_grab():
                timeout = min(timeout, 0.05)

            fds = [pad.fileno() for pad in self.pads.values()]
            if self._wake_r >= 0:
                fds.append(self._wake_r)
            if self.exit_with_stdin:
                fds.append(sys.stdin.fileno())
            try:
                ready, _, _ = select.select(fds, [], [], timeout)
            except InterruptedError:
                continue
            except OSError:
                ready = []

            now = time.monotonic()
            if self._reload_requested:
                self._apply_reload()
                rescan_interval = self.config.setting("rescan_interval_s")
            self._process_safety_changes()
            by_fd = {pad.fileno(): pad for pad in self.pads.values()}
            native_ready = []
            for fd in ready:
                if fd == self._wake_r:
                    self._drain_wakeup()
                    continue
                if self.exit_with_stdin and fd == sys.stdin.fileno():
                    self._check_stdin()
                    continue
                pad = by_fd.get(fd)
                if pad is not None:
                    if self.config.modes_enabled:
                        native_ready.append(pad)
                    else:
                        self._pump(pad, now)
            if native_ready:
                self._pump_batch(native_ready, now)

            for activation in self.engine.tick(time.monotonic()):
                self._fire(activation)
            self._tick_pointer(time.monotonic())

            self.runner.reap()
            now = time.monotonic()
            if now - self._last_config_check >= rescan_interval:
                self._last_config_check = now
                if stamp(self.config.path) != self._config_stamp:
                    self._reload_requested = True
            if now - self._last_scan >= (min(rescan_interval, 0.05) if self._waiting_for_grab() else rescan_interval):
                self.rescan()

    def _waiting_for_grab(self) -> bool:
        return (self.config.modes_enabled and self.config.input_mode == "os"
                and self.config.enabled and not self.paused and bool(self.pads)
                and any(not pad.grabbed for pad in self.pads.values()))

    def _check_stdin(self) -> None:
        try:
            data = os.read(sys.stdin.fileno(), 4096)
        except OSError:
            data = b""
        if not data:
            self.running = False

    def _open_wakeup_pipe(self) -> None:
        try:
            self._wake_r, self._wake_w = os.pipe()
            os.set_blocking(self._wake_r, False)
            os.set_blocking(self._wake_w, False)
            signal.set_wakeup_fd(self._wake_w)
        except (OSError, ValueError):
            self._wake_r = self._wake_w = -1

    def _close_wakeup_pipe(self) -> None:
        try:
            signal.set_wakeup_fd(-1)
        except (OSError, ValueError):
            pass
        for fd in (self._wake_r, self._wake_w):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        self._wake_r = self._wake_w = -1

    def _drain_wakeup(self) -> None:
        if self._wake_r < 0:
            return
        try:
            while os.read(self._wake_r, 4096):
                pass
        except (BlockingIOError, OSError):
            pass

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
        def pause(_signum, _frame):
            self.paused = True
            self._safety_reset_requested = True

        def resume(_signum, _frame):
            self.paused = False
            self._safety_reset_requested = True

        for sig, handler in (
            (signal.SIGHUP, reload_config),
            (signal.SIGUSR1, pause),
            (signal.SIGUSR2, resume),
        ):
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass

    def shutdown(self) -> None:
        self._close_wakeup_pipe()
        self._remove_pid_file()
        for path in list(self.pads):
            pad = self.pads.pop(path)
            pad.close()
        self.runner.close()
        self._reset_pointer(close=True)
        self.emit("stopped")
