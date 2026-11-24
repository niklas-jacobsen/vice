"""User settings: which sources vice reads and where results go.

Read from ~/.vice/config.toml. Unknown keys are errors.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import adapters, paths
from .adapters.base import SourceAdapter, SourceConfigError
from .config import Config

OUTPUT_TYPES = ("context_file", "command", "webhook")
ACTIONS = ("surface", "attach")

DEFAULT_CONFIG = '''\
# vice configuration. Edit freely; run `vice status` to check it.

# ---- Sources: where information comes from --------------------------------------------
# One [[sources]] entry per source. Built-in types: "obsidian", "markdown", "jsonl".
{sources}# ---- Outputs: where context goes ------------------------------------------------------
# `on` lists the decisions an output reacts to: "surface" (strong match) and/or "attach".
[outputs.context_file]
enabled = true
on = ["surface", "attach"]

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
class Output:
    type: str
    on: tuple[str, ...]
    options: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Settings:
    sources: tuple[SourceAdapter, ...] = ()
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
    if "notes" in data:
        raise SettingsError("[[notes]] has been renamed to [[sources]]")
    if isinstance(data.get("sources"), dict):
        raise SettingsError("[sources.*] has been renamed to [triggers.*]; [[sources]] now lists indexed sources")
    if "triggers" in data:
        raise SettingsError("[triggers] has been removed: vice no longer watches the clipboard or drop folders; "
                            "delete the [triggers.*] sections")
    _only(data, {"sources", "outputs", "pipeline", "resync_s", "tracing"}, "config.toml")

    sources = []
    for i, n in enumerate(data.get("sources", [])):
        try:
            sources.append(adapters.build(n))
        except SourceConfigError as e:
            raise SettingsError(f"[[sources]] #{i + 1}: {e}") from e
    names = [n.name for n in sources]
    if len(set(names)) != len(names):
        raise SettingsError("[[sources]] need distinct names; add name = \"...\" to disambiguate")

    outputs = []
    for typ, o in data.get("outputs", {}).items():
        where = f"[outputs.{typ}]"
        if typ == "notification":
            raise SettingsError(f"{where} has been removed; delete the section")
        if typ not in OUTPUT_TYPES:
            raise SettingsError(f"{where}: unknown output; options: {OUTPUT_TYPES}")
        allowed = {"context_file": {"path"}, "command": {"run", "timeout_s"}, "webhook": {"url", "timeout_s"}}[typ]
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
        sources=tuple(sources),
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


def render_default(sources: list[tuple[str, str]]) -> str:
    entries = "".join(f'[[sources]]\ntype = "{t}"\npath = "{p}"\n\n' for t, p in sources) or (
        '# [[sources]]\n# type = "obsidian"\n# path = "~/Documents/MyVault"\n# exclude = ["Templates/**"]\n\n')
    return DEFAULT_CONFIG.format(sources=entries)
