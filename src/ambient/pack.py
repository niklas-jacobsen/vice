"""0/1 knapsack over the token budget.

Value is each note's adjusted relevance probability, so the packed set maximises the
expected number of relevant notes that fit. Exact dynamic programme; with K <= ~20
candidates and budgets of a few thousand tokens it runs in well under a millisecond.
"""
from __future__ import annotations

from .config import Config
from .types import Candidate


def knapsack(values: list[float], weights: list[int], budget: int) -> list[int]:
    n = len(values)
    if n == 0 or budget <= 0:
        return []
    best = [[0.0] * (budget + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        v, w = values[i - 1], weights[i - 1]
        row, prev = best[i], best[i - 1]
        for b in range(budget + 1):
            row[b] = prev[b]
            if w <= b and prev[b - w] + v > row[b]:
                row[b] = prev[b - w] + v
    chosen, b = [], budget
    for i in range(n, 0, -1):
        if best[i][b] != best[i - 1][b]:
            chosen.append(i - 1)
            b -= weights[i - 1]
    return chosen[::-1]


def pack(cands: list[Candidate], cfg: Config) -> list[Candidate]:
    # Eligibility is judged on the calibrated probability, the scale the threshold was fitted on.
    # `value` (probability after temporal adjustment) only ranks notes competing for the budget.
    eligible = [c for c in cands if c.p is not None and c.p >= cfg.relevance_min and not c.superseded_by]
    idx = knapsack([c.value for c in eligible], [max(1, c.chunk.tokens) for c in eligible], cfg.token_budget)
    return sorted((eligible[i] for i in idx), key=lambda c: -c.value)
