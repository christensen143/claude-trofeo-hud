"""Usage limits (session / weekly %) via Anthropic's OAuth usage endpoint.

Reads the Claude Code OAuth token fresh from the macOS Keychain each refresh
(Claude Code rotates it; the Keychain always has the current one) and makes a
read-only GET. The token goes nowhere except api.anthropic.com over HTTPS.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import subprocess
import urllib.request
from datetime import datetime

from ..state import LimitGauge, Limits
from .base import Collector

log = logging.getLogger(__name__)

_KEYCHAIN_SERVICE = "Claude Code-credentials"
_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
_BETA_HEADER = "oauth-2025-04-20"
_TIMEOUT_S = 15


def _access_token() -> str:
    out = subprocess.run(
        ["security", "find-generic-password", "-s", _KEYCHAIN_SERVICE, "-w"],
        capture_output=True, text=True, timeout=10, check=True,
    ).stdout
    return json.loads(out)["claudeAiOauth"]["accessToken"]


def _local_naive(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso).astimezone().replace(tzinfo=None)
    except ValueError:
        return None


class LimitsCollector(Collector):
    name_ = "limits"
    # The usage endpoint admits roughly one call every two minutes. At a 60s
    # cadence it refuses every other poll with HTTP 429 — measured over a
    # 5-hour run: 103 of 145 failures were exactly 120s apart, i.e. one
    # success, one refusal, repeating. The 429 carries no rate-limit metadata
    # and `Retry-After: 0`, so there is nothing to pace against; the only fix
    # is to poll slower than the limiter.
    #
    # Nothing on the panel suffers: utilization moves slowly, and the reset
    # countdowns are computed client-side from `resets_at` on every frame.
    cadence_s = 300.0

    def refresh(self) -> None:
        req = urllib.request.Request(_USAGE_URL, headers={
            "Authorization": f"Bearer {_access_token()}",
            "anthropic-beta": _BETA_HEADER,
            "Content-Type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            data = json.loads(resp.read())

        def gauge(section: dict | None, label: str) -> LimitGauge | None:
            if not section:
                return None
            return LimitGauge(
                label=label,
                used_pct=float(section.get("utilization") or 0.0),
                resets_at=_local_naive(section.get("resets_at")),
            )

        limits = Limits(
            session=gauge(data.get("five_hour"), "SESSION"),
            weekly=gauge(data.get("seven_day"), "WEEK"),
        )
        self.shared.update(limits=limits)
        log.debug("limits: session=%s weekly=%s",
                  limits.session and limits.session.used_pct,
                  limits.weekly and limits.weekly.used_pct)

    def mark_stale(self) -> None:
        def apply(state) -> None:
            state.limits = dataclasses.replace(state.limits, stale=True)
        self.shared.mutate(apply)
