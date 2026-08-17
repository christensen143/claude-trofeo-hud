"""Config: config.toml next to the project (or ~/.config/claude-trofeo-hud/).

Missing file or fields fall back to defaults; a broken file logs and uses
defaults rather than refusing to start (the HUD is an appliance).
"""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, field
from datetime import time as dtime
from pathlib import Path

log = logging.getLogger(__name__)

_CANDIDATES = [
    Path(__file__).resolve().parent.parent / "config.toml",
    Path.home() / ".config" / "claude-trofeo-hud" / "config.toml",
]


@dataclass
class Night:
    """Panel behavior during quiet hours. mode: 'on' (normal), 'dim', 'off'."""

    mode: str = "off"
    start: dtime = dtime(0, 0)
    end: dtime = dtime(7, 0)
    dim_factor: float = 0.3

    def active(self, now: dtime) -> bool:
        if self.mode == "on":
            return False
        if self.start <= self.end:
            # Equal bounds are an empty window: no quiet hours at all.
            return self.start <= now < self.end
        return now >= self.start or now < self.end  # crosses midnight


@dataclass
class Config:
    fps: float = 2.0
    jpeg_quality: int = 90
    night: Night = field(default_factory=Night)
    log_dir: Path = field(
        default_factory=lambda: Path.home() / "Library" / "Logs" / "claude-trofeo-hud"
    )


_MODES = ("on", "dim", "off")
_FPS_RANGE = (0.1, 30.0)
_QUALITY_RANGE = (1, 95)  # Pillow: above ~95 costs bytes for no visible gain

# A malformed field can surface as any of these. ValueError covers bad numbers
# and impossible clock times; TypeError covers TOML's *native* time literal
# (`start = 22:00:00` parses to a datetime.time, which fromisoformat rejects);
# AttributeError covers a scalar where a table was expected.
_BAD_CONFIG = (OSError, tomllib.TOMLDecodeError, ValueError, TypeError, AttributeError)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _as_time(value: object, default: dtime) -> dtime:
    """Accept a string ("22:00") or TOML's native time literal (22:00:00)."""
    if value is None:
        return default
    if isinstance(value, dtime):
        return value
    return dtime.fromisoformat(value)


def _parse(raw: dict, defaults: Config) -> Config:
    night = raw.get("night", {})
    if not isinstance(night, dict):
        raise TypeError(
            f"[night] must be a table, got {type(night).__name__} — did you "
            f'mean "[night]\\nmode = ..."?'
        )

    mode = night.get("mode", defaults.night.mode)
    if mode not in _MODES:
        raise ValueError(f"night.mode must be one of {_MODES}, got {mode!r}")

    return Config(
        fps=_clamp(float(raw.get("fps", defaults.fps)), *_FPS_RANGE),
        jpeg_quality=int(
            _clamp(int(raw.get("jpeg_quality", defaults.jpeg_quality)), *_QUALITY_RANGE)
        ),
        night=Night(
            mode=mode,
            start=_as_time(night.get("start"), defaults.night.start),
            end=_as_time(night.get("end"), defaults.night.end),
            dim_factor=_clamp(
                float(night.get("dim_factor", defaults.night.dim_factor)), 0.0, 1.0
            ),
        ),
        log_dir=defaults.log_dir,
    )


def load(path: Path | None = None) -> Config:
    """Load config, falling back to defaults for anything malformed.

    Never raises. The daemon runs under launchd with KeepAlive and a 10 s
    ThrottleInterval, so an exception here would crash-loop indefinitely rather
    than fail once — a typo in config.toml must not be able to do that.
    """
    defaults = Config()
    for candidate in [path] if path is not None else _CANDIDATES:
        if not candidate.exists():
            continue
        try:
            cfg = _parse(tomllib.loads(candidate.read_text()), defaults)
        except _BAD_CONFIG as e:
            log.warning(
                "ignoring bad config %s (%s: %s) — using defaults",
                candidate,
                type(e).__name__,
                e,
            )
            return defaults
        log.info("config loaded from %s", candidate)
        return cfg
    return defaults
