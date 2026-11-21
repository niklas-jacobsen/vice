"""Event-driven interceptor pipeline.

    event -> pre-gate (code) -> [ Noul gate  ||  pre-filter -> speculative fan-out ]
          -> calibrate -> conflict resolution -> knapsack -> decision (code)

The gate and the fan-out run concurrently. If the gate says no, the fan-out is cancelled
and its answers are never read.
"""
from __future__ import annotations

import asyncio
import time

from .calibrate import Calibration
from .config import Config
from .conflict import resolve
from .decide import decide
from .fanout import FanoutOutcome, conflict_pairs, run_conflict_followup, run_fanout
from .gate import run_gate
from .jev import Judge, JudgeError
from .pack import pack
from .pregate import PreGate
from .retrieve import Retriever
from .tracing import tracer
from .types import Action, AmbientEvent, Decision, PipelineResult


class Pipeline:
    def __init__(self, cfg: Config, judge: Judge, retriever: Retriever, cal: Calibration | None = None):
        self.cal = cal or Calibration()
        self.cfg = self.cal.apply(cfg)
        self.judge, self.retriever = judge, retriever
        self.pregate = PreGate(self.cfg)

    async def _retrieve_and_fan_out(self, event: AmbientEvent, timings: dict):
        t0 = time.perf_counter()
        with tracer.start_as_current_span("prefilter"):
            # Embedding is CPU work; keep it off the event loop so the gate request goes out at once.
            cands = await asyncio.to_thread(self.retriever.search, event.text, self.cfg.top_k)
            pairs = conflict_pairs(cands, self.retriever, self.cfg)
        timings["prefilter"] = (time.perf_counter() - t0) * 1000
        fan = await run_fanout(self.judge, event, cands, pairs, self.cfg)
        timings["fanout"] = fan.latency_ms
        return cands, fan

    async def handle(self, raw_event: AmbientEvent, now: float | None = None) -> PipelineResult:
        t_start = time.perf_counter()
        timings: dict[str, float] = {}
        with tracer.start_as_current_span("pipeline") as span:
            span.set_attribute("event.trigger", raw_event.trigger)
            res = await self._handle(raw_event, now if now is not None else raw_event.ts, timings)
            timings["total"] = (time.perf_counter() - t_start) * 1000
            res.timings_ms = timings
            span.set_attribute("decision.action", res.decision.action.value)
            span.set_attribute("decision.reason", res.decision.reason)
            span.set_attribute("decision.blocks", len(res.decision.context))
            return res

    async def _handle(self, raw_event: AmbientEvent, now: float, timings: dict) -> PipelineResult:
        t0 = time.perf_counter()
        pre = self.pregate.check(raw_event)
        timings["pregate"] = (time.perf_counter() - t0) * 1000
        if not pre.ok:
            return PipelineResult(raw_event, Decision(Action.SUPPRESS, f"pregate_{pre.reason}"))
        event = pre.event

        gate_task = asyncio.create_task(run_gate(self.judge, event, self.cfg, self.cal))
        fan_task = asyncio.create_task(self._retrieve_and_fan_out(event, timings))

        gate = await gate_task
        timings["gate"] = gate.latency_ms
        result = PipelineResult(event, Decision(Action.SUPPRESS, "pending"), gate.p, gate.status,
                                input_tokens=gate.input_tokens)

        if gate.status in ("no", "unavailable"):
            fan_task.cancel()
            await asyncio.gather(fan_task, return_exceptions=True)
            result.decision = decide(gate.status, None, self.cfg)
            return result

        try:
            cands, fan = await fan_task
        except JudgeError:
            result.decision = decide(gate.status, None, self.cfg)
            return result

        t0 = time.perf_counter()
        result.input_tokens += fan.input_tokens
        result.candidates = cands
        self._score(cands, fan)
        try:
            result.input_tokens += await self._check_missing_conflicts(event, cands, fan, timings)
        except JudgeError:
            # Without the comparison a stale fact could be shown as current; stay silent instead.
            result.decision = decide(gate.status, None, self.cfg)
            return result
        t0 = time.perf_counter()
        resolve(cands, fan.conflicts, self.cfg, now)
        packed = pack(cands, self.cfg)
        result.decision = decide(gate.status, packed, self.cfg)
        timings["resolve_pack_decide"] = (time.perf_counter() - t0) * 1000
        return result

    async def _check_missing_conflicts(self, event, cands, fan: FanoutOutcome, timings: dict) -> int:
        if self.cfg.max_conflict_pairs <= 0:  # conflict checking switched off
            return 0
        relevant = sorted((c.block for c in cands if c.p >= self.cfg.relevance_min), key=lambda ch: ch.ts)
        missing = [(a, b) for i, a in enumerate(relevant) for b in relevant[i + 1:]
                   if a.ts != b.ts and (a.id, b.id) not in fan.conflicts]
        if not missing:
            return 0
        t0 = time.perf_counter()
        extra, tokens = await run_conflict_followup(self.judge, event, missing, self.cfg)
        fan.conflicts.update(extra)
        timings["conflict_followup"] = (time.perf_counter() - t0) * 1000
        return tokens

    def _score(self, cands, fan: FanoutOutcome) -> None:
        for c in cands:
            if c.block.id not in fan.relevance:
                raise JudgeError(f"fan-out returned no relevance answer for {c.block.id}")
            c.raw_p = fan.relevance[c.block.id]
            c.p = self.cal.relevance_p(c.raw_p)
