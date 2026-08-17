"""Shared test doubles.

The HUD's main loop is a `while` over real wall-clock time talking to real
hardware. Both are replaced here: `FakeClock` makes pacing and backoff
deterministic (time advances only when the code sleeps), and `FakePanel`
scripts the panel's responses so every failure path is reachable without a
Trofeo plugged in.
"""

from __future__ import annotations

import dataclasses

import pytest

from claude_trofeo_hud.state import HudState


class FakeClock:
    """Stands in for the `time` module inside a module under test.

    Time advances *only* through `sleep`, so a loop's iteration count is a
    function of what it sleeps rather than of how fast the test machine is.
    """

    # A loop that never sleeps never advances this clock, so a deadline-driven
    # `while` would hang the suite instead of failing it. Cap the queries: a
    # spinning loop trips this in well under a second, while the loops these
    # tests exercise legitimately need only a few dozen.
    MAX_QUERIES = 600

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start
        self.sleeps: list[float] = []
        self._queries = 0

    def time(self) -> float:
        self._queries += 1
        if self._queries > self.MAX_QUERIES:
            raise AssertionError(
                f"clock queried {self._queries} times having slept only "
                f"{len(self.sleeps)} time(s) — the loop under test is spinning "
                f"on a path that does not sleep",
            )
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        # The epsilon guarantees forward progress even for sleep(0), so a
        # misbehaving loop terminates the test instead of hanging it.
        self.now += max(seconds, 0.0) + 1e-6


@dataclasses.dataclass
class FakePanel:
    """A `TrofeoPanel` stand-in that records calls and scripts outcomes.

    `send_results` is consumed one entry per send: `True`/`False` are returned,
    an exception instance is raised. The list's last entry repeats once
    exhausted, so a test can describe a permanent failure with one element.
    """

    send_results: list = dataclasses.field(default_factory=lambda: [True])
    connect_results: list = dataclasses.field(default_factory=lambda: [None])
    calls: list[str] = dataclasses.field(default_factory=list)
    sent: int = 0
    _dev: bool = False

    @property
    def connected(self) -> bool:
        return self._dev

    def _next(self, results: list):
        return results[0] if len(results) == 1 else results.pop(0)

    def connect(self):
        self.calls.append("connect")
        outcome = self._next(self.connect_results)
        if isinstance(outcome, BaseException):
            raise outcome
        self._dev = True
        return (1280, 480)

    def send(self, img) -> bool:
        self.calls.append("send")
        self.sent += 1
        outcome = self._next(self.send_results)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def close(self) -> None:
        self.calls.append("close")
        self._dev = False

    @property
    def closes(self) -> int:
        return self.calls.count("close")

    @property
    def connects(self) -> int:
        return self.calls.count("connect")


class StubShared:
    """Minimal `SharedState`: enough for `_frame` to render something."""

    def __init__(self, state: HudState | None = None) -> None:
        self._state = state or HudState()

    def snapshot(self) -> HudState:
        return self._state


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def panel() -> FakePanel:
    return FakePanel()


@pytest.fixture
def shared() -> StubShared:
    return StubShared()
