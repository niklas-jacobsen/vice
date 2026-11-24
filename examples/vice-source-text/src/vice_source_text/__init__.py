"""Example vice source type: a folder of .txt files, one block per paragraph.

    [[sources]]
    type = "text"
    path = "~/notes"
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from vice_ai.adapters import SourceAdapter, SourceConfigError, SourceUnavailable, block_id
from vice_ai.types import Block


class TextSource(SourceAdapter):
    type = "text"
    option_keys = frozenset({"path"})

    def configure(self, options: dict[str, Any]) -> None:
        path = options.get("path")
        if not isinstance(path, str) or not path:
            raise SourceConfigError("type 'text': path is required")
        self.path = Path(path).expanduser()

    def default_name(self) -> str:
        return self.path.name

    def describe(self) -> str:
        return f"text {self.path}"

    def _files(self) -> list[Path]:
        if not self.path.is_dir():
            raise SourceUnavailable(f"{self.path} is not a folder")
        return sorted(self.path.rglob("*.txt"))

    def fingerprint(self) -> str:
        h = hashlib.sha1()
        for p in self._files():
            st = p.stat()
            h.update(f"{p}|{st.st_mtime_ns}|{st.st_size}\n".encode())
        return h.hexdigest()

    def load(self) -> list[Block]:
        blocks = []
        for p in self._files():
            try:
                raw = p.read_text(encoding="utf-8")
                ts = p.stat().st_mtime
            except (OSError, UnicodeDecodeError):
                continue
            rel = f"{self.name}/{p.relative_to(self.path).as_posix()}"
            for para in (s.strip() for s in raw.split("\n\n")):
                if para:
                    # Tokens are a budget estimate; roughly 4 characters each.
                    blocks.append(Block(block_id(self.name, rel, para), para, ts, len(para) // 4 + 1, rel))
        return blocks

    def indexes(self, path: Path, is_dir: bool) -> bool:
        root = self.path.resolve()
        if is_dir:
            return path == root or root in path.parents
        return path.suffix == ".txt" and root in path.parents
