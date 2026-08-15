"""Renderer smoke tests. Pixel-exact golden images would be font-dependent
across machines; we assert structure instead."""
from datetime import datetime

from claude_trofeo_hud.render import widgets as w
from claude_trofeo_hud.render.layout import HEIGHT, WIDTH, render
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
