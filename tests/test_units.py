import itertools
import random

import pytest

from ambient.calibrate import Calibration
from ambient.config import Config
from ambient.conflict import DAY, resolve
from ambient.decide import decide
from ambient.eval import metrics as M
from ambient.pack import knapsack, pack
from ambient.pregate import PreGate, redact
from ambient.types import Action, AmbientEvent, Candidate, Chunk

CFG = Config()
NOW = 1_800_000_000.0


def cand(cid, p, age_days=1.0, tokens=10):
    c = Candidate(Chunk(cid, f"note {cid}", NOW - age_days * DAY, tokens), 0.0)
    c.raw_p = c.p = p
    return c


# --- pre-gate ---

def ev(text, ts=NOW, i=[0]):
    i[0] += 1
    return AmbientEvent(f"t{i[0]}", "clipboard", text, ts)


@pytest.mark.parametrize("text,reason", [
    ("ok", "too_short"), ("#ff8800", "too_short"), ("12:30 - 14:45", "non_linguistic"), ("1,234.50 + 99", "non_linguistic"),
    ("xK9$mPq2vL7nRt4wZ8", "probable_secret"), ("password: hunter2hunter2", "secret_only"),
])
def test_pregate_rejects(text, reason):
    out = PreGate(CFG).check(ev(text))
    assert not out.ok and out.reason == reason


def test_pregate_masks_embedded_secrets_and_passes_the_rest():
    out = PreGate(CFG).check(ev("deploy Atlas with AKIAIOSFODNN7EXAMPLE then ping Priya about the launch date"))
    assert out.ok and "AKIA" not in out.event.text and "launch date" in out.event.text and out.redactions == 1


def test_redact_card_needs_luhn():
    assert redact("card 4242 4242 4242 4242 thanks")[1] == 1
    assert redact("order 1234 5678 9012 3456 thanks")[1] == 0


def test_pregate_dedupes_within_window_only():
    g = PreGate(CFG)
    assert g.check(ev("when does Atlas ship?", NOW)).ok
    assert g.check(ev("when does Atlas ship?", NOW + 5)).reason == "duplicate"
    assert g.check(ev("when does Atlas ship?", NOW + CFG.dedupe_window_s + 6)).ok


def test_pregate_urls_reach_the_gate():
    assert PreGate(CFG).check(ev("https://staging.atlas.example.dev/login")).ok


# --- knapsack ---

def test_knapsack_matches_brute_force():
    r = random.Random(0)
    for _ in range(200):
        n = r.randint(0, 9)
        vals = [r.random() for _ in range(n)]
        wts = [r.randint(1, 30) for _ in range(n)]
        budget = r.randint(0, 80)
        best = max((sum(vals[i] for i in s) for k in range(n + 1) for s in itertools.combinations(range(n), k)
                    if sum(wts[i] for i in s) <= budget), default=0.0)
        got = knapsack(vals, wts, budget)
        assert sum(wts[i] for i in got) <= budget
        assert sum(vals[i] for i in got) == pytest.approx(best)


def test_pack_beats_greedy_by_value_and_skips_ineligible():
    # Greedy-by-value takes the 0.9 note (60 tokens) and nothing else; two 0.8 notes fit and are worth more.
    cs = [cand("big", 0.9, tokens=60), cand("a", 0.8, tokens=30), cand("b", 0.8, tokens=30), cand("low", 0.2, tokens=1)]
    for c in cs:
        c.value = c.p
    cs.append(cand("old", 0.9, tokens=1)); cs[-1].value = 0.9; cs[-1].superseded_by = "a"
    assert {c.chunk.id for c in pack(cs, CFG.replace(token_budget=60))} == {"a", "b"}


# --- conflict resolution ---

def test_newer_fact_supersedes_older_after_long_gap():
    old, new = cand("old", 0.95, age_days=120), cand("new", 0.95, age_days=2)
    resolve([old, new], {("old", "new"): 0.97}, CFG, NOW)
    assert old.superseded_by == "new" and old.value < CFG.relevance_min
    assert new.superseded_by is None and new.value > 0.9


def test_same_day_disagreement_keeps_both():
    a, b = cand("a", 0.95, age_days=2.0), cand("b", 0.95, age_days=1.9)
    resolve([a, b], {("a", "b"): 0.97}, CFG, NOW)
    assert a.superseded_by is None and a.value > CFG.relevance_min


def test_no_supersession_without_confirmed_conflict_or_relevant_successor():
    old, new = cand("old", 0.95, age_days=120), cand("new", 0.95, age_days=2)
    resolve([old, new], {("old", "new"): 0.2}, CFG, NOW)
    assert old.superseded_by is None
    old, weak = cand("old", 0.95, age_days=120), cand("weak", 0.1, age_days=2)
    resolve([old, weak], {("old", "weak"): 0.99}, CFG, NOW)
    assert old.superseded_by is None  # an irrelevant note cannot knock out a relevant one


def test_three_versions_only_newest_survives():
    v1, v2, v3 = cand("v1", 0.9, 300), cand("v2", 0.9, 150), cand("v3", 0.9, 5)
    resolve([v1, v2, v3], {("v1", "v2"): 0.9, ("v2", "v3"): 0.9, ("v1", "v3"): 0.9}, CFG, NOW)
    assert [c.chunk.id for c in pack([v1, v2, v3], CFG)] == ["v3"]


# --- decision truth table: every row ---

@pytest.mark.parametrize("gate,values,action,reason", [
    ("unavailable", [0.99], Action.SUPPRESS, "gate_unavailable"),
    ("no", [0.99], Action.SUPPRESS, "gate_no"),
    ("yes", None, Action.SUPPRESS, "fanout_unavailable"),
    ("yes", [], Action.SUPPRESS, "no_relevant_context"),
    ("yes", [0.9], Action.SURFACE, "strong_match"),
    ("yes", [0.6], Action.ATTACH, "relevant_context"),
    ("unsettled", [0.9], Action.ATTACH, "unsettled_gate_strong_match"),
    ("unsettled", [0.6], Action.SUPPRESS, "unsettled_gate_weak_match"),
    ("unsettled", [], Action.SUPPRESS, "unsettled_gate_weak_match"),
    ("unsettled", None, Action.SUPPRESS, "fanout_unavailable"),
])
def test_decision_table(gate, values, action, reason):
    packed = None
    if values is not None:
        packed = [cand(f"c{i}", v) for i, v in enumerate(values)]
        for c in packed:
            c.value = c.p
    d = decide(gate, None if gate in ("no", "unavailable") else packed, CFG)
    assert (d.action, d.reason) == (action, reason)
    assert bool(d.context) == (action != Action.SUPPRESS)


def test_decide_rejects_unknown_gate_status():
    with pytest.raises(ValueError):
        decide("maybe", [], CFG)


# --- calibration ---

def test_calibration_identity_and_fitted():
    c = Calibration()
    assert c.gate_p(0.9, 0.4) == 0.4 and c.relevance_p(0.3) == 0.3
    c = Calibration(gate={"coef": [1.0, 1.0], "intercept": 0.0}, relevance={"x": [0.0, 0.5, 1.0], "y": [0.0, 0.1, 1.0]},
                    thresholds={"gate_yes": 0.9})
    assert c.gate_p(0.5, 0.5) == pytest.approx(0.5) and c.gate_p(0.9, 0.9) > 0.98
    assert c.relevance_p(0.25) == pytest.approx(0.05)
    assert c.apply(CFG).gate_yes == 0.9
    with pytest.raises(ValueError):
        Calibration(thresholds={"token_budget": 1}).apply(CFG)


# --- metrics ---

def test_metrics_by_hand():
    y, s = [1, 0, 1, 0], [0.9, 0.8, 0.7, 0.1]
    curve = M.pr_curve(y, s)
    assert curve[0] == {"threshold": 0.9, "precision": 1.0, "recall": 0.5}
    assert curve[2]["precision"] == pytest.approx(2 / 3) and curve[2]["recall"] == 1.0
    assert M.average_precision(y, s) == pytest.approx(0.5 * 1.0 + 0.5 * 2 / 3)
    assert M.threshold_for_precision(y, s, 0.99)["threshold"] == 0.9
    assert M.recall_at_k(["a", "b", "c"], {"b", "z"}, 2) == 0.5
    assert M.context_precision(["a", "b"], {"a"}) == 0.5 and M.context_recall(["a"], {"a", "b"}) == 0.5
    assert M.ece([1, 1, 0, 0], [1.0, 1.0, 0.0, 0.0]) == 0.0
    assert M.ece([1, 0], [0.5, 0.5]) == 0.0 and M.ece([0, 0], [0.95, 0.95]) == pytest.approx(0.95)
