from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


@dataclass(frozen=True)
class AmbientEvent:
    id: str
    source: str  # "clipboard" | "file_drop" | "palette"
    text: str
    ts: float  # epoch seconds
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Chunk:
    id: str
    text: str
    ts: float  # epoch seconds the note was written
    tokens: int


@dataclass
class Candidate:
    chunk: Chunk
    retrieval_score: float
    raw_p: float | None = None  # Jev's relevance probability, uncalibrated
    p: float | None = None  # calibrated relevance probability
    value: float | None = None  # p after temporal / conflict adjustment
    superseded_by: str | None = None


class Action(str, Enum):
    SUPPRESS = "suppress"  # do nothing; the user never sees anything
    ATTACH = "attach"  # make context available silently to the next action
    SURFACE = "surface"  # proactively show the context


@dataclass
class Decision:
    action: Action
    reason: str
    context: list[Chunk] = field(default_factory=list)


@dataclass
class PipelineResult:
    event: AmbientEvent
    decision: Decision
    gate_p: float | None = None
    gate_status: str | None = None
    candidates: list[Candidate] = field(default_factory=list)
    timings_ms: dict[str, float] = field(default_factory=dict)
    input_tokens: int = 0
