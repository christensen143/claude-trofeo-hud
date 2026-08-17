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

# Pinned deliberately. `-y` suppresses npm's install prompt, so a floating tag
# would have the daemon fetch and execute whatever was most recently published
# under this name — unreviewed, every 60 s, in a process that reads the OAuth
# token from a Keychain item the user was told to grant "Always Allow".
# Bumping this version is a reviewed commit; see tests/test_tokens.py.
_CCUSAGE_VERSION = "20.0.20"
_CMD = ["npx", "-y", f"ccusage@{_CCUSAGE_VERSION}", "daily", "--json", "--since"]
# Exceeds cadence_s on purpose: a cold npx run plus a full log parse can be
# slow. Note this makes the 60 s cadence a floor, not a period — `Collector.run`
# only starts waiting once refresh() returns.
_TIMEOUT_S = 120


class TokensCollector(Collector):
    name_ = "tokens"
    cadence_s = 60.0

    def refresh(self) -> None:
        week_start = date.today() - timedelta(days=date.today().weekday())
        cmd = _CMD + [week_start.strftime("%Y%m%d")]
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=_TIMEOUT_S, check=True
        ).stdout
        days = json.loads(out).get("daily", [])

        today_key = date.today().isoformat()
        stats = TokenStats()
        for day in days:
            stats.week_tokens += day.get("totalTokens", 0)
            stats.week_cost_usd += day.get("totalCost", 0.0)
            if day.get("period") == today_key:
                stats.today_tokens = day.get("totalTokens", 0)
                stats.today_cost_usd = day.get("totalCost", 0.0)
                stats.input_tokens = day.get("inputTokens", 0)
                stats.output_tokens = day.get("outputTokens", 0)
                stats.cache_tokens = day.get("cacheReadTokens", 0) + day.get(
                    "cacheCreationTokens", 0
                )

        def apply(state) -> None:
            stats.session_count = state.tokens.session_count  # activity owns it
            state.tokens = stats

        self.shared.mutate(apply)
        log.debug("tokens: today=%s week=%s", stats.today_tokens, stats.week_tokens)

    def mark_stale(self) -> None:
        def apply(state) -> None:
            state.tokens = dataclasses.replace(state.tokens, stale=True)

        self.shared.mutate(apply)
