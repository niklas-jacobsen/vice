"""Maps Jev's raw outputs to calibrated probabilities, and carries the fitted thresholds.

Fitting (in vice_ai.eval.calibrate) uses scikit-learn. Inference here is plain numpy so
the runtime does not depend on it.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .config import Config
from .paths import DEFAULT_CALIBRATION as CALIBRATION_PATH

_THRESHOLD_KEYS = {"gate_yes", "gate_no", "relevance_min", "surface_min", "conflict_min",
                   "relevance_primitive", "fanout_shape", "top_k", "conflict_variant"}


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


@dataclass
class Calibration:
    gate: dict | None = None  # {"coef": [a, b], "intercept": c} over logits of the two gate Nouls
    relevance: dict | None = None  # isotonic knots {"x": [...], "y": [...]}
    thresholds: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)

    def gate_p(self, p_specific: float, p_needs_detail: float) -> float:
        if not self.gate:
            # Uncalibrated default: both judgments must hold, so the weaker one governs.
            return min(p_specific, p_needs_detail)
        a, b = self.gate["coef"]
        z = a * _logit(p_specific) + b * _logit(p_needs_detail) + self.gate["intercept"]
        return 1.0 / (1.0 + math.exp(-z))

    def relevance_p(self, raw: float) -> float:
        if not self.relevance:
            return raw
        return float(np.interp(raw, self.relevance["x"], self.relevance["y"]))

    def apply(self, cfg: Config) -> Config:
        unknown = set(self.thresholds) - _THRESHOLD_KEYS
        if unknown:
            raise ValueError(f"calibration sets keys it may not: {sorted(unknown)}")
        return cfg.replace(**self.thresholds)

    def save(self, path: Path = CALIBRATION_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.__dict__, indent=2))


def load_calibration(path: Path = CALIBRATION_PATH, model: str | None = None) -> Calibration:
    if not path.exists():
        return Calibration()
    cal = Calibration(**json.loads(path.read_text()))
    fitted_on = cal.meta.get("model")
    if model and fitted_on and fitted_on != model:
        raise ValueError(f"calibration was fitted on {fitted_on} but config pins {model}; re-run calibration")
    return cal
