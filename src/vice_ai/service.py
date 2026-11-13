"""Run vice in the background on macOS, as a per-user launchd agent.

`vice start` writes ~/Library/LaunchAgents/ai.vice.agent.plist and loads it; the agent
starts at login and restarts if it crashes. `vice stop` unloads it and removes the file.
"""
from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

from . import paths

LABEL = "ai.vice.agent"


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def plist_bytes() -> bytes:
    env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin"}
    if os.environ.get("VICE_HOME"):
        env["VICE_HOME"] = os.environ["VICE_HOME"]
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [sys.executable, "-m", "vice_ai", "run"],
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},  # restart on crash, not after a clean stop
        "ThrottleInterval": 30,
        "ProcessType": "Background",
        "StandardOutPath": str(paths.logs_dir() / "vice.log"),
        "StandardErrorPath": str(paths.logs_dir() / "vice.err.log"),
        "EnvironmentVariables": env,
    })


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _require_macos() -> None:
    if sys.platform != "darwin":
        raise SystemExit("The background service is macOS-only. Use `vice run` under your own process manager.")


def is_loaded() -> bool:
    if sys.platform != "darwin":
        return False
    return subprocess.run(["launchctl", "print", f"{_domain()}/{LABEL}"], capture_output=True).returncode == 0


def start() -> None:
    _require_macos()
    paths.logs_dir().mkdir(parents=True, exist_ok=True)
    p = plist_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    if is_loaded():
        subprocess.run(["launchctl", "bootout", f"{_domain()}/{LABEL}"], capture_output=True)
    p.write_bytes(plist_bytes())
    r = subprocess.run(["launchctl", "bootstrap", _domain(), str(p)], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"launchctl could not start vice: {r.stderr.strip() or r.stdout.strip()}")


def stop() -> bool:
    _require_macos()
    was = is_loaded()
    if was:
        subprocess.run(["launchctl", "bootout", f"{_domain()}/{LABEL}"], capture_output=True)
    plist_path().unlink(missing_ok=True)
    return was
