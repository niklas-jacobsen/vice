"""End-to-end evaluation on the held-out test split, through the real pipeline.

    python -m vice_ai.eval.e2e

Pass 1 calls Jev live, one event at a time, so latency numbers are honest. Answers are
recorded, and the ablations in pass 2 replay them from disk at no cost.
"""
from __future__ import annotations

import asyncio
import json
from collections import Counter

from ..calibrate import load_calibration
from ..config import ROOT, load_config
from ..pipeline import Pipeline
from ..runtime import build_judge, build_retriever
from ..types import Action
from .dataset import load
from .metrics import context_precision, context_recall, nanmean, pctl, recall_at_k

REPORT = ROOT / "reports" / "e2e.json"


def summarise(results, gold) -> dict:
    acted = lambda r: r.decision.action != Action.SUPPRESS
    pos = [(r, g) for r, g in zip(results, gold) if g.warrants_retrieval]
    neg = [(r, g) for r, g in zip(results, gold) if not g.warrants_retrieval]
    packed = lambda r: [c.id for c in r.decision.context]
    stale = [len(set(packed(r)) & (set(g.relevant_ids) - set(g.required_ids))) > 0 for r, g in pos if acted(r)]
    return {
        "events": len(results),
        "intrusion_rate": sum(acted(r) for r, _ in neg) / max(len(neg), 1),  # acted when nothing was warranted
        "intrusions_by_kind": dict(Counter(g.kind for r, g in neg if acted(r))),
        "surface_intrusion_rate": sum(r.decision.action == Action.SURFACE for r, _ in neg) / max(len(neg), 1),
        "miss_rate": sum(not acted(r) for r, _ in pos) / max(len(pos), 1),  # stayed silent when context was needed
        "context_precision": nanmean([context_precision(packed(r), set(g.required_ids)) for r, g in pos if acted(r)]),
        "context_recall": nanmean([context_recall(packed(r), set(g.required_ids)) for r, g in pos]),
        "exact_context_rate": sum(set(packed(r)) == set(g.required_ids) for r, g in pos) / max(len(pos), 1),
        "stale_fact_rate": sum(stale) / max(len(stale), 1),  # a superseded version made it into the context
        "prefilter_recall_required@k": nanmean([recall_at_k([c.block.id for c in r.candidates], set(g.required_ids), 10**6)
                                                for r, g in pos if r.candidates]),
        "actions": dict(Counter(r.decision.action.value for r in results)),
        "reasons": dict(Counter(r.decision.reason for r in results)),
        "mean_context_tokens": nanmean([sum(c.tokens for c in r.decision.context) for r in results if acted(r)]),
    }


def latency(results) -> dict:
    stages = sorted({k for r in results for k in r.timings_ms})
    return {s: {"p50_ms": round(pctl([r.timings_ms[s] for r in results if s in r.timings_ms], 50), 1),
                "p95_ms": round(pctl([r.timings_ms[s] for r in results if s in r.timings_ms], 95), 1),
                "n": sum(s in r.timings_ms for r in results)} for s in stages}


async def run_pass(cfg, cal, rt, gold, judge) -> list:
    pipe = Pipeline(cfg, judge, rt, cal)
    return [await pipe.handle(g.to_event()) for g in gold]


async def main() -> None:
    cfg = load_config()
    cal = load_calibration(model=cfg.model)
    if not cal.gate:
        raise SystemExit("No calibration found. Run: python -m vice_ai.eval.calibrate")
    blocks, events = load()
    gold = [e for e in events if e.split == "test"]
    rt = build_retriever(cal.apply(cfg), blocks)

    live = build_judge(cfg, cache=True, read_cache=False)
    await live.warm()
    results = await run_pass(cfg, cal, rt, gold, live)
    await live.aclose()
    report = {"model": cfg.model, "thresholds": cal.thresholds, "live": summarise(results, gold), "latency": latency(results),
              "input_tokens_per_event": round(sum(r.input_tokens for r in results) / len(results)), "ablations": {}}
    print(json.dumps(report["live"], indent=2), json.dumps(report["latency"], indent=2), sep="\n")

    # Replays. The gate budget is lifted because cached answers return instantly either way,
    # and events whose live gate timed out need a real answer here.
    replay = build_judge(cfg, cache=True)
    base = cfg.replace(gate_timeout_ms=30_000)
    variants = {
        "no_gate_timeout": base,
        "no_conflict_resolution": base.replace(max_conflict_pairs=0),
        "uncalibrated_default_thresholds": None,
        **{f"token_budget_{b}": base.replace(token_budget=b) for b in (30, 60, 120)},
    }
    for name, c in variants.items():
        if c is None:
            from ..calibrate import Calibration
            res = await run_pass(base.replace(relevance_primitive=cal.thresholds["relevance_primitive"]), Calibration(), rt, gold, replay)
        else:
            res = await run_pass(c, cal, rt, gold, replay)
        report["ablations"][name] = summarise(res, gold)
        s = report["ablations"][name]
        print(f"{name:34s} intrusion {s['intrusion_rate']:.3f}  miss {s['miss_rate']:.3f}  ctx-P {s['context_precision']:.3f}  ctx-R {s['context_recall']:.3f}  stale {s['stale_fact_rate']:.3f}")
    await replay.aclose()

    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, default=float))


if __name__ == "__main__":
    asyncio.run(main())
