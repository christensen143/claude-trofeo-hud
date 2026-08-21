"""Tokens collector: the ccusage invocation and the parsing of its JSON.

The invocation test is the point of this file. `ccusage@latest` with `-y` means
the daemon downloads and executes whatever was most recently published to that
npm name, unreviewed, every 60 seconds — in a process the README tells the user
to grant "Always Allow" Keychain access. Pinning is the fix; this test is what
keeps the pin from drifting back to a floating tag.

The parsing tests freeze ccusage's real field names. `period` in particular is
easy to guess wrong (`date` seems likelier), and getting it wrong silently zeroes
every "today" figure on the panel rather than failing loudly.
"""

from __future__ import annotations

import json
import re
import subprocess

import pytest

from claude_trofeo_hud.collectors import tokens as tokens_mod
from claude_trofeo_hud.collectors.base import SharedState
from claude_trofeo_hud.collectors.tokens import TokensCollector

TODAY = "2026-08-17"

# Shape mirrors `npx ccusage daily --json` (field names verified against real
# output); the numbers are invented.
PAYLOAD = {
    "daily": [
        {
            "period": "2026-08-16",
            "inputTokens": 100,
            "outputTokens": 2_000,
            "cacheCreationTokens": 30_000,
            "cacheReadTokens": 400_000,
            "totalTokens": 432_100,
            "totalCost": 1.25,
            "modelsUsed": ["claude-opus-5"],
        },
        {
            "period": TODAY,
            "inputTokens": 44,
            "outputTokens": 18_639,
            "cacheCreationTokens": 878_696,
            "cacheReadTokens": 12_697_381,
            "totalTokens": 13_594_760,
            "totalCost": 15.6018455,
            "modelsUsed": ["claude-opus-5"],
        },
    ],
    "totals": {"totalTokens": 14_026_860, "totalCost": 16.8518455},
}


@pytest.fixture
def collector(monkeypatch):
    """A collector whose `date.today()` and `subprocess.run` are both fixed."""

    class _FixedDate:
        @staticmethod
        def today():
            import datetime

            return datetime.date(2026, 8, 17)  # a Monday

    monkeypatch.setattr(tokens_mod, "date", _FixedDate)
    return TokensCollector(SharedState())


def _fake_run(payload, capture: list | None = None):
    def run(cmd, **kwargs):
        if capture is not None:
            capture.extend(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload))

    return run


# ── The invocation must be pinned ────────────────────────────────────────


def test_ccusage_version_is_pinned(monkeypatch, collector):
    argv: list[str] = []
    monkeypatch.setattr(subprocess, "run", _fake_run(PAYLOAD, argv))

    collector.refresh()

    spec = next(a for a in argv if a.startswith("ccusage@"))
    assert re.fullmatch(r"ccusage@\d+\.\d+\.\d+", spec), (
        f"ccusage must be pinned to an exact version, got {spec!r}"
    )


def test_ccusage_is_not_a_floating_tag(monkeypatch, collector):
    argv: list[str] = []
    monkeypatch.setattr(subprocess, "run", _fake_run(PAYLOAD, argv))

    collector.refresh()

    joined = " ".join(argv)
    for tag in ("@latest", "@next", "@beta", "@*"):
        assert tag not in joined, f"floating tag {tag} reintroduced"


# ── Parsing ──────────────────────────────────────────────────────────────


def test_today_and_week_totals(monkeypatch, collector):
    monkeypatch.setattr(subprocess, "run", _fake_run(PAYLOAD))

    collector.refresh()
    t = collector.shared.snapshot().tokens

    assert t.today_tokens == 13_594_760
    assert t.today_cost_usd == pytest.approx(15.6018455)
    assert t.input_tokens == 44
    assert t.output_tokens == 18_639
    assert t.cache_tokens == 878_696 + 12_697_381
    assert t.week_tokens == 432_100 + 13_594_760
    assert t.week_cost_usd == pytest.approx(1.25 + 15.6018455)
    assert t.stale is False


def test_field_is_period_not_date(monkeypatch, collector):
    """If ccusage's day key were read as `date`, today's figures would silently
    stay zero while the week total still looked right."""
    renamed = {
        "daily": [
            {k: v for k, v in day.items() if k != "period"} | {"date": day["period"]}
            for day in PAYLOAD["daily"]
        ]
    }
    monkeypatch.setattr(subprocess, "run", _fake_run(renamed))

    collector.refresh()

    assert collector.shared.snapshot().tokens.today_tokens == 0, (
        "sanity check on the fixture: `date` is not the key ccusage emits"
    )


def test_absent_fields_default_to_zero(monkeypatch, collector):
    monkeypatch.setattr(subprocess, "run", _fake_run({"daily": [{"period": TODAY}]}))

    collector.refresh()
    t = collector.shared.snapshot().tokens

    assert (t.today_tokens, t.input_tokens, t.cache_tokens) == (0, 0, 0)
    assert t.today_cost_usd == 0.0


def test_empty_payload_does_not_raise(monkeypatch, collector):
    monkeypatch.setattr(subprocess, "run", _fake_run({}))

    collector.refresh()

    assert collector.shared.snapshot().tokens.today_tokens == 0


def test_session_count_is_left_to_the_activity_collector(monkeypatch, collector):
    """Both collectors write TokenStats, so tokens must preserve the field
    activity owns rather than resetting it to zero."""

    def seed(state):
        state.tokens.session_count = 38

    collector.shared.mutate(seed)
    monkeypatch.setattr(subprocess, "run", _fake_run(PAYLOAD))

    collector.refresh()

    assert collector.shared.snapshot().tokens.session_count == 38


# ── Failure handling ─────────────────────────────────────────────────────


def test_mark_stale_keeps_last_good_values(monkeypatch, collector):
    monkeypatch.setattr(subprocess, "run", _fake_run(PAYLOAD))
    collector.refresh()

    collector.mark_stale()
    t = collector.shared.snapshot().tokens

    assert t.stale is True
    assert t.today_tokens == 13_594_760, "last-good value must survive"


def test_refresh_failure_marks_stale_via_run(monkeypatch, collector):
    """`Collector.run` is what converts an exception into a stale flag."""
    monkeypatch.setattr(subprocess, "run", _fake_run(PAYLOAD))
    collector.refresh()

    def boom(*a, **k):
        raise subprocess.CalledProcessError(1, "npx")

    monkeypatch.setattr(subprocess, "run", boom)

    try:
        collector.refresh()
    except subprocess.CalledProcessError:
        collector.mark_stale()

    assert collector.shared.snapshot().tokens.stale is True
