"""Calendar writes for commitment follow-ups.

Backend is chosen by RECALL_CALENDAR:
  local (default) -- append to data/calendar.json. Free, offline, demo-safe.
  mcp             -- Google Calendar MCP server named by GCAL_MCP_COMMAND.

Both paths share the same idempotency guard: an event key derived from the
commitment text, so re-running the same memo (which happens constantly during a
demo) updates nothing instead of stacking duplicate events.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, timedelta
from pathlib import Path

from langchain_core.tools import tool

LEDGER_PATH = Path(os.environ.get("RECALL_CALENDAR_PATH", "data/calendar.json"))


def idempotency_key(person_name: str, what: str, due: str | None) -> str:
    """Stable key for one commitment. Same promise -> same key -> one event."""
    raw = f"{person_name.strip().lower()}|{what.strip().lower()}|{due or ''}"
    return "recall-" + hashlib.sha1(raw.encode()).hexdigest()[:16]


@tool
def create_followup_event(
    person_name: str, what: str, due: str | None = None, channel: str = "email"
) -> str:
    """Put a follow-up commitment on the user's calendar as a dated reminder.

    Call this once per commitment the user made to a person. Safe to call twice
    with the same arguments -- duplicates are detected and skipped.

    Args:
        person_name: Who the follow-up is owed to.
        what: The promised action, short imperative, e.g. "send the Kestrel repo".
        due: ISO date YYYY-MM-DD. Omit if the memo gave no timing; a default of
            three days out will be used.
        channel: email, linkedin, whatsapp, call, or other.

    Returns a one-line status starting with CREATED, DUPLICATE, or ERROR.
    """
    result = write_event(person_name, what, due, channel)
    return f"{result['status'].upper()}: {result['detail']}"


def write_event(
    person_name: str, what: str, due: str | None = None, channel: str = "email"
) -> dict:
    """Direct-call form used by the graph node. Never raises -- errors come back
    in the returned dict so the node can record them and move on."""
    when = due or (date.today() + timedelta(days=3)).isoformat()
    title = f"Follow up with {person_name}: {what}"
    key = idempotency_key(person_name, what, due)
    event = {
        "title": title,
        "date": when,
        "person_name": person_name,
        "idempotency_key": key,
        "channel": channel,
    }

    backend = os.environ.get("RECALL_CALENDAR", "local").lower()
    try:
        if backend == "mcp":
            return _write_mcp(event)
        return _write_local(event)
    except Exception as exc:  # noqa: BLE001
        return {**event, "status": "error", "detail": f"{type(exc).__name__}: {exc}"}


def _load_ledger() -> list[dict]:
    if LEDGER_PATH.exists():
        return json.loads(LEDGER_PATH.read_text() or "{}").get("events", [])
    return []


def _write_local(event: dict) -> dict:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    events = _load_ledger()
    if any(e.get("idempotency_key") == event["idempotency_key"] for e in events):
        return {**event, "status": "duplicate", "detail": f"already on calendar: {event['title']}"}
    events.append(event)
    LEDGER_PATH.write_text(json.dumps({"events": events}, indent=2))
    return {**event, "status": "created", "detail": f"{event['date']} - {event['title']}"}


def _write_mcp(event: dict) -> dict:
    """Write through the Google Calendar MCP server.

    The idempotency check still runs against the local ledger first: it is a
    cheap exact-match guard, and it means a re-run does not need a round-trip
    to the calendar API just to discover the event already exists.
    """
    events = _load_ledger()
    if any(e.get("idempotency_key") == event["idempotency_key"] for e in events):
        return {**event, "status": "duplicate", "detail": f"already on calendar: {event['title']}"}

    command = os.environ.get("GCAL_MCP_COMMAND")
    if not command:
        return {
            **event,
            "status": "error",
            "detail": "RECALL_CALENDAR=mcp but GCAL_MCP_COMMAND is unset.",
        }

    from recall.mcp_client import call_mcp_tool

    detail = call_mcp_tool(
        command=command,
        tool_name=os.environ.get("GCAL_MCP_TOOL", "create-event"),
        arguments={
            "summary": event["title"],
            "start": {"date": event["date"]},
            "end": {"date": event["date"]},
            "description": f"Auto-created by Recall. key={event['idempotency_key']}",
        },
    )
    if detail.startswith("ERROR:"):
        return {**event, "status": "error", "detail": detail}

    events.append(event)
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEDGER_PATH.write_text(json.dumps({"events": events}, indent=2))
    return {**event, "status": "created", "detail": f"{event['date']} - {event['title']}"}
