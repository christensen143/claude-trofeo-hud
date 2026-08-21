"""CLI: python -m claude_trofeo_hud {run|preview|panel|install-agent|uninstall-agent}

run              — the real HUD: live collectors → LCD, reconnect-resilient
preview          — render one frame (mock, or --live) to a PNG, no hardware
panel            — stream MOCK frames to the LCD (layout demo)
install-agent    — launchd LaunchAgent: start at login, restart on crash
uninstall-agent  — stop and remove the LaunchAgent
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import time
from pathlib import Path

from .config import load as load_config
from .render.layout import render
from .state import mock_state


def main() -> int:
    p = argparse.ArgumentParser(prog="claude-trofeo-hud")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    prev = sub.add_parser("preview", help="render one frame to a PNG")
    prev.add_argument("out", nargs="?", default="out/preview.png")
    prev.add_argument(
        "--live", action="store_true", help="use live collectors instead of mock data"
    )

    pan = sub.add_parser("panel", help="stream MOCK frames to the LCD")
    pan.add_argument("--seconds", type=float, default=0)
    pan.add_argument("--fps", type=float, default=2.0)

    run = sub.add_parser("run", help="the real HUD: live collectors → LCD")
    run.add_argument("--seconds", type=float, default=0)

    sub.add_parser("install-agent", help="install launchd agent (login start)")
    sub.add_parser("uninstall-agent", help="remove launchd agent")

    args = p.parse_args()
    cfg = load_config()
    _setup_logging(cfg, verbose=args.verbose, to_file=args.cmd == "run")

    if args.cmd == "preview":
        state = _start_collectors(wait=True).snapshot() if args.live else mock_state()
        out = Path(args.out)
        # `out/` is gitignored, so it does not exist in a fresh clone — and
        # preview is the first command the README tells a new user to run.
        out.parent.mkdir(parents=True, exist_ok=True)
        render(state).save(out)
        print(f"wrote {out}")
        return 0

    if args.cmd == "panel":
        from .display.panel import TrofeoPanel

        panel = TrofeoPanel()
        panel.connect()
        deadline = time.time() + args.seconds if args.seconds else None
        try:
            while deadline is None or time.time() < deadline:
                start = time.time()
                panel.send(render(mock_state()))
                time.sleep(max(0.0, 1.0 / args.fps - (time.time() - start)))
        except KeyboardInterrupt:
            pass
        finally:
            panel.close()
        return 0

    if args.cmd == "run":
        from .app import run_loop

        shared = _start_collectors()
        try:
            run_loop(shared, cfg, stop_after_s=args.seconds)
        except KeyboardInterrupt:
            pass
        return 0

    from . import agent

    if args.cmd == "install-agent":
        agent.install(cfg.log_dir)
    else:
        agent.uninstall()
    return 0


def _setup_logging(cfg, verbose: bool, to_file: bool) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if to_file:
        cfg.log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(
            logging.handlers.RotatingFileHandler(
                cfg.log_dir / "hud.log", maxBytes=1_000_000, backupCount=3
            )
        )
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
    )


def _start_collectors(wait: bool = False):
    from .collectors.activity import ActivityCollector
    from .collectors.base import SharedState
    from .collectors.limits import LimitsCollector
    from .collectors.tokens import TokensCollector

    shared = SharedState()
    for cls in (TokensCollector, ActivityCollector, LimitsCollector):
        cls(shared).start()
    if wait:
        # First ccusage run can take a while (npx fetch + full log parse);
        # give collectors a beat so the first frame isn't empty.
        deadline = time.time() + 90
        while time.time() < deadline:
            s = shared.snapshot()
            if s.tokens.today_tokens and s.limits.session:
                break
            time.sleep(0.5)
    return shared


if __name__ == "__main__":
    raise SystemExit(main())
