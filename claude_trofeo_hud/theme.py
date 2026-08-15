"""Colors and fonts for the HUD. Dark theme tuned for an IPS panel on a desk."""
from __future__ import annotations

from functools import lru_cache

from PIL import ImageFont

# ── Palette ──────────────────────────────────────────────────────────────
BG = "#0d0d14"
PANEL = "#15151f"          # card background
BORDER = "#26263a"
FG = "#e8e6e3"
MUTED = "#8a8794"
FAINT = "#4a4757"
ACCENT = "#d97757"          # Claude orange
GOOD = "#6bbf8a"
WARN = "#e0b04c"
CRIT = "#e05c5c"
STALE = "#5a5766"


def limit_color(pct: float) -> str:
    if pct >= 95:
        return CRIT
    if pct >= 80:
        return WARN
    return ACCENT


# ── Fonts ────────────────────────────────────────────────────────────────
# macOS system fonts with graceful fallback; bundle TTFs in assets/ later
# if we ever want pixel-identical rendering elsewhere.
_MONO_CANDIDATES = [
    "/System/Library/Fonts/SFNSMono.ttf",
    "/System/Library/Fonts/Menlo.ttc",
]
_SANS_CANDIDATES = [
    "/System/Library/Fonts/SFNSDisplay.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]


@lru_cache(maxsize=64)
def _load(candidates: tuple[str, ...], size: int) -> ImageFont.FreeTypeFont:
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def mono(size: int) -> ImageFont.FreeTypeFont:
    return _load(tuple(_MONO_CANDIDATES), size)


def sans(size: int) -> ImageFont.FreeTypeFont:
    return _load(tuple(_SANS_CANDIDATES), size)
