"""Collect Jev's judgments on the calibration split, fit calibrators, choose thresholds.

    python -m ambient.eval.calibrate

Writes config/calibration.json (read by the runtime) and reports/calibration.json (PR
curves and the evidence behind each choice). Only the `cal` split is used; the `test`
split is first touched by ambient.eval.e2e.

How each threshold is chosen (policy lives here, in code, not in Jev):
  gate_yes       lowest gate probability whose precision is >= GATE_PRECISION_FLOOR
  gate_no        highest gate probability that still keeps >= GATE_RECALL_FLOOR of true events above it
  relevance_min  best F1 on cross-validated calibrated relevance
  surface_min    lowest calibrated relevance whose precision is >= SURFACE_PRECISION_FLOOR
  conflict_min   best F1 on conflict pairs
"""
from __future__ import annotations

import asyncio
import json

import numpy as np

from .. import questions as Q
from ..calibrate import Calibration, _logit
from ..config import ROOT, load_config
from ..fanout import conflict_pairs
from ..runtime import build_judge, build_retriever
from .dataset import load, load_facts
from .metrics import average_precision, best_f_beta, brier, ece, pr_curve, threshold_for_precision

REPORT = ROOT / "reports" / "calibration.json"
VARIANTS = ("noul", "score", "choice")
CONFLICT_VARIANTS = ("different_values", "same_fact")
GATE_PRECISION_FLOOR = 0.98
GATE_RECALL_FLOOR = 0.98
SURFACE_PRECISION_FLOOR = 0.95
SHAPE_SUBSET = 40


async def collect(split: str = "cal") -> dict:
    """One gate request and one fan-out request per event. Cached on disk, so reruns are free."""
    cfg = load_config()
    chunks, events = load()
    fact_of = load_facts()
    rt = build_retriever(cfg, chunks)
    judge = build_judge(cfg, cache=True)
    await judge.warm()
    sem = asyncio.Semaphore(8)
    rows = {"gate": [], "rel": [], "conf": [], "shape": [], "tokens": 0}
    evs = [e for e in events if e.split == split]

    async def one(i: int, g):
        ev = g.to_event()
        async with sem:
            gate = await judge.ask(Q.event_state(ev), Q.gate_questions())
            cands = rt.search(ev.text, cfg.top_k)
            pairs = conflict_pairs(cands, rt, cfg)
            # All three relevance wordings in one request over the same state: a fair comparison.
            qs = {Q.relevance_id(c.chunk.id, v): Q.relevance_question(c.chunk, v) for v in VARIANTS for c in cands}
            qs |= {f"{v}:{Q.conflict_id(a.id, b.id)}": Q.conflict_question(a, b, v) for v in CONFLICT_VARIANTS for a, b in pairs}
            fan = await judge.ask(Q.event_state(ev), qs)
            per = None
            if g.warrants_retrieval and i < SHAPE_SUBSET:
                per = await asyncio.gather(*(judge.ask(Q.event_state(ev), {Q.relevance_id(c.chunk.id): Q.relevance_question(c.chunk)}) for c in cands))
        rows["tokens"] += gate.input_tokens + fan.input_tokens + sum(p.input_tokens for p in per or [])
        rows["gate"].append({"event": g.id, "label": g.warrants_retrieval, "kind": g.kind,
                             "specific": gate.answers[Q.GATE_SPECIFIC]["noul"], "needs_detail": gate.answers[Q.GATE_NEEDS_DETAIL]["noul"]})
        rel = set(g.relevant_ids)
        for c in cands:
            row = {"event": g.id, "chunk": c.chunk.id, "label": c.chunk.id in rel, "warrants": g.warrants_retrieval}
            for v in VARIANTS:
                row[v] = Q.relevance_probability(fan.answers[Q.relevance_id(c.chunk.id, v)], v)
            rows["rel"].append(row)
        for a, b in pairs:
            same = fact_of.get(a.id) is not None and fact_of.get(a.id) == fact_of.get(b.id)
            # `both_relevant` marks the pairs the runtime actually acts on: conflict answers
            # are only read when both notes are relevant to the event.
            rows["conf"].append({"event": g.id, "earlier": a.id, "later": b.id, "label": same,
                                 "both_relevant": a.id in rel and b.id in rel,
                                 **{v: fan.answers[f"{v}:{Q.conflict_id(a.id, b.id)}"]["noul"] for v in CONFLICT_VARIANTS}})
        if per:
            for c, p in zip(cands, per):
                rows["shape"].append({"event": g.id, "chunk": c.chunk.id, "label": c.chunk.id in rel,
                                      "per_candidate": p.answers[Q.relevance_id(c.chunk.id)]["noul"],
                                      "single": Q.relevance_probability(fan.answers[Q.relevance_id(c.chunk.id)], "noul")})

    await asyncio.gather(*(one(i, g) for i, g in enumerate(evs)))
    await judge.aclose()
    rows["model"] = cfg.model
    return rows


def _thin(curve: list[dict], n: int = 60) -> list[dict]:
    step = max(1, len(curve) // n)
    return curve[::step] + ([curve[-1]] if (len(curve) - 1) % step else [])


def _mid_gap(scores, threshold: float) -> float:
    """Move a threshold from the lowest accepted score to halfway toward the next score below it."""
    below = [x for x in scores if x < threshold]
    return (threshold + max(below)) / 2 if below else threshold


def fit(rows: dict) -> tuple[Calibration, dict]:
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import GroupKFold, StratifiedKFold

    report: dict = {"model": rows["model"], "input_tokens": rows["tokens"]}

    # ---- gate: logistic regression over the logits of two Nouls ----
    g = rows["gate"]
    X = np.array([[_logit(r["specific"]), _logit(r["needs_detail"])] for r in g])
    y = np.array([r["label"] for r in g])
    lr = LogisticRegression(C=1.0).fit(X, y)
    cv_p = np.zeros(len(y))
    for tr, te in StratifiedKFold(5, shuffle=True, random_state=0).split(X, y):
        cv_p[te] = LogisticRegression(C=1.0).fit(X[tr], y[tr]).predict_proba(X[te])[:, 1]
    naive = np.minimum([r["specific"] for r in g], [r["needs_detail"] for r in g])
    yes_pt = threshold_for_precision(y, cv_p, GATE_PRECISION_FLOOR)
    lo, hi = float(cv_p[~y].max()), float(cv_p[y].min())
    if lo < hi:
        # Perfectly separated: the data cannot say where in the gap the line belongs, so
        # split it in thirds and keep the middle third as the unsettled band.
        gate_no, gate_yes = lo + (hi - lo) / 3, lo + 2 * (hi - lo) / 3
    else:
        gate_yes = yes_pt["threshold"] if yes_pt else 0.99
        pos_sorted = np.sort(cv_p[y])
        gate_no = float(pos_sorted[int(np.floor((1 - GATE_RECALL_FLOOR) * len(pos_sorted)))]) - 1e-6
        gate_no = min(gate_no, gate_yes - 1e-6)
    report["gate"] = {
        "n": len(y), "positives": int(y.sum()),
        "ap": {"specific_only": average_precision(y, [r["specific"] for r in g]),
               "needs_detail_only": average_precision(y, [r["needs_detail"] for r in g]),
               "min_of_both": average_precision(y, naive), "logistic_cv": average_precision(y, cv_p)},
        "ece": {"min_of_both": ece(y, naive), "logistic_cv": ece(y, cv_p)},
        "brier": {"min_of_both": brier(y, naive), "logistic_cv": brier(y, cv_p)},
        "gate_yes": gate_yes, "gate_yes_point": yes_pt, "gate_no": gate_no,
        "highest_negative_p": lo, "lowest_positive_p": hi,
        "unsettled_share": float(np.mean((cv_p > gate_no) & (cv_p < gate_yes))),
        "false_positive_rate_at_yes": float(np.mean(cv_p[~y] >= gate_yes)),
        "by_kind_mean_p": {k: float(np.mean([p for p, r in zip(cv_p, g) if r["kind"] == k])) for k in sorted({r["kind"] for r in g})},
        "pr_curve": _thin(pr_curve(y, cv_p)),
    }

    # ---- relevance: pick the primitive, then isotonic calibration ----
    rel = rows["rel"]
    yr = np.array([r["label"] for r in rel])
    groups = np.array([r["event"] for r in rel])
    report["relevance"] = {"n": len(yr), "positives": int(yr.sum()), "primitives": {}}
    for v in VARIANTS:
        s = np.array([r[v] for r in rel])
        report["relevance"]["primitives"][v] = {"ap": average_precision(yr, s), "ece_raw": ece(yr, s), "brier_raw": brier(yr, s),
                                                "best_f1_raw": best_f_beta(yr, s)}
    primitive = max(VARIANTS, key=lambda v: report["relevance"]["primitives"][v]["ap"])
    raw = np.array([r[primitive] for r in rel])
    cv_r = np.zeros(len(yr))
    for tr, te in GroupKFold(5).split(raw, yr, groups):
        cv_r[te] = IsotonicRegression(y_min=0, y_max=1, out_of_bounds="clip").fit(raw[tr], yr[tr]).predict(raw[te])
    iso = IsotonicRegression(y_min=0, y_max=1, out_of_bounds="clip").fit(raw, yr)
    f1 = best_f_beta(yr, cv_r)
    surf = threshold_for_precision(yr, cv_r, SURFACE_PRECISION_FLOOR)
    relevance_min = f1["threshold"]
    surface_min = max(surf["threshold"] if surf else 0.99, relevance_min)
    report["relevance"] |= {"chosen": primitive, "ece_calibrated_cv": ece(yr, cv_r), "brier_calibrated_cv": brier(yr, cv_r),
                            "relevance_min": relevance_min, "relevance_min_point": f1, "surface_min": surface_min,
                            "surface_point": surf, "pr_curve_raw": _thin(pr_curve(yr, raw)), "pr_curve_calibrated_cv": _thin(pr_curve(yr, cv_r))}

    # ---- fan-out shape: same question, one request vs one request per candidate ----
    sh = rows["shape"]
    shape = "single"
    if sh:
        ys = [r["label"] for r in sh]
        ap = {k: average_precision(ys, [r[k] for r in sh]) for k in ("single", "per_candidate")}
        diff = float(np.mean(np.abs(np.array([r["single"] for r in sh]) - np.array([r["per_candidate"] for r in sh]))))
        # One request is cheaper and one round trip; switch only if isolation is clearly more accurate.
        shape = "per_candidate" if ap["per_candidate"] - ap["single"] > 0.02 else "single"
        report["shape"] = {"n": len(sh), "ap": ap, "mean_abs_probability_difference": diff, "chosen": shape}

    # ---- conflict ----
    cf = rows["conf"]
    conflict_min, conflict_variant = 0.7, "different_values"
    acted = [r for r in cf if r["both_relevant"]]
    if acted and any(r["label"] for r in acted):
        yc = [r["label"] for r in acted]
        ya = [r["label"] for r in cf]
        per = {v: {"ap_pairs_acted_on": average_precision(yc, [r[v] for r in acted]),
                   "ap_all_pairs": average_precision(ya, [r[v] for r in cf]),
                   "ece_pairs_acted_on": ece(yc, [r[v] for r in acted]),
                   "best_f1": best_f_beta(yc, [r[v] for r in acted])} for v in CONFLICT_VARIANTS}
        conflict_variant = max(CONFLICT_VARIANTS, key=lambda v: per[v]["ap_pairs_acted_on"])
        conflict_min = _mid_gap([r[conflict_variant] for r in acted], per[conflict_variant]["best_f1"]["threshold"])
        report["conflict"] = {"n_all_pairs": len(cf), "n_pairs_acted_on": len(acted), "positives_acted_on": int(sum(yc)),
                              "variants": per, "chosen": conflict_variant, "conflict_min": conflict_min,
                              "pr_curve": _thin(pr_curve(yc, [r[conflict_variant] for r in acted]))}

    xs, ys_ = iso.X_thresholds_.tolist(), iso.y_thresholds_.tolist()
    cal = Calibration(
        gate={"coef": lr.coef_[0].tolist(), "intercept": float(lr.intercept_[0])},
        relevance={"x": xs, "y": ys_},
        thresholds={"gate_yes": gate_yes, "gate_no": gate_no, "relevance_min": relevance_min, "surface_min": surface_min,
                    "conflict_min": conflict_min, "conflict_variant": conflict_variant, "relevance_primitive": primitive, "fanout_shape": shape},
        meta={"model": rows["model"], "split": "cal", "n_events": len(g)},
    )
    return cal, report


def main() -> None:
    rows = asyncio.run(collect("cal"))
    cal, report = fit(rows)
    cal.save()
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, default=float))
    print(json.dumps({k: v for k, v in cal.thresholds.items()}, indent=2))
    print("gate AP", report["gate"]["ap"], "| relevance AP", {v: round(d["ap"], 4) for v, d in report["relevance"]["primitives"].items()})
    print(f"input tokens used: {rows['tokens']:,}")


if __name__ == "__main__":
    main()
