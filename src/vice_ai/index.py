"""Persistent index of blocks. Embeddings are cached by block content, so only new or edited
text is embedded again. The cache is disposable: delete ~/.vice/index and it is rebuilt.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import paths
from .config import Config
from .embed import Embedder, make_embedder
from .retrieve import Retriever
from .adapters.base import SourceAdapter, SourceUnavailable
from .store import make_store


@dataclass
class SyncStats:
    blocks: int
    embedded: int
    reused: int
    seconds: float
    skipped: tuple[tuple[str, str], ...] = ()  # (source name, why it was left out)

    def skipped_lines(self) -> list[str]:
        return [f"skipped source {n}: {m}" for n, m in self.skipped]


class Index:
    def __init__(self, sources: tuple[SourceAdapter, ...], cfg: Config, directory: Path | None = None,
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

    def _fingerprint(self) -> str:
        h = hashlib.sha1()
        for src in self.sources:
            try:
                part = src.fingerprint()
            except SourceUnavailable:
                part = "unavailable"  # a source coming back changes the fingerprint, so it is picked up
            h.update(f"{src.name}\0{part}\n".encode())
        return h.hexdigest()

    def changed(self) -> bool:
        return self._fingerprint() != self.fingerprint

    def build(self) -> tuple[Retriever, SyncStats]:
        """Read every source, embed what is new, and return a ready retriever."""
        t0 = time.perf_counter()
        fp = self._fingerprint()
        blocks, skipped = [], []
        for src in self.sources:
            try:
                blocks += src.load()
            except SourceUnavailable as e:
                skipped.append((src.name, str(e)))
        cache = self._load_cache()
        missing = [c for c in blocks if c.id not in cache]
        if missing:
            for c, v in zip(missing, self.embedder.embed_docs([c.text for c in missing])):
                cache[c.id] = v
        dim = len(next(iter(cache.values()))) if cache else 384
        vecs = np.stack([cache[c.id] for c in blocks]) if blocks else np.zeros((0, dim), dtype=np.float32)
        if missing or len(cache) != len(blocks):
            self._save_cache([c.id for c in blocks], vecs)  # also drops vectors for deleted text
        rt = Retriever(self.embedder, make_store(self.cfg.store), hybrid=self.cfg.hybrid and bool(blocks), rrf_k=self.cfg.rrf_k)
        if blocks:
            rt.index(blocks, vecs)
        else:
            rt.blocks, rt.vecs = [], vecs
        self.embedder.embed_query("warm up")
        self.fingerprint = fp
        return rt, SyncStats(len(blocks), len(missing), len(blocks) - len(missing), time.perf_counter() - t0, tuple(skipped))
