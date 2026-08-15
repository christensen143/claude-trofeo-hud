# Claude Trofeo HUD — Tasks

See [PLANNING.md](PLANNING.md) for context. Tasks are ordered; each phase ends
with something demonstrable. Check items off as they land.

## Phase 0 — Project setup

- [x] `git init`, `.gitignore` (Python, macOS) *(init done; .gitignore pending)*
- [x] `uv init` with Python 3.12+; add `ruff` + `pytest` dev deps *(uv done; dev deps pending)*
- [x] Skeleton package: `claude_trofeo_hud/` with `render/`, `display/`
      (`collectors/` lands with Phase 3)
- [x] `config.toml` loader with sensible defaults — `config.py` (fps, JPEG
      quality, night schedule)

## Phase 1 — Hardware spike (Milestone M1: pixels on glass) ✅

- [x] Install prerequisites: `brew install libusb hidapi` (+ `uv add hidapi` —
      trcc declares it Linux-only, see PLANNING.md)
- [x] Plug in display; enumerate USB device and record VID:PID → `0416:5302`,
      "USBDISPLAY", firmware 4.07, via Anker USB-A hub
- [x] Install `trcc-linux`; confirm protocol → HID Type 2; handshake reports
      1280×480, JPEG payload
- [x] Send test image → done via `spike/send_test_frame.py` (trcc's CLI is
      unusable on macOS: libusb transport + Qt renderer; we drive
      `HidLcd` + `HidApiTransport` directly instead)
- [x] Verify on glass: test pattern confirmed visible
- [x] Verify orientation precisely (corner markers: red TL / green TR /
      blue BL / yellow BR) and color fidelity — confirmed by user
- [x] Frame pacing: 5 fps comfortable in spike; panel has `keepalive_stream`
      firmware — blanks when idle, so stream continuously
- [x] Write findings into PLANNING.md
- [x] ~~Fallback: vendor minimal driver~~ not needed — library classes work
      when bypassing the CLI

## Phase 2 — Renderer (Milestone M2: static dashboard)

- [x] Define `HudState` dataclass: limits, tokens/cost, activity, clock fields
      (every field optional + `stale` flags) — `state.py`
- [x] Theme module: colors + macOS system fonts w/ fallback — `theme.py`
      (bundling TTFs in `assets/` deferred)
- [x] Widget primitives: progress bar, sparkline, status dot, formatters — `render/widgets.py`
- [x] Layout for 1280×480: limits / tokens / activity+clock zones + sparkline
      footer — `render/layout.py`
- [x] Preview mode: `python -m claude_trofeo_hud preview [out.png]`; panel
      streaming: `python -m claude_trofeo_hud panel [--seconds N --fps F]`
- [x] Renderer tests: structural smoke tests + formatter units in
      `tests/test_render.py` (pixel-golden skipped — font-dependent across machines)
- [x] Iterate on design with user feedback — approved

## Phase 3 — Data collectors (Milestone M3: live data)

### Usage limits (session/weekly %)

- [x] Discovery: Keychain item "Claude Code-credentials" →
      `claudeAiOauth.accessToken`; endpoint
      `GET https://api.anthropic.com/api/oauth/usage` with
      `Authorization: Bearer` + `anthropic-beta: oauth-2025-04-20`;
      response `five_hour`/`seven_day` = `{utilization, resets_at}`
- [x] `limits.py` collector: session %, weekly %, reset timestamps; 60 s
      cadence; token re-read from Keychain each refresh (Claude Code rotates it)
- [x] Errors → stale flag, last-good values kept
- [ ] Fallback path: estimate 5-hour block usage from JSONL timestamps if endpoint fails

### Tokens & cost

- [x] Verify `ccusage` output: `npx ccusage@latest daily --json` works
- [x] `tokens.py` collector: today + this-week totals, in/out/cache split,
      hypothetical cost; 60 s cadence (session count comes from activity;
      per-model breakdown not displayed yet)
- [x] Stale flag on failure (last-good value kept)
- [ ] (Optional, later) native JSONL parser to drop the Node/ccusage dependency

### Live activity

- [x] `activity.py` collector: incremental JSONL tail (byte offsets) →
      project (from `cwd` field), model, active/idle, 5 s cadence
- [x] Burn rate: tokens over trailing 10-minute window
- [x] Daily usage sparkline series (hourly token buckets since midnight)

### Wiring

- [x] Main loop: collector threads + locked SharedState (atomic `mutate` for
      cross-section updates), render loop at frame cadence
- [x] CLI: `preview [--live]`, `panel` (mock demo), `run` (live → LCD)
- [x] End-to-end `run`: live data on the physical panel ✅ M3

## Phase 4 — Daemonize & polish (Milestone M4) ✅

- [x] USB reconnect loop with capped exponential backoff in `app.py`
      (collectors keep running; first frame after reconnect is current)
- [ ] Field-test reconnect: unplug/replug the panel and confirm recovery
- [x] launchd LaunchAgent via `install-agent` / `uninstall-agent` subcommands
      (venv python + node PATH baked into plist; KeepAlive; installed & running)
- [x] Rotating file logging to `~/Library/Logs/claude-trofeo-hud/`; `--verbose`
- [x] Warn/critical colors at 80%/95% (`theme.limit_color`, wired since Phase 2)
- [x] Night mode in `config.toml`: off/dim schedule (`config.py` + `app._frame`)
- [x] README: hardware, install, Keychain note, troubleshooting

## Phase 5 — Stretch

- [ ] Screen-cycling framework (dashboard becomes one of N rotating screens)
- [ ] Calendar countdown screen (next meeting "IN 34 MIN" style)
- [ ] Background art / theming options for the Claude screen
