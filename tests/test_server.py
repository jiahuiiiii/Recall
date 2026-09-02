"""Web transport tests. No AWS, no Groq, no network.

The server must never be a second implementation of the pipeline, so these only
check transport: that audio reaches the transcriber, that tool errors come back
as readable messages rather than 500s, and that the graph is streamed one node
at a time so the UI can show the conditional branch firing.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langgraph.types import Command, Interrupt

from web.server import MIME_TO_SUFFIX, app

client = TestClient(app)


def test_index_serves_the_page():
    r = client.get("/")
    assert r.status_code == 200
    assert "<title>Recall</title>" in r.text


def test_empty_recording_is_rejected_cleanly():
    r = client.post("/api/transcribe", files={"audio": ("memo.webm", b"", "audio/webm")})
    assert r.status_code == 400
    assert "empty" in r.json()["error"]


def test_transcription_result_comes_back(monkeypatch):
    monkeypatch.setattr("web.server.transcribe", lambda path: "  met Kang Ling at camp  ")
    r = client.post("/api/transcribe", files={"audio": ("memo.webm", b"\x00\x01", "audio/webm")})
    assert r.status_code == 200
    assert r.json()["transcript"] == "met Kang Ling at camp"


def test_transcription_failure_is_a_message_not_a_crash(monkeypatch):
    """Tool errors surface as readable text. A 500 mid-demo tells the user nothing."""
    monkeypatch.setattr("web.server.transcribe", lambda path: "ERROR: GROQ_API_KEY is not set")
    r = client.post("/api/transcribe", files={"audio": ("m.webm", b"\x00", "audio/webm")})
    assert r.status_code == 400
    assert "GROQ_API_KEY" in r.json()["error"]


def test_browser_recording_formats_map_to_extensions_groq_accepts():
    """Chrome records webm, Safari records mp4. Guessing one breaks the other."""
    assert MIME_TO_SUFFIX["audio/webm"] == ".webm"
    assert MIME_TO_SUFFIX["audio/mp4"] == ".mp4"


def _events(body: str) -> list[dict]:
    return [json.loads(line) for line in body.strip().split("\n") if line.strip()]


def test_blank_transcript_returns_an_error_event():
    r = client.post("/api/run", json={"transcript": "   "})
    events = _events(r.text)
    assert events[0]["type"] == "error"


class _FakeGraph:
    """Yields the shape LangGraph's stream_mode='updates' produces."""

    def stream(self, payload, config=None, stream_mode=None):
        yield {"extract": {"messages": [AIMessage(content="Extracted 1 people: Kang Ling.")],
                           "new_people": []}}
        yield {"dedupe": {"messages": [AIMessage(content="Dedupe: 0 new, 1 already known.")],
                          "known_matches": [{"person": {"name": "Kang Ling"}, "record_id": "p_1",
                                             "confidence": 0.95, "reasoning": "same person"}]}}
        yield {"merge": {"messages": [AIMessage(content="Merged 1 known contacts.")]}}


def test_run_streams_one_event_per_node_then_a_done_payload(monkeypatch):
    monkeypatch.setattr("web.server.build_graph", lambda **kw: _FakeGraph())
    r = client.post("/api/run", json={"transcript": "met Kang Ling"})
    events = _events(r.text)

    assert [e["node"] for e in events if e["type"] == "node"] == ["extract", "dedupe", "merge"]
    assert events[0]["label"] == "Extract people"

    done = events[-1]
    assert done["type"] == "done"
    assert done["state"]["known_matches"][0]["person"]["name"] == "Kang Ling"
    assert "cost" in done["usage"]


class _AskingGraph:
    """A run where the band could not settle a mention, so `ask` fires."""

    QUESTION = {
        "mention": "Kang",
        "question": "What do they study at NUS?",
        "eig": 0.8034,
        "answers": ["computer science", "geospatial intelligence", "something else"],
        "kind": "multi",
        "prior_entropy": 1.2674,
        "hypotheses": [{"record_id": "p_1", "name": "Kang Ling", "prior": 0.47},
                       {"record_id": "", "name": "someone new", "prior": 0.06}],
        "rejected": [{"question": "Were they met at camp?", "eig": 0.671, "kind": "binary"},
                     {"question": "Does this sound right — from MCIS?", "eig": 0.0,
                      "kind": "binary"}],
        "outcomes": {"p_1": "computer science"},
    }

    def stream(self, payload, config=None, stream_mode=None):
        yield {"dedupe": {"ambiguous": [{"person": {"name": "Kang"}, "hypotheses": []}]}}
        yield {"ask": {"question": self.QUESTION,
                       "messages": [AIMessage(content="Question (0.803 bits)")]}}


def test_the_chosen_question_reaches_the_browser_whole(monkeypatch):
    """The demo rests on showing the bits of the questions it did NOT ask. If
    the server drops `rejected` on the way out, the UI can only display a
    question -- which is exactly what a prompt could have produced, and proves
    nothing about how it was chosen."""
    monkeypatch.setattr("web.server.build_graph", lambda **kw: _AskingGraph())
    r = client.post("/api/run", json={"transcript": "met a Kang"})
    done = _events(r.text)[-1]

    q = done["state"]["question"]
    assert q["question"] == "What do they study at NUS?"
    assert q["eig"] == 0.8034
    assert q["prior_entropy"] == 1.2674
    assert [x["eig"] for x in q["rejected"]] == [0.671, 0.0]
    assert q["answers"][-1] == "something else"


def test_the_ask_node_is_labelled_in_the_pipeline_strip(monkeypatch):
    monkeypatch.setattr("web.server.build_graph", lambda **kw: _AskingGraph())
    r = client.post("/api/run", json={"transcript": "met a Kang"})
    labels = {e["node"]: e["label"] for e in _events(r.text) if e["type"] == "node"}
    assert labels["ask"] == "Choose question (EIG)"


def test_a_run_with_nothing_to_ask_reports_no_question(monkeypatch):
    """`question: None` and a missing key must not look different to the UI."""
    monkeypatch.setattr("web.server.build_graph", lambda **kw: _FakeGraph())
    r = client.post("/api/run", json={"transcript": "met Kang Ling"})
    assert _events(r.text)[-1]["state"]["question"] is None


class _PausingGraph:
    """A graph that stops on a question and finishes once answered.

    Mirrors what LangGraph actually emits: `__interrupt__` arrives as its own
    chunk in the updates stream, carrying an `Interrupt` whose `.value` is the
    payload the node passed to `interrupt()`.
    """

    def __init__(self):
        self.resumed = None

    def stream(self, payload, config=None, stream_mode=None):
        if isinstance(payload, Command):
            self.resumed = payload.resume
            yield {"ask": {"resolution": {"name": "Tiu Chuei Enn", "confidence": 0.96,
                                          "confident": True, "answer": payload.resume},
                           "messages": [AIMessage(content="resolved")]}}
            return
        yield {"dedupe": {"ambiguous": [{"person": {"name": "the malaysian girl"}}]}}
        yield {"__interrupt__": (Interrupt(value=_AskingGraph.QUESTION,
                                           id="i1"),)}

    def get_state(self, config):
        return SimpleNamespace(values={"transcript": "met the malaysian girl",
                                       "resolution": {"name": "Tiu Chuei Enn"}})


def test_a_pause_ends_the_stream_with_a_question_not_a_done(monkeypatch):
    """The run is alive in the checkpointer at this point. Emitting `done` would
    tell the browser it finished, and the pending question would be abandoned."""
    monkeypatch.setattr("web.server.build_graph", lambda **kw: _PausingGraph())
    events = _events(client.post("/api/run", json={"transcript": "met the malaysian girl"}).text)

    assert events[-1]["type"] == "question"
    assert not any(e["type"] == "done" for e in events)
    assert events[-1]["question"]["question"] == "What do they study at NUS?"
    assert events[-1]["thread_id"]


def test_the_thread_id_survives_to_the_answer(monkeypatch):
    """The whole point of the id: it is how the second request finds the run the
    first request left paused."""
    graph = _PausingGraph()
    monkeypatch.setattr("web.server.build_graph", lambda **kw: graph)

    paused = _events(client.post("/api/run", json={"transcript": "met her"}).text)[-1]
    done = _events(client.post("/api/answer",
                               json={"thread_id": paused["thread_id"],
                                     "answer": "computer science"}).text)[-1]

    assert graph.resumed == "computer science"
    assert done["type"] == "done"
    assert done["state"]["resolution"]["name"] == "Tiu Chuei Enn"


def test_answering_without_a_run_is_an_error_not_a_crash(monkeypatch):
    r = client.post("/api/answer", json={"thread_id": "  ", "answer": "cs"})
    assert _events(r.text)[0]["type"] == "error"


def test_a_resumed_leg_still_reports_the_transcript(monkeypatch):
    """The resumed stream replays only the nodes from `ask` onward, so the
    streamed view has no transcript in it. It has to come from the checkpointer,
    or the UI shows an empty memo after the answer."""
    graph = _PausingGraph()
    monkeypatch.setattr("web.server.build_graph", lambda **kw: graph)
    paused = _events(client.post("/api/run", json={"transcript": "met her"}).text)[-1]
    done = _events(client.post("/api/answer",
                               json={"thread_id": paused["thread_id"], "answer": "cs"}).text)[-1]

    assert done["state"]["transcript"] == "met the malaysian girl"


def test_only_the_branch_that_ran_appears_in_the_stream(monkeypatch):
    """The UI dims whatever never arrives -- that dimming is how a viewer sees
    the conditional edge chose merge over enrich."""
    monkeypatch.setattr("web.server.build_graph", lambda **kw: _FakeGraph())
    r = client.post("/api/run", json={"transcript": "met Kang Ling"})
    nodes = {e["node"] for e in _events(r.text) if e["type"] == "node"}

    assert "merge" in nodes
    assert "enrich" not in nodes


def test_graph_explosion_is_reported_as_an_error_event(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("bedrock exploded")

    monkeypatch.setattr("web.server.build_graph", boom)
    r = client.post("/api/run", json={"transcript": "met someone"})
    last = _events(r.text)[-1]
    assert last["type"] == "error"
    assert "bedrock exploded" in last["message"]


def test_people_endpoint_returns_the_graph_most_recent_first(monkeypatch):
    class _Store:
        def all(self):
            return [
                {"id": "p_1", "name": "Wei Lin", "company": "GIC", "role": "lead",
                 "met_at": ["mixer"], "notes": ["a", "b"], "first_seen": "2026-08-01",
                 "last_seen": "2026-08-02"},
                {"id": "p_2", "name": "Kang Ling", "company": None, "role": None,
                 "met_at": ["camp"], "notes": ["c"], "first_seen": "2026-08-20",
                 "last_seen": "2026-08-21"},
            ]

    monkeypatch.setattr("web.server.get_store", lambda: _Store())
    r = client.get("/api/people")
    body = r.json()

    assert body["count"] == 2
    assert [p["name"] for p in body["people"]] == ["Kang Ling", "Wei Lin"]
    assert body["people"][1]["notes"] == ["a", "b"]


def test_people_endpoint_carries_aliases(graph):
    """The UI renders `p.aliases`, so leaving them out of the payload is not a
    missing field -- it is an empty section. A merge records the absorbed name as
    an alias, and without this the nickname looked thrown away."""
    rid = _id(graph, "Kang Ling")
    graph.upsert({"id": rid, "aliases": ["KL", "Ling"]})
    person = next(p for p in client.get("/api/people").json()["people"] if p["id"] == rid)
    assert person["aliases"] == ["KL", "Ling"]


def test_people_endpoint_carries_the_meeting_count(graph):
    """`met_at` is deduplicated places; the card cannot derive occasions from it."""
    rid = _id(graph, "Kang Ling")
    graph.upsert({"id": rid, "met_at": ["orientation camp"], "notes": ["plays tennis"]})
    person = next(p for p in client.get("/api/people").json()["people"] if p["id"] == rid)
    assert person["met_at"] == ["orientation camp"]
    assert person["times_met"] == 2


def test_people_endpoint_handles_an_empty_graph(monkeypatch):
    monkeypatch.setattr("web.server.get_store", lambda: type("S", (), {"all": lambda s: []})())
    body = client.get("/api/people").json()
    assert body == {"count": 0, "people": []}


def test_usage_is_reported_per_run_not_cumulative(monkeypatch):
    """The ledger is process-global. Without diffing against a baseline the UI
    would show the whole session's spend and creep upward every demo run."""
    from recall._common import LEDGER

    LEDGER.record("earlier_run", {"input_tokens": 9_000, "output_tokens": 900}, "some.model")
    monkeypatch.setattr("web.server.build_graph", lambda **kw: _FakeGraph())

    usage = _events(client.post("/api/run", json={"transcript": "met Kang Ling"}).text)[-1]["usage"]
    assert usage["calls"] == 0, "the fake graph makes no model calls, so this run cost nothing"
    assert usage["input"] == 0


def test_every_node_event_carries_a_usage_snapshot(monkeypatch):
    monkeypatch.setattr("web.server.build_graph", lambda **kw: _FakeGraph())
    events = _events(client.post("/api/run", json={"transcript": "met Kang Ling"}).text)
    assert all("usage" in e for e in events if e["type"] == "node")


# --------------------------------------------------------------------------
# Editing the person graph. The agent occasionally records someone it should
# not have, and a contact book you cannot correct is one you stop trusting.
# --------------------------------------------------------------------------


@pytest.fixture()
def graph(tmp_path, monkeypatch):
    from recall.memory import LocalPersonStore

    store = LocalPersonStore(tmp_path / "graph.json")
    store.upsert({"name": "Kang Ling", "notes": ["very smart", "very nice"],
                  "met_at": ["orientation camp"]})
    monkeypatch.setattr("web.server.get_store", lambda: store)
    return store


def _id(store, name):
    return next(r["id"] for r in store.all() if r["name"] == name)


def test_deleting_one_note_keeps_the_rest(graph):
    rid = _id(graph, "Kang Ling")
    r = client.patch(f"/api/people/{rid}", json={"notes": ["very smart"]})

    assert r.status_code == 200
    assert graph.get(rid)["notes"] == ["very smart"]
    assert graph.get(rid)["met_at"] == ["orientation camp"], "untouched field must survive"


def test_a_deleted_note_does_not_come_back(graph):
    """The store ACCUMULATES list fields on upsert, so a shorter list written
    through upsert would re-append what was just removed. This must go through
    replace()."""
    rid = _id(graph, "Kang Ling")
    client.patch(f"/api/people/{rid}", json={"notes": []})
    assert graph.get(rid)["notes"] == []


def test_patch_ignores_omitted_fields(graph):
    rid = _id(graph, "Kang Ling")
    client.patch(f"/api/people/{rid}", json={"met_at": ["library"]})
    assert graph.get(rid)["notes"] == ["very smart", "very nice"]


def test_patch_normalises_a_bare_string(graph):
    rid = _id(graph, "Kang Ling")
    r = client.patch(f"/api/people/{rid}", json={"notes": "one note"})
    # FastAPI rejects a str for list[str], so the client never gets to corrupt it.
    assert r.status_code == 422


def test_people_endpoint_carries_contacts_and_their_links(graph):
    """The panel renders `p.contacts` and hrefs `p.contact_links`. The links are
    built server-side so the page cannot disagree with the store about what a
    stored handle means."""
    rid = _id(graph, "Kang Ling")
    graph.upsert({"id": rid, "contacts": {"instagram": "kangling", "phone": "+65 9123 4567"}})
    person = next(p for p in client.get("/api/people").json()["people"] if p["id"] == rid)
    assert person["contacts"] == {"phone": "+65 9123 4567", "instagram": "kangling"}
    assert person["contact_links"]["instagram"] == "https://instagram.com/kangling"
    assert person["contact_links"]["phone"] == "tel:+6591234567"


def test_a_person_with_no_contacts_gets_an_empty_map_not_a_missing_key(graph):
    """The section is an editor and always renders, so the page reads the key
    unconditionally."""
    person = client.get("/api/people").json()["people"][0]
    assert person["contacts"] == {} and person["contact_links"] == {}


def test_patching_contacts_stores_the_normalised_handle(graph):
    rid = _id(graph, "Kang Ling")
    r = client.patch(f"/api/people/{rid}",
                     json={"contacts": {"instagram": "https://www.instagram.com/kangling/?hl=en"}})

    assert r.status_code == 200
    assert r.json()["contacts"] == {"instagram": "kangling"}, "the field redraws as what was stored"
    assert graph.get(rid)["contacts"] == {"instagram": "kangling"}
    assert graph.get(rid)["notes"] == ["very smart", "very nice"], "untouched field must survive"


def test_a_channel_left_out_of_the_patch_is_one_the_user_cleared(graph):
    """The whole map, not one channel: an omitted field means "leave alone"
    everywhere else in this patch, so there would otherwise be no way to say
    "delete this number"."""
    rid = _id(graph, "Kang Ling")
    client.patch(f"/api/people/{rid}", json={"contacts": {"phone": "+65 9123 4567",
                                                          "telegram": "kangling"}})
    client.patch(f"/api/people/{rid}", json={"contacts": {"telegram": "kangling"}})
    assert graph.get(rid)["contacts"] == {"telegram": "kangling"}


def test_an_unknown_channel_is_refused_rather_than_silently_dropped(graph):
    """`as_contacts` drops it, which is right for loading an old record and
    wrong for a write -- a client that typed `whatsapp` should be told."""
    rid = _id(graph, "Kang Ling")
    r = client.patch(f"/api/people/{rid}", json={"contacts": {"whatsapp": "+65 9123 4567"}})
    assert r.status_code == 400
    assert "whatsapp" in r.json()["error"]
    assert graph.get(rid).get("contacts", {}) == {}


def test_patching_notes_leaves_contacts_alone(graph):
    rid = _id(graph, "Kang Ling")
    client.patch(f"/api/people/{rid}", json={"contacts": {"telegram": "kangling"}})
    client.patch(f"/api/people/{rid}", json={"notes": ["very smart"]})
    assert graph.get(rid)["contacts"] == {"telegram": "kangling"}


def test_deleting_a_person_removes_them(graph):
    rid = _id(graph, "Kang Ling")
    assert client.delete(f"/api/people/{rid}").status_code == 200
    assert graph.get(rid) is None
    assert graph.all() == []


def test_deleting_an_unknown_person_is_a_404(graph):
    assert client.delete("/api/people/p_nope").status_code == 404
    assert client.patch("/api/people/p_nope", json={"notes": []}).status_code == 404


# --------------------------------------------------------------------------
# Relationship edges. Transport only -- the guard itself is tested in
# tests/test_relations.py. What matters here is that an edge cannot outlive the
# person it points at: `merge` deletes a record and `delete` removes one, and an
# edge left behind draws a line to nobody and disappears with no explanation.
# --------------------------------------------------------------------------


@pytest.fixture()
def edges(tmp_path, monkeypatch, graph):
    from recall.relations import RelationStore

    store = RelationStore(tmp_path / "relations.json")
    monkeypatch.setattr("web.server.get_relation_store", lambda: store)
    graph.upsert({"name": "Marcus", "notes": ["runs a supper club with Kang Ling"]})
    return store


def test_graph_page_is_served():
    r = client.get("/graph")
    assert r.status_code == 200
    assert "<title>Connections · Recall</title>" in r.text


def test_the_kind_vocabulary_is_sent_with_the_edges(edges):
    """The page colours edges by kind. Sending the vocabulary rather than
    duplicating it in JS means a ninth kind cannot exist server-side with no
    colour client-side and render as an invisible line."""
    from recall.relations import KINDS

    body = client.get("/api/relations").json()
    assert [k["kind"] for k in body["kinds"]] == list(KINDS)
    assert body["relations"] == []


def test_a_user_can_draw_an_edge_the_notes_never_supported(edges, graph):
    """The derived edges are guarded hard, so the model will miss relationships
    the user knows about. Without this the guard reads as the feature broken."""
    a, b = _id(graph, "Kang Ling"), _id(graph, "Marcus")
    r = client.post("/api/relations",
                    json={"a": a, "b": b, "kind": "partner", "what": "run a supper club"})
    assert r.status_code == 200
    assert r.json()["source"] == "user"
    assert len(edges.all()) == 1


@pytest.mark.parametrize("payload,code", [
    ({"kind": "collaborator"}, 400),      # outside the closed vocabulary
    ({"kind": "partner", "same": True}, 400),   # a person cannot relate to themselves
])
def test_a_bad_edge_is_refused_with_a_reason(edges, graph, payload, code):
    a, b = _id(graph, "Kang Ling"), _id(graph, "Marcus")
    body = {"a": a, "b": b if not payload.pop("same", False) else a, **payload}
    r = client.post("/api/relations", json=body)
    assert r.status_code == code
    assert "error" in r.json()


def test_an_edge_to_a_person_who_does_not_exist_is_refused(edges, graph):
    r = client.post("/api/relations",
                    json={"a": _id(graph, "Kang Ling"), "b": "p_nope", "kind": "friend"})
    assert r.status_code == 404


def test_removing_an_edge(edges, graph):
    a, b = _id(graph, "Kang Ling"), _id(graph, "Marcus")
    rid = client.post("/api/relations", json={"a": a, "b": b, "kind": "friend"}).json()["id"]
    assert client.delete(f"/api/relations/{rid}").status_code == 200
    assert client.delete(f"/api/relations/{rid}").status_code == 404


def test_forgetting_a_person_forgets_their_edges(edges, graph):
    """An edge outliving its endpoint does not error -- the line simply stops
    being drawn, and the relationship disappears with no record of why."""
    a, b = _id(graph, "Kang Ling"), _id(graph, "Marcus")
    client.post("/api/relations", json={"a": a, "b": b, "kind": "partner"})
    r = client.delete(f"/api/people/{b}")
    assert r.json()["relations_dropped"] == 1
    assert edges.all() == []


def test_merging_two_people_moves_their_edges_onto_the_survivor(edges, graph):
    a, b = _id(graph, "Kang Ling"), _id(graph, "Marcus")
    graph.upsert({"name": "Crispy", "notes": ["same person as Marcus"]})
    c = _id(graph, "Crispy")
    client.post("/api/relations", json={"a": a, "b": c, "kind": "partner"})

    r = client.post(f"/api/people/{b}/merge", json={"source_id": c})
    assert r.json()["relations_moved"] == 1
    assert {(e["a"], e["b"]) for e in edges.all()} == {(min(a, b), max(a, b))}


def test_an_edge_whose_person_vanished_is_flagged_not_hidden(edges, graph):
    """A store that has drifted out of step with the person graph should be
    visible rather than silently thinner than it is."""
    edges.add({"a": _id(graph, "Kang Ling"), "b": "p_ghost", "kind": "friend"})
    assert client.get("/api/relations").json()["relations"][0]["dangling"] is True


def test_a_refresh_replaces_derived_edges_and_keeps_user_drawn_ones(edges, graph, monkeypatch):
    a, b = _id(graph, "Kang Ling"), _id(graph, "Marcus")
    client.post("/api/relations", json={"a": a, "b": b, "kind": "friend"})
    monkeypatch.setattr(
        "recall.relations.generate_relations",
        lambda records: [{"a": a, "b": b, "kind": "partner", "source": "derived",
                          "evidence": "runs a supper club with Kang Ling"}],
    )
    body = client.post("/api/relations/refresh").json()
    assert body["derived"] == 1 and body["user_drawn"] == 1
    assert {e["kind"] for e in edges.all()} == {"friend", "partner"}


def test_a_failed_refresh_is_a_message_not_a_500(edges, monkeypatch):
    def _boom(_records):
        raise RuntimeError("ValidationException: invalid model identifier")
    monkeypatch.setattr("recall.relations.generate_relations", _boom)
    r = client.post("/api/relations/refresh")
    assert r.status_code == 502
    assert "invalid model identifier" in r.json()["error"]


def test_the_graph_overlay_cannot_swallow_a_click():
    """Cheap tripwire for a bug that took the whole page down silently.

    `.empty` covers the canvas. The `hidden` attribute only hides it through the
    UA rule `[hidden]{display:none}`, which ANY author `display` declaration
    outranks -- so with `display:flex` and no `[hidden]` rule, `el.hidden = true`
    set the attribute, changed nothing, and left an invisible overlay eating
    every pointerdown. Nodes could not be selected and the cause was nowhere
    near the click handler.

    `pointer-events:none` is the second half: on a graph with no edges the
    overlay legitimately shows, and its own text invites you to "draw one
    yourself by clicking a person".
    """
    page = (Path(__file__).resolve().parent.parent / "web" / "graph.html").read_text()
    assert ".empty[hidden]{display:none}" in page
    empty_rule = page.split(".empty{", 1)[1].split("}", 1)[0]
    assert "pointer-events:none" in empty_rule
