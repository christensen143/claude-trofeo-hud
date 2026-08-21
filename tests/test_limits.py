"""Limits collector: token expiry, redirect safety, and honest gauges.

Three things are being pinned here.

**Expiry.** The Keychain token is rotated by Claude Code, not by us. When Claude
Code has not run for a while the token simply expires, and an unattended daemon
then shows two frozen gauges behind a small "(stale)" label indefinitely. The
expiry timestamp sits in the same Keychain blob as the token, so the collector
can say "AUTH EXPIRED" instead of implying the numbers are merely late.

**Redirects.** `urllib`'s redirect handler copies every header except
content-length/content-type onto the new request, with no host comparison — so a
redirect off api.anthropic.com would carry the OAuth bearer token to whatever
host answered.

**Unknown vs zero.** `float(x or 0.0)` turns a null utilization into a confident
"0%". The renderer already has a placeholder for "no data"; use it.
"""

from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timedelta

import pytest

from claude_trofeo_hud.collectors import limits as limits_mod
from claude_trofeo_hud.collectors.base import SharedState
from claude_trofeo_hud.collectors.limits import LimitsCollector

# Trimmed from a real response. `utilization` is 0-100; `resets_at` is
# offset-aware ISO 8601.
RESPONSE = {
    "five_hour": {"utilization": 41.0, "resets_at": "2026-08-17T19:10:00.084456+00:00"},
    "seven_day": {"utilization": 33.0, "resets_at": "2026-08-21T12:00:00.084474+00:00"},
}


def _keychain(expires_at: datetime | None, token: str = "sk-ant-oat01-x"):
    """Fake the `security find-generic-password` call."""
    blob = {"claudeAiOauth": {"accessToken": token}}
    if expires_at is not None:
        blob["claudeAiOauth"]["expiresAt"] = int(
            expires_at.timestamp() * 1000
        )  # the real field is epoch millis

    def run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(blob))

    return run


class _FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeOpener:
    def __init__(self, payload=None, error=None):
        self.payload, self.error = payload, error
        self.calls = 0

    def open(self, req, timeout=None):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return _FakeResponse(self.payload)


@pytest.fixture
def collector():
    return LimitsCollector(SharedState())


def _wire(monkeypatch, expires_at, payload=None, error=None):
    monkeypatch.setattr(subprocess, "run", _keychain(expires_at))
    opener = _FakeOpener(payload, error)
    monkeypatch.setattr(limits_mod, "_OPENER", opener)
    return opener


# ── Happy path ───────────────────────────────────────────────────────────


def test_populates_both_gauges(monkeypatch, collector):
    _wire(monkeypatch, datetime.now() + timedelta(hours=1), RESPONSE)

    collector.refresh()
    lim = collector.shared.snapshot().limits

    assert lim.session.used_pct == 41.0
    assert lim.weekly.used_pct == 33.0
    assert lim.session.label == "SESSION"
    assert lim.stale is False
    assert lim.auth_expired is False


def test_resets_at_is_converted_from_utc(monkeypatch, collector):
    """The endpoint sends an offset; the HUD renders naive local time."""
    _wire(monkeypatch, datetime.now() + timedelta(hours=1), RESPONSE)

    collector.refresh()
    resets = collector.shared.snapshot().limits.session.resets_at

    expected = (
        datetime.fromisoformat(RESPONSE["five_hour"]["resets_at"])
        .astimezone()
        .replace(tzinfo=None)
    )
    assert resets == expected
    assert resets.tzinfo is None


def test_absent_section_leaves_gauge_none(monkeypatch, collector):
    _wire(
        monkeypatch,
        datetime.now() + timedelta(hours=1),
        {"five_hour": RESPONSE["five_hour"]},
    )

    collector.refresh()

    assert collector.shared.snapshot().limits.weekly is None


# ── Expiry is detected locally, before any request ───────────────────────


def test_expired_token_does_not_hit_the_network(monkeypatch, collector):
    opener = _wire(monkeypatch, datetime.now() - timedelta(minutes=1), RESPONSE)

    collector.refresh()

    assert opener.calls == 0, "an expired token must not be sent"
    assert collector.shared.snapshot().limits.auth_expired is True


def test_expired_token_keeps_last_good_gauges(monkeypatch, collector):
    _wire(monkeypatch, datetime.now() + timedelta(hours=1), RESPONSE)
    collector.refresh()

    _wire(monkeypatch, datetime.now() - timedelta(minutes=1), RESPONSE)
    collector.refresh()
    lim = collector.shared.snapshot().limits

    assert lim.auth_expired is True
    assert lim.session.used_pct == 41.0, "keep the last-good reading"


def test_recovering_a_fresh_token_clears_the_flag(monkeypatch, collector):
    _wire(monkeypatch, datetime.now() - timedelta(minutes=1), RESPONSE)
    collector.refresh()

    _wire(monkeypatch, datetime.now() + timedelta(hours=1), RESPONSE)
    collector.refresh()

    assert collector.shared.snapshot().limits.auth_expired is False


def test_absent_expiry_field_is_not_treated_as_expired(monkeypatch, collector):
    """Older credential blobs may not carry expiresAt; don't invent a failure."""
    opener = _wire(monkeypatch, None, RESPONSE)

    collector.refresh()

    assert opener.calls == 1
    assert collector.shared.snapshot().limits.auth_expired is False


# ── Unknown utilization must not render as 0% ────────────────────────────


def test_null_utilization_is_unknown_not_zero(monkeypatch, collector):
    _wire(
        monkeypatch,
        datetime.now() + timedelta(hours=1),
        {"five_hour": {"utilization": None, "resets_at": None}},
    )

    collector.refresh()

    assert collector.shared.snapshot().limits.session.used_pct is None


def test_genuine_zero_is_preserved(monkeypatch, collector):
    _wire(
        monkeypatch,
        datetime.now() + timedelta(hours=1),
        {"five_hour": {"utilization": 0.0, "resets_at": None}},
    )

    collector.refresh()

    assert collector.shared.snapshot().limits.session.used_pct == 0.0


# ── Failures keep last-good values ───────────────────────────────────────


def test_http_error_marks_stale_and_keeps_values(monkeypatch, collector):
    _wire(monkeypatch, datetime.now() + timedelta(hours=1), RESPONSE)
    collector.refresh()

    _wire(
        monkeypatch,
        datetime.now() + timedelta(hours=1),
        error=urllib.error.HTTPError("u", 429, "rate limited", {}, None),
    )
    with pytest.raises(urllib.error.HTTPError):
        collector.refresh()
    collector.mark_stale()
    lim = collector.shared.snapshot().limits

    assert lim.stale is True
    assert lim.session.used_pct == 41.0


# ── The redirect handler must not forward the bearer token ───────────────


def test_cross_host_redirect_is_refused():
    handler = limits_mod._NoCrossHostRedirect()
    req = urllib.request.Request(
        "https://api.anthropic.com/api/oauth/usage",
        headers={"Authorization": "Bearer secret"},
    )

    with pytest.raises(urllib.error.HTTPError):
        handler.redirect_request(
            req, None, 302, "Found", {}, "https://evil.example.com/collect"
        )


def test_same_host_redirect_is_allowed():
    handler = limits_mod._NoCrossHostRedirect()
    req = urllib.request.Request(
        "https://api.anthropic.com/api/oauth/usage",
        headers={"Authorization": "Bearer secret"},
    )

    new = handler.redirect_request(
        req, None, 302, "Found", {}, "https://api.anthropic.com/api/oauth/usage2"
    )

    assert new is not None
    assert new.full_url.endswith("usage2")


def test_collector_uses_the_guarded_opener():
    """A bare urlopen() would bypass the redirect guard entirely."""
    import inspect

    src = inspect.getsource(limits_mod)

    assert "_OPENER.open(" in src
    assert "urllib.request.urlopen(" not in src
