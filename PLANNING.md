# Claude Trofeo HUD — Planning

A desk HUD that displays live Claude usage stats on a Thermalright Trofeo Vision
6.86" LCD, driven by a Python app running on the Mac the display is plugged into.

Inspired by the r/ClaudeAI "$38 Claude LCD Table Display" post. Notes from that
post (author was also on a Mac over USB): their screen showed today's
*hypothetical* API cost (they're on a subscription — the dollar figure is a
"what this would have cost" calculation), a session-limit % meter, total tokens
and session count, an input/output/cache token split, a reset countdown, and a
bar chart, over a stylized background. Their app also cycles through multiple
screens (Claude Code / DaVinci Resolve / calendar countdown). The discussion
thread confirms usage data is obtainable from an Anthropic endpoint.

## Hardware

| Item | Detail |
|---|---|
| Display | Thermalright Trofeo Vision 6.86" IPS (~$38) |
| Resolution | 1280×480 (ultrawide landscape strip) |
| Connection | USB Type-C (data + power over USB) |
| Nature | Not a real monitor — a USB device that receives rendered image frames |

The display is normally driven by Thermalright's Windows-only TRCC software. The
protocol has been reverse-engineered by the open-source
[thermalright-trcc-linux](https://github.com/Lexonight1/thermalright-trcc-linux)
project (Python, pyusb/hidapi; on PyPI as `trcc-linux`), which lists macOS 11+ as
experimentally supported. Known Thermalright USB IDs include `0416:5302` (Trofeo
Vision LCD, HID Type 2 protocol) and `0416:5408` (Trofeo Vision 9.16, LY chunked
bulk protocol); we will confirm our exact unit's VID:PID during the hardware spike.

## Goals

Display, on a single always-on dashboard:

1. **Usage limits (primary)** — Pro/Max plan 5-hour session and weekly limit
   utilization as progress bars, with time-until-reset countdowns (what
   Claude Code's `/usage` shows).
2. **Tokens & cost** — today / this week token totals and *hypothetical* API
   cost ("what this would have cost at API pricing" — you're on a subscription,
   so it's a fun number, not a bill), with input/output/cache split and
   per-model breakdown, parsed from local Claude Code logs.
3. **Live activity** — current or most recent session: project name, model,
   active/idle indicator, burn rate (tokens per minute).
4. **Clock & extras** — time/date, Claude branding, a sparkline of usage
   through the day.

Stretch goal (post-M4): a screen-cycling framework like the original post's —
the Claude dashboard becomes one of several rotating screens (e.g. calendar
countdown, system stats), each a `render(state) -> Image` plugin.

Non-goals (for now): multi-machine aggregation, API-key billing data, touch or
input handling, Windows/Linux hosts.

## Architecture

Three decoupled layers, one asyncio (or simple threaded) loop:

```
┌─────────────────────────────────────────────────────────┐
│  collectors/          ── fetch + cache usage data       │
│    limits.py          OAuth usage endpoint (session/wk) │
│    tokens.py          Claude Code JSONL parsing         │
│    activity.py        live session watcher              │
├─────────────────────────────────────────────────────────┤
│  render/              ── Pillow → 1280×480 RGB frame    │
│    layout.py          zone layout, theme, fonts         │
│    widgets.py         progress bars, sparkline, text    │
├─────────────────────────────────────────────────────────┤
│  display/             ── push frame to panel over USB   │
│    trcc_driver.py     wraps trcc-linux                  │
└─────────────────────────────────────────────────────────┘
```

- **Collectors** each own a refresh cadence and never block the render loop.
  Failed refreshes keep the last-good value plus a stale indicator.
- **Renderer** is pure: `render(state) -> PIL.Image`, trivially testable by
  writing PNGs (`--preview` mode renders to a file without any hardware).
- **Display driver** is an interface with two implementations: the real panel
  (via `trcc-linux`) and a file/window preview for development.

### Data sources

**Usage limits.** *(Validated 2026-08-15, live in `collectors/limits.py`.)*
Claude Code's OAuth credentials live in the macOS Keychain item
`Claude Code-credentials` as JSON (`claudeAiOauth.accessToken`, rotated by
Claude Code itself — read fresh each refresh). The usage endpoint:

    GET https://api.anthropic.com/api/oauth/usage
    Authorization: Bearer <accessToken>
    anthropic-beta: oauth-2025-04-20

Response includes `five_hour` and `seven_day` objects, each
`{utilization: <0-100>, resets_at: <ISO datetime>}` (plus a richer `limits`
array with severity levels we could use later). Read-only; token goes only to
api.anthropic.com. On error the collector keeps last-good values + stale flag.
JSONL-based block estimation remains a possible fallback if the endpoint ever
changes.

**Tokens & cost.** Claude Code writes per-message JSONL transcripts under
`~/.claude/projects/<project>/*.jsonl` including token counts and model IDs.

- Phase 1: shell out to `ccusage` (`npx ccusage@latest --json`, plus daily/
  weekly variants) and read its JSON — battle-tested dedupe and pricing.
- Phase 2 (optional): native Python parser to drop the Node dependency
  (dedupe by message+request ID, static pricing table).

**Live activity.** Watch mtimes of the newest JSONL files; the most recently
modified file gives project (from directory name), model, and last-event
timestamp. "Active" = event within the last N seconds. Burn rate = tokens over a
trailing 10-minute window.

### Rendering

- Pillow, dark theme (near-black background — it's an IPS panel on a desk),
  Claude-orange accent (#D97757), red/amber states as limits approach.
- 1280×480 split into zones: left ~40% usage-limit bars + countdowns; middle
  tokens/cost + model breakdown; right activity + clock; bottom strip sparkline.
- Fonts: a monospace for numbers (JetBrains Mono or SF Mono), sans for labels;
  bundle TTFs in `assets/` so rendering is reproducible.
- Frame push every ~2–5 s (data changes slowly; no need to stress the USB link).
  Refresh cadences: limits every 60 s, tokens every 60 s, activity every 5 s,
  clock every frame.

### Display driver

**Hardware spike findings (2026-08-15, M1 complete — test image confirmed on
the panel):**

- Our unit: VID:PID `0416:5302`, product string "USBDISPLAY", firmware
  bcdDevice `4.07`, connected through an Anker USB-A hub (works fine).
- Protocol: trcc's **HID Type 2** ("H" variant, `DA DB DC DD` magic). Standard
  handshake answers `PM=128 SUB=1 → 1280×480`, **JPEG payload** (the registry's
  240×320 for this PID is a placeholder; the handshake result is authoritative).
- Frame = 20-byte header + JPEG bytes, zero-padded to 512-byte alignment,
  written as a sequence of 512-byte HID reports (never one blob).
- **macOS gotcha #1:** trcc's platform layer routes the HID wire through
  libusb bulk on every OS; macOS's HID kernel driver owns the device, so that
  fails with `Errno 13`. Fix: use trcc's `HidApiTransport` (IOHIDManager-backed)
  + `HidLcd` classes directly — see `spike/send_test_frame.py`. No sudo needed.
- **macOS gotcha #2:** the `hidapi` Python package is declared Linux-only in
  trcc's dependencies; we add it explicitly (`uv add hidapi`, plus
  `brew install hidapi` for the C library).
- **Firmware quirk row** for `(0416:5302, 4.07)`: `keepalive_stream=True` —
  the panel blanks when idle, so the HUD must stream frames continuously
  (~5 fps was comfortable in the spike; 43 KB JPEG at quality 95).
- We bypass trcc's CLI/App entirely (it drags in a Qt renderer we don't need);
  we depend on it only for the device/transport/protocol classes.

## Operations (macOS)

- Run as a `launchd` LaunchAgent so it starts at login and restarts on crash.
- Handle sleep/wake and USB unplug/replug: driver reconnect loop with backoff;
  render a "reconnecting" state rather than crashing.
- Config in `config.toml` (refresh cadences, plan reset day, theme, timezone).
- Logging to a rotating file; `--verbose` for debugging.

## Tooling

- Python 3.12+, `uv` for env/deps, `ruff` for lint/format, `pytest` for the
  renderer and parsers (golden-image tests for layout).
- Not a git repo yet — `git init` as part of project setup.

## Risks

| Risk | Mitigation |
|---|---|
| `trcc-linux` macOS support is "experimental" | Hardware spike is task #1; vendored-driver fallback |
| Our 6.86" unit's VID:PID/protocol variant differs from documented ones | Enumerate first; the repo supports several protocol families |
| OAuth usage endpoint is undocumented and could change | Isolate in one collector; JSONL block-estimation fallback |
| macOS USB permissions/quirks | libusb via Homebrew; document any TCC prompts in README |
| Panel burn-in / brightness at night | Dark theme; optional scheduled dimming or sleep hours |

## Milestones

1. **M1 — Pixels on glass:** test image renders on the physical display from macOS.
2. **M2 — Static dashboard:** full layout rendering with mocked data; PNG preview mode.
3. **M3 — Live data:** all three collectors feeding the renderer.
4. **M4 — Daemonized:** launchd agent, reconnect handling, config, docs.
