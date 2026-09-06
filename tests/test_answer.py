"""Applying the human's answer, and the pause that collects it.

Two things are tested here and they fail in different ways:

- `recall.answer` is pure arithmetic. If it is wrong, the system resolves to the
  wrong person while sounding confident.
- The `interrupt()` round-trip is graph machinery. If it is wrong, the demo
  hangs or silently skips the question, which is visible immediately.
"""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from recall.answer import CONFIDENT, resolve_with_answer
from recall.eig import Hypothesis, Question
from recall.nodes.ask import ask_node
from recall.state import RecallState, is_interactive

KIT, CRI = "p_kit", "p_cri"
HYPS = [Hypothesis(KIT, "Kit Yee", 0.47),
        Hypothesis(CRI, "Crispy", 0.47),
        Hypothesis("", "someone new", 0.06)]
COURSE = Question(
    key="course", text="What do they study at NUS?",
    outcomes={KIT: "geospatial intelligence", CRI: "computer science"},
    answer_space=("computer science", "geospatial intelligence", "something else"),
    noise=0.05,
)


def test_the_answer_picks_the_hypothesis_that_predicted_it():
    assert resolve_with_answer(HYPS, COURSE, "computer science").record_id == CRI
    assert resolve_with_answer(HYPS, COURSE, "geospatial intelligence").record_id == KIT


def test_an_answer_nobody_predicted_argues_for_someone_new():
    """The answer the closed-answer-space version could not express. It is a real
    outcome, not a failure -- it is how a stranger avoids being merged into an
    acquaintance."""
    r = resolve_with_answer(HYPS, COURSE, "something else")
    assert r.record_id == ""
    assert r.name == "someone new"
    # It wins on a 0.06 prior, so it must NOT come back sounding settled.
    assert not r.confident


def test_confidence_is_reported_not_implied():
    """One answer does not always settle a three-way tie. A UI that asserts an
    identity at 46% belief is lying in exactly the way the band exists to stop."""
    settled = resolve_with_answer(HYPS, COURSE, "computer science")
    unsettled = resolve_with_answer(HYPS, COURSE, "something else")
    assert settled.confident and settled.confidence >= CONFIDENT
    assert not unsettled.confident and unsettled.confidence < CONFIDENT


def test_the_posterior_sums_to_one_and_covers_every_hypothesis():
    r = resolve_with_answer(HYPS, COURSE, "computer science")
    assert set(r.posterior) == {KIT, CRI, ""}
    assert sum(r.posterior.values()) == pytest.approx(1.0, abs=1e-3)


def test_bits_remaining_falls_when_the_answer_settles_it():
    settled = resolve_with_answer(HYPS, COURSE, "computer science")
    unsettled = resolve_with_answer(HYPS, COURSE, "something else")
    assert settled.bits_remaining < unsettled.bits_remaining


def test_resolution_is_deterministic():
    """A demo that resolves to a different person on the second run of the same
    input is unusable."""
    a = resolve_with_answer(HYPS, COURSE, "computer science")
    b = resolve_with_answer(HYPS, COURSE, "computer science")
    assert (a.record_id, a.confidence) == (b.record_id, b.confidence)


def test_no_hypotheses_resolves_to_nothing_rather_than_guessing():
    assert resolve_with_answer([], COURSE, "computer science") is None


# --------------------------------------------------------------------------
# The pause itself.
# --------------------------------------------------------------------------


def test_is_interactive_defaults_to_false():
    """Every non-web caller -- CLI, eval, tests -- must take the non-pausing
    path without having to say so. `interrupt()` without a checkpointer raises."""
    assert not is_interactive(None)
    assert not is_interactive({})
    assert not is_interactive({"configurable": {}})
    assert is_interactive({"configurable": {"interactive": True}})


def _entry(records):
    return {
        "person": {"name": "the malaysian girl"},
        "hypotheses": [{"record_id": KIT, "name": "Kit Yee", "score": 3.5, "explain": ""},
                       {"record_id": CRI, "name": "Crispy", "score": 3.5, "explain": ""},
                       {"record_id": "", "name": "someone new", "score": 0.0, "explain": ""}],
        "resolved_to": None,
    }


@pytest.fixture
def asking_graph(monkeypatch, tmp_path):
    records = {
        KIT: {"id": KIT, "name": "Kit Yee", "met_at": [],
              "notes": ["lives at the 18th floor", "studies geospatial intelligence at NUS"]},
        CRI: {"id": CRI, "name": "Crispy", "met_at": [],
              "notes": ["lives on the 4th floor", "studies computer science at NUS"]},
    }
    monkeypatch.setattr("recall.nodes.ask.get_store",
                        lambda: type("S", (), {"get": staticmethod(records.get)})())
    g = StateGraph(RecallState)
    g.add_node("ask", ask_node)
    g.add_edge(START, "ask")
    g.add_edge("ask", END)
    return g.compile(checkpointer=InMemorySaver())


INTERACTIVE = {"configurable": {"thread_id": "t", "interactive": True}}


def test_the_graph_stops_and_surfaces_the_question(asking_graph):
    state = {"ambiguous": [_entry(None)], "new_people": [], "known_matches": []}
    chunks = list(asking_graph.stream(state, config=INTERACTIVE, stream_mode="updates"))

    paused = [c for c in chunks if "__interrupt__" in c]
    assert paused, "the graph must stop, not run past the question"
    payload = paused[0]["__interrupt__"][0].value
    assert payload["question"] == "What do they study at NUS?"
    assert "something else" in payload["answers"]


def test_the_answer_resolves_the_mention_into_a_known_match(asking_graph):
    state = {"ambiguous": [_entry(None)], "new_people": [], "known_matches": []}
    list(asking_graph.stream(state, config=INTERACTIVE, stream_mode="updates"))

    out = list(asking_graph.stream(Command(resume="computer science"),
                                   config=INTERACTIVE, stream_mode="updates"))
    update = out[0]["ask"]
    assert update["resolution"]["record_id"] == CRI
    assert [m["record_id"] for m in update["known_matches"]] == [CRI]
    assert update["known_matches"][0]["person"]["name"] == "Crispy"
    assert "the malaysian girl" in update["known_matches"][0]["person"]["aliases"]
    assert update["new_people"] == []


def test_something_else_files_the_mention_as_a_new_person(asking_graph):
    state = {"ambiguous": [_entry(None)], "new_people": [], "known_matches": []}
    list(asking_graph.stream(state, config=INTERACTIVE, stream_mode="updates"))

    out = list(asking_graph.stream(Command(resume="something else"),
                                   config=INTERACTIVE, stream_mode="updates"))
    update = out[0]["ask"]
    assert update["resolution"]["record_id"] == ""
    assert [p["name"] for p in update["new_people"]] == ["the malaysian girl"]
    assert update["known_matches"] == []


def test_without_the_interactive_flag_nothing_pauses(asking_graph):
    """The CLI and the eval harness run this same node. If it paused for them
    they would hang, or raise for want of a checkpointer."""
    state = {"ambiguous": [_entry(None)], "new_people": [], "known_matches": []}
    chunks = list(asking_graph.stream(state, config={"configurable": {"thread_id": "q"}},
                                      stream_mode="updates"))

    assert not any("__interrupt__" in c for c in chunks)
    update = chunks[0]["ask"]
    assert update["question"]["question"] == "What do they study at NUS?"
    # It selected, it did not place -- dedupe already did that on this path.
    assert "resolution" not in update
