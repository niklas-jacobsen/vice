"""The contract every source type implements.

A source adapter turns one kind of source (a Markdown folder, a JSONL export, a chat
workspace, an issue tracker...) into `Block`s. Each `[[sources]]` entry in config.toml
becomes one adapter instance:

    [[sources]]
    type = "obsidian"          # selects the adapter class
    name = "vault"             # optional; unique label, defaults to `default_name()`
    guard = true               # optional; see `indexes()`
    path = "~/Documents/Vault" # everything else is the adapter's own options
    exclude = ["Templates/**"]

vice never inspects an adapter's options; the adapter validates them in `configure()`.
Adapters are registered under the `vice.sources` entry point group (see `registry.py`), so
a separate package can add a source type without changing vice.
"""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar, Mapping

from ..types import Block

RESERVED_KEYS = frozenset({"type", "name", "guard"})


class SourceConfigError(ValueError):
    """The `[[sources]]` entry is invalid. Raised at configuration time; vice refuses to start."""


class SourceUnavailable(Exception):
    """The source cannot be read right now (missing folder, network, credentials). vice skips
    this source, logs the message, and keeps serving the others."""


def block_id(source_name: str, locator: str, text: str) -> str:
    """A stable id for a block: the same text at the same place always gets the same id, so
    its embedding is reused across syncs."""
    return hashlib.sha1(f"{source_name}\0{locator}\0{text}".encode()).hexdigest()[:16]


class SourceAdapter(ABC):
    """One configured source. Subclass once per source type."""

    type: ClassVar[str]  # the `type` value in [[sources]]
    option_keys: ClassVar[frozenset[str]] = frozenset()  # allowed keys besides type, name, guard

    def __init__(self, name: str | None, options: Mapping[str, Any], guard: bool = True):
        extra = set(options) - self.option_keys
        if extra:
            raise SourceConfigError(f"unknown key(s) {sorted(extra)} for type {self.type!r}; "
                                    f"allowed: {sorted(self.option_keys | RESERVED_KEYS)}")
        self.guard = guard
        self.configure(dict(options))
        self.name = name or self.default_name()
        if not self.name:
            raise SourceConfigError(f"type {self.type!r} needs a name = \"...\"")

    # --- required -----------------------------------------------------------------------

    @abstractmethod
    def configure(self, options: dict[str, Any]) -> None:
        """Validate and store the adapter's own options. Raise SourceConfigError on bad input.
        Must not do I/O that can fail transiently; that belongs in `load()`."""

    @abstractmethod
    def fingerprint(self) -> str:
        """A cheap value that changes whenever `load()` would return different blocks. Called
        every resync interval, so it should cost far less than `load()`. Raise SourceUnavailable
        if the source cannot be checked."""

    @abstractmethod
    def load(self) -> list[Block]:
        """Every block this source currently provides. Block ids must be stable (see
        `block_id`) and unique within the source; `Block.source` should let a person find the
        original. Raise SourceUnavailable if the source cannot be read."""

    # --- optional -----------------------------------------------------------------------

    def default_name(self) -> str | None:
        """The name used when [[sources]] gives none. Return None to require one."""
        return None

    def describe(self) -> str:
        """One line for `vice status`, after the name."""
        return self.type

    def indexes(self, path: Path, is_dir: bool) -> bool:
        """For the read guard: True if `path` (absolute, resolved) is a file this source
        indexes, or, when `is_dir`, a directory whose indexed files a search would read.
        Sources that are not local files keep the default."""
        return False
