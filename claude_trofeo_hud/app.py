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
# Declined frames are expected to come in runs; log the first, then sparsely.
_SOFT_FAIL_LOG_EVERY = 30


def run_loop(shared, cfg: Config, stop_after_s: float = 0, panel=None) -> None:
    panel = TrofeoPanel() if panel is None else panel
    deadline = time.time() + stop_after_s if stop_after_s else None
    backoff = 1.0
    declined = 0
    try:
        while deadline is None or time.time() < deadline:
            frame_start = time.time()

            if not panel.connected:
                try:
                    panel.connect()
                    backoff = 1.0
                except Exception as e:
                    log.warning(
                        "panel connect failed (%s) — retry in %.0fs", e, backoff
                    )
                    time.sleep(backoff)
                    backoff = min(backoff * 2, _BACKOFF_MAX_S)
                    continue

            img = _frame(shared, cfg)
            try:
                ok = panel.send(img)
            except Exception as e:
                # A *raise* is a transport failure: a stale handle after
                # sleep/wake, or a genuine unplug. Reconnecting is right here.
                log.warning("panel send raised (%s) — reconnecting", e)
                panel.close()
                declined = 0
                _pace(frame_start, cfg.fps)
                continue

            if ok:
                declined = 0
            else:
                # A *False* return is a soft, protocol-level decline. Our panel
                # carries trcc's `keepalive_stream` quirk, and trcc converts
                # transport errors to False for such firmware precisely because
                # a close→reopen wedges the panel until a physical replug (#228).
                # So: never reconnect here — drop the frame and let the next
                # keepalive tick resend it.
                declined += 1
                if declined == 1 or declined % _SOFT_FAIL_LOG_EVERY == 0:
                    log.warning(
                        "panel declined %d frame(s) in a row — skipping, will "
                        "resend on the next tick",
                        declined,
                    )
            _pace(frame_start, cfg.fps)
    finally:
        panel.close()


def _pace(frame_start: float, fps: float) -> None:
    """Sleep out the remainder of this frame's budget. Every path through the
    loop must call this — an unpaced path spins the CPU."""
    time.sleep(max(0.0, 1.0 / fps - (time.time() - frame_start)))


def _frame(shared, cfg: Config) -> Image.Image:
    night = cfg.night.active(datetime.now().time())
    if night and cfg.night.mode == "off":
        return Image.new("RGB", (1280, 480), "black")
    img = render(shared.snapshot())
    if night and cfg.night.mode == "dim":
        img = ImageEnhance.Brightness(img).enhance(cfg.night.dim_factor)
    return img
