"""`vice connect claude-code`: register vice with Claude Code.

Writes two hooks into Claude Code's user settings and adds the MCP server at user scope:

  UserPromptSubmit   vice hook    relevant blocks are added with each prompt
  PreToolUse         vice guard   reads of files vice indexes are refused
  MCP server         vice mcp     `recall` for lookups mid-task

Re-running replaces vice's entries; `--remove` deletes them. Other hooks are left as they are.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

GUARD_MATCHER = "Read|Grep|Glob|Bash"
_OURS = re.compile(r"(?:^|[/\s])(?:vice|-m vice_ai) (?:hook|guard)$")


def settings_path() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "settings.json"


def vice_command() -> list[str]:
    """How Claude Code should start this installation of vice."""
    argv0 = Path(sys.argv[0])
    if argv0.name == "vice" and argv0.exists():
        return [str(argv0.resolve())]
    return [sys.executable, "-m", "vice_ai"]


def _is_ours(hook: dict) -> bool:
    return bool(_OURS.search(str(hook.get("command", "")).strip()))


def _strip(settings: dict) -> dict:
    hooks = settings.get("hooks") or {}
    for event in ("UserPromptSubmit", "PreToolUse"):
        groups = []
        for g in hooks.get(event) or []:
            kept = [h for h in g.get("hooks") or [] if not _is_ours(h)]
            if kept:
                groups.append({**g, "hooks": kept})
            elif not g.get("hooks"):
                groups.append(g)
        if groups:
            hooks[event] = groups
        else:
            hooks.pop(event, None)
    if hooks:
        settings["hooks"] = hooks
    else:
        settings.pop("hooks", None)
    return settings


def merged(settings: dict, command: list[str], remove: bool = False) -> dict:
    settings = _strip(json.loads(json.dumps(settings)))
    if remove:
        return settings
    cmd = shlex.join(command)
    hooks = settings.setdefault("hooks", {})
    hooks.setdefault("UserPromptSubmit", []).append(
        {"hooks": [{"type": "command", "command": f"{cmd} hook", "timeout": 10}]})
    hooks.setdefault("PreToolUse", []).append(
        {"matcher": GUARD_MATCHER, "hooks": [{"type": "command", "command": f"{cmd} guard", "timeout": 5}]})
    return settings


def write_settings(path: Path, command: list[str], remove: bool = False) -> Path | None:
    """Update `path` in place. Returns the backup of the previous file, if there was one."""
    current = {}
    if path.exists():
        try:
            current = json.loads(path.read_text() or "{}")
        except json.JSONDecodeError as e:
            raise SystemExit(f"vice: {path} is not valid JSON ({e}); fix it first, nothing was changed")
    backup = None
    if path.exists():
        backup = path.with_name(path.name + ".vice-backup")
        shutil.copy2(path, backup)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(merged(current, command, remove), indent=2) + "\n")
    tmp.replace(path)
    return backup


def mcp(command: list[str], remove: bool = False) -> str:
    """Register the MCP server at user scope through the `claude` CLI. Returns a status line."""
    claude = shutil.which("claude")
    add = ["claude", "mcp", "add", "--scope", "user", "vice", "--", *command, "mcp"]
    if not claude:
        return "MCP: `claude` not found on PATH; run: " + (
            "claude mcp remove vice --scope user" if remove else shlex.join(add))
    subprocess.run([claude, "mcp", "remove", "vice", "--scope", "user"], capture_output=True, check=False)
    if remove:
        return "MCP: removed `vice` (user scope)."
    r = subprocess.run([claude, *add[1:]], capture_output=True, text=True, check=False)
    if r.returncode:
        return f"MCP: `{shlex.join(add)}` failed: {(r.stderr or r.stdout).strip()}"
    return "MCP: added `vice` (user scope)."
