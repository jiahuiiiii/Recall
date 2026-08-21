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

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
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


@app.post("/api/run")
def api_run(req: RunRequest) -> StreamingResponse:
    """Stream the graph as it executes, one NDJSON line per node.

    NDJSON over a streamed POST body rather than SSE: EventSource is GET-only,
    which would force the server to hold per-session state just to deliver
    progress. This keeps the server stateless.
    """
    return StreamingResponse(_run_stream(req.transcript), media_type="application/x-ndjson")


def _run_stream(transcript: str) -> Iterator[str]:
    def line(payload: dict[str, Any]) -> str:
        return json.dumps(payload) + "\n"

    transcript = (transcript or "").strip()
    if not transcript:
        yield line({"type": "error", "message": "no transcript to run"})
        return

    # The ledger is process-global and accumulates across runs, so a raw read
    # would show the session total and creep upward every demo. Diff against a
    # baseline taken here to report the cost of THIS memo.
    base = _usage_snapshot()

    try:
        graph = build_graph()
        final: dict[str, Any] = {}

        # stream_mode="updates" yields {node_name: partial_update} as each node
        # finishes -- exactly the granularity the pipeline strip needs, and it
        # makes the conditional branch visible (only one of enrich/merge appears
        # unless the memo genuinely contains both new and known people).
        for chunk in graph.stream(
            {"transcript": transcript, "messages": []}, stream_mode="updates"
        ):
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

        yield line(
            {
                "type": "done",
                "state": {
                    "transcript": transcript,
                    "new_people": final.get("new_people", []),
                    "known_matches": final.get("known_matches", []),
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
