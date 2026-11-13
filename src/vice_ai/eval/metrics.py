"""Metrics for the harness. Plain numpy; each function is small enough to check by hand."""
from __future__ import annotations

import numpy as np


def pr_curve(labels, scores) -> list[dict]:
    """Precision and recall at every distinct score threshold, highest threshold first."""
    y = np.asarray(labels, dtype=bool)
    s = np.asarray(scores, dtype=float)
    order = np.argsort(-s, kind="stable")
    y, s = y[order], s[order]
    tp = np.cumsum(y)
    fp = np.cumsum(~y)
    last = np.r_[s[1:] != s[:-1], True]  # one point per distinct threshold
    total = max(int(y.sum()), 1)
    return [{"threshold": float(t), "precision": float(a / (a + b)), "recall": float(a / total)}
            for t, a, b in zip(s[last], tp[last], fp[last])]


def average_precision(labels, scores) -> float:
    curve = pr_curve(labels, scores)
    ap, prev_r = 0.0, 0.0
    for pt in curve:
        ap += (pt["recall"] - prev_r) * pt["precision"]
        prev_r = pt["recall"]
    return ap


def threshold_for_precision(labels, scores, min_precision: float) -> dict | None:
    """Lowest threshold (so highest recall) at which precision still meets the floor."""
    ok = [pt for pt in pr_curve(labels, scores) if pt["precision"] >= min_precision]
    return max(ok, key=lambda pt: pt["recall"]) if ok else None


def best_f_beta(labels, scores, beta: float = 1.0) -> dict:
    def f(pt):
        p, r = pt["precision"], pt["recall"]
        return (1 + beta**2) * p * r / (beta**2 * p + r) if p + r else 0.0
    best = max(pr_curve(labels, scores), key=f)
    return {**best, "f_beta": f(best), "beta": beta}


def recall_at_k(ranked_ids: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return float("nan")
    return len(set(ranked_ids[:k]) & relevant) / len(relevant)


def reciprocal_rank(ranked_ids: list[str], relevant: set[str]) -> float:
    for i, cid in enumerate(ranked_ids):
        if cid in relevant:
            return 1.0 / (i + 1)
    return 0.0


def context_precision(packed_ids: list[str], required: set[str]) -> float:
    """Share of the packed context that is actually required. Empty context scores NaN, not 1."""
    if not packed_ids:
        return float("nan")
    return len(set(packed_ids) & required) / len(packed_ids)


def context_recall(packed_ids: list[str], required: set[str]) -> float:
    if not required:
        return float("nan")
    return len(set(packed_ids) & required) / len(required)


def ece(labels, probs, bins: int = 10) -> float:
    """Expected calibration error with equal-width bins."""
    y = np.asarray(labels, dtype=float)
    p = np.asarray(probs, dtype=float)
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    err = 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            err += m.mean() * abs(y[m].mean() - p[m].mean())
    return float(err)


def brier(labels, probs) -> float:
    return float(np.mean((np.asarray(probs, dtype=float) - np.asarray(labels, dtype=float)) ** 2))


def pctl(values, q: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=float), q)) if len(values) else float("nan")


def nanmean(values) -> float:
    a = np.asarray(values, dtype=float)
    return float(np.nanmean(a)) if np.isfinite(a).any() else float("nan")
