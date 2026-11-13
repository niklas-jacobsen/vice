"""Persistent notes index. Embeddings are cached by chunk content, so only new or edited
text is embedded again. The cache is disposable: delete ~/.vice/index and it is rebuilt.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import notes, paths
from .config import Config
from .embed import Embedder, make_embedder
from .retrieve import Retriever
from .settings import NotesSource
from .store import make_store


@dataclass
class SyncStats:
    chunks: int
    embedded: int
    reused: int
    seconds: float


class NotesIndex:
    def __init__(self, sources: tuple[NotesSource, ...], cfg: Config, directory: Path | None = None,
                 embedder: Embedder | None = None):
        self.sources, self.cfg = sources, cfg
        self.dir = directory or paths.index_dir()
        self._embedder = embedder
        self.fingerprint: str | None = None

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = make_embedder(self.cfg.embedder)
        return self._embedder

    def _load_cache(self) -> dict[str, np.ndarray]:
        meta, vecs = self.dir / "meta.json", self.dir / "vectors.npy"
        if not (meta.exists() and vecs.exists()):
            return {}
        try:
            m = json.loads(meta.read_text())
            if m.get("embedder") != self.cfg.embedder:
                return {}  # a different model's vectors are not comparable
            arr = np.load(vecs)
            return dict(zip(m["ids"], arr)) if len(m["ids"]) == len(arr) else {}
        except (OSError, ValueError, KeyError):
            return {}

    def _save_cache(self, ids: list[str], vecs: np.ndarray) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / "vectors.tmp.npy"
        np.save(tmp, vecs)
        tmp.replace(self.dir / "vectors.npy")
        (self.dir / "meta.json").write_text(json.dumps({"embedder": self.cfg.embedder, "ids": ids, "saved": time.time()}))

    def changed(self) -> bool:
        return notes.fingerprint(self.sources) != self.fingerprint

    def build(self) -> tuple[Retriever, SyncStats]:
        """Read every source, embed what is new, and return a ready retriever."""
        t0 = time.perf_counter()
        fp = notes.fingerprint(self.sources)
        chunks = notes.load_all(self.sources)
        cache = self._load_cache()
        missing = [c for c in chunks if c.id not in cache]
        if missing:
            for c, v in zip(missing, self.embedder.embed_docs([c.text for c in missing])):
                cache[c.id] = v
        dim = len(next(iter(cache.values()))) if cache else 384
        vecs = np.stack([cache[c.id] for c in chunks]) if chunks else np.zeros((0, dim), dtype=np.float32)
        if missing or len(cache) != len(chunks):
            self._save_cache([c.id for c in chunks], vecs)  # also drops vectors for deleted text
        rt = Retriever(self.embedder, make_store(self.cfg.store), hybrid=self.cfg.hybrid and bool(chunks), rrf_k=self.cfg.rrf_k)
        if chunks:
            rt.index(chunks, vecs)
        else:
            rt.chunks, rt.vecs = [], vecs
        self.embedder.embed_query("warm up")
        self.fingerprint = fp
        return rt, SyncStats(len(chunks), len(missing), len(chunks) - len(missing), time.perf_counter() - t0)
