"""launchd LaunchAgent install/uninstall for start-at-login operation."""
from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

LABEL = "com.varlogchris.claude-trofeo-hud"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _plist_dict(log_dir: Path) -> dict:
    # NOT .resolve(): the venv python is a symlink to the bare uv-managed
    # interpreter; resolving it loses the venv (and every package with it).
    python = Path(sys.executable)
    project = Path(__file__).resolve().parent.parent
    # launchd agents get a bare PATH; npx (nvm) and brew libs must be findable.
    node_bin = Path(shutil.which("npx") or "").parent
    path = ":".join(p for p in (
        str(node_bin), "/opt/homebrew/bin", "/usr/local/bin",
        "/usr/bin", "/bin",
    ) if p)
    return {
        "Label": LABEL,
        "ProgramArguments": [str(python), "-m", "claude_trofeo_hud", "run"],
        "WorkingDirectory": str(project),
        "EnvironmentVariables": {"PATH": path},
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "StandardOutPath": str(log_dir / "agent-stdout.log"),
        "StandardErrorPath": str(log_dir / "agent-stderr.log"),
    }


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def install(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    uninstall(quiet=True)  # idempotent reinstall
    PLIST.write_bytes(plistlib.dumps(_plist_dict(log_dir)))
    r = _launchctl("bootstrap", f"gui/{os.getuid()}", str(PLIST))
    if r.returncode != 0:
        raise SystemExit(f"launchctl bootstrap failed: {r.stderr.strip()}")
    print(f"installed + started {LABEL}\n  plist: {PLIST}\n  logs:  {log_dir}")


def uninstall(quiet: bool = False) -> None:
    r = _launchctl("bootout", f"gui/{os.getuid()}/{LABEL}")
    if PLIST.exists():
        PLIST.unlink()
    if not quiet:
        stopped = "stopped and " if r.returncode == 0 else ""
        print(f"{stopped}removed {LABEL}")
