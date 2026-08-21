"""Tokens & hypothetical cost via ccusage (npx). 60s cadence.

ccusage parses ~/.claude/projects JSONL with battle-tested dedupe and
LiteLLM pricing; we just read its JSON. A native parser can replace this
later to drop the Node dependency.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import subprocess
from datetime import date, timedelta

from ..state import TokenStats
from .base import Collector

log = logging.getLogger(__name__)

_CMD = ["npx", "-y", "ccusage@latest", "daily", "--json", "--since"]
_TIMEOUT_S = 120


def _stats_from_days(days: list[dict], today: date,
                     week_start: date, month_start: date) -> TokenStats:
    """Fold ccusage daily rows into totals; periods are ISO date strings."""
    week_key = week_start.isoformat()
    month_key = month_start.isoformat()
    today_key = today.isoformat()
    stats = TokenStats()
    for day in days:
        period = day.get("period", "")
        if period >= week_key:
            stats.week_tokens += day.get("totalTokens", 0)
            stats.week_cost_usd += day.get("totalCost", 0.0)
        if period >= month_key:
            stats.month_cost_usd += day.get("totalCost", 0.0)
        if period == today_key:
            stats.today_tokens = day.get("totalTokens", 0)
            stats.today_cost_usd = day.get("totalCost", 0.0)
            stats.input_tokens = day.get("inputTokens", 0)
            stats.output_tokens = day.get("outputTokens", 0)
            stats.cache_tokens = (day.get("cacheReadTokens", 0)
                                  + day.get("cacheCreationTokens", 0))
    return stats


class TokensCollector(Collector):
    name_ = "tokens"
    cadence_s = 60.0

    def refresh(self) -> None:
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)
        cmd = _CMD + [min(week_start, month_start).strftime("%Y%m%d")]
        out = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=_TIMEOUT_S, check=True).stdout
        days = json.loads(out).get("daily", [])

        stats = _stats_from_days(days, today, week_start, month_start)
        def apply(state) -> None:
            stats.session_count = state.tokens.session_count  # activity owns it
            state.tokens = stats
        self.shared.mutate(apply)
        log.debug("tokens: today=%s week=%s", stats.today_tokens,
                  stats.week_tokens)

    def mark_stale(self) -> None:
        def apply(state) -> None:
            state.tokens = dataclasses.replace(state.tokens, stale=True)
        self.shared.mutate(apply)
