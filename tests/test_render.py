"""Renderer smoke tests. Pixel-exact golden images would be font-dependent
across machines; we assert structure instead."""
from datetime import datetime, timedelta

from PIL import Image, ImageColor, ImageDraw

from claude_trofeo_hud import theme
from claude_trofeo_hud.render import widgets as w
from claude_trofeo_hud.render.layout import (
    HEIGHT,
    WIDTH,
    _elapsed_window_pct,
    render,
)
from claude_trofeo_hud.state import HudState, mock_state


def test_render_size_and_content():
    img = render(mock_state(datetime(2026, 8, 15, 17, 0)))
    assert img.size == (WIDTH, HEIGHT)
    assert len(img.getcolors(maxcolors=1 << 20)) > 10  # actually drew things


def test_render_empty_state_does_not_crash():
    img = render(HudState(now=datetime(2026, 8, 15, 3, 0)))
    assert img.size == (WIDTH, HEIGHT)


def test_render_stale_sections_do_not_crash():
    state = mock_state(datetime(2026, 8, 15, 17, 0))
    state.limits.stale = True
    state.tokens.stale = True
    state.activity.stale = True
    render(state)


def test_fmt_tokens():
    assert w.fmt_tokens(999) == "999"
    assert w.fmt_tokens(1_500) == "1.5k"
    assert w.fmt_tokens(229_200_000) == "229.2M"
    assert w.fmt_tokens(1_100_000_000) == "1.1B"


def test_fmt_countdown():
    assert w.fmt_countdown(59) == "0m"
    assert w.fmt_countdown(4 * 3600 + 45 * 60) == "4h 45m"
    assert w.fmt_countdown(2 * 86400 + 9 * 3600) == "2d 9h"
    assert w.fmt_countdown(-5) == "0m"


def test_progress_bar_draws_elapsed_marker():
    img = Image.new("RGB", (120, 40), theme.BG)
    d = ImageDraw.Draw(img)

    w.progress_bar(
        d, (10, 10, 110, 30), 50, theme.ACCENT, marker_pct=25,
    )

    assert img.getpixel((35, 6)) == ImageColor.getrgb(theme.FG)
    assert img.getpixel((35, 34)) == ImageColor.getrgb(theme.FG)


def test_progress_bar_without_marker_preserves_surrounding_pixels():
    img = Image.new("RGB", (120, 40), theme.BG)
    d = ImageDraw.Draw(img)

    w.progress_bar(d, (10, 10, 110, 30), 50, theme.ACCENT)

    assert img.getpixel((35, 6)) == ImageColor.getrgb(theme.BG)


def test_progress_bar_clamps_elapsed_marker_to_inside_edges():
    for marker_pct, expected_x in ((-10, 11), (110, 109)):
        img = Image.new("RGB", (120, 40), theme.BG)
        d = ImageDraw.Draw(img)

        w.progress_bar(
            d, (10, 10, 110, 30), 50, theme.ACCENT,
            marker_pct=marker_pct,
        )

        assert img.getpixel((expected_x, 6)) == ImageColor.getrgb(theme.FG)


def test_elapsed_window_pct_start_midpoint_and_end():
    now = datetime(2026, 8, 17, 12, 0)
    duration = timedelta(hours=5)

    assert _elapsed_window_pct(now, now + duration, duration) == 0.0
    assert _elapsed_window_pct(
        now, now + timedelta(hours=2, minutes=30), duration,
    ) == 50.0
    assert _elapsed_window_pct(now, now, duration) == 100.0


def test_elapsed_window_pct_clamps_outside_window():
    now = datetime(2026, 8, 17, 12, 0)
    duration = timedelta(days=7)

    assert _elapsed_window_pct(now, now + timedelta(days=8), duration) == 0.0
    assert _elapsed_window_pct(now, now - timedelta(hours=1), duration) == 100.0


def test_render_places_session_and_week_elapsed_markers():
    now = datetime(2026, 8, 15, 17, 0)

    img = render(mock_state(now))

    assert img.getpixel((49, 142)) == ImageColor.getrgb(theme.FG)
    assert img.getpixel((302, 292)) == ImageColor.getrgb(theme.FG)
