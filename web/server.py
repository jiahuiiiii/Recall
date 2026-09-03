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
import os
import sys
import tempfile
import threading
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from recall._common import LEDGER  # noqa: E402
from recall.contacts import CHANNELS, as_contacts, links, unknown_channels  # noqa: E402
from recall.graph import build_graph  # noqa: E402
from recall.memory import get_store  # noqa: E402
from recall.relations import KINDS, get_relation_store  # noqa: E402
from recall.relations import LABELS as REL_LABELS  # noqa: E402
from recall.state import as_list  # noqa: E402
from recall.tools.calendar import backend_name, gcal_link, ics_path  # noqa: E402
from recall.tools.transcribe import transcribe  # noqa: E402

HERE = Path(__file__).resolve().parent
app = FastAPI(title="Recall")

# Whether the Telegram poller is running inside THIS process, and why not if it
# isn't. Surfaced on /healthz because a bot that has quietly stopped answering
# is indistinguishable from a bot that is thinking.
TELEGRAM_STATE: dict[str, str] = {"status": "not started"}

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
    # No caching. The page is a single file edited constantly during the build,
    # and a browser reusing it makes a shipped change look like a change that
    # never applied -- which cost a debugging round once already. Nothing here
    # is served at a scale where caching buys anything.
    return FileResponse(
        HERE / "index.html",
        headers={"Cache-Control": "no-store, must-revalidate"},
    )


@app.get("/people")
def people_page() -> FileResponse:
    """The whole person graph, with filtering and sorting.

    A separate page rather than a wider sidebar: 286px cannot show a contact
    book, and the memo column is what the app is for. Clicking a person here
    links back to `/` with `?person=`, so the detail panel -- notes, merge,
    forget -- stays defined in exactly one place.
    """
    return FileResponse(HERE / "people.html",
                        headers={"Cache-Control": "no-store, must-revalidate"})


@app.get("/graph")
def graph_page() -> FileResponse:
    """The person graph drawn as a graph.

    /people is a card grid -- it answers "who do I know" and cannot show how
    anyone stands to anyone else, because until relations.py a record held no
    edges to show. This page is the same data laid out by its connections.
    """
    return FileResponse(HERE / "graph.html",
                        headers={"Cache-Control": "no-store, must-revalidate"})


@app.get("/app.css")
def app_css() -> FileResponse:
    """The stylesheet both pages use."""
    return FileResponse(HERE / "app.css", media_type="text/css",
                        headers={"Cache-Control": "no-store, must-revalidate"})


@app.get("/shared.js")
def shared_js() -> FileResponse:
    """Helpers both pages use. Shared so the tag vocabulary and the subtitle
    rule cannot drift between them."""
    return FileResponse(HERE / "shared.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-store, must-revalidate"})


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


@app.get("/healthz")
def healthz() -> JSONResponse:
    """Liveness, and enough state to diagnose a bad deploy without a shell.

    Reports what is CONFIGURED, never a secret and never a token. A health check
    that says "ok" while the calendar is unreachable and the model id is wrong
    is a health check that hides exactly the two things that break a deploy.
    """
    from web import google_calendar

    return JSONResponse(
        {
            "ok": True,
            "calendar_backend": backend_name(),
            "google_oauth_configured": google_calendar.configured(),
            "google_calendar_connected": google_calendar.connected(),
            "model": os.environ.get("RECALL_MODEL_ID", "(default)"),
            "store": os.environ.get("RECALL_STORE_PATH", "data/person_graph.json"),
            "telegram_poller": TELEGRAM_STATE.get("status", "not started"),
        }
    )


@app.get("/oauth/google/start")
def oauth_start() -> Response:
    """Begin consent. The link the Telegram button opens.

    No user id in the URL, deliberately. This deployment is single-tenant and
    the Telegram allowlist is what decides who may connect, so there is nothing
    to pass -- and `upgrade.md`'s warning about trusting a user id from a query
    string is best answered by not having one.
    """
    from web import google_calendar

    if not google_calendar.configured():
        return HTMLResponse(_page("Not configured",
            "Google OAuth is not set up on this server. "
            "GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and GOOGLE_REDIRECT_URI must all be set."),
            status_code=503)
    state = google_calendar.create_state()
    return RedirectResponse(google_calendar.authorization_url(state))


@app.get("/oauth/google/callback")
def oauth_callback(request: Request) -> Response:
    """Where Google sends the user back. Stores the refresh token."""
    from web import google_calendar

    params = request.query_params
    if error := params.get("error"):
        return HTMLResponse(_page("Not connected",
            f"Google reported: {error}. Nothing was changed."), status_code=400)

    code, state = params.get("code"), params.get("state")
    if not code or not state:
        return HTMLResponse(_page("Missing information",
            "That link is incomplete. Start again from Telegram."), status_code=400)
    if not google_calendar.consume_state(state):
        # Expired, already used, or not ours. All three mean the same thing to
        # the user and none of them should say which -- a specific message here
        # tells an attacker which of their guesses was close.
        return HTMLResponse(_page("Link expired",
            "That link is no longer valid. Send /connect_calendar again."), status_code=400)

    try:
        google_calendar.save_connection(google_calendar.exchange_code(code, state))
    except Exception as exc:  # noqa: BLE001 - the user sees text, never a trace
        return HTMLResponse(_page("Could not connect", str(exc)), status_code=400)

    return HTMLResponse(_page("Calendar connected",
        "Recall can now add follow-ups to your calendar. You can close this tab "
        "and go back to Telegram."))


def _page(title: str, body: str) -> str:
    """The only HTML this server generates. Kept plain and self-contained."""
    return (
        "<!doctype html><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{title} - Recall</title>"
        "<style>body{font:16px/1.6 system-ui,sans-serif;max-width:34rem;margin:18vh auto;"
        "padding:0 1.5rem;color:#1E2423;background:#F7F4F0}"
        "h1{font-size:1.4rem;margin:0 0 .6rem}p{color:#3E4746;margin:0}"
        "@media(prefers-color-scheme:dark){body{color:#F3FAF8;background:#122120}"
        "p{color:#DAE9E6}}</style>"
        f"<h1>{title}</h1><p>{body}</p>"
    )


@app.get("/api/calendar/{key}.ics")
def api_calendar_ics(key: str) -> Response:
    """Hand back one follow-up as a calendar file the browser can open.

    The whole point of the `ics` backend is that it needs nothing from the user
    -- no Google project, no OAuth, no account. They click, their own calendar
    app opens with the event filled in, and they decide whether to keep it. That
    is the same bargain as the drafts: we propose, the human commits.

    `ics_path` validates the key against the generated shape and returns None
    otherwise, so a crafted `key` cannot walk out of the directory.
    """
    path = ics_path(key)
    if path is None:
        return JSONResponse({"error": "not a calendar key"}, status_code=400)
    if not path.exists():
        return JSONResponse({"error": "no calendar file for that event"}, status_code=404)
    return FileResponse(
        path,
        media_type="text/calendar",
        # Named for a human looking at their downloads folder, not for the key.
        filename="recall-followup.ics",
    )


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
                    # The detail panel's "Also known as" section and the alias
                    # search on /people both read this. Omitted, they did not
                    # error -- they silently rendered nothing, so a merge that
                    # correctly recorded "Crispy" as an alias looked like it had
                    # thrown the nickname away.
                    "aliases": r.get("aliases", []),
                    "company": r.get("company"),
                    "role": r.get("role"),
                    "met_at": r.get("met_at", []),
                    "notes": r.get("notes", []),
                    # Display-only dates, parallel to `notes`. The detail panel
                    # groups by these; without them it can only render one
                    # undated block, which is what made a record look like
                    # unrelated fragments.
                    "note_log": r.get("note_log", []),
                    "tags": r.get("tags", []),
                    # How to reach them, plus the URL for each. The links are
                    # built server-side so the page cannot disagree with the
                    # store about what a stored handle means -- there is one
                    # implementation of "kangling" -> instagram.com/kangling.
                    "contacts": as_contacts(r.get("contacts")),
                    "contact_links": links(r.get("contacts")),
                    "enrichment": r.get("enrichment"),
                    "first_seen": r.get("first_seen"),
                    "last_seen": r.get("last_seen"),
                    # Occasions, not places. The card cannot derive this from
                    # met_at -- that list is deduplicated locations.
                    "times_met": r.get("times_met"),
                }
                for r in people
            ],
        }
    )


@app.get("/api/export")
def api_export() -> JSONResponse:
    """The whole graph as one JSON file the user can keep.

    `business.md` promises export even at the free-plan limit; the reason to
    build it is the principle rather than the plan tier -- a contact book you
    cannot get out of is one you stop trusting.

    Whole records, not the projection `/api/people` renders. That endpoint picks
    fields for a card, so exporting through it would quietly drop whatever the
    UI does not happen to show, and the export is the copy the user keeps.
    Relations travel alongside because they live in their own file and reference
    people by id -- exporting people alone would hand back a graph with no edges
    and no way to tell that any were lost.
    """
    people = get_store().all()
    relations = get_relation_store().all()
    return JSONResponse(
        {
            "format": "recall.person_graph",
            "version": 1,
            "exported_at": date.today().isoformat(),
            "counts": {"people": len(people), "relations": len(relations)},
            "people": people,
            "relations": relations,
        },
        headers={
            "Content-Disposition": 'attachment; filename="recall-export.json"'
        },
    )


@app.delete("/api/people/{record_id}")
def api_delete_person(record_id: str) -> JSONResponse:
    """Forget a person entirely, edges included."""
    ok = get_store().delete(record_id)
    if not ok:
        return JSONResponse({"error": "no such person"}, status_code=404)
    # An edge outliving one of its endpoints points at a person who no longer
    # exists. It would not error -- the graph page simply drops the line and the
    # relationship disappears with no record of why.
    dropped = get_relation_store().drop_person(record_id)
    return JSONResponse({"deleted": record_id, "relations_dropped": dropped})


@app.post("/api/tags/refresh")
def api_refresh_tags() -> JSONResponse:
    """Re-tag the whole graph in one model call.

    Not done on every run: tags are for filtering, they change only when the
    graph does, and re-deriving them per memo would spend a call per memo for a
    result nobody looked at. The user asks when they want them refreshed.
    """
    from recall.tags import generate_tags

    store = get_store()
    records = store.all()
    try:
        assigned = generate_tags(records)
    except Exception as exc:  # noqa: BLE001 - surface it, do not 500 the UI
        return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=502)

    for rec in records:
        tags = assigned.get(rec.get("id", ""))
        if tags is None:
            continue
        store.replace({**rec, "tags": tags})
    return JSONResponse({
        "tagged": sum(1 for v in assigned.values() if v),
        "people": len(records),
        "vocabulary": sorted({t for v in assigned.values() for t in v}),
    })


@app.get("/api/relations")
def api_relations() -> JSONResponse:
    """The edges of the person graph.

    Served separately from /api/people rather than embedded in each record: an
    edge belongs to a PAIR, so putting it on both records ships two copies that
    can disagree, and putting it on one makes it invisible from the other.
    """
    store = get_relation_store()
    known = {r.get("id") for r in get_store().all()}
    rels = store.all()
    return JSONResponse({
        "count": len(rels),
        # The vocabulary the page colours by. Sent rather than duplicated in JS,
        # so a ninth kind cannot exist server-side with no colour client-side.
        "kinds": [{"kind": k, "label": REL_LABELS[k]} for k in KINDS],
        "relations": [
            {
                "id": r.get("id"), "a": r.get("a"), "b": r.get("b"),
                "kind": r.get("kind"), "what": r.get("what", ""),
                "evidence": r.get("evidence", ""),
                "source": r.get("source", "derived"),
                # An edge whose endpoint is gone would draw a line to nothing.
                # Flagged rather than filtered, so a store that has drifted out
                # of step with the person graph is visible instead of silent.
                "dangling": not (r.get("a") in known and r.get("b") in known),
            }
            for r in rels
        ],
    })


class RelationRequest(BaseModel):
    """An edge the user drew themselves."""

    a: str
    b: str
    kind: str
    what: str = ""


@app.post("/api/relations")
def api_add_relation(req: RelationRequest) -> JSONResponse:
    """Record a relationship by hand.

    The derived edges are guarded hard -- a stored note has to name the other
    person -- which means the model will miss relationships the user knows
    about and never wrote down. Without this the only way to add one would be to
    write a memo about it, so the guard would read as the feature being broken.

    No corroboration check here on purpose: the user IS the evidence, and
    `source: "user"` records that, so a refresh cannot withdraw it.
    """
    kind = (req.kind or "").strip().lower()
    if kind not in KINDS:
        return JSONResponse(
            {"error": f"unknown kind {req.kind!r}", "kinds": list(KINDS)}, status_code=400
        )
    if req.a == req.b:
        return JSONResponse({"error": "a person cannot relate to themselves"},
                            status_code=400)
    known = {r.get("id") for r in get_store().all()}
    missing = [pid for pid in (req.a, req.b) if pid not in known]
    if missing:
        return JSONResponse({"error": f"no such person: {missing[0]}"}, status_code=404)

    rel = get_relation_store().add({
        "a": req.a, "b": req.b, "kind": kind,
        "what": " ".join((req.what or "").split()),
        "evidence": "", "source": "user",
    })
    return JSONResponse(rel)


@app.delete("/api/relations/{rel_id}")
def api_delete_relation(rel_id: str) -> JSONResponse:
    """Remove one edge. The graph will get relationships wrong, and a graph you
    cannot correct is one you stop trusting -- the same argument as delete() on
    a person."""
    if not get_relation_store().remove(rel_id):
        return JSONResponse({"error": "no such relation"}, status_code=404)
    return JSONResponse({"deleted": rel_id})


@app.post("/api/relations/refresh")
def api_refresh_relations() -> JSONResponse:
    """Re-derive every edge from the stored notes, in one model call.

    On demand rather than per memo, exactly like /api/tags/refresh: relations
    only change when the notes do, and re-deriving per memo spends a call per
    memo on a picture nobody has opened.

    A separate call from extraction is the whole reason this can ship without
    re-running the resolution benchmark -- see the module docstring in
    `recall/relations.py`. Do not fold it into `extract`.
    """
    from recall.relations import generate_relations

    store = get_relation_store()
    records = get_store().all()
    try:
        derived = generate_relations(records)
    except Exception as exc:  # noqa: BLE001 - surface it, do not 500 the UI
        return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=502)

    kept = store.replace_derived(derived)
    return JSONResponse({
        "derived": len(derived),
        "total": len(kept),
        "user_drawn": sum(1 for r in kept if r.get("source") == "user"),
        "people": len(records),
    })


class MergeRequest(BaseModel):
    """Fold `source_id` into the person named in the path."""

    source_id: str


@app.post("/api/people/{record_id}/merge")
def api_merge_person(record_id: str, req: MergeRequest) -> JSONResponse:
    """Declare that two records are the same human.

    The counterpart to delete(). Resolution will miss returns -- a nickname it
    did not recognise, a name spelled differently -- and without this the user
    can only delete one of the duplicates, losing its notes. Merging keeps both
    sets and teaches the resolver: the absorbed name becomes an alias, so the
    next mention resolves instead of duplicating again.
    """
    try:
        merged = get_store().merge(req.source_id, record_id)
    except KeyError:
        return JSONResponse({"error": "no such person"}, status_code=404)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    # `merge` deletes the source record, so its edges have to follow it onto the
    # survivor or they point at nobody. Repointing also drops the edge BETWEEN
    # the two, which after a merge is the duplicate that was just fixed rather
    # than a relationship.
    moved = get_relation_store().repoint(req.source_id, record_id)
    return JSONResponse({
        "id": merged.get("id"), "name": merged.get("name"),
        "aliases": merged.get("aliases", []), "notes": merged.get("notes", []),
        "met_at": merged.get("met_at", []), "absorbed": req.source_id,
        "relations_moved": moved,
    })


class PersonPatch(BaseModel):
    """Partial edit of a stored record. Omitted fields are left alone."""

    notes: list[str] | None = None
    met_at: list[str] | None = None
    # The WHOLE contact map when present, not one channel: a channel the client
    # leaves out is one the user cleared, and there is no other way to say
    # "delete this number" in a patch whose omitted fields mean "leave alone".
    contacts: dict[str, str] | None = None


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
    if patch.contacts is not None:
        # `as_contacts` would drop an unknown channel silently, which is right
        # for loading an old record and wrong for a write: a client that typed
        # `whatsapp` should be told, not watch it vanish.
        unknown = unknown_channels(patch.contacts)
        if unknown:
            return JSONResponse(
                {"error": f"unknown contact channel(s): {', '.join(unknown)}. "
                          f"Valid: {', '.join(CHANNELS)}"},
                status_code=400,
            )
        updated["contacts"] = as_contacts(patch.contacts)
    stored = store.replace(updated)
    # The stored values, not the submitted ones: a pasted profile URL comes back
    # as the handle it was normalised to, so the field the user is looking at
    # shows what the graph actually holds.
    return JSONResponse({"id": record_id, "notes": stored.get("notes", []),
                         "met_at": stored.get("met_at", []),
                         "contacts": stored.get("contacts", {}),
                         "contact_links": links(stored.get("contacts"))})


class RunRequest(BaseModel):
    transcript: str


class AnswerRequest(BaseModel):
    """The human's reply to whichever pause is outstanding.

    One shape for both: the clarifying question answers with the option text,
    the calendar confirmation answers with `"all"`, `"none"`, or the indices to
    create (`"0,2"`). The node that paused is the node that interprets it.
    """

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

    The stream ends one of three ways: `done`, `question` when the graph paused
    to ask which person a mention meant, or `confirm` when it paused to ask which
    calendar events to create. Neither pause is an error and neither is an ending
    -- the run is alive in the checkpointer, waiting for `/api/answer`.
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


def _with_gcal(events: list[dict]) -> list[dict]:
    """Copy each calendar event with a `gcal` one-tap add-to-Google link.

    A declined event gets none -- there is nothing to add. A copy, not an
    in-place edit, because the same dicts came from the checkpointer's state and
    are not ours to mutate.
    """
    out = []
    for e in events:
        e = dict(e)
        if e.get("status") != "declined":
            e["gcal"] = gcal_link(e)
        out.append(e)
    return out


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
                # Two nodes can pause: `ask` with a clarifying question, and
                # `calendar` asking which events to create. Both resume through
                # /api/answer, but they render differently, so the payload's own
                # `type` decides the line kind rather than the client guessing
                # from which keys happen to be present.
                kind = "confirm" if (asked or {}).get("type") == "confirm_events" else "question"
                yield line({"type": kind, "thread_id": thread_id,
                            kind: asked, "usage": _usage_since(base)})
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
                    # Attach the one-tap Google link per event. Computed here,
                    # not in the browser, so the exclusive-end-date rule lives in
                    # exactly one place (recall.tools.calendar) and cannot drift.
                    "calendar_events": _with_gcal(final.get("calendar_events", [])),
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


def _start_telegram_poller() -> None:
    """Run the Telegram bot inside the web process when RECALL_TELEGRAM=1.

    One service, not two, and the reason is storage: a Render disk attaches to a
    single service, so a separate bot worker could not read the OAuth token the
    web service wrote at the end of the consent flow. Same process means shared
    disk and shared memory, and for a single-tenant deployment there is nothing
    to gain from splitting them.

    Off by default. Locally you want `uv run telegram_bot.py` in its own
    terminal, where its output is not interleaved with request logs.
    """
    if os.environ.get("RECALL_TELEGRAM", "").strip() not in ("1", "true", "yes"):
        TELEGRAM_STATE["status"] = "disabled (set RECALL_TELEGRAM=1)"
        return
    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        TELEGRAM_STATE["status"] = "no TELEGRAM_BOT_TOKEN"
        return

    import telegram_bot

    def run() -> None:
        try:
            TELEGRAM_STATE["status"] = "polling"
            telegram_bot.poll(telegram_bot.Bot(os.environ["TELEGRAM_BOT_TOKEN"]))
        except Exception as exc:  # noqa: BLE001 - a dead poller must not kill the web app
            TELEGRAM_STATE["status"] = f"stopped: {type(exc).__name__}: {exc}"

    # Daemon, so a hung long-poll cannot keep the container alive through a
    # deploy. Telegram's getUpdates blocks for 30s at a time and would otherwise
    # hold shutdown open for exactly that long.
    threading.Thread(target=run, name="telegram-poller", daemon=True).start()


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    _start_telegram_poller()
    yield


# Attached after definition rather than at construction, so the routes above
# read in the order a person would look for them and the app object stays where
# every other module expects to import it from.
app.router.lifespan_context = _lifespan


if __name__ == "__main__":
    import uvicorn

    # 0.0.0.0 and $PORT, both required by every container host. Bound to
    # localhost with a fixed port, the process starts, passes its own health
    # check from inside, and is unreachable from outside -- which reads as a
    # networking problem rather than a one-line bind problem.
    uvicorn.run(
        app,
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        log_level="warning",
    )
