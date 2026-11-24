"""Legacy loader entry points over `settings.Source`. Thin shims over `vice_ai.adapters`;
they will be removed once callers use adapters directly."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterator

from .adapters._common import count_tokens  # noqa: F401
from .adapters.base import SourceAdapter
from .adapters.jsonl import JsonlSource
from .adapters.markdown import (ALWAYS_EXCLUDE, MAX_FILE_BYTES, MAX_TOKENS, OBSIDIAN_EXCLUDE,  # noqa: F401
                                TARGET_TOKENS, MarkdownSource, ObsidianSource, clean_obsidian,
                                note_timestamp, split_markdown)
from .adapters._common import legacy_block_id as _block_id  # noqa: F401
from .settings import Source
from .types import Block

_TYPES = {"markdown": MarkdownSource, "obsidian": ObsidianSource, "jsonl": JsonlSource}


def _adapter(src: Source) -> SourceAdapter:
    opts = {"path": "x"} | ({"exclude": list(src.exclude)} if src.type != "jsonl" else {})
    a = _TYPES[src.type](src.name, opts, src.guard)
    a.path = src.path
    return a


def iter_files(src: Source) -> Iterator[Path]:
    a = _adapter(src)
    if src.type == "jsonl":
        return iter([src.path] if src.path.is_file() else [])
    return a.iter_files()


def fingerprint(sources: tuple[Source, ...]) -> str:
    h = hashlib.sha1()
    for src in sources:
        for p in iter_files(src):
            try:
                st = p.stat()
            except OSError:
                continue
            h.update(f"{p}|{st.st_mtime_ns}|{st.st_size}\n".encode())
    return h.hexdigest()


def indexes_file(src: Source, path: Path) -> bool:
    return _adapter(src).indexes(path, False)


def indexes_dir(src: Source, path: Path) -> bool:
    return _adapter(src).indexes(path, True)


def load_source(src: Source) -> list[Block]:
    return _adapter(src)._load()


def load_all(sources: tuple[Source, ...]) -> list[Block]:
    seen: dict[str, Block] = {}
    for src in sources:
        if not src.path.exists():
            raise FileNotFoundError(f"source {src.name!r}: {src.path} does not exist")
        for c in load_source(src):
            seen.setdefault(c.id, c)  # identical text in the same file collapses to one block
    return list(seen.values())
