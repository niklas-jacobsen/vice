"""Helpers shared by the built-in file adapters."""
from __future__ import annotations

import hashlib
from typing import Any

from .. import paths
from .base import SourceAdapter, SourceConfigError, SourceUnavailable

_enc = None
_unk: int | None = None


def count_tokens(text: str) -> int:
    """Tokens as the embedding model counts them (MiniLM WordPiece, no special tokens).

    Within about 2% of cl100k on notes, and it keeps chunk limits in the same units as
    the model's 256-token window. WordPiece turns any word over 100 characters (a long
    URL, base64, minified code) into one [UNK]; those spans count at 4 characters a
    token so they cannot slip past a budget.
    """
    global _enc, _unk
    if _enc is None:
        from tokenizers import Tokenizer

        from ..embed import minilm_files

        _enc = Tokenizer.from_file(str(minilm_files(only=("tokenizer.json",)) / "tokenizer.json"))
        _enc.no_truncation()
        _enc.no_padding()
        _unk = _enc.token_to_id("[UNK]")
    e = _enc.encode(text, add_special_tokens=False)
    n = len(e.ids)
    for tid, (start, end) in zip(e.ids, e.offsets):
        if tid == _unk and end - start > 4:
            n += -(-(end - start) // 4) - 1
    return n


def legacy_block_id(source: str, text: str) -> str:
    """The id scheme the built-in sources have always used (kept so cached embeddings stay valid)."""
    return hashlib.sha1(f"{source}\0{text}".encode()).hexdigest()[:16]


class PathSource(SourceAdapter):
    """A source backed by one local path."""

    option_keys = frozenset({"path"})

    def configure(self, options: dict[str, Any]) -> None:
        if not isinstance(options.get("path"), str) or not options["path"]:
            raise SourceConfigError(f"type {self.type!r}: path is required")
        self.path = paths.expand(options["path"])

    def default_name(self) -> str:
        return self.path.name

    def describe(self) -> str:
        return f"{self.type} {self.path}"

    def _check(self) -> None:
        if not self.path.exists():
            raise SourceUnavailable(f"{self.path} does not exist")

    def fingerprint(self) -> str:
        self._check()
        return self._fingerprint()

    def load(self):
        self._check()
        return self._load()
