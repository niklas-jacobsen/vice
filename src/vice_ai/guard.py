"""Claude Code PreToolUse hook: keeps the agent from reading files vice indexes.

vice already pushes what is relevant with each prompt and answers `recall`; an agent
reading or searching the same files spends its context on the search vice exists to
replace. Only files vice indexes are blocked: paths outside every source, files a source
excludes, non-Markdown files and sources with `guard = false` stay readable.

Bash is checked by its arguments: a command naming an indexed file, or a directory inside
a source, is blocked. A command that reads a source without naming it (`grep -r x` run
from inside the vault) is not caught.
"""
from __future__ import annotations

import os
import shlex
from pathlib import Path

from .adapters.base import SourceAdapter

READ_TOOLS = ("Read", "Grep", "Glob", "Bash")
REASON = ("{path} is indexed by vice. Its relevant content is added to each prompt; to look up "
          "anything else from the user's sources, call the vice `recall` tool instead of reading files.")
_GLOB_CHARS = set("*?[{")


def _resolve(p: str, cwd: str) -> Path:
    return Path(os.path.normpath(Path(cwd, os.path.expanduser(p)))).resolve()


def _glob_root(pattern: str) -> str:
    """The literal directory prefix of a glob pattern (`~/vault/**/*.md` -> `~/vault`)."""
    parts = []
    for part in pattern.split("/"):
        if _GLOB_CHARS & set(part):
            break
        parts.append(part)
    return "/".join(parts) or "."


def _bash_paths(command: str) -> list[str]:
    try:
        tokens = shlex.split(command, comments=True)
    except ValueError:
        tokens = command.split()
    out = []
    for t in tokens:
        for piece in (t, t.partition("=")[2]):
            if piece and ("/" in piece or piece.startswith(("~", ".")) or "." in piece):
                out.append(_glob_root(piece) if _GLOB_CHARS & set(piece) else piece)
    return out


def _candidates(tool: str, tool_input: dict, cwd: str) -> list[tuple[str, bool]]:
    """(path, may_be_directory) pairs the tool call would read."""
    if tool == "Read":
        return [(tool_input.get("file_path") or "", False)]
    if tool == "Grep":
        return [(tool_input.get("path") or cwd, True)]
    if tool == "Glob":
        pattern = tool_input.get("pattern") or ""
        base = tool_input.get("path") or cwd
        if pattern.startswith(("/", "~")):
            base = _glob_root(pattern)
        return [(base, True)]
    if tool == "Bash":
        return [(p, True) for p in _bash_paths(tool_input.get("command") or "")]
    return []


def blocked_path(tool: str, tool_input: dict, cwd: str, sources: tuple[SourceAdapter, ...]) -> str | None:
    """The first path this call would read that vice indexes, or None to allow it."""
    guarded = [s for s in sources if s.guard]
    if not guarded:
        return None
    for raw, may_be_dir in _candidates(tool, tool_input, cwd):
        if not raw:
            continue
        path = _resolve(raw, cwd)
        is_dir = may_be_dir and path.is_dir()
        for src in guarded:
            if src.indexes(path, is_dir):
                return raw
    return None


def decide(event: dict, sources: tuple[SourceAdapter, ...]) -> dict | None:
    """The PreToolUse reply denying the call, or None to let it through."""
    tool = event.get("tool_name") or ""
    if tool not in READ_TOOLS:
        return None
    path = blocked_path(tool, event.get("tool_input") or {}, event.get("cwd") or os.getcwd(), sources)
    if path is None:
        return None
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": REASON.format(path=path)}}
