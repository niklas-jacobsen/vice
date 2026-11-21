"""Temporal logic. Jev says whether two blocks disagree; code decides which one wins.

When two relevant blocks give different values for the same fact, the older one's value
decays with the time between them:

    value_older = p_older * 0.5 ** (gap_days / conflict_half_life_days)

So a block contradicted the same afternoon keeps most of its value (the disagreement is
probably live and both are worth showing), while one contradicted months later falls
below the relevance floor and is dropped as superseded.
"""
from __future__ import annotations

from .config import Config
from .types import Candidate

DAY = 86400.0


def resolve(cands: list[Candidate], conflicts: dict[tuple[str, str], float], cfg: Config, now: float) -> list[Candidate]:
    by_id = {c.block.id: c for c in cands}

    for c in cands:
        age_days = max(0.0, (now - c.block.ts) / DAY)
        recency = 0.5 ** (age_days / cfg.recency_half_life_days)
        c.value = c.p * ((1 - cfg.recency_weight) + cfg.recency_weight * recency)
        c.superseded_by = None

    # Longest gap first, so each older block is discounted by its most decisive contradiction.
    confirmed = [(e, l) for (e, l), p in conflicts.items()
                 if p >= cfg.conflict_min and e in by_id and l in by_id]
    for earlier_id, later_id in sorted(confirmed, key=lambda pr: by_id[pr[0]].block.ts - by_id[pr[1]].block.ts):
        earlier, later = by_id[earlier_id], by_id[later_id]
        # Only a block that is itself relevant can supersede another.
        if later.p < cfg.relevance_min or earlier.superseded_by:
            continue
        gap_days = (later.block.ts - earlier.block.ts) / DAY
        decayed = earlier.p * 0.5 ** (gap_days / cfg.conflict_half_life_days)
        if decayed < earlier.value:
            earlier.value = decayed
            if decayed < cfg.relevance_min:
                earlier.superseded_by = later_id
    return cands
