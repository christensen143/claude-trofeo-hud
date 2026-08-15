"""Reusable drawing primitives. All take a Draw + a box, return nothing."""
from __future__ import annotations

from PIL import ImageDraw

from .. import theme

Box = tuple[int, int, int, int]  # x0, y0, x1, y1


def progress_bar(d: ImageDraw.ImageDraw, box: Box, pct: float,
                 color: str, track: str = theme.PANEL) -> None:
    x0, y0, x1, y1 = box
    r = (y1 - y0) // 2
    d.rounded_rectangle(box, radius=r, fill=track, outline=theme.BORDER)
    pct = max(0.0, min(100.0, pct))
    fill_w = int((x1 - x0) * pct / 100)
    if fill_w > 2 * r:
        d.rounded_rectangle((x0, y0, x0 + fill_w, y1), radius=r, fill=color)
    elif fill_w > 0:
        d.ellipse((x0, y0, x0 + max(fill_w, 2 * r), y1), fill=color)


def sparkline(d: ImageDraw.ImageDraw, box: Box, values: list[int],
              color: str = theme.ACCENT, slots: int | None = None) -> None:
    """Bar sparkline; `slots` fixes the x-scale (e.g. 24 for a full day)."""
    x0, y0, x1, y1 = box
    n = slots or max(len(values), 1)
    peak = max(values) if values else 0
    if peak == 0:
        d.line((x0, y1 - 1, x1, y1 - 1), fill=theme.FAINT)
        return
    gap = 2
    bar_w = max(2, ((x1 - x0) - gap * (n - 1)) // n)
    h = y1 - y0
    for i, v in enumerate(values):
        bx = x0 + i * (bar_w + gap)
        bh = max(2, int(h * v / peak))
        d.rectangle((bx, y1 - bh, bx + bar_w, y1),
                    fill=color if v else theme.FAINT)


def status_dot(d: ImageDraw.ImageDraw, cx: int, cy: int, r: int,
               active: bool) -> None:
    color = theme.GOOD if active else theme.FAINT
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)


def fmt_tokens(n: int | float) -> str:
    n = float(n)
    for div, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if n >= div:
            return f"{n / div:.1f}{suffix}"
    return f"{int(n)}"


def fmt_countdown(seconds: float) -> str:
    seconds = max(0, int(seconds))
    d_, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d_:
        return f"{d_}d {h}h"
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m"
