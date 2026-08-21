"""Pure summing logic for the tokens collector; no subprocess, no ccusage."""
from datetime import date

from claude_trofeo_hud.collectors.tokens import _stats_from_days


def _day(period: str, total: int = 0, cost: float = 0.0, **extra) -> dict:
    row = {"period": period, "totalTokens": total, "totalCost": cost}
    row.update(extra)
    return row


def test_stats_accumulate_today_week_and_month():
    days = [
        _day("2026-08-01", 100, 1.0),   # month only, before the week
        _day("2026-08-10", 200, 2.0),   # week + month
        _day("2026-08-12", 300, 3.5),   # today + week + month
    ]

    stats = _stats_from_days(days, today=date(2026, 8, 12),
                             week_start=date(2026, 8, 10),
                             month_start=date(2026, 8, 1))

    assert stats.month_cost_usd == 6.5
    assert stats.week_cost_usd == 5.5
    assert stats.week_tokens == 500
    assert stats.today_cost_usd == 3.5
    assert stats.today_tokens == 300


def test_stats_month_boundary_keeps_week_rows_out_of_month():
    days = [
        _day("2026-08-31", 100, 1.0),   # in week, previous month
        _day("2026-09-01", 200, 2.0),   # in week and in month
    ]

    stats = _stats_from_days(days, today=date(2026, 9, 1),
                             week_start=date(2026, 8, 31),
                             month_start=date(2026, 9, 1))

    assert stats.week_cost_usd == 3.0
    assert stats.month_cost_usd == 2.0


def test_stats_today_breakdown_fields():
    days = [_day("2026-08-12", 300, 3.5, inputTokens=10, outputTokens=20,
                 cacheReadTokens=30, cacheCreationTokens=40)]

    stats = _stats_from_days(days, today=date(2026, 8, 12),
                             week_start=date(2026, 8, 10),
                             month_start=date(2026, 8, 1))

    assert stats.input_tokens == 10
    assert stats.output_tokens == 20
    assert stats.cache_tokens == 70
