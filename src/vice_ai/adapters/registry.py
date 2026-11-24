"""Finding adapter classes by source type.

Built-in types are listed here; other packages register theirs in their own pyproject.toml:

    [project.entry-points."vice.sources"]
    slack = "vice_source_slack:SlackSource"

Adapter modules are imported only when a configured source uses them, so an unused or
broken third-party adapter costs nothing.
"""
from __future__ import annotations

import importlib
from importlib.metadata import entry_points
from typing import Any, Mapping

from .base import RESERVED_KEYS, SourceAdapter, SourceConfigError

ENTRY_POINT_GROUP = "vice.sources"

BUILTIN = {
    "markdown": "vice_ai.adapters.markdown:MarkdownSource",
    "obsidian": "vice_ai.adapters.markdown:ObsidianSource",
    "jsonl": "vice_ai.adapters.jsonl:JsonlSource",
}


def available() -> dict[str, str]:
    """type -> "module:Class". Built-ins win over a third-party package claiming the same type."""
    found = {ep.name: ep.value for ep in entry_points(group=ENTRY_POINT_GROUP)}
    return {**found, **BUILTIN}


def adapter_class(type_: str) -> type[SourceAdapter]:
    target = available().get(type_)
    if target is None:
        raise SourceConfigError(f"unknown source type {type_!r}; available: {sorted(available())}")
    module, _, attr = target.partition(":")
    try:
        cls = getattr(importlib.import_module(module), attr)
    except (ImportError, AttributeError) as e:
        raise SourceConfigError(f"source type {type_!r} ({target}) could not be loaded: {e}") from e
    if not (isinstance(cls, type) and issubclass(cls, SourceAdapter)):
        raise SourceConfigError(f"source type {type_!r} ({target}) is not a SourceAdapter")
    return cls


def build(entry: Mapping[str, Any]) -> SourceAdapter:
    """One [[sources]] entry -> a configured adapter."""
    if "type" not in entry:
        raise SourceConfigError("type is required")
    guard = entry.get("guard", True)
    if not isinstance(guard, bool):
        raise SourceConfigError("guard must be true or false")
    name = entry.get("name")
    if name is not None and not (isinstance(name, str) and name):
        raise SourceConfigError("name must be a non-empty string")
    options = {k: v for k, v in entry.items() if k not in RESERVED_KEYS}
    return adapter_class(entry["type"])(name, options, guard)
