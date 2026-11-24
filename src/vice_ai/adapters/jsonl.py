"""A JSONL file: one block per line, `{"text": ..., "ts": ...}` plus optional id, tokens, source."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..types import Block
from ._common import PathSource, count_tokens, legacy_block_id


class JsonlSource(PathSource):
    type = "jsonl"

    def _fingerprint(self) -> str:
        h = hashlib.sha1()
        if self.path.is_file():
            try:
                st = self.path.stat()
                h.update(f"{self.path}|{st.st_mtime_ns}|{st.st_size}\n".encode())
            except OSError:
                pass
        return h.hexdigest()

    def _load(self) -> list[Block]:
        blocks: list[Block] = []
        for n, line in enumerate(self.path.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            d = json.loads(line)
            text = str(d["text"])
            blocks.append(Block(str(d.get("id") or legacy_block_id(self.name, text)), text, float(d["ts"]),
                                int(d.get("tokens") or count_tokens(text)), d.get("source") or f"{self.name}:{n + 1}"))
        return blocks

    def indexes(self, path: Path, is_dir: bool) -> bool:
        return not is_dir and path == self.path.resolve()
