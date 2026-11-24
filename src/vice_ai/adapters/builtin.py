"""Built-in source types. Temporary: these wrap the loaders in `sources.py` until that logic
moves into the adapters themselves."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import paths
from .. import sources as legacy
from ..settings import Source as LegacySource
from ..types import Block
from .base import SourceAdapter, SourceConfigError, SourceUnavailable


class _PathSource(SourceAdapter):
    option_keys = frozenset({"path", "exclude"})

    def configure(self, options: dict[str, Any]) -> None:
        if not isinstance(options.get("path"), str) or not options["path"]:
            raise SourceConfigError(f"type {self.type!r}: path is required")
        exclude = options.get("exclude", [])
        if not (isinstance(exclude, list) and all(isinstance(p, str) for p in exclude)):
            raise SourceConfigError(f"type {self.type!r}: exclude must be a list of glob patterns")
        self.path = paths.expand(options["path"])
        self.exclude = tuple(exclude)

    def default_name(self) -> str:
        return self.path.name

    def describe(self) -> str:
        return f"{self.type} {self.path}"

    def _legacy(self) -> LegacySource:
        return LegacySource(self.type, self.path, self.name, self.exclude, self.guard)

    def _check(self) -> None:
        if not self.path.exists():
            raise SourceUnavailable(f"{self.path} does not exist")

    def fingerprint(self) -> str:
        self._check()
        return legacy.fingerprint((self._legacy(),))

    def load(self) -> list[Block]:
        self._check()
        return legacy.load_source(self._legacy())

    def indexes(self, path: Path, is_dir: bool) -> bool:
        src = self._legacy()
        src = LegacySource(src.type, src.path.resolve(), src.name, src.exclude, src.guard)
        return legacy.indexes_dir(src, path) if is_dir else legacy.indexes_file(src, path)


class MarkdownSource(_PathSource):
    type = "markdown"


class ObsidianSource(_PathSource):
    type = "obsidian"


class JsonlSource(_PathSource):
    type = "jsonl"
    option_keys = frozenset({"path"})
