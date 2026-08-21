"""Usage limits (session / weekly %) via Anthropic's OAuth usage endpoint.

Reads the Claude Code OAuth credentials fresh from the macOS Keychain each
refresh (Claude Code rotates the token; the Keychain always has the current one)
and makes a read-only GET. The token goes nowhere except api.anthropic.com over
HTTPS — see `_NoCrossHostRedirect`, which is what enforces that.

We deliberately do **not** refresh the token ourselves. The Keychain item is
owned by Claude Code, and a second writer would race its rotation. Instead we
read the expiry that ships alongside the token and say so on the panel.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import subprocess
import urllib.error
import urllib.request
from datetime import datetime
from urllib.parse import urlsplit

from ..state import LimitGauge, Limits
from .base import Collector

log = logging.getLogger(__name__)

_KEYCHAIN_SERVICE = "Claude Code-credentials"
_USAGE_HOST = "api.anthropic.com"
_USAGE_URL = f"https://{_USAGE_HOST}/api/oauth/usage"
_BETA_HEADER = "oauth-2025-04-20"
_TIMEOUT_S = 15


class _NoCrossHostRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects that leave the original host.

    `HTTPRedirectHandler.redirect_request` copies every header except
    content-length/content-type onto the redirected request, and compares
    nothing about the target host. Our request carries an `Authorization:
    Bearer` header, so an off-host redirect would hand the OAuth token to
    whoever answered. (`requests` strips auth on cross-host redirect; urllib
    does not.) The endpoint does not redirect today — this keeps it that way.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).netloc.lower() != urlsplit(req.full_url).netloc.lower():
            raise urllib.error.HTTPError(
                req.full_url,
                code,
                f"refusing cross-host redirect to {urlsplit(newurl).netloc} "
                f"— it would forward the OAuth bearer token",
                headers,
                fp,
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_NoCrossHostRedirect)


def _credentials() -> dict:
    out = subprocess.run(
        ["security", "find-generic-password", "-s", _KEYCHAIN_SERVICE, "-w"],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    ).stdout
    return json.loads(out)["claudeAiOauth"]


def _expired(creds: dict) -> bool:
    """True when the access token's own expiry has passed.

    `expiresAt` is epoch milliseconds. Absent on older credential blobs, in
    which case we say nothing and let the request decide — an expired token
    comes back as HTTP 429 `rate_limit_error` rather than 401, so the response
    alone cannot tell us this.
    """
    expires_at = creds.get("expiresAt")
    if not expires_at:
        return False
    return datetime.fromtimestamp(expires_at / 1000) <= datetime.now()


def _local_naive(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso).astimezone().replace(tzinfo=None)
    except ValueError:
        return None


def _utilization(section: dict) -> float | None:
    """0-100, or None when the server reports it as null.

    Coercing null to 0.0 would render a confident "0%" for "unknown", which is
    indistinguishable from genuinely-unused — so keep the distinction and let
    the renderer show its placeholder.
    """
    value = section.get("utilization")
    return None if value is None else float(value)


class LimitsCollector(Collector):
    name_ = "limits"
    cadence_s = 60.0

    def refresh(self) -> None:
        creds = _credentials()
        if _expired(creds):
            log.warning(
                "OAuth token expired — run Claude Code to refresh it "
                "(we must not rotate it ourselves)"
            )
            self._flag(auth_expired=True)
            return

        req = urllib.request.Request(
            _USAGE_URL,
            headers={
                "Authorization": f"Bearer {creds['accessToken']}",
                "anthropic-beta": _BETA_HEADER,
                "Content-Type": "application/json",
            },
        )
        with _OPENER.open(req, timeout=_TIMEOUT_S) as resp:
            data = json.loads(resp.read())

        def gauge(section: dict | None, label: str) -> LimitGauge | None:
            if not section:
                return None
            return LimitGauge(
                label=label,
                used_pct=_utilization(section),
                resets_at=_local_naive(section.get("resets_at")),
            )

        limits = Limits(
            session=gauge(data.get("five_hour"), "SESSION"),
            weekly=gauge(data.get("seven_day"), "WEEK"),
        )
        self.shared.update(limits=limits)
        log.debug(
            "limits: session=%s weekly=%s",
            limits.session and limits.session.used_pct,
            limits.weekly and limits.weekly.used_pct,
        )

    def mark_stale(self) -> None:
        self._flag(stale=True)

    def _flag(self, **fields) -> None:
        """Set flags while keeping the last-good gauges."""

        def apply(state) -> None:
            state.limits = dataclasses.replace(state.limits, **fields)

        self.shared.mutate(apply)
