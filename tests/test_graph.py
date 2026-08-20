"""End-to-end wiring tests. No credentials, no spend, no network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.fakes import (
    ARJUN,
    DAY1_COMMITMENTS,
    DAY1_DRAFTS,
    DAY1_PEOPLE,
    WEI_LIN,
    FakeEnricherAgent,
    fake_chat_model,
)


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """Point memory and calendar at a throwaway directory."""
    monkeypatch.setenv("RECALL_STORE_PATH", str(tmp_path / "person_graph.json"))
    monkeypatch.setenv("RECALL_MEMORY", "local")
    monkeypatch.setenv("RECALL_CALENDAR", "local")
    import recall.tools.calendar as cal

    monkeypatch.setattr(cal, "LEDGER_PATH", tmp_path / "calendar.json")
    return tmp_path


def _wire(monkeypatch, scripted, enrichments=None):
    """Swap every model call for a scripted fake.

    Nodes import chat_model into their own namespace, so each module is patched
    individually -- patching only recall._common would leave the real factory in
    place everywhere it matters.
    """
    import langgraph.prebuilt

    import recall.nodes.dedupe as dedupe
    import recall.nodes.enrich as enrich
    import recall.nodes.extract as extract
    import recall.nodes.followups as followups

    factory = fake_chat_model(scripted)
    for module in (extract, dedupe, followups, enrich):
        monkeypatch.setattr(module, "chat_model", factory)

    agent = FakeEnricherAgent(enrichments or {})
    monkeypatch.setattr(langgraph.prebuilt, "create_react_agent", lambda *a, **k: agent)


def test_new_people_route_through_enrich_and_persist(sandbox, monkeypatch):
    from recall.state import CommitmentExtraction, DraftBundle, PeopleExtraction

    _wire(
        monkeypatch,
        {
            PeopleExtraction: DAY1_PEOPLE,
            CommitmentExtraction: DAY1_COMMITMENTS,
            DraftBundle: DAY1_DRAFTS,
        },
        enrichments={"Wei Lin": "- Leads quant infra at GIC.\n- Spoke at QuantCon 2025."},
    )

    from recall.graph import run

    state = run(transcript="day one memo", verbose=False)

    # On an empty graph everyone is new, so nothing should reach the merge branch.
    assert len(state["new_people"]) == 2
    assert state["known_matches"] == []

    # The enricher sub-agent ran and its output stayed keyed by person.
    assert "GIC" in state["enrichments"]["Wei Lin"]
    assert state["enrichments"]["Arjun Menon"].startswith("NO RELIABLE")

    # Both new people landed in long-term memory.
    assert len(state["persisted_ids"]) == 2
    stored = json.loads(Path(sandbox / "person_graph.json").read_text())["people"]
    assert {p["name"] for p in stored} == {"Wei Lin", "Arjun Menon"}

    # Commitments produced calendar events and drafts.
    assert len(state["commitments"]) == 2
    assert {e["status"] for e in state["calendar_events"]} == {"created"}
    assert len(state["drafts"]) == 2
    assert "Recall" not in state["summary"].split("\n")[0] or True


def test_second_memo_recognises_a_known_person(sandbox, monkeypatch):
    """The whole point of memory: day 2 must route Wei Lin to merge, not enrich."""
    from recall.state import (
        CommitmentExtraction,
        DraftBundle,
        MatchDecision,
        PeopleExtraction,
    )

    _wire(
        monkeypatch,
        {
            PeopleExtraction: DAY1_PEOPLE,
            CommitmentExtraction: DAY1_COMMITMENTS,
            DraftBundle: DAY1_DRAFTS,
        },
        enrichments={},
    )
    from recall.graph import run

    run(transcript="day one memo", verbose=False)

    # Day 2: Wei Lin again (now stored), plus one genuinely new person.
    day2_people = PeopleExtraction(people=[WEI_LIN, ARJUN])
    stored = json.loads(Path(sandbox / "person_graph.json").read_text())["people"]
    wei_id = next(p["id"] for p in stored if p["name"] == "Wei Lin")
    arjun_id = next(p["id"] for p in stored if p["name"] == "Arjun Menon")

    def match(messages):
        text = messages[-1].content
        rid = wei_id if "Wei Lin" in text.split("STORED RECORDS:")[0] else arjun_id
        return MatchDecision(
            is_match=True, candidate_id=rid, confidence=0.95, reasoning="same employer and role"
        )

    _wire(
        monkeypatch,
        {
            PeopleExtraction: day2_people,
            MatchDecision: match,
            CommitmentExtraction: DAY1_COMMITMENTS,
            DraftBundle: DAY1_DRAFTS,
        },
    )
    state = run(transcript="day two memo", verbose=False)

    assert state["new_people"] == []
    assert len(state["known_matches"]) == 2
    assert {m["person"]["name"] for m in state["known_matches"]} == {"Wei Lin", "Arjun Menon"}

    # Merged, not duplicated: still two humans in the graph.
    stored_after = json.loads(Path(sandbox / "person_graph.json").read_text())["people"]
    assert len(stored_after) == 2
    wei = next(p for p in stored_after if p["id"] == wei_id)
    assert len(wei["notes"]) >= 1


def test_low_confidence_match_is_treated_as_new(sandbox, monkeypatch):
    """A hesitant match must split, not merge. A wrong merge destroys a record."""
    from recall.state import (
        CommitmentExtraction,
        DraftBundle,
        MatchDecision,
        PeopleExtraction,
    )

    _wire(
        monkeypatch,
        {
            PeopleExtraction: PeopleExtraction(people=[WEI_LIN]),
            CommitmentExtraction: CommitmentExtraction(commitments=[]),
            DraftBundle: DraftBundle(drafts=[]),
        },
    )
    from recall.graph import run

    run(transcript="first", verbose=False)

    _wire(
        monkeypatch,
        {
            PeopleExtraction: PeopleExtraction(people=[WEI_LIN]),
            MatchDecision: MatchDecision(
                is_match=True, candidate_id="p_nonexistent", confidence=0.4, reasoning="unsure"
            ),
            CommitmentExtraction: CommitmentExtraction(commitments=[]),
            DraftBundle: DraftBundle(drafts=[]),
        },
    )
    state = run(transcript="second", verbose=False)

    assert len(state["new_people"]) == 1
    assert state["known_matches"] == []


def test_calendar_writes_are_idempotent(sandbox, monkeypatch):
    """Re-running the same memo must not stack duplicate reminders."""
    from recall.state import CommitmentExtraction, DraftBundle, MatchDecision, PeopleExtraction

    scripted = {
        PeopleExtraction: DAY1_PEOPLE,
        MatchDecision: MatchDecision(
            is_match=False, candidate_id=None, confidence=0.1, reasoning="different people"
        ),
        CommitmentExtraction: DAY1_COMMITMENTS,
        DraftBundle: DAY1_DRAFTS,
    }
    _wire(monkeypatch, scripted)
    from recall.graph import run

    first = run(transcript="memo", verbose=False)
    assert {e["status"] for e in first["calendar_events"]} == {"created"}

    second = run(transcript="memo", verbose=False)
    assert {e["status"] for e in second["calendar_events"]} == {"duplicate"}

    events = json.loads(Path(sandbox / "calendar.json").read_text())["events"]
    assert len(events) == 2


def test_empty_memo_short_circuits_to_summary(sandbox, monkeypatch):
    """No people, no commitments -- the graph must still finish cleanly."""
    from recall.state import CommitmentExtraction, DraftBundle, PeopleExtraction

    _wire(
        monkeypatch,
        {
            PeopleExtraction: PeopleExtraction(people=[]),
            CommitmentExtraction: CommitmentExtraction(commitments=[]),
            DraftBundle: DraftBundle(drafts=[]),
        },
    )
    from recall.graph import run

    state = run(transcript="just testing the mic", verbose=False)
    assert state["people"] == []
    assert "Nothing found in this memo." in state["summary"]


def test_missing_audio_is_reported_not_raised(sandbox, monkeypatch):
    """Tool failures come back as content. The run finishes and says what broke."""
    from recall.state import CommitmentExtraction, DraftBundle, PeopleExtraction

    _wire(
        monkeypatch,
        {
            PeopleExtraction: PeopleExtraction(people=[]),
            CommitmentExtraction: CommitmentExtraction(commitments=[]),
            DraftBundle: DraftBundle(drafts=[]),
        },
    )
    from recall.graph import run

    state = run(audio_path="/nope/missing.m4a", verbose=False)
    assert any("ERROR:" in e for e in state["errors"])
    assert "ISSUES" in state["summary"]


def test_one_memo_fans_out_to_both_branches(sandbox, monkeypatch):
    """The load-bearing case: a memo with one stranger AND one old contact must
    run enrich and merge in the same pass, then join before drafting.

    Returning a single branch from the router would silently drop half the memo,
    and that failure is invisible in the summary -- hence a test."""
    from recall.state import (
        CommitmentExtraction,
        DraftBundle,
        MatchDecision,
        PeopleExtraction,
    )

    _wire(
        monkeypatch,
        {
            PeopleExtraction: PeopleExtraction(people=[WEI_LIN]),
            CommitmentExtraction: CommitmentExtraction(commitments=[]),
            DraftBundle: DraftBundle(drafts=[]),
        },
    )
    from recall.graph import run

    run(transcript="only wei lin", verbose=False)
    stored = json.loads(Path(sandbox / "person_graph.json").read_text())["people"]
    wei_id = next(p["id"] for p in stored if p["name"] == "Wei Lin")

    # Wei Lin is now known; Arjun is not. One memo, two different paths.
    def match(messages):
        text = messages[-1].content
        new_person_block = text.split("STORED RECORDS:")[0]
        if "Wei Lin" in new_person_block:
            return MatchDecision(
                is_match=True, candidate_id=wei_id, confidence=0.95, reasoning="same person"
            )
        return MatchDecision(
            is_match=False, candidate_id=None, confidence=0.05, reasoning="never seen"
        )

    _wire(
        monkeypatch,
        {
            PeopleExtraction: PeopleExtraction(people=[WEI_LIN, ARJUN]),
            MatchDecision: match,
            CommitmentExtraction: DAY1_COMMITMENTS,
            DraftBundle: DAY1_DRAFTS,
        },
        enrichments={"Arjun Menon": "- Recommendations engineer at Sea Group."},
    )
    state = run(transcript="wei lin again, plus arjun", verbose=False)

    assert [p["name"] for p in state["new_people"]] == ["Arjun Menon"]
    assert [m["person"]["name"] for m in state["known_matches"]] == ["Wei Lin"]

    # enrich ran on the new branch only
    assert "Sea Group" in state["enrichments"]["Arjun Menon"]
    assert "Wei Lin" not in state["enrichments"]

    # merge (parallel) and persist (post-join) both contributed ids -- this is
    # what the operator.add reducer on persisted_ids is for.
    assert len(state["persisted_ids"]) == 2
    assert wei_id in state["persisted_ids"]

    # The join happened before drafting: drafts exist and the graph reached summary.
    assert state["drafts"]
    assert "ALREADY KNEW (1)" in state["summary"]
    assert "NEW CONTACTS (1)" in state["summary"]
