"""Local pre-filter: dense search, optionally fused with BM25 by reciprocal rank."""
from __future__ import annotations

import numpy as np

from .embed import Embedder
from .store import VectorStore
from .types import Candidate, Block


class Retriever:
    def __init__(self, embedder: Embedder, store: VectorStore, hybrid: bool = True, rrf_k: int = 60):
        self.embedder, self.store, self.hybrid, self.rrf_k = embedder, store, hybrid, rrf_k
        self.blocks: list[Block] = []
        self.vecs: np.ndarray | None = None
        self._bm25 = None

    def index(self, blocks: list[Block], vecs: np.ndarray | None = None) -> None:
        self.blocks = blocks
        self.vecs = vecs if vecs is not None else self.embedder.embed_docs([c.text for c in blocks])
        self.store.build(self.vecs)
        if self.hybrid:
            import bm25s

            self._bm25 = bm25s.BM25()
            self._bm25.index(bm25s.tokenize([c.text for c in blocks], stopwords="en", show_progress=False), show_progress=False)

    def search(self, text: str, k: int) -> list[Candidate]:
        if not self.blocks:
            return []
        q = self.embedder.embed_query(text)
        depth = k * 3 if self.hybrid else k
        dense = self.store.search(q, depth)
        if not self.hybrid:
            return [Candidate(self.blocks[i], s) for i, s in dense[:k]]

        import bm25s

        n = min(depth, len(self.blocks))
        ids, _ = self._bm25.retrieve(bm25s.tokenize([text], stopwords="en", show_progress=False), k=n, show_progress=False)
        fused: dict[int, float] = {}
        for rank, (i, _) in enumerate(dense):
            fused[i] = fused.get(i, 0.0) + 1.0 / (self.rrf_k + rank + 1)
        for rank, i in enumerate(ids[0]):
            fused[int(i)] = fused.get(int(i), 0.0) + 1.0 / (self.rrf_k + rank + 1)
        top = sorted(fused.items(), key=lambda kv: -kv[1])[:k]
        return [Candidate(self.blocks[i], s) for i, s in top]

    def similarity(self, a: Block, b: Block) -> float:
        ia, ib = self._row(a), self._row(b)
        return float(self.vecs[ia] @ self.vecs[ib])

    def _row(self, c: Block) -> int:
        if not hasattr(self, "_rows") or len(self._rows) != len(self.blocks):
            self._rows = {ch.id: i for i, ch in enumerate(self.blocks)}
        return self._rows[c.id]
