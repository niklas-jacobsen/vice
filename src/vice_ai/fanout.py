"""Speculative fan-out: every judgment the later stages might need, asked at once.

Relevance of each candidate and conflict between similar candidates are requested together,
before the gate has answered. Code reads the answers only if the gate lets the event through.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from . import questions as Q
from .config import Config
from .jev import Judge
from .retrieve import Retriever
from .tracing import tracer
from .types import AmbientEvent, Candidate, Chunk


@dataclass
class FanoutOutcome:
    relevance: dict[str, float] = field(default_factory=dict)  # chunk id -> raw probability
    conflicts: dict[tuple[str, str], float] = field(default_factory=dict)  # (earlier id, later id) -> probability
    latency_ms: float = 0.0
    input_tokens: int = 0
    requests: int = 0


def conflict_pairs(cands: list[Candidate], retriever: Retriever, cfg: Config) -> list[tuple[Chunk, Chunk]]:
    """Pairs worth a conflict check: similar enough to be about the same fact, written at different times."""
    scored = []
    for i, a in enumerate(cands):
        for b in cands[i + 1:]:
            if a.chunk.ts == b.chunk.ts:
                continue
            sim = retriever.similarity(a.chunk, b.chunk)
            if sim >= cfg.conflict_pair_sim:
                earlier, later = sorted((a.chunk, b.chunk), key=lambda c: c.ts)
                scored.append((sim, earlier, later))
    scored.sort(key=lambda t: -t[0])
    return [(e, l) for _, e, l in scored[: cfg.max_conflict_pairs]]


async def run_conflict_followup(judge: Judge, event: AmbientEvent, pairs: list[tuple[Chunk, Chunk]],
                                cfg: Config) -> tuple[dict[tuple[str, str], float], int]:
    """Second request, used only when two relevant notes were not compared speculatively."""
    with tracer.start_as_current_span("conflict_followup") as span:
        span.set_attribute("conflict.pairs", len(pairs))
        res = await judge.ask(Q.event_state(event), {Q.conflict_id(e.id, l.id): Q.conflict_question(e, l, cfg.conflict_variant) for e, l in pairs},
                              timeout_s=cfg.request_timeout_s)
    return {Q.parse_conflict_id(k): float(a["noul"]) for k, a in res.answers.items()}, res.input_tokens


async def run_fanout(judge: Judge, event: AmbientEvent, cands: list[Candidate],
                     pairs: list[tuple[Chunk, Chunk]], cfg: Config) -> FanoutOutcome:
    variant = cfg.relevance_primitive
    state = Q.event_state(event)
    rel_qs = {Q.relevance_id(c.chunk.id, variant): Q.relevance_question(c.chunk, variant) for c in cands}
    conf_qs = {Q.conflict_id(e.id, l.id): Q.conflict_question(e, l, cfg.conflict_variant) for e, l in pairs}

    if cfg.fanout_shape == "single":
        batches = [{**rel_qs, **conf_qs}]
    elif cfg.fanout_shape == "per_candidate":
        batches = [{k: q} for k, q in rel_qs.items()] + ([conf_qs] if conf_qs else [])
    else:
        raise ValueError(cfg.fanout_shape)

    out = FanoutOutcome(requests=len(batches))
    t0 = time.perf_counter()
    with tracer.start_as_current_span("fanout") as span:
        span.set_attribute("fanout.candidates", len(cands))
        span.set_attribute("fanout.conflict_pairs", len(pairs))
        span.set_attribute("fanout.requests", len(batches))
        # A failure in any request propagates: a partial fan-out is not silently accepted.
        results = await asyncio.gather(*(judge.ask(state, b, timeout_s=cfg.request_timeout_s) for b in batches if b))
    out.latency_ms = (time.perf_counter() - t0) * 1000
    for res in results:
        out.input_tokens += res.input_tokens
        for qid, ans in res.answers.items():
            if qid.startswith(Q.CONF_PREFIX):
                out.conflicts[Q.parse_conflict_id(qid)] = float(ans["noul"])
            else:
                chunk_id = qid.split(".", 2)[2]
                out.relevance[chunk_id] = Q.relevance_probability(ans, variant)
    return out
