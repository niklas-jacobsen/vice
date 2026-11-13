"""Pipeline behaviour with a scripted judge. These test the code paths, not Jev's accuracy."""
import asyncio
import tempfile
from pathlib import Path

import numpy as np
import pytest

from ambient import questions as Q
from ambient.config import Config
from ambient.conflict import DAY
from ambient.jev import FakeJudge
from ambient.listeners import palette_listener, palette_send, read_dropped_file
from ambient.pipeline import Pipeline
from ambient.retrieve import Retriever
from ambient.store import NumpyStore
from ambient.types import Action, AmbientEvent, Chunk

NOW = 1_800_000_000.0
CHUNKS = [
    Chunk("old", "Atlas launch is set for March 3.", NOW - 200 * DAY, 9),
    Chunk("new", "Atlas launch moved to April 18.", NOW - 3 * DAY, 8),
    Chunk("logo", "Long thread about the Atlas logo.", NOW - 50 * DAY, 8),
    Chunk("run", "Ran 10 km along the canal.", NOW - 9 * DAY, 8),
]


class StubEmbedder:
    """Fixed vectors: the two launch notes are near-identical, the rest are orthogonal."""
    name = "stub"
    vecs = np.array([[1, 0, 0, 0], [0.9, 0.436, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]], dtype=np.float32)

    def embed_docs(self, texts):
        return self.vecs

    def embed_query(self, text):
        return np.array([0.7, 0.5, 0.4, 0.1], dtype=np.float32)


def retriever():
    rt = Retriever(StubEmbedder(), NumpyStore(), hybrid=False)
    rt.index(CHUNKS)
    return rt


def scripted(gate=(0.95, 0.95), relevant=("old", "new"), conflict=0.95, **kw):
    def fn(state, qid, q):
        if qid == Q.GATE_SPECIFIC:
            return {"type": "noul", "noul": gate[0]}
        if qid == Q.GATE_NEEDS_DETAIL:
            return {"type": "noul", "noul": gate[1]}
        if qid.startswith(Q.CONF_PREFIX):
            return {"type": "noul", "noul": conflict}
        return {"type": "noul", "noul": 0.95 if qid.split(".", 2)[2] in relevant else 0.03}
    return FakeJudge(fn, **kw)


def event(text="when does Atlas ship?"):
    return AmbientEvent("e1", "clipboard", text, NOW)


CFG = Config(top_k=4)


async def test_yes_path_surfaces_only_the_current_fact():
    judge = scripted()
    res = await Pipeline(CFG, judge, retriever()).handle(event())
    assert res.decision.action == Action.SURFACE and res.gate_status == "yes"
    assert [c.id for c in res.decision.context] == ["new"]
    assert next(c for c in res.candidates if c.chunk.id == "old").superseded_by == "new"
    # Speculative: gate and fan-out are two requests, and the fan-out carries the conflict question.
    assert len(judge.calls) == 2
    fan = max(judge.calls, key=lambda c: len(c["questions"]))
    assert Q.conflict_id("old", "new") in fan["questions"] and len(fan["questions"]) == 5
    # The note travels inside its own question; state holds only the event.
    assert fan["state"] == Q.event_state(event()) and "April 18" in fan["questions"][Q.relevance_id("new")]["instructions"]["note"]


async def test_gate_no_suppresses_and_never_reads_fanout():
    res = await Pipeline(CFG, scripted(gate=(0.9, 0.05)), retriever()).handle(event("Atlas demo went great today!"))
    assert (res.decision.action, res.decision.reason) == (Action.SUPPRESS, "gate_no")
    assert res.candidates == [] and res.decision.context == []


async def test_slow_gate_fails_closed():
    judge = scripted(delay_s=0.3)
    res = await Pipeline(CFG.replace(gate_timeout_ms=50), judge, retriever()).handle(event())
    assert (res.decision.action, res.decision.reason, res.gate_status) == (Action.SUPPRESS, "gate_unavailable", "unavailable")
    assert res.timings_ms["gate"] < 150


async def test_judge_failure_is_not_treated_as_an_answer():
    res = await Pipeline(CFG, scripted(fail=True), retriever()).handle(event())
    assert res.decision.reason == "gate_unavailable" and res.gate_p is None


async def test_unsettled_gate_attaches_on_strong_match_but_never_surfaces():
    res = await Pipeline(CFG, scripted(gate=(0.5, 0.5)), retriever()).handle(event())
    assert (res.decision.action, res.decision.reason) == (Action.ATTACH, "unsettled_gate_strong_match")
    res = await Pipeline(CFG, scripted(gate=(0.5, 0.5), relevant=()), retriever()).handle(event())
    assert (res.decision.action, res.decision.reason) == (Action.SUPPRESS, "unsettled_gate_weak_match")


async def test_yes_gate_with_nothing_relevant_stays_silent():
    res = await Pipeline(CFG, scripted(relevant=()), retriever()).handle(event())
    assert (res.decision.action, res.decision.reason) == (Action.SUPPRESS, "no_relevant_context")


async def test_pregate_blocks_before_any_request():
    judge = scripted()
    res = await Pipeline(CFG, judge, retriever()).handle(event("xK9$mPq2vL7nRt4wZ8"))
    assert res.decision.reason == "pregate_probable_secret" and judge.calls == []


async def test_relevant_pair_missed_speculatively_gets_a_followup():
    judge = scripted()
    cfg = CFG.replace(conflict_pair_sim=0.999)  # nothing qualifies speculatively
    res = await Pipeline(cfg, judge, retriever()).handle(event())
    assert len(judge.calls) == 3 and [c.id for c in res.decision.context] == ["new"]
    assert "conflict_followup" in res.timings_ms


async def test_per_candidate_shape_gives_the_same_decision():
    judge = scripted()
    res = await Pipeline(CFG.replace(fanout_shape="per_candidate"), judge, retriever()).handle(event())
    assert [c.id for c in res.decision.context] == ["new"]
    assert len(judge.calls) == 1 + 4 + 1  # gate, one per candidate, one for conflicts


@pytest.mark.parametrize("variant,answer", [
    ("score", {"type": "score", "score": 1.9, "confidence": 0.9, "legend": {}, "probabilities": {0: 0.02, 1: 0.06, 2: 0.92}}),
    ("choice", {"type": "choice", "choice": Q.CHOICE_RELEVANT, "confidence": 0.9,
                "probabilities": {Q.CHOICE_RELEVANT: 0.92, "same_subject_other_fact": 0.06, "different_subject": 0.02}}),
])
def test_other_primitives_map_to_one_probability(variant, answer):
    assert Q.relevance_probability(answer, variant) == 0.92
    assert Q.relevance_question(CHUNKS[0], variant).model_dump()["type"] == variant


async def test_palette_round_trip():
    # AF_UNIX paths are capped near 104 bytes on macOS; pytest's tmp_path is longer than that.
    sock = Path(tempfile.mkdtemp(prefix="amb", dir="/tmp")) / "p.sock"

    async def handle(ev):
        return {"action": "attach", "echo": ev.text, "source": ev.source}

    server = asyncio.create_task(palette_listener(handle, sock))
    for _ in range(50):
        if sock.exists():
            break
        await asyncio.sleep(0.01)
    assert await palette_send("when does Atlas ship?", sock) == {"action": "attach", "echo": "when does Atlas ship?", "source": "palette"}
    assert oct(sock.stat().st_mode)[-3:] == "600"
    server.cancel()


def test_dropped_file_reading(tmp_path):
    (tmp_path / "agenda.md").write_text("1. Confirm Atlas launch date\n")
    (tmp_path / "scan.pdf").write_bytes(b"%PDF-1.7\x00\xff")
    assert read_dropped_file(tmp_path / "agenda.md") == "Dropped file: agenda.md\n---\n1. Confirm Atlas launch date"
    assert read_dropped_file(tmp_path / "scan.pdf") == "Dropped file: scan.pdf"
