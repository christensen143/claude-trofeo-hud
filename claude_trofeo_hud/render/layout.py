"""render(state) -> 1280x480 PIL image. Pure function of HudState."""

from __future__ import annotations

from PIL import Image, ImageDraw

from .. import theme
from ..state import HudState, LimitGauge
from . import widgets as w

WIDTH, HEIGHT = 1280, 480

# Zone x-boundaries (three columns + full-width footer strip)
_COL1 = 470  # limits
_COL2 = 900  # tokens / cost
_PAD = 28
_FOOTER_H = 74


def render(state: HudState) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), theme.BG)
    d = ImageDraw.Draw(img)

    _limits_zone(d, state, x0=0, x1=_COL1)
    _tokens_zone(d, state, x0=_COL1, x1=_COL2)
    _activity_zone(d, state, x0=_COL2, x1=WIDTH)
    _footer(d, state)

    # Column separators
    body_y1 = HEIGHT - _FOOTER_H
    for x in (_COL1, _COL2):
        d.line((x, 24, x, body_y1 - 12), fill=theme.BORDER)
    d.line((_PAD, body_y1, WIDTH - _PAD, body_y1), fill=theme.BORDER)
    return img


# ── Zones ────────────────────────────────────────────────────────────────


def _limits_zone(d: ImageDraw.ImageDraw, state: HudState, x0: int, x1: int) -> None:
    x = x0 + _PAD
    d.text((x, 26), "CLAUDE CODE", font=theme.sans(30), fill=theme.ACCENT)
    lim = state.limits

    # Auth expiry outranks staleness: the reading isn't late, it's unobtainable
    # until the user runs Claude Code again. Say so instead of quietly holding a
    # frozen percentage behind a small "(stale)".
    if lim.auth_expired:
        status, color_hdr = "AUTH EXPIRED", theme.CRIT
    elif lim.stale:
        status, color_hdr = "USAGE (stale)", theme.STALE
    else:
        status, color_hdr = "USAGE", theme.MUTED
    d.text((x1 - _PAD, 34), status, font=theme.sans(18), fill=color_hdr, anchor="ra")
    if lim.auth_expired:
        d.text(
            (x1 - _PAD, 56),
            "run Claude Code to refresh",
            font=theme.sans(15),
            fill=theme.FAINT,
            anchor="ra",
        )

    def gauge(g: LimitGauge | None, y: int) -> None:
        if g is None:
            d.text((x, y), "—", font=theme.mono(22), fill=theme.FAINT)
            return
        d.text((x, y), g.label, font=theme.sans(22), fill=theme.MUTED)
        if g.used_pct is None:
            # Server reported null: unknown, which is not the same as 0%.
            d.text(
                (x1 - _PAD, y - 14),
                "—%",
                font=theme.mono(44),
                fill=theme.FAINT,
                anchor="ra",
            )
            w.progress_bar(d, (x, y + 38, x1 - _PAD, y + 60), 0.0, theme.FAINT)
        else:
            color = theme.limit_color(g.used_pct)
            d.text(
                (x1 - _PAD, y - 14),
                f"{g.used_pct:.0f}%",
                font=theme.mono(44),
                fill=color,
                anchor="ra",
            )
            w.progress_bar(d, (x, y + 38, x1 - _PAD, y + 60), g.used_pct, color)
        if g.resets_at:
            secs = (g.resets_at - state.now).total_seconds()
            d.text(
                (x, y + 70),
                f"resets {g.resets_at:%-I:%M %p} · {w.fmt_countdown(secs)}",
                font=theme.mono(19),
                fill=theme.FAINT,
            )

    gauge(lim.session, 108)
    gauge(lim.weekly, 258)


def _tokens_zone(d: ImageDraw.ImageDraw, state: HudState, x0: int, x1: int) -> None:
    x = x0 + _PAD
    t = state.tokens
    d.text(
        (x, 26),
        "TODAY" + (" (stale)" if t.stale else ""),
        font=theme.sans(18),
        fill=theme.STALE if t.stale else theme.MUTED,
    )
    d.text((x, 56), f"${t.today_cost_usd:,.2f}", font=theme.sans(72), fill=theme.FG)
    d.text((x, 148), "hypothetical API cost", font=theme.sans(17), fill=theme.FAINT)

    d.text(
        (x, 196),
        f"{w.fmt_tokens(t.today_tokens)} tokens · {t.session_count} sessions",
        font=theme.mono(21),
        fill=theme.FG,
    )

    y = 248
    for label, val in (
        ("IN", t.input_tokens),
        ("OUT", t.output_tokens),
        ("CACHE", t.cache_tokens),
    ):
        d.text((x, y), label, font=theme.mono(19), fill=theme.MUTED)
        d.text((x + 90, y), w.fmt_tokens(val), font=theme.mono(19), fill=theme.FG)
        y += 30

    d.text(
        (x, y + 12),
        f"week  {w.fmt_tokens(t.week_tokens)} · ${t.week_cost_usd:,.0f}",
        font=theme.mono(19),
        fill=theme.MUTED,
    )


def _activity_zone(d: ImageDraw.ImageDraw, state: HudState, x0: int, x1: int) -> None:
    x = x0 + _PAD
    a = state.activity
    d.text(
        (x1 - _PAD, 26),
        f"{state.now:%-I:%M %p}",
        font=theme.sans(46),
        fill=theme.FG,
        anchor="ra",
    )
    d.text(
        (x1 - _PAD, 86),
        f"{state.now:%a %b %-d}",
        font=theme.sans(20),
        fill=theme.MUTED,
        anchor="ra",
    )

    w.status_dot(d, x + 9, 152, 9, a.active)
    d.text(
        (x + 30, 140),
        "ACTIVE" if a.active else "IDLE",
        font=theme.sans(22),
        fill=theme.GOOD if a.active else theme.MUTED,
    )

    y = 186
    if a.project:
        d.text((x, y), a.project, font=theme.mono(24), fill=theme.FG)
        y += 38
    if a.model:
        d.text((x, y), a.model, font=theme.sans(20), fill=theme.ACCENT)
        y += 34
    if a.active and a.burn_rate_tpm:
        d.text(
            (x, y),
            f"{w.fmt_tokens(a.burn_rate_tpm)} tok/min",
            font=theme.mono(20),
            fill=theme.MUTED,
        )


def _footer(d: ImageDraw.ImageDraw, state: HudState) -> None:
    y0 = HEIGHT - _FOOTER_H
    d.text((_PAD, y0 + 12), "TOKENS TODAY", font=theme.sans(15), fill=theme.FAINT)
    w.sparkline(
        d,
        (_PAD + 150, y0 + 14, WIDTH - _PAD, HEIGHT - 16),
        state.hourly_tokens,
        slots=24,
    )
