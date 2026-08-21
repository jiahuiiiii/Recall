"""Web transport tests. No AWS, no Groq, no network.

The server must never be a second implementation of the pipeline, so these only
check transport: that audio reaches the transcriber, that tool errors come back
as readable messages rather than 500s, and that the graph is streamed one node
at a time so the UI can show the conditional branch firing.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from langchain_core.messages import AIMessage
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

    def stream(self, initial, stream_mode=None):
        yield {"extract": {"messages": [AIMessage(content="Extracted 1 people: Kang Ling.")],
                           "new_people": []}}
        yield {"dedupe": {"messages": [AIMessage(content="Dedupe: 0 new, 1 already known.")],
                          "known_matches": [{"person": {"name": "Kang Ling"}, "record_id": "p_1",
                                             "confidence": 0.95, "reasoning": "same person"}]}}
        yield {"merge": {"messages": [AIMessage(content="Merged 1 known contacts.")]}}


def test_run_streams_one_event_per_node_then_a_done_payload(monkeypatch):
    monkeypatch.setattr("web.server.build_graph", lambda: _FakeGraph())
    r = client.post("/api/run", json={"transcript": "met Kang Ling"})
    events = _events(r.text)

    assert [e["node"] for e in events if e["type"] == "node"] == ["extract", "dedupe", "merge"]
    assert events[0]["label"] == "Extract people"

    done = events[-1]
    assert done["type"] == "done"
    assert done["state"]["known_matches"][0]["person"]["name"] == "Kang Ling"
    assert "cost" in done["usage"]


def test_only_the_branch_that_ran_appears_in_the_stream(monkeypatch):
    """The UI dims whatever never arrives -- that dimming is how a viewer sees
    the conditional edge chose merge over enrich."""
    monkeypatch.setattr("web.server.build_graph", lambda: _FakeGraph())
    r = client.post("/api/run", json={"transcript": "met Kang Ling"})
    nodes = {e["node"] for e in _events(r.text) if e["type"] == "node"}

    assert "merge" in nodes
    assert "enrich" not in nodes


def test_graph_explosion_is_reported_as_an_error_event(monkeypatch):
    def boom():
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


def test_people_endpoint_handles_an_empty_graph(monkeypatch):
    monkeypatch.setattr("web.server.get_store", lambda: type("S", (), {"all": lambda s: []})())
    body = client.get("/api/people").json()
    assert body == {"count": 0, "people": []}


def test_usage_is_reported_per_run_not_cumulative(monkeypatch):
    """The ledger is process-global. Without diffing against a baseline the UI
    would show the whole session's spend and creep upward every demo run."""
    from recall._common import LEDGER

    LEDGER.record("earlier_run", {"input_tokens": 9_000, "output_tokens": 900}, "some.model")
    monkeypatch.setattr("web.server.build_graph", lambda: _FakeGraph())

    usage = _events(client.post("/api/run", json={"transcript": "met Kang Ling"}).text)[-1]["usage"]
    assert usage["calls"] == 0, "the fake graph makes no model calls, so this run cost nothing"
    assert usage["input"] == 0


def test_every_node_event_carries_a_usage_snapshot(monkeypatch):
    monkeypatch.setattr("web.server.build_graph", lambda: _FakeGraph())
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


def test_deleting_a_person_removes_them(graph):
    rid = _id(graph, "Kang Ling")
    assert client.delete(f"/api/people/{rid}").status_code == 200
    assert graph.get(rid) is None
    assert graph.all() == []


def test_deleting_an_unknown_person_is_a_404(graph):
    assert client.delete("/api/people/p_nope").status_code == 404
    assert client.patch("/api/people/p_nope", json={"notes": []}).status_code == 404
