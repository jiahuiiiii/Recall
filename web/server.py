"""Local web UI for Recall. Record a memo, watch the graph run, read the result.

    uv run web/server.py     ->  http://localhost:8000

Transport only. The graph in `recall/` is imported and used unchanged -- there is
exactly one implementation of the pipeline, and this file must never grow a
second one.

Two endpoints rather than one, deliberately: transcription is the step most
likely to get a name wrong, so the transcript comes back to the browser for the
user to correct before any model work starts. It also means a broken Groq key
and a broken graph fail in visibly different places.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from recall._common import LEDGER  # noqa: E402
from recall.graph import build_graph  # noqa: E402
from recall.memory import get_store  # noqa: E402
from recall.state import as_list  # noqa: E402
from recall.tools.transcribe import transcribe  # noqa: E402

HERE = Path(__file__).resolve().parent
app = FastAPI(title="Recall")

# Groq accepts these container formats. The browser picks its own -- Chrome
# records webm/opus, Safari records mp4 -- so the extension is derived from the
# blob's declared MIME type rather than assumed.
MIME_TO_SUFFIX = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mp4": ".mp4",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-m4a": ".m4a",
    "audio/flac": ".flac",
}

# Human labels for the graph's node names, shown in the pipeline strip.
NODE_LABELS = {
    "transcribe": "Transcribe",
    "extract": "Extract people",
    "dedupe": "Dedupe vs memory",
    "ask": "Choose question (EIG)",
    "enrich": "Enrich (sub-agent)",
    "merge": "Merge into record",
    "commitments": "Find commitments",
    "drafts": "Draft follow-ups",
    "calendar": "Write calendar",
    "persist": "Save to memory",
    "summary": "Summarise",
}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(HERE / "index.html")


@app.post("/api/transcribe")
async def api_transcribe(audio: UploadFile = File(...)) -> JSONResponse:
    """Audio blob in, transcript out. Errors come back as text, never a 500."""
    raw = await audio.read()
    if not raw:
        return JSONResponse({"error": "empty recording"}, status_code=400)

    suffix = MIME_TO_SUFFIX.get((audio.content_type or "").split(";")[0], "")
    if not suffix:
        suffix = Path(audio.filename or "memo.webm").suffix or ".webm"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(raw)
        tmp_path = tmp.name
    try:
        text = transcribe(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    if text.startswith("ERROR:"):
        return JSONResponse({"error": text}, status_code=400)
    return JSONResponse({"transcript": text.strip(), "seconds": None})


@app.get("/api/people")
def api_people() -> JSONResponse:
    """The person graph, most recently seen first.

    This is what makes memory visible: it survives restarts, and the same names
    reappear across runs. Without it the dedupe step is a claim; with it the
    viewer can see the record it matched against.
    """
    people = sorted(
        get_store().all(), key=lambda r: r.get("last_seen") or "", reverse=True
    )
    return JSONResponse(
        {
            "count": len(people),
            "people": [
                {
                    "id": r.get("id"),
                    "name": r.get("name"),
                    "company": r.get("company"),
                    "role": r.get("role"),
                    "met_at": r.get("met_at", []),
                    "notes": r.get("notes", []),
                    "enrichment": r.get("enrichment"),
                    "first_seen": r.get("first_seen"),
                    "last_seen": r.get("last_seen"),
                }
                for r in people
            ],
        }
    )


@app.delete("/api/people/{record_id}")
def api_delete_person(record_id: str) -> JSONResponse:
    """Forget a person entirely."""
    ok = get_store().delete(record_id)
    if not ok:
        return JSONResponse({"error": "no such person"}, status_code=404)
    return JSONResponse({"deleted": record_id})


class PersonPatch(BaseModel):
    """Partial edit of a stored record. Omitted fields are left alone."""

    notes: list[str] | None = None
    met_at: list[str] | None = None


@app.patch("/api/people/{record_id}")
def api_patch_person(record_id: str, patch: PersonPatch) -> JSONResponse:
    """Rewrite a person's notes or meeting places.

    Goes through `replace`, not `upsert`: upsert accumulates list fields, so
    patching a shorter list through it would append the edit to the original and
    leave everything the user just deleted still sitting there.
    """
    store = get_store()
    record = store.get(record_id)
    if record is None:
        return JSONResponse({"error": "no such person"}, status_code=404)

    updated = dict(record)
    if patch.notes is not None:
        updated["notes"] = as_list(patch.notes)
    if patch.met_at is not None:
        updated["met_at"] = as_list(patch.met_at)
    store.replace(updated)
    return JSONResponse({"id": record_id, "notes": updated.get("notes", []),
                         "met_at": updated.get("met_at", [])})


class RunRequest(BaseModel):
    transcript: str


class AnswerRequest(BaseModel):
    """The human's reply to the one clarifying question."""

    thread_id: str
    answer: str


# The half-finished run has to survive between two HTTP requests -- the one that
# hits the question and the one that answers it -- so the graph needs somewhere
# to keep it. This is that somewhere.
#
# In memory, deliberately: it is a local demo tool, a paused run is worth
# nothing once the browser tab is gone, and a SQLite checkpointer would add a
# dependency and a file to clean up for no gain. **It does not survive a server
# restart** -- restart mid-demo and any pending question is lost, which is worth
# knowing before it happens on stage.
CHECKPOINTER = InMemorySaver()


@app.post("/api/run")
def api_run(req: RunRequest) -> StreamingResponse:
    """Stream the graph as it executes, one NDJSON line per node.

    NDJSON over a streamed POST body rather than SSE: EventSource is GET-only,
    which would force a second channel just to deliver progress.

    The stream ends one of two ways: `done`, or `question` when the graph paused
    to ask something. A `question` is not an error and not an ending -- the run
    is alive in the checkpointer, waiting for `/api/answer`.
    """
    return StreamingResponse(_run_stream(req.transcript), media_type="application/x-ndjson")


@app.post("/api/answer")
def api_answer(req: AnswerRequest) -> StreamingResponse:
    """Answer the pending question and stream the rest of the run.

    Same NDJSON shape as `/api/run`, so the browser feeds both through one
    handler. The graph re-executes `ask` from the top with the answer supplied,
    which is how LangGraph resumes -- so the answer must be a value the node can
    interpret, not a diff against state it never saw.
    """
    return StreamingResponse(_answer_stream(req.thread_id, req.answer),
                             media_type="application/x-ndjson")


def _run_stream(transcript: str) -> Iterator[str]:
    transcript = (transcript or "").strip()
    if not transcript:
        yield json.dumps({"type": "error", "message": "no transcript to run"}) + "\n"
        return
    thread_id = uuid4().hex
    yield from _drive({"transcript": transcript, "messages": []}, thread_id, transcript)


def _answer_stream(thread_id: str, answer: str) -> Iterator[str]:
    if not (thread_id or "").strip():
        yield json.dumps({"type": "error", "message": "no run to answer"}) + "\n"
        return
    yield from _drive(Command(resume=answer), thread_id, None)


def _config(thread_id: str) -> dict[str, Any]:
    """`interactive` is what tells the nodes a human is reachable.

    Without it `dedupe_node` settles ambiguity with the adjudicator and
    `ask_node` never pauses -- the CLI and the eval harness rely on exactly that.
    The flag, not the presence of a checkpointer, is the switch.
    """
    return {"configurable": {"thread_id": thread_id, "interactive": True}}


def _drive(payload: Any, thread_id: str, transcript: str | None) -> Iterator[str]:
    """Run or resume, emitting one line per node until done or paused."""
    def line(value: dict[str, Any]) -> str:
        return json.dumps(value) + "\n"

    # The ledger is process-global and accumulates across runs, so a raw read
    # would show the session total and creep upward every demo. Diff against a
    # baseline taken here to report the cost of THIS leg.
    base = _usage_snapshot()

    try:
        graph = build_graph(checkpointer=CHECKPOINTER)
        config = _config(thread_id)
        final: dict[str, Any] = {}

        # stream_mode="updates" yields {node_name: partial_update} as each node
        # finishes -- exactly the granularity the pipeline strip needs, and it
        # makes the conditional branch visible (only one of enrich/merge appears
        # unless the memo genuinely contains both new and known people).
        for chunk in graph.stream(payload, config=config, stream_mode="updates"):
            if "__interrupt__" in chunk:
                interrupts = chunk["__interrupt__"]
                asked = interrupts[0].value if interrupts else {}
                yield line({"type": "question", "thread_id": thread_id,
                            "question": asked, "usage": _usage_since(base)})
                return

            for node, update in chunk.items():
                note = ""
                for message in (update or {}).get("messages", []) or []:
                    content = getattr(message, "content", "")
                    if isinstance(content, str) and not content.startswith("="):
                        note = content
                yield line(
                    {
                        "type": "node",
                        "node": node,
                        "label": NODE_LABELS.get(node, node),
                        "note": note,
                        "usage": _usage_since(base),
                    }
                )
                for key, value in (update or {}).items():
                    if key != "messages":
                        final[key] = value

        # Prefer the checkpointer's view. On a resumed leg the stream only
        # replays nodes from `ask` onward, so `final` is missing everything the
        # first leg produced -- including the transcript the UI echoes back.
        final = _final_state(graph, config) or final

        yield line(
            {
                "type": "done",
                "thread_id": thread_id,
                "state": {
                    "transcript": final.get("transcript") or transcript or "",
                    "new_people": final.get("new_people", []),
                    "known_matches": final.get("known_matches", []),
                    # The money shot. Carried through to the client whole --
                    # chosen question, its bits, and the ones it turned down --
                    # because the claim is the selection, and a UI that shows
                    # only the question it asked demonstrates nothing that a
                    # prompt could not have produced.
                    "question": final.get("question"),
                    "resolution": final.get("resolution"),
                    "ambiguous": [
                        {"person": a.get("person", {}),
                         "hypotheses": a.get("hypotheses", [])}
                        for a in final.get("ambiguous", []) or []
                    ],
                    "enrichments": final.get("enrichments", {}),
                    "commitments": final.get("commitments", []),
                    "drafts": final.get("drafts", []),
                    "calendar_events": final.get("calendar_events", []),
                    "errors": final.get("errors", []),
                },
                "usage": _usage_since(base),
            }
        )
    except Exception as exc:  # noqa: BLE001 - a stack trace mid-demo helps nobody
        yield line({"type": "error", "message": f"{type(exc).__name__}: {exc}"})


def _final_state(graph, config) -> dict[str, Any] | None:
    """The authoritative end state, when the graph can report one."""
    getter = getattr(graph, "get_state", None)
    if getter is None:
        return None
    try:
        return dict(getter(config).values)
    except Exception:  # noqa: BLE001 - falling back to the streamed view is fine
        return None


def _usage_snapshot() -> dict[str, float]:
    return {
        "calls": LEDGER.calls,
        "input": LEDGER.input_tokens,
        "output": LEDGER.output_tokens,
        "cost": LEDGER.cost_usd,
    }


def _usage_since(base: dict[str, float]) -> dict[str, Any]:
    now = _usage_snapshot()
    return {
        "calls": int(now["calls"] - base["calls"]),
        "input": int(now["input"] - base["input"]),
        "output": int(now["output"] - base["output"]),
        "cost": round(now["cost"] - base["cost"], 4),
        "unpriced": sorted(LEDGER.unpriced_models),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
