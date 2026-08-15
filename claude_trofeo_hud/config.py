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
            return self.start <= now < self.end
        return now >= self.start or now < self.end  # crosses midnight


@dataclass
class Config:
    fps: float = 2.0
    jpeg_quality: int = 90
    night: Night = field(default_factory=Night)
    log_dir: Path = field(
        default_factory=lambda: Path.home() / "Library" / "Logs"
        / "claude-trofeo-hud")


def load() -> Config:
    cfg = Config()
    for path in _CANDIDATES:
        if not path.exists():
            continue
        try:
            raw = tomllib.loads(path.read_text())
        except (OSError, tomllib.TOMLDecodeError) as e:
            log.warning("ignoring bad config %s: %s", path, e)
            break
        cfg.fps = float(raw.get("fps", cfg.fps))
        cfg.jpeg_quality = int(raw.get("jpeg_quality", cfg.jpeg_quality))
        n = raw.get("night", {})
        cfg.night = Night(
            mode=n.get("mode", cfg.night.mode),
            start=dtime.fromisoformat(n.get("start", "00:00")),
            end=dtime.fromisoformat(n.get("end", "07:00")),
            dim_factor=float(n.get("dim_factor", cfg.night.dim_factor)),
        )
        log.info("config loaded from %s", path)
        break
    return cfg
