"""The Noul gate: two small judgments about the event, banded by code."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from . import questions as Q
from .calibrate import Calibration
from .config import Config
from .jev import Judge, JudgeError
from .tracing import tracer
from .types import AmbientEvent


@dataclass
class GateOutcome:
    status: str  # "yes" | "no" | "unsettled" | "unavailable"
    p: float | None
    raw: dict
    latency_ms: float
    input_tokens: int = 0
    error: str | None = None


def band(p: float, cfg: Config) -> str:
    if p >= cfg.gate_yes:
        return "yes"
    if p <= cfg.gate_no:
        return "no"
    return "unsettled"


async def run_gate(judge: Judge, event: AmbientEvent, cfg: Config, cal: Calibration) -> GateOutcome:
    budget_s = cfg.gate_timeout_ms / 1000
    t0 = time.perf_counter()
    with tracer.start_as_current_span("gate") as span:
        try:
            res = await asyncio.wait_for(
                judge.ask(Q.event_state(event), Q.gate_questions(), timeout_s=budget_s), timeout=budget_s
            )
        except (JudgeError, asyncio.TimeoutError) as e:
            ms = (time.perf_counter() - t0) * 1000
            span.set_attribute("gate.status", "unavailable")
            # Not a "no": a distinct status with its own row in the decision table.
            return GateOutcome("unavailable", None, {}, ms, error=type(e).__name__ + (f": {e}" if str(e) else ""))
        raw = {k: res.answers[k]["noul"] for k in (Q.GATE_SPECIFIC, Q.GATE_NEEDS_DETAIL)}
        p = cal.gate_p(raw[Q.GATE_SPECIFIC], raw[Q.GATE_NEEDS_DETAIL])
        status = band(p, cfg)
        span.set_attribute("gate.status", status)
        span.set_attribute("gate.p", p)
        return GateOutcome(status, p, raw, (time.perf_counter() - t0) * 1000, res.input_tokens)
