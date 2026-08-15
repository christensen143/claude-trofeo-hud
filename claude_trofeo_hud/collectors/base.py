"""Collector scaffolding: each collector refreshes on its own thread at its
own cadence and publishes into a shared, locked HudState. A failed refresh
keeps the last-good value and flips the section's stale flag."""
from __future__ import annotations

import logging
import threading

from ..state import HudState

log = logging.getLogger(__name__)


class SharedState:
    def __init__(self) -> None:
        self._state = HudState()
        self._lock = threading.Lock()

    def snapshot(self) -> HudState:
        """A shallow-ish copy safe for rendering (sections are replaced
        wholesale by collectors, never mutated in place)."""
        import copy
        from datetime import datetime
        with self._lock:
            snap = copy.copy(self._state)
        snap.now = datetime.now()
        return snap

    def update(self, **sections) -> None:
        with self._lock:
            for name, value in sections.items():
                setattr(self._state, name, value)

    def mutate(self, fn) -> None:
        """Run `fn(state)` under the lock — for read-modify-write updates
        that span sections (plain `update` would race between collectors)."""
        with self._lock:
            fn(self._state)


class Collector(threading.Thread):
    """Runs `refresh()` every `cadence_s`, marks its section stale on error."""

    name_: str = "collector"
    cadence_s: float = 60.0

    def __init__(self, shared: SharedState) -> None:
        super().__init__(daemon=True, name=self.name_)
        self.shared = shared
        self._stop = threading.Event()

    def refresh(self) -> None:  # writes via self.shared.update(...)
        raise NotImplementedError

    def mark_stale(self) -> None:
        """Best-effort: flip this collector's section(s) stale."""

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                self.refresh()
            except Exception:
                log.exception("%s refresh failed", self.name_)
                self.mark_stale()
            self._stop.wait(self.cadence_s)

    def stop(self) -> None:
        self._stop.set()
