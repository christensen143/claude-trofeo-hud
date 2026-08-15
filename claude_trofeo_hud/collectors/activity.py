"""Live activity + sparkline from ~/.claude/projects JSONL. 5s cadence.

Cheap scan: only files modified today are read, and each file is re-read
only from the byte offset we last reached (transcripts are append-only).
"""
from __future__ import annotations

import dataclasses
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from ..state import Activity
from .base import Collector

log = logging.getLogger(__name__)

PROJECTS_DIR = Path.home() / ".claude" / "projects"
ACTIVE_WINDOW_S = 120          # "active" = assistant event in the last 2 min
BURN_WINDOW_MIN = 10

# Model id → short display name; unknown ids fall back to the raw id tail.
_MODEL_NAMES = {
    "claude-fable-5": "Fable 5",
    "claude-opus-5": "Opus 5",
    "claude-sonnet-5": "Sonnet 5",
    "claude-haiku-4-5": "Haiku 4.5",
}


def _display_model(model_id: str) -> str:
    for prefix, name in _MODEL_NAMES.items():
        if model_id.startswith(prefix):
            return name
    return model_id.removeprefix("claude-")


@dataclasses.dataclass
class _Event:
    ts: datetime
    tokens: int
    model: str
    file: Path
    project: str


class ActivityCollector(Collector):
    name_ = "activity"
    cadence_s = 5.0

    def __init__(self, shared) -> None:
        super().__init__(shared)
        self._offsets: dict[Path, int] = {}
        self._events: list[_Event] = []      # today's assistant events
        self._events_day: datetime | None = None

    def refresh(self) -> None:
        now = datetime.now().astimezone()
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

        if self._events_day is None or self._events_day != midnight:
            self._events, self._offsets, self._events_day = [], {}, midnight

        for f in PROJECTS_DIR.glob("*/*.jsonl"):
            if datetime.fromtimestamp(f.stat().st_mtime).astimezone() < midnight:
                continue
            self._ingest(f, midnight)

        self._publish(now, midnight)

    def _ingest(self, f: Path, midnight: datetime) -> None:
        offset = self._offsets.get(f, 0)
        try:
            size = f.stat().st_size
            if size <= offset:
                return
            with f.open("rb") as fh:
                fh.seek(offset)
                data = fh.read()
                # Only consume complete lines; partial tail is re-read next tick.
                last_nl = data.rfind(b"\n")
                if last_nl < 0:
                    return
                self._offsets[f] = offset + last_nl + 1
                lines = data[:last_nl].split(b"\n")
        except OSError:
            return

        for line in lines:
            if b'"assistant"' not in line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") != "assistant":
                continue
            msg = entry.get("message") or {}
            usage = msg.get("usage") or {}
            try:
                ts = datetime.fromisoformat(entry["timestamp"]).astimezone()
            except (KeyError, ValueError):
                continue
            if ts < midnight:
                continue
            tokens = sum(usage.get(k, 0) or 0 for k in
                         ("input_tokens", "output_tokens",
                          "cache_read_input_tokens",
                          "cache_creation_input_tokens"))
            project = Path(entry["cwd"]).name if entry.get("cwd") else f.parent.name
            self._events.append(
                _Event(ts, tokens, msg.get("model", ""), f, project))

    def _publish(self, now: datetime, midnight: datetime) -> None:
        act = Activity()
        if self._events:
            latest = max(self._events, key=lambda e: e.ts)
            act.project = latest.project
            act.model = _display_model(latest.model)
            act.last_event = latest.ts
            act.active = (now - latest.ts).total_seconds() < ACTIVE_WINDOW_S

            burn_start = now - timedelta(minutes=BURN_WINDOW_MIN)
            burned = sum(e.tokens for e in self._events if e.ts >= burn_start)
            act.burn_rate_tpm = burned / BURN_WINDOW_MIN

        buckets = [0] * (now.hour + 1)
        for e in self._events:
            buckets[e.ts.hour] += e.tokens

        sessions_today = len({e.file for e in self._events})

        def apply(state) -> None:
            state.activity = act
            state.hourly_tokens = buckets
            state.tokens = dataclasses.replace(
                state.tokens, session_count=sessions_today)
        self.shared.mutate(apply)

    def mark_stale(self) -> None:
        def apply(state) -> None:
            state.activity = dataclasses.replace(state.activity, stale=True)
        self.shared.mutate(apply)
