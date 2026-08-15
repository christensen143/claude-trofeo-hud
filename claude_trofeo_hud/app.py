"""The HUD main loop: collectors → render → panel, with reconnect resilience.

The panel firmware blanks when idle, so we stream continuously. USB unplug,
Mac sleep/wake, or a hub hiccup surface as connect/send errors; we close the
device and retry with capped exponential backoff. Collectors keep running
throughout, so the first frame after reconnect is current.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime

from PIL import Image, ImageEnhance

from .config import Config
from .display.panel import TrofeoPanel
from .render.layout import render

log = logging.getLogger(__name__)

_BACKOFF_MAX_S = 60.0


def run_loop(shared, cfg: Config, stop_after_s: float = 0) -> None:
    panel = TrofeoPanel()
    deadline = time.time() + stop_after_s if stop_after_s else None
    backoff = 1.0
    try:
        while deadline is None or time.time() < deadline:
            if not panel.connected:
                try:
                    panel.connect()
                    backoff = 1.0
                except Exception as e:
                    log.warning("panel connect failed (%s) — retry in %.0fs",
                                e, backoff)
                    time.sleep(backoff)
                    backoff = min(backoff * 2, _BACKOFF_MAX_S)
                    continue

            frame_start = time.time()
            img = _frame(shared, cfg)
            try:
                ok = panel.send(img)
            except Exception as e:
                log.warning("panel send failed (%s) — reconnecting", e)
                panel.close()
                continue
            if not ok:
                log.warning("panel send returned False — reconnecting")
                panel.close()
                continue
            time.sleep(max(0.0, 1.0 / cfg.fps - (time.time() - frame_start)))
    finally:
        panel.close()


def _frame(shared, cfg: Config) -> Image.Image:
    night = cfg.night.active(datetime.now().time())
    if night and cfg.night.mode == "off":
        return Image.new("RGB", (1280, 480), "black")
    img = render(shared.snapshot())
    if night and cfg.night.mode == "dim":
        img = ImageEnhance.Brightness(img).enhance(cfg.night.dim_factor)
    return img
