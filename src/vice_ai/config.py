"""Pipeline tunables. Nothing else hard-codes a threshold.

Users override these under [pipeline] in ~/.vice/config.toml (see settings.py). Thresholds
fitted by calibration live in calibration JSON and take precedence over both.
"""
from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass
from pathlib import Path

# Repository root. Only the evaluation harness uses it (golden data, reports); an installed
# copy of vice never reads from here.
ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Config:
    # Jev. Pinned: the `jev-latest` alias moves and would invalidate calibration.
    model: str = "jev-1.14.0"
    http2: bool = True
    keepalive_s: float = 300.0  # SDK default is 30s; ambient events are sparse
    request_timeout_s: float = 5.0

    # Pre-gate (pure code)
    min_chars: int = 8
    max_chars: int = 2000
    dedupe_window_s: float = 60.0

    # Noul gate. 0.7 / 0.3 are TypeSafe's documented starting values; calibration overrides.
    gate_yes: float = 0.7
    gate_no: float = 0.3
    # The design target was 100 ms. Measured (reports/latency.json): a warm gate request
    # takes 162 ms p50 / 195 ms p95 and never came in under 134 ms, so 100 ms would
    # suppress every event. 300 ms covers the observed tail.
    gate_timeout_ms: float = 300.0

    # Pre-filter. Chosen by `python -m vice_ai.eval.prefilter` (reports/prefilter.json).
    embedder: str = "minilm"
    store: str = "numpy"
    hybrid: bool = True
    top_k: int = 20
    rrf_k: int = 60

    # Fan-out
    fanout_shape: str = "single"  # "single" = one request, K questions; "per_candidate" = K requests
    relevance_primitive: str = "noul"  # "noul" | "score" | "choice"
    relevance_min: float = 0.5
    # Speculative conflict checks: candidate pairs at least this similar. On the calibration
    # split 0.5 catches ~88% of same-fact pairs at ~36 extra questions per event.
    # Tried 0.4 / cap 80: the bigger request was slower (fan-out p50 206 -> 250 ms) and did not
    # lower end-to-end p95, so 0.5 stays.
    # Relevant pairs not compared speculatively get a follow-up request
    # (pipeline._check_missing_conflicts); that second round trip is what sets p95.
    conflict_pair_sim: float = 0.5
    max_conflict_pairs: int = 40
    conflict_min: float = 0.7
    conflict_variant: str = "different_values"  # or "same_fact"; see questions.conflict_question

    # Temporal logic
    conflict_half_life_days: float = 14.0  # how fast a contradicted older fact loses value
    recency_half_life_days: float = 365.0
    recency_weight: float = 0.1  # mild global tie-breaker toward newer blocks

    # Packing and decision
    token_budget: int = 400
    surface_min: float = 0.85

    def replace(self, **kw) -> "Config":
        return dataclasses.replace(self, **kw)

    @classmethod
    def from_overrides(cls, data: dict, where: str = "[pipeline]") -> "Config":
        known = {f.name: f.type for f in dataclasses.fields(cls)}
        unknown = set(data) - set(known)
        if unknown:
            raise ValueError(f"unknown keys in {where}: {sorted(unknown)}")
        return cls(**data)


def load_config() -> Config:
    """Defaults only. Used by the evaluation harness so results do not depend on a user's settings."""
    return Config()


def load_dotenv(path: Path | None = None) -> None:
    """Development convenience: read TYPESAFE_API_KEY from a .env in the repository."""
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
