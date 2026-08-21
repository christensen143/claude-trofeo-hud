"""HudState — everything the renderer needs, with no knowledge of sources.

Every section is optional: a collector that hasn't produced data yet (or has
gone stale) leaves its section None / stale=True and the renderer degrades
gracefully instead of crashing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class LimitGauge:
    """One rate-limit window (session or weekly)."""
    label: str
    used_pct: float                 # 0..100
    resets_at: datetime | None = None


@dataclass
class Limits:
    session: LimitGauge | None = None
    weekly: LimitGauge | None = None
    stale: bool = False


@dataclass
class TokenStats:
    today_cost_usd: float = 0.0     # hypothetical API cost
    today_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_tokens: int = 0
    session_count: int = 0
    week_tokens: int = 0
    week_cost_usd: float = 0.0
    month_cost_usd: float = 0.0
    stale: bool = False


@dataclass
class Activity:
    project: str | None = None
    model: str | None = None
    active: bool = False
    last_event: datetime | None = None
    burn_rate_tpm: float = 0.0      # tokens per minute, trailing window
    stale: bool = False


@dataclass
class HudState:
    now: datetime = field(default_factory=datetime.now)
    limits: Limits = field(default_factory=Limits)
    tokens: TokenStats = field(default_factory=TokenStats)
    activity: Activity = field(default_factory=Activity)
    # Hourly token buckets since midnight, for the sparkline (24 slots).
    hourly_tokens: list[int] = field(default_factory=list)


def mock_state(now: datetime | None = None) -> HudState:
    """A believable state for previews and layout tests."""
    now = now or datetime.now()
    return HudState(
        now=now,
        limits=Limits(
            session=LimitGauge("SESSION", 6.0, now + timedelta(hours=4, minutes=45)),
            weekly=LimitGauge("WEEK", 38.0, now + timedelta(days=2, hours=9)),
        ),
        tokens=TokenStats(
            today_cost_usd=215.75,
            today_tokens=229_200_000,
            input_tokens=50_000,
            output_tokens=404_000,
            cache_tokens=228_700_000,
            session_count=38,
            week_tokens=612_000_000,
            week_cost_usd=581.20,
            month_cost_usd=1_842.00,
        ),
        activity=Activity(
            project="claude-trofeo-hud",
            model="Fable 5",
            active=True,
            last_event=now - timedelta(seconds=8),
            burn_rate_tpm=1_240_000,
        ),
        hourly_tokens=[0, 0, 0, 0, 0, 0, 2, 9, 14, 8, 3, 11, 18, 24, 9, 4,
                       16, 22, 0, 0, 0, 0, 0, 0][: now.hour + 1],
    )
