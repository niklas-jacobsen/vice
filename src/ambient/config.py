"""All tunable numbers live here or in config/pipeline.toml. Nothing else hard-codes a threshold."""
from __future__ import annotations

import dataclasses
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "pipeline.toml"
CALIBRATION_PATH = ROOT / "config" / "calibration.json"


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

    # Noul gate. Starting values are TypeSafe's documented 0.7 / 0.3; calibration overrides.
    gate_yes: float = 0.7
    gate_no: float = 0.3
    gate_timeout_ms: float = 100.0
    gate_on_timeout: str = "suppress"  # fail closed: a slow gate never causes an intrusion

    # Pre-filter
    embedder: str = "bge-small"
    store: str = "numpy"
    hybrid: bool = True
    top_k: int = 12
    rrf_k: int = 60

    # Fan-out
    fanout_shape: str = "single"  # "single" = one request, K questions; "per_candidate" = K requests
    relevance_primitive: str = "noul"  # "noul" | "score" | "choice"
    relevance_min: float = 0.5
    # Speculative conflict checks: candidate pairs at least this similar. Measured on the
    # calibration split, 0.5 catches ~88% of same-fact pairs at ~36 extra questions per event.
    # Relevant pairs it misses get a follow-up request (pipeline._check_missing_conflicts).
    conflict_pair_sim: float = 0.5
    max_conflict_pairs: int = 40
    conflict_min: float = 0.7

    # Temporal logic
    conflict_half_life_days: float = 14.0  # how fast a contradicted older fact loses value
    recency_half_life_days: float = 365.0
    recency_weight: float = 0.1  # mild global tie-breaker toward newer notes

    # Packing and decision
    token_budget: int = 400
    surface_min: float = 0.85

    def replace(self, **kw) -> "Config":
        return dataclasses.replace(self, **kw)


def load_config(path: Path | None = None) -> Config:
    path = path or CONFIG_PATH
    data = tomllib.loads(path.read_text()) if path.exists() else {}
    known = {f.name for f in dataclasses.fields(Config)}
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"unknown config keys in {path}: {sorted(unknown)}")
    return Config(**data)


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env loader so the API key never needs to be exported or pasted into chat."""
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
