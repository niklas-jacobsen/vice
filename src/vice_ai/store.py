"""Interchangeable local vector stores. All take unit-normalised vectors and return cosine scores."""
from __future__ import annotations

import sqlite3
import tempfile
from typing import Protocol

import numpy as np


class VectorStore(Protocol):
    name: str

    def build(self, vecs: np.ndarray) -> None: ...
    def search(self, q: np.ndarray, k: int) -> list[tuple[int, float]]: ...  # (row index, cosine)


class NumpyStore:
    name = "numpy"

    def build(self, vecs):
        self._m = np.ascontiguousarray(vecs, dtype=np.float32)

    def search(self, q, k):
        s = self._m @ q
        k = min(k, len(s))
        idx = np.argpartition(-s, k - 1)[:k]
        idx = idx[np.argsort(-s[idx])]
        return [(int(i), float(s[i])) for i in idx]


class SqliteVecStore:
    name = "sqlite-vec"

    def build(self, vecs):
        import sqlite_vec

        self._db = sqlite3.connect(":memory:", check_same_thread=False)
        self._db.enable_load_extension(True)
        sqlite_vec.load(self._db)
        self._db.execute(f"create virtual table v using vec0(e float[{vecs.shape[1]}] distance_metric=cosine)")
        self._db.executemany("insert into v(rowid, e) values (?, ?)",
                             [(i, v.astype(np.float32).tobytes()) for i, v in enumerate(vecs)])

    def search(self, q, k):
        rows = self._db.execute("select rowid, distance from v where e match ? and k = ? order by distance",
                                (q.astype(np.float32).tobytes(), k)).fetchall()
        return [(int(i), 1.0 - float(d)) for i, d in rows]


class LanceStore:
    name = "lancedb"

    def build(self, vecs):
        import lancedb
        import pyarrow as pa

        self._dir = tempfile.mkdtemp(prefix="vice-lance-")
        tbl = pa.table({"idx": pa.array(range(len(vecs)), pa.int32()),
                        "vector": pa.FixedSizeListArray.from_arrays(pa.array(vecs.ravel(), pa.float32()), vecs.shape[1])})
        self._t = lancedb.connect(self._dir).create_table("v", tbl)

    def search(self, q, k):
        rows = self._t.search(q).metric("cosine").limit(k).to_list()
        return [(int(r["idx"]), 1.0 - float(r["_distance"])) for r in rows]


class HnswStore:
    name = "hnswlib"

    def build(self, vecs):
        import hnswlib

        self._i = hnswlib.Index(space="cosine", dim=vecs.shape[1])
        self._i.init_index(max_elements=len(vecs), ef_construction=200, M=16)
        self._i.add_items(vecs, np.arange(len(vecs)))
        self._i.set_ef(100)

    def search(self, q, k):
        ids, dist = self._i.knn_query(q, k=min(k, self._i.get_current_count()))
        return [(int(i), 1.0 - float(d)) for i, d in zip(ids[0], dist[0])]


STORES = {"numpy": NumpyStore, "sqlite-vec": SqliteVecStore, "lancedb": LanceStore, "hnswlib": HnswStore}


def make_store(name: str) -> VectorStore:
    return STORES[name]()
