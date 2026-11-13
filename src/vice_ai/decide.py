"""The decision, as a truth table. No model is consulted here.

    gate         | packed context       | action
    -------------|----------------------|---------------------------------------------
    unavailable  | (not read)           | SUPPRESS  gate_unavailable   (fail closed)
    no           | (not read)           | SUPPRESS  gate_no
    yes          | fan-out failed       | SUPPRESS  fanout_unavailable
    yes          | empty                | SUPPRESS  no_relevant_context
    yes          | best p >= surface    | SURFACE   strong_match
    yes          | otherwise            | ATTACH    relevant_context
    unsettled    | best p >= surface    | ATTACH    unsettled_gate_strong_match
    unsettled    | otherwise / empty    | SUPPRESS  unsettled_gate_weak_match

An unsettled gate can never SURFACE: when the event's intent is in doubt, the most the
system does is make context quietly available.
"""
from __future__ import annotations

from .config import Config
from .types import Action, Candidate, Decision


def decide(gate_status: str, packed: list[Candidate] | None, cfg: Config) -> Decision:
    if gate_status == "unavailable":
        return Decision(Action.SUPPRESS, "gate_unavailable")
    if gate_status == "no":
        return Decision(Action.SUPPRESS, "gate_no")
    if gate_status not in ("yes", "unsettled"):
        raise ValueError(f"unknown gate status {gate_status!r}")
    if packed is None:
        return Decision(Action.SUPPRESS, "fanout_unavailable")

    best = max((c.p for c in packed), default=0.0)
    context = [c.chunk for c in packed]
    if gate_status == "unsettled":
        if best >= cfg.surface_min:
            return Decision(Action.ATTACH, "unsettled_gate_strong_match", context)
        return Decision(Action.SUPPRESS, "unsettled_gate_weak_match")
    if not packed:
        return Decision(Action.SUPPRESS, "no_relevant_context")
    if best >= cfg.surface_min:
        return Decision(Action.SURFACE, "strong_match", context)
    return Decision(Action.ATTACH, "relevant_context", context)
