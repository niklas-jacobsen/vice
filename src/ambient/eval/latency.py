"""Measure Jev round-trip latency from this machine. Answers the sub-100ms question with data.

    python -m ambient.eval.latency

Sends about 250 small requests (calibration-split events only). Nothing is cached.
"""
from __future__ import annotations

import asyncio
import json
import time

from .. import questions as Q
from ..config import ROOT, load_config
from ..fanout import conflict_pairs, run_fanout
from ..runtime import build_judge, build_retriever
from .dataset import load
from .metrics import pctl

REPORT = ROOT / "reports" / "latency.json"


def _summary(ms: list[float]) -> dict:
    return {"n": len(ms), "p50_ms": round(pctl(ms, 50), 1), "p95_ms": round(pctl(ms, 95), 1),
            "min_ms": round(min(ms), 1), "max_ms": round(max(ms), 1),
            "share_under_100ms": round(sum(m < 100 for m in ms) / len(ms), 3)}


async def run() -> dict:
    cfg = load_config()
    chunks, events = load()
    cal = [e for e in events if e.split == "cal"]
    out: dict = {"model": cfg.model, "gate": {}, "fanout": {}}

    for http2 in (True, False):
        c = cfg.replace(http2=http2)
        # Cold: a fresh client per request pays DNS, TCP and TLS every time.
        cold = []
        for e in cal[:6]:
            j = build_judge(c)
            t0 = time.perf_counter()
            await j.ask(Q.event_state(e.to_event()), Q.gate_questions())
            cold.append((time.perf_counter() - t0) * 1000)
            await j.aclose()
        j = build_judge(c)
        await j.warm()
        warm = []
        for e in cal[:60]:
            res = await j.ask(Q.event_state(e.to_event()), Q.gate_questions())
            warm.append(res.latency_ms)
        await j.aclose()
        key = "http2" if http2 else "http1.1"
        out["gate"][key] = {"cold": _summary(cold), "warm": _summary(warm)}
        print("gate", key, out["gate"][key], flush=True)

    rt = build_retriever(cfg, chunks)
    pos = [e for e in cal if e.warrants_retrieval][:15]
    for shape in ("single", "per_candidate"):
        for k in (4, 8, 12, 20):
            c = cfg.replace(fanout_shape=shape, top_k=k)
            j = build_judge(c)
            await j.warm()
            ms, toks = [], []
            for e in pos:
                ev = e.to_event()
                cands = rt.search(ev.text, k)
                fan = await run_fanout(j, ev, cands, conflict_pairs(cands, rt, c), c)
                ms.append(fan.latency_ms)
                toks.append(fan.input_tokens)
            await j.aclose()
            out["fanout"][f"{shape}_k{k}"] = {**_summary(ms), "mean_input_tokens": round(sum(toks) / len(toks))}
            print("fanout", shape, k, out["fanout"][f"{shape}_k{k}"], flush=True)

    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    asyncio.run(run())
