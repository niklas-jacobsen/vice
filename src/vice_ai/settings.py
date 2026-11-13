"""User settings: which sources vice listens to, which notes it reads, where results go.

Read from ~/.vice/config.toml. Unknown keys are errors, so a typo never silently does nothing.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import paths
from .config import Config

NOTE_TYPES = ("obsidian", "markdown", "jsonl")
OUTPUT_TYPES = ("context_file", "notification", "command", "webhook")
ACTIONS = ("surface", "attach")

DEFAULT_CONFIG = '''\
# vice configuration. Edit freely; run `vice status` to check it.

# ---- Event sources: what vice watches -------------------------------------------------
[sources.clipboard]
enabled = {clipboard}

[sources.file_drop]
enabled = {file_drop}
folders = ["{drop_folder}"]

[sources.palette]       # `vice ask "..."` and the MCP server
enabled = true

# ---- Notes: what vice remembers -------------------------------------------------------
# Add one [[notes]] block per source. Types: "obsidian", "markdown", "jsonl".
{notes}
# ---- Outputs: where context goes ------------------------------------------------------
# `on` lists the decisions an output reacts to: "surface" (strong match) and/or "attach".
[outputs.context_file]
enabled = true
on = ["surface", "attach"]

[outputs.notification]
enabled = {notification}
on = ["surface"]

# Run a program with the decision as JSON on stdin.
# [outputs.command]
# enabled = true
# on = ["surface", "attach"]
# run = ["/path/to/script"]

# POST the decision as JSON.
# [outputs.webhook]
# enabled = true
# on = ["surface"]
# url = "http://127.0.0.1:8787/vice"

# ---- Advanced: pipeline tunables (see docs/configuration.md) --------------------------
# [pipeline]
# token_budget = 400
# top_k = 20
'''


@dataclass(frozen=True)
class NotesSource:
    type: str
    path: Path
    name: str
    exclude: tuple[str, ...] = ()


@dataclass(frozen=True)
class Output:
    type: str
    on: tuple[str, ...]
    options: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Settings:
    clipboard: bool = False
    file_drop: bool = False
    drop_folders: tuple[Path, ...] = ()
    palette: bool = True
    notes: tuple[NotesSource, ...] = ()
    outputs: tuple[Output, ...] = (Output("context_file", ACTIONS),)
    pipeline: Config = field(default_factory=Config)
    resync_s: float = 120.0
    tracing: bool = False


class SettingsError(ValueError):
    pass


def _only(d: dict, allowed: set[str], where: str) -> None:
    extra = set(d) - allowed
    if extra:
        raise SettingsError(f"unknown key(s) {sorted(extra)} in {where}; allowed: {sorted(allowed)}")


def parse(data: dict) -> Settings:
    _only(data, {"sources", "notes", "outputs", "pipeline", "resync_s", "tracing"}, "config.toml")
    src = data.get("sources", {})
    _only(src, {"clipboard", "file_drop", "palette"}, "[sources]")
    clip, drop, pal = src.get("clipboard", {}), src.get("file_drop", {}), src.get("palette", {})
    _only(clip, {"enabled"}, "[sources.clipboard]")
    _only(drop, {"enabled", "folders"}, "[sources.file_drop]")
    _only(pal, {"enabled"}, "[sources.palette]")

    notes = []
    for i, n in enumerate(data.get("notes", [])):
        where = f"[[notes]] #{i + 1}"
        _only(n, {"type", "path", "name", "exclude"}, where)
        if n.get("type") not in NOTE_TYPES:
            raise SettingsError(f"{where}: type must be one of {NOTE_TYPES}")
        if "path" not in n:
            raise SettingsError(f"{where}: path is required")
        p = paths.expand(n["path"])
        notes.append(NotesSource(n["type"], p, n.get("name") or p.name, tuple(n.get("exclude", ()))))
    names = [n.name for n in notes]
    if len(set(names)) != len(names):
        raise SettingsError("[[notes]] sources need distinct names; add name = \"...\" to disambiguate")

    outputs = []
    for typ, o in data.get("outputs", {}).items():
        where = f"[outputs.{typ}]"
        if typ not in OUTPUT_TYPES:
            raise SettingsError(f"{where}: unknown output; options: {OUTPUT_TYPES}")
        allowed = {"context_file": {"path"}, "notification": set(), "command": {"run", "timeout_s"}, "webhook": {"url", "timeout_s"}}[typ]
        _only(o, {"enabled", "on"} | allowed, where)
        on = tuple(o.get("on", ACTIONS))
        if not on or any(a not in ACTIONS for a in on):
            raise SettingsError(f"{where}: `on` must list one or both of {ACTIONS}")
        if typ == "command" and not (isinstance(o.get("run"), list) and o["run"]):
            raise SettingsError(f"{where}: run must be a list such as [\"/path/to/script\", \"arg\"]")
        if typ == "webhook" and not str(o.get("url", "")).startswith(("http://", "https://")):
            raise SettingsError(f"{where}: url must start with http:// or https://")
        if o.get("enabled", True):
            outputs.append(Output(typ, on, {k: v for k, v in o.items() if k in allowed}))

    try:
        pipeline = Config.from_overrides(data.get("pipeline", {}))
    except (ValueError, TypeError) as e:
        raise SettingsError(str(e)) from e

    return Settings(
        clipboard=bool(clip.get("enabled", False)),
        file_drop=bool(drop.get("enabled", False)),
        drop_folders=tuple(paths.expand(f) for f in drop.get("folders", ())),
        palette=bool(pal.get("enabled", True)),
        notes=tuple(notes),
        outputs=tuple(outputs),
        pipeline=pipeline,
        resync_s=float(data.get("resync_s", 120.0)),
        tracing=bool(data.get("tracing", False)),
    )


def load(path: Path | None = None) -> Settings:
    path = path or paths.config_file()
    if not path.exists():
        raise SettingsError(f"no configuration at {path}. Run `vice setup` first.")
    try:
        return parse(tomllib.loads(path.read_text()))
    except tomllib.TOMLDecodeError as e:
        raise SettingsError(f"{path} is not valid TOML: {e}") from e


def render_default(notes: list[tuple[str, str]], clipboard: bool, file_drop: bool, drop_folder: str, notification: bool) -> str:
    blocks = "".join(f'[[notes]]\ntype = "{t}"\npath = "{p}"\n\n' for t, p in notes) or (
        '# [[notes]]\n# type = "obsidian"\n# path = "~/Documents/MyVault"\n# exclude = ["Templates/**"]\n\n')
    b = lambda v: "true" if v else "false"
    return DEFAULT_CONFIG.format(clipboard=b(clipboard), file_drop=b(file_drop), drop_folder=drop_folder,
                                 notes=blocks, notification=b(notification))
