"""Every word sent to Jev lives in this module.

Each question asks for one judgment a person could make at a glance. None of them asks
Jev what the system should do; `decide.py` holds that logic.
"""
from __future__ import annotations

from typesafe_sdk import Choice, Noul, NoulCriteria, Score

from .types import AmbientEvent, Chunk

# --- State -------------------------------------------------------------------------------

SOURCE_DESCRIPTIONS = {
    "clipboard": "text the user just copied",
    "file_drop": "a file the user just dropped, shown as its name and opening lines",
    "palette": "a command the user just typed",
}


def event_state(event: AmbientEvent) -> dict:
    return {
        "event": {
            "kind": SOURCE_DESCRIPTIONS.get(event.source, event.source),
            "text": event.text,
        }
    }


# --- Gate: two independent judgments, combined in code -----------------------------------

GATE_SPECIFIC = "gate.specific"
GATE_NEEDS_DETAIL = "gate.needs_detail"


def gate_questions() -> dict:
    return {
        GATE_SPECIFIC: Noul(
            instructions=(
                "Does `event.text` name a particular project, person, company, "
                "or personal arrangement?"
            ),
            criteria=NoulCriteria(
                true="It names one, such as a project codename, a colleague, a supplier, or the user's own appointment or booking.",
                false="It names nothing particular: a code snippet, a bare link or number, a general remark, or a passage of public writing.",
            ),
        ),
        GATE_NEEDS_DETAIL: Noul(
            instructions="Does `event.text` ask for, or depend on, a detail that it does not itself state?",
            criteria=NoulCriteria(
                true="It asks a question or sets a task whose answer (a date, name, number, place, setting, or preference) is missing from the text.",
                false="It is complete as written: an acknowledgement, a status remark, small talk, or content that needs nothing looked up.",
            ),
        ),
    }


# --- Relevance: one question per candidate note ------------------------------------------

REL_PREFIX = "rel."
CHOICE_RELEVANT = "states_needed_detail"


def relevance_id(chunk_id: str, variant: str = "noul") -> str:
    return f"{REL_PREFIX}{variant}.{chunk_id}"


def relevance_question(chunk: Chunk, variant: str = "noul"):
    """The note sits in its own question so no question has to look it up in a shared list."""
    if variant == "noul":
        return Noul(
            instructions={
                "question": "Does this note state the detail that `event.text` asks about or depends on?",
                "note": chunk.text,
            },
            criteria=NoulCriteria(
                true="The note states the specific fact needed, such as the date, name, number, or setting in question.",
                false="The note concerns the same project, person, or topic without stating the needed fact, or it concerns something else.",
            ),
        )
    if variant == "score":
        return Score(
            instructions={
                "question": "How well does this note supply the detail that `event.text` asks about or depends on?",
                "note": chunk.text,
            },
            criteria=[
                "The note concerns a different project, person, or topic.",
                "The note concerns the same project, person, or topic but does not state the needed fact.",
                "The note states the specific fact needed.",
            ],
        )
    if variant == "choice":
        return Choice(
            instructions={
                "question": "How does this note relate to what `event.text` asks about or depends on?",
                "note": chunk.text,
            },
            criteria={
                CHOICE_RELEVANT: "The note states the specific fact needed.",
                "same_subject_other_fact": "The note concerns the same project, person, or topic but states some other fact.",
                "different_subject": "The note concerns a different project, person, or topic.",
            },
        )
    raise ValueError(f"unknown relevance variant: {variant}")


def relevance_probability(answer: dict, variant: str) -> float:
    """Map any primitive's answer to one number in [0, 1]. Arithmetic stays in code."""
    if variant == "noul":
        return float(answer["noul"])
    if variant == "score":
        # Probability mass on the top level, read from the distribution rather than the
        # blended position, which can hide a two-peaked answer.
        probs = answer["probabilities"]
        return float(probs.get(2, probs.get("2", 0.0)))
    if variant == "choice":
        return float(answer["probabilities"].get(CHOICE_RELEVANT, 0.0))
    raise ValueError(variant)


# --- Conflict: do two notes disagree about the same fact? --------------------------------
# Jev is weak at comparing dates, so it is never asked which note is newer. Code knows.

CONF_PREFIX = "conf."


def conflict_id(earlier_id: str, later_id: str) -> str:
    return f"{CONF_PREFIX}{earlier_id}|{later_id}"


def parse_conflict_id(qid: str) -> tuple[str, str]:
    earlier, later = qid[len(CONF_PREFIX):].split("|", 1)
    return earlier, later


def conflict_question(earlier: Chunk, later: Chunk, variant: str = "different_values") -> Noul:
    """Two candidate wordings; calibration picks one on the calibration split.

    "same_fact" asks a single judgment and leaves the rest to code: if two notes record the
    same attribute of the same thing, the newer one stands, whether or not the values differ.
    "different_values" asks for sameness and disagreement in one question.
    """
    if variant == "same_fact":
        return Noul(
            instructions={
                "question": "Do these two notes record the same kind of fact about the same thing?",
                "earlier_note": earlier.text,
                "later_note": later.text,
            },
            criteria=NoulCriteria(
                true="Both notes are about one attribute of one subject, such as one project's launch date or one person's manager, whether or not they agree.",
                false="The notes concern different subjects, or different attributes of the same subject.",
            ),
        )
    if variant != "different_values":
        raise ValueError(f"unknown conflict variant: {variant}")
    return Noul(
        instructions={
            "question": "Do these two notes give different values for the same fact?",
            "earlier_note": earlier.text,
            "later_note": later.text,
        },
        criteria=NoulCriteria(
            true="Both notes describe the same attribute of the same thing, such as one project's launch date, and the values differ.",
            false="The notes describe different things or different attributes, or they give the same value.",
        ),
    )
