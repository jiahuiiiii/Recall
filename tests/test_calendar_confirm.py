"""The calendar confirmation gate.

Two properties carry the feature, and only one of them is about parsing:

1. **Nothing reaches the calendar before the human answers.** `interrupt()`
   re-executes the node from the top on resume, so an effect placed above it
   runs twice and, worse, runs at all for an event that is then declined.
2. **Non-interactive runs are unchanged.** The CLI, the eval harness and every
   other test write without stopping; a gate that pauses them would hang the
   benchmark rather than fail it.
"""

from __future__ import annotations

import json

import pytest

from recall.nodes.calendar import approved_indices, calendar_node
from recall.tools.calendar import propose_event

COMMITMENTS = [
    {"person_name": "Wei Lin", "what": "send the Kestrel repo",
     "due": "2026-09-09", "channel": "email"},
    {"person_name": "Marcus", "what": "share the supper club list",
     "due": "2026-09-11", "channel": "whatsapp"},
]

INTERACTIVE = {"configurable": {"interactive": True}}


@pytest.fixture(autouse=True)
def ledger(tmp_path, monkeypatch):
    """Point the ledger at a scratch file. Never the user's own calendar."""
    path = tmp_path / "calendar.json"
    monkeypatch.setenv("RECALL_CALENDAR_PATH", str(path))
    monkeypatch.setenv("RECALL_CALENDAR", "local")
    monkeypatch.setattr("recall.tools.calendar.LEDGER_PATH", path)
    return path


def written(path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text()).get("events", [])


# ---- the parser ----------------------------------------------------------

@pytest.mark.parametrize(
    "reply,expected",
    [
        ("all", {0, 1, 2}), ("yes", {0, 1, 2}), ("Y", {0, 1, 2}), ("*", {0, 1, 2}),
        ("none", set()), ("no", set()), ("skip", set()), ("", set()),
        ("0,2", {0, 2}), ("0 2", {0, 2}), (" 1 ", {1}),
        ([0, 2], {0, 2}), (("1",), {1}),
        (True, {0, 1, 2}), (False, set()),
        (None, set()),
    ],
)
def test_approved_indices_accepts_what_a_person_or_a_browser_sends(reply, expected):
    assert approved_indices(reply, 3) == expected


def test_an_unrecognised_reply_approves_nothing():
    """Fails closed. Defaulting to 'write everything' would mean a malformed
    answer silently puts events on a real calendar -- the outcome the gate is
    for."""
    assert approved_indices("sure why not", 3) == set()
    assert approved_indices("{}", 3) == set()


def test_out_of_range_indices_are_dropped_not_clamped():
    assert approved_indices("0,7,-1", 2) == {0}


# ---- non-interactive: unchanged -------------------------------------------

def test_non_interactive_writes_everything_without_pausing(ledger):
    out = calendar_node({"commitments": COMMITMENTS})
    assert [e["status"] for e in out["calendar_events"]] == ["created", "created"]
    assert len(written(ledger)) == 2


def test_no_commitments_is_not_a_pause(ledger):
    """An empty memo must not stop an interactive run to confirm nothing."""
    assert calendar_node({"commitments": []}, INTERACTIVE) == {"calendar_events": []}
    assert written(ledger) == []


# ---- interactive: the pause ----------------------------------------------

def _graph():
    """The node inside the smallest thing that gives `interrupt()` a context.

    `interrupt()` reads the runnable config, so calling the node bare raises
    `RuntimeError` rather than pausing -- the node has to run inside a graph
    with a checkpointer, exactly as it does in the server.
    """
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.func import entrypoint

    saver = InMemorySaver()

    @entrypoint(checkpointer=saver)
    def run(payload):
        return calendar_node(payload, INTERACTIVE)

    return run, {"configurable": {"thread_id": "t", "interactive": True}}


def _pause(state):
    """Run until it stops, and hand back what it asked."""
    run, config = _graph()
    out = run.invoke(state, config)
    assert "__interrupt__" in out, f"expected a pause, got {out}"
    return out["__interrupt__"][0].value, run, config


def _resume(state, reply):
    """Run, then resume from the top with the answer, as LangGraph does."""
    from langgraph.types import Command

    _, run, config = _pause(state)
    return run.invoke(Command(resume=reply), config)


def test_interactive_pauses_and_writes_nothing_before_the_answer(ledger):
    payload, _, _ = _pause({"commitments": COMMITMENTS})

    assert payload["type"] == "confirm_events"
    assert payload["backend"] == "local"
    assert [e["index"] for e in payload["events"]] == [0, 1]
    # The calendar is untouched. This is the property the ordering exists for.
    assert written(ledger) == []


def test_what_is_shown_is_exactly_what_would_be_written(ledger):
    """The confirmation must not paraphrase. Approving a title that differs
    from the one that lands is approving something else."""
    payload, _, _ = _pause({"commitments": COMMITMENTS})
    shown = payload["events"][0]

    expected = propose_event(**{k: COMMITMENTS[0][k]
                                for k in ("person_name", "what", "due", "channel")})
    for field in ("title", "date", "idempotency_key", "channel"):
        assert shown[field] == expected[field]


def test_approving_everything_writes_everything(ledger):
    out = _resume({"commitments": COMMITMENTS}, "all")
    assert [e["status"] for e in out["calendar_events"]] == ["created", "created"]
    assert len(written(ledger)) == 2


def test_declining_writes_nothing_but_records_the_events(ledger):
    out = _resume({"commitments": COMMITMENTS}, "none")
    assert [e["status"] for e in out["calendar_events"]] == ["declined", "declined"]
    assert written(ledger) == []
    # Recorded, not dropped: "nothing appeared on my calendar" is answerable.
    assert "declined" in out["messages"][0].content


def test_a_partial_selection_writes_only_what_was_ticked(ledger):
    out = _resume({"commitments": COMMITMENTS}, "1")
    assert [e["status"] for e in out["calendar_events"]] == ["declined", "created"]
    rows = written(ledger)
    assert len(rows) == 1
    assert rows[0]["person_name"] == "Marcus"


def test_the_drafter_never_writes_a_message_about_a_party_you_are_going_to():
    """There is nothing to send about your own plans.

    Handed an `attending` entry, the drafter writes a fluent, confident message
    addressed to nobody about something the recipient was not asked to do.
    """
    from recall.nodes.followups import drafter_node

    state = {
        "transcript": "Going to the Acacia Welcome Night on the 18th with Crispy.",
        "commitments": [
            {"kind": "attending", "person_name": "Crispy",
             "what": "Acacia Welcome Night", "due": "2026-09-18", "channel": "email"},
        ],
    }
    # No model is stubbed, so reaching one would raise. Returning cleanly IS
    # the assertion: the filter short-circuits before any call is made.
    assert drafter_node(state) == {"drafts": []}


def test_one_event_makes_one_entry_however_many_people_you_went_with():
    """Observed bug, not a hypothetical.

    "the Acacia Welcome Night with Crispy and Kit Yee" produced two `attending`
    entries with the same name and date. `person_name` is part of the
    idempotency key, so they were not duplicates of each other and the same
    party landed on the calendar twice.
    """
    from recall.nodes.followups import _collapse_attending

    collapsed = _collapse_attending([
        {"kind": "attending", "person_name": "Crispy",
         "what": "Acacia Welcome Night", "due": "2026-09-18"},
        {"kind": "attending", "person_name": "Kit Yee",
         "what": "Acacia Welcome Night", "due": "2026-09-18"},
    ])
    assert len(collapsed) == 1
    assert collapsed[0]["person_name"] == "Crispy, Kit Yee"


def test_two_promises_on_one_day_stay_two_obligations():
    """Follow-ups are per person and must never collapse."""
    from recall.nodes.followups import _collapse_attending

    same_day = [
        {"kind": "followup", "person_name": "Crispy", "what": "send details",
         "due": "2026-09-18"},
        {"kind": "followup", "person_name": "Kit Yee", "what": "send details",
         "due": "2026-09-18"},
    ]
    assert len(_collapse_attending(same_day)) == 2


def test_two_different_events_on_one_day_stay_separate():
    from recall.nodes.followups import _collapse_attending

    events = [
        {"kind": "attending", "person_name": "Crispy", "what": "Welcome Night",
         "due": "2026-09-18"},
        {"kind": "attending", "person_name": "Crispy", "what": "Supper after",
         "due": "2026-09-18"},
    ]
    assert len(_collapse_attending(events)) == 2
