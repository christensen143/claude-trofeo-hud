"""Main-loop behavior: pacing, reconnect policy, and — the point of this file —
what the loop must NOT do when a send is declined.

This panel's firmware carries trcc's `keepalive_stream` quirk, and trcc's send
contract for such devices is explicit (trcc/core/ports.py):

    # Single-session firmware: a close→reopen wedges the panel
    # until a physical replug (#228), so NEVER reconnect — soft-
    # fail and let the next keepalive tick resend the frame.

trcc converts transport errors into `return False` for these devices, so a
declined frame is the *normal* failure signal and must not trigger a teardown.
A raised exception is the genuine-disconnect signal and must.
"""

from __future__ import annotations

from datetime import time as dtime

import pytest

from claude_trofeo_hud import app
from claude_trofeo_hud.config import Config, Night


@pytest.fixture
def cfg() -> Config:
    # mode="on" keeps night dimming out of these assertions.
    return Config(fps=2.0, night=Night(mode="on"))


@pytest.fixture(autouse=True)
def _fake_time(monkeypatch, clock):
    """Replace the `time` module inside app.py wholesale, so the loop's pacing
    and backoff are deterministic rather than wall-clock dependent."""
    monkeypatch.setattr(app, "time", clock)


def _run(shared, cfg, panel, seconds: float) -> None:
    app.run_loop(shared, cfg, stop_after_s=seconds, panel=panel)


# ── A declined frame must not close the device ───────────────────────────


def test_single_declined_frame_does_not_reconnect(shared, cfg, panel):
    panel.send_results = [False, True, True, True]

    _run(shared, cfg, panel, seconds=2.0)

    assert panel.closes == 1, "only the final close() in the finally block"
    assert panel.connects == 1, "a declined frame must not force a re-handshake"
    assert panel.sent > 1, "the loop must keep streaming after a declined frame"


def test_permanently_declined_frames_never_reconnect(shared, cfg, panel):
    panel.send_results = [False]

    _run(shared, cfg, panel, seconds=3.0)

    assert panel.connects == 1
    assert panel.closes == 1
    assert panel.sent >= 4, "must keep resending, not tear down"


def test_declined_frames_still_pace_at_fps(shared, cfg, panel, clock):
    """The soft-failure path must not skip the pacing sleep — the old code
    `continue`d straight past it."""
    panel.send_results = [False]

    _run(shared, cfg, panel, seconds=3.0)

    paced = [s for s in clock.sleeps if s == pytest.approx(0.5)]
    assert len(paced) >= 4, "each declined frame should still cost one 1/fps tick"


def test_repeated_declines_are_not_logged_every_frame(shared, cfg, panel, caplog):
    panel.send_results = [False]

    with caplog.at_level("WARNING", logger=app.log.name):
        _run(shared, cfg, panel, seconds=10.0)

    declined = [r for r in caplog.records if "declined" in r.getMessage()]
    assert declined, "a declined frame must be reported at least once"
    assert len(declined) < panel.sent, "must not log once per frame"


# ── A raised send is a genuine transport failure: reconnect ──────────────


def test_raised_send_reconnects(shared, cfg, panel):
    panel.send_results = [OSError("stale handle after wake"), True, True]

    _run(shared, cfg, panel, seconds=2.0)

    assert panel.closes >= 2, "close() on the raise, plus the finally block"
    assert panel.connects >= 2, "must re-handshake after a transport error"


def test_raised_send_still_paces(shared, cfg, panel, clock):
    """Reconnect-on-raise must not spin: the old code `continue`d with no sleep,
    and connect() resets backoff, so nothing throttled that path."""
    panel.send_results = [OSError("wedged")]

    _run(shared, cfg, panel, seconds=3.0)

    assert clock.sleeps, "the loop must sleep on the raise path"
    assert all(s > 0 for s in clock.sleeps), "no zero-length sleeps"
    assert panel.sent <= 8, "a raising send must not spin the loop"


# ── Connect failures keep their capped exponential backoff ───────────────


def test_connect_failure_backs_off_and_caps(shared, cfg, panel, clock):
    panel.connect_results = [RuntimeError("no device")]

    _run(shared, cfg, panel, seconds=300.0)

    assert clock.sleeps[:4] == [1.0, 2.0, 4.0, 8.0], "capped exponential backoff"
    assert max(clock.sleeps) == app._BACKOFF_MAX_S
    assert panel.sent == 0


def test_connect_recovery_resets_backoff(shared, cfg, panel):
    panel.connect_results = [RuntimeError("hub hiccup"), None]

    _run(shared, cfg, panel, seconds=2.0)

    assert panel.sent >= 1, "must stream once the device comes back"


# ── Night mode ───────────────────────────────────────────────────────────


def test_night_off_sends_black_frame_without_stopping(shared, panel):
    """`off` must keep streaming: the firmware blanks when idle, so a black
    frame is how the HUD goes dark."""
    cfg = Config(fps=2.0, night=Night(mode="off", start=dtime(0, 0), end=dtime(23, 59)))

    _run(shared, cfg, panel, seconds=2.0)

    assert panel.sent >= 1
