"""Experiment: which local embedding model, vector store, and fusion gives the best Top-K?

No network calls to Jev. Uses only the calibration split so the test split stays unseen.

    python -m vice_ai.eval.prefilter
"""
from __future__ import annotations

import json
import time

import numpy as np

from ..config import ROOT
from ..embed import FASTEMBED_MODELS, STATIC_MODELS, make_embedder
from ..retrieve import Retriever
from ..store import STORES, make_store
from .dataset import load
from .metrics import nanmean, pctl, recall_at_k, reciprocal_rank

KS = (5, 8, 12, 20)
REPORT = ROOT / "reports" / "prefilter.json"


def run() -> dict:
    chunks, events = load()
    pos = [e for e in events if e.warrants_retrieval and e.split == "cal"]
    texts = [c.text for c in chunks]
    out: dict = {"n_chunks": len(chunks), "n_events": len(pos), "embedders": [], "stores": []}

    best_vecs = {}
    for name in [*FASTEMBED_MODELS, *STATIC_MODELS]:
        t0 = time.perf_counter()
        emb = make_embedder(name)
        load_s = time.perf_counter() - t0
        t0 = time.perf_counter()
        vecs = emb.embed_docs(texts)
        index_s = time.perf_counter() - t0
        best_vecs[name] = vecs
        emb.embed_query("warm up")
        q_ms = []
        for e in pos[:60]:
            t0 = time.perf_counter()
            emb.embed_query(e.text)
            q_ms.append((time.perf_counter() - t0) * 1000)
        for hybrid in (False, True):
            rt = Retriever(emb, make_store("numpy"), hybrid=hybrid)
            rt.index(chunks, vecs)
            row = {"embedder": name, "hybrid": hybrid, "dim": int(vecs.shape[1]), "load_s": round(load_s, 2),
                   "index_docs_per_s": round(len(texts) / index_s), "embed_query_p50_ms": round(pctl(q_ms, 50), 2),
                   "embed_query_p95_ms": round(pctl(q_ms, 95), 2)}
            ranked = {e.id: [c.chunk.id for c in rt.search(e.text, max(KS))] for e in pos}
            for k in KS:
                row[f"recall_required@{k}"] = round(nanmean([recall_at_k(ranked[e.id], set(e.required_ids), k) for e in pos]), 4)
            row["recall_relevant@12"] = round(nanmean([recall_at_k(ranked[e.id], set(e.relevant_ids), 12) for e in pos]), 4)
            row["mrr"] = round(nanmean([reciprocal_rank(ranked[e.id], set(e.required_ids)) for e in pos]), 4)
            t0 = time.perf_counter()
            for e in pos[:60]:
                rt.search(e.text, 12)
            row["search_total_ms_mean"] = round((time.perf_counter() - t0) * 1000 / 60, 2)
            out["embedders"].append(row)
            print(row, flush=True)

    # Vector stores: same vectors, scaled up with jittered copies to see how each behaves as memory grows.
    base = best_vecs["bge-small"]
    rng = np.random.default_rng(0)
    for n in (len(base), 20_000, 100_000):
        reps = int(np.ceil(n / len(base)))
        big = np.concatenate([base] + [base + rng.normal(0, 0.05, base.shape).astype(np.float32) for _ in range(reps - 1)])[:n]
        big /= np.linalg.norm(big, axis=1, keepdims=True)
        queries = big[rng.choice(len(base), 200)] + rng.normal(0, 0.02, (200, base.shape[1])).astype(np.float32)
        queries /= np.linalg.norm(queries, axis=1, keepdims=True)
        exact = make_store("numpy")
        exact.build(big)
        truth = [{i for i, _ in exact.search(q, 12)} for q in queries]
        for sname in STORES:
            st = make_store(sname)
            t0 = time.perf_counter()
            try:
                st.build(big)
            except Exception as e:  # noqa: BLE001 - record the store as unusable here rather than hide it
                out["stores"].append({"store": sname, "n": n, "error": f"{type(e).__name__}: {e}"})
                print(out["stores"][-1], flush=True)
                continue
            build_s = time.perf_counter() - t0
            ms, overlap = [], []
            for q, tr in zip(queries, truth):
                t0 = time.perf_counter()
                got = st.search(q, 12)
                ms.append((time.perf_counter() - t0) * 1000)
                overlap.append(len({i for i, _ in got} & tr) / 12)
            row = {"store": sname, "n": n, "build_s": round(build_s, 3), "query_p50_ms": round(pctl(ms, 50), 3),
                   "query_p95_ms": round(pctl(ms, 95), 3), "recall_vs_exact@12": round(float(np.mean(overlap)), 4)}
            out["stores"].append(row)
            print(row, flush=True)

    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    run()
