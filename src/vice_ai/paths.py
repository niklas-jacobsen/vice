"""Where vice keeps things. Everything lives under one folder so it is easy to find and delete.

    ~/.vice/config.toml        your settings
    ~/.vice/index/             embedded blocks (rebuildable; safe to delete)
    ~/.vice/context.json       the latest context vice decided was worth having
    ~/.vice/decisions.jsonl    one line per event handled
    ~/.vice/logs/              output of the background service
    ~/.vice/traces/            OpenTelemetry spans, if tracing is on
    ~/.vice/calibration.json   optional: your own fitted thresholds
    ~/.vice/plugins/           third-party source packages (see `vice plugin`)
    ~/.vice/plugins.toml       the packages to rebuild that folder from

Set VICE_HOME to use a different folder.
"""
from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_CALIBRATION = PACKAGE_DIR / "default_calibration.json"


def home() -> Path:
    return Path(os.environ.get("VICE_HOME") or Path.home() / ".vice").expanduser()


def ensure_home() -> Path:
    h = home()
    h.mkdir(parents=True, exist_ok=True)
    os.chmod(h, 0o700)  # blocks and decisions are private to this user
    return h


def config_file() -> Path: return home() / "config.toml"
def index_dir() -> Path: return home() / "index"
def context_file() -> Path: return home() / "context.json"
def decisions_file() -> Path: return home() / "decisions.jsonl"
def logs_dir() -> Path: return home() / "logs"
def traces_dir() -> Path: return home() / "traces"
def plugins_dir() -> Path: return home() / "plugins"
def user_calibration() -> Path: return home() / "calibration.json"


def socket_file() -> Path:
    # AF_UNIX paths are capped near 104 bytes on macOS; allow an override for long homes.
    return Path(os.environ.get("VICE_SOCKET") or home() / "vice.sock")


def expand(p: str | Path) -> Path:
    return Path(os.path.expandvars(str(p))).expanduser()
