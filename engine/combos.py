"""The chord recogniser.

Turns a stream of button press/release events into binding activations.

Design notes
------------
* Bindings only ever fire on a *press* or on a timer -- never on a release.
  That alone removes most of the classic "released L+R and it also fired R"
  misfires.
* When the buttons currently held could still grow into a longer binding, the
  decision is deferred by `combo_window_ms`. When no longer binding could
  possibly match, the decision is immediate, so ordinary single-button presses
  have no added latency.
* A binding that has fired is *latched* until one of its own buttons is
  released, so holding a chord does not retrigger it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Activation:
    """One binding firing, with the reason it fired (for logs and the UI)."""

    binding: object
    reason: str  # "press" | "hold" | "repeat"


class ComboEngine:
    def __init__(self, bindings, settings):
        self.set_bindings(bindings, settings)
        self.held: set[str] = set()
        self._pending: tuple[object, float] | None = None
        self._latched: tuple[str, ...] | None = None
        self._hold_deadline: float | None = None
        self._hold_binding: object | None = None
        self._repeat_at: float | None = None
        self._repeat_binding: object | None = None

    # -- configuration ------------------------------------------------------

    def set_bindings(self, bindings, settings) -> None:
        self.bindings = list(bindings)
        self.combo_window = float(settings.get("combo_window_ms", 45)) / 1000.0
        self.hold_time = float(settings.get("hold_ms", 450)) / 1000.0
        self.repeat_delay = float(settings.get("repeat_delay_ms", 400)) / 1000.0
        self.repeat_interval = float(settings.get("repeat_interval_ms", 110)) / 1000.0
        self._combos = [frozenset(b.combo) for b in self.bindings]

    def reset(self) -> None:
        """Forget all state. Used when the pad disconnects."""
        self.held.clear()
        self._pending = None
        self._latched = None
        self._cancel_hold()
        self._cancel_repeat()

    # -- queries ------------------------------------------------------------

    def _candidates(self):
        held = frozenset(self.held)
        return [
            (binding, combo)
            for binding, combo in zip(self.bindings, self._combos)
            if combo <= held
        ]

    def _best_match(self):
        candidates = self._candidates()
        if not candidates:
            return None
        # Longest chord wins; ties fall back to config order.
        return max(candidates, key=lambda item: len(item[1]))[0]

    def _could_grow(self) -> bool:
        """True if pressing more buttons could still complete a longer binding."""
        held = frozenset(self.held)
        return any(held < combo for combo in self._combos)

    def next_deadline(self) -> float | None:
        """Earliest time `tick` needs to be called, or None if idle."""
        deadlines = [
            d
            for d in (
                self._pending[1] if self._pending else None,
                self._hold_deadline,
                self._repeat_at,
            )
            if d is not None
        ]
        return min(deadlines) if deadlines else None

    # -- event input --------------------------------------------------------

    def press(self, button: str, now: float) -> list[Activation]:
        if button in self.held:
            return []
        self.held.add(button)
        return self._resolve(now)

    def release(self, button: str, now: float) -> list[Activation]:
        self.held.discard(button)

        if self._latched is not None and button in self._latched:
            self._latched = None
            self._cancel_repeat()
            self._cancel_hold()

        if self._pending is not None:
            binding, _deadline = self._pending
            if button in binding.combo:
                # The chord came apart before it settled; drop it.
                self._pending = None

        if self._hold_binding is not None and button in self._hold_binding.combo:
            self._cancel_hold()
        if self._repeat_binding is not None and button in self._repeat_binding.combo:
            self._cancel_repeat()

        if not self.held:
            self._pending = None
            self._latched = None
            self._cancel_hold()
            self._cancel_repeat()
        return []

    def tick(self, now: float) -> list[Activation]:
        fired: list[Activation] = []

        if self._pending is not None and now >= self._pending[1]:
            binding, _ = self._pending
            self._pending = None
            fired.extend(self._commit(binding, now))

        if self._hold_deadline is not None and now >= self._hold_deadline:
            binding = self._hold_binding
            self._cancel_hold()
            if binding is not None and frozenset(binding.combo) <= self.held:
                fired.append(Activation(binding, "hold"))

        if self._repeat_at is not None and now >= self._repeat_at:
            binding = self._repeat_binding
            if binding is not None and frozenset(binding.combo) <= self.held:
                fired.append(Activation(binding, "repeat"))
                self._repeat_at = now + self.repeat_interval
            else:
                self._cancel_repeat()

        return fired

    # -- internals ----------------------------------------------------------

    def _resolve(self, now: float) -> list[Activation]:
        best = self._best_match()
        if best is None:
            self._pending = None
            return []
        if self._latched is not None and tuple(best.combo) == self._latched:
            return []
        if self._could_grow():
            # Hold the decision briefly in case the rest of the chord is on
            # its way. Re-arming on every press keeps the window rolling.
            self._pending = (best, now + self.combo_window)
            return []
        self._pending = None
        return self._commit(best, now)

    def _commit(self, binding, now: float) -> list[Activation]:
        self._latched = tuple(binding.combo)
        if binding.hold:
            self._hold_binding = binding
            self._hold_deadline = now + self.hold_time
            return []
        if binding.repeat:
            self._repeat_binding = binding
            self._repeat_at = now + self.repeat_delay
        return [Activation(binding, "press")]

    def _cancel_hold(self) -> None:
        self._hold_binding = None
        self._hold_deadline = None

    def _cancel_repeat(self) -> None:
        self._repeat_binding = None
        self._repeat_at = None
