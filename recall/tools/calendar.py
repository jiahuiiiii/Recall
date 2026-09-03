"""Calendar writes for commitment follow-ups.

Backend is chosen by RECALL_CALENDAR:
  local (default) -- append to data/calendar.json. Free, offline, demo-safe.
  ics             -- write a .ics file the user opens in whatever calendar they
                     already use. No credentials, no API, no setup for anybody.
  google          -- the connected Google account, over OAuth. For the hosted
                     deployment; the user consents once in a browser.
  mcp             -- Google Calendar MCP server named by GCAL_MCP_COMMAND.

`ics` is the one that works for someone who is not you. `mcp` needs a Google
Cloud project and an OAuth client per machine, which is a developer credential,
not a distribution mechanism -- see README. An .ics file imports into Google,
Apple, Outlook and everything else, and it keeps the project's standing rule
that we propose and the human commits: the event lands only when they open it.

Both paths share the same idempotency guard: an event key derived from the
commitment text, so re-running the same memo (which happens constantly during a
demo) updates nothing instead of stacking duplicate events.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from langchain_core.tools import tool

LEDGER_PATH = Path(os.environ.get("RECALL_CALENDAR_PATH", "data/calendar.json"))

# Where .ics files land. One file per event, named by its idempotency key, so a
# re-run overwrites rather than accumulates and the web route can find one by key.
ICS_DIR = Path(os.environ.get("RECALL_ICS_DIR", "data/ics"))

# An idempotency key, and the only shape allowed to name a file or reach the
# .ics route. Keys are generated, never user input -- but the web server maps a
# URL segment onto a path with this, and "generated" stops being true the moment
# someone types the URL themselves.
KEY_RE = re.compile(r"^recall-[0-9a-f]{16}$")


def idempotency_key(
    person_name: str, what: str, due: str | None, kind: str = "followup"
) -> str:
    """Stable key for one entry. Same promise -> same key -> one event.

    `kind` joins the key only when it is NOT "followup", so every key generated
    before `attending` existed still hashes to the same value. Folding it in
    unconditionally would change every existing key at once, and a ledger full
    of keys that no longer match means the next run re-creates every event the
    user already has.
    """
    raw = f"{person_name.strip().lower()}|{what.strip().lower()}|{due or ''}"
    if kind != "followup":
        raw = f"{kind}|{raw}"
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


def backend_name() -> str:
    """Which calendar a write would land on. Shown on the confirmation."""
    return os.environ.get("RECALL_CALENDAR", "local").lower()


def propose_event(
    person_name: str,
    what: str,
    due: str | None = None,
    channel: str = "email",
    kind: str = "followup",
) -> dict:
    """The event a commitment *would* create. Pure -- no I/O, nothing written.

    Split out from `write_event` so the confirmation step can show exactly what
    is about to happen: same title, same date, same idempotency key. A
    confirmation that paraphrases the event is a confirmation of something the
    user did not actually approve.

    Repeatable, which matters more than it looks: `calendar_node` calls this
    above its `interrupt()`, and LangGraph re-executes the node from the top on
    resume. The key is derived from `due` rather than the resolved date, so a
    run that spans midnight still produces the same key it showed you.
    """
    when = due or (date.today() + timedelta(days=3)).isoformat()
    # A promise and a party are both a dated entry, and that is where the
    # similarity stops. "Follow up with Crispy: Acacia Welcome Night" is not
    # what the speaker said, and a reminder that marks you busy all day is worse
    # than no reminder -- so the title and the free/busy state both branch here.
    title = what if kind == "attending" else f"Follow up with {person_name}: {what}"
    return {
        "title": title,
        "date": when,
        "person_name": person_name,
        "kind": kind,
        "idempotency_key": idempotency_key(person_name, what, due, kind),
        "channel": channel,
    }


def _esc(text: str) -> str:
    """Escape one TEXT value per RFC 5545 section 3.3.11.

    Order matters: backslash first, or the escapes we add get escaped again. A
    promise like "send the deck, the pricing, and the demo" contains commas,
    which are FIELD SEPARATORS in iCalendar -- unescaped, the summary silently
    truncates at the first one and the user gets an event called "Follow up with
    Alex Chua: send the deck".
    """
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """Wrap at 75 octets with a leading space on continuations (RFC 5545 3.1).

    Folded on BYTES, not characters: the limit is octets, and splitting a
    multi-byte character in half produces a file that some parsers reject and
    others render as mojibake. Our titles carry names, so this is not theoretical.
    """
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    out, chunk = [], b""
    for ch in line:
        enc = ch.encode("utf-8")
        limit = 75 if not out else 74  # continuations lose one octet to the space
        if len(chunk) + len(enc) > limit:
            out.append(chunk.decode("utf-8"))
            chunk = b""
        chunk += enc
    if chunk:
        out.append(chunk.decode("utf-8"))
    return "\r\n ".join(out)


def ics_text(event: dict) -> str:
    """One event as an iCalendar file. Pure -- no I/O, no clock beyond DTSTAMP.

    Deliberately an all-day event: a commitment is "by Friday", not "at 14:30",
    and inventing a time would put a meeting in someone's day that they never
    agreed to. Nothing here needs a timezone, which removes the single largest
    source of .ics bugs.

    **DTEND is exclusive.** An all-day event on the 11th ends on the 12th. Set
    both to the same date and Google renders it, Apple renders it, and Outlook
    drops it -- the kind of bug you only find on someone else's phone.

    The UID is the idempotency key, so importing the same file twice UPDATES the
    event instead of duplicating it. That is the same guarantee the local ledger
    gives us, enforced by the calendar client rather than by us.
    """
    start = date.fromisoformat(event["date"])
    attending = event.get("kind") == "attending"
    with_whom = (event.get("person_name") or "").strip()
    if attending:
        described = (
            f"With {with_whom}. Captured by Recall." if with_whom
            else "Captured by Recall."
        )
    else:
        described = (
            f"Follow up owed to {with_whom} "
            f"via {event.get('channel') or 'email'}. Captured by Recall."
        )
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Recall//Follow-up//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{event['idempotency_key']}@recall.local",
        f"DTSTAMP:{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}",
        f"DTSTART;VALUE=DATE:{start.strftime('%Y%m%d')}",
        f"DTEND;VALUE=DATE:{(start + timedelta(days=1)).strftime('%Y%m%d')}",
        f"SUMMARY:{_esc(event['title'])}",
        f"DESCRIPTION:{_esc(described)}",
        # A follow-up is a nudge and must not mark you busy; an event you said
        # you are going to should. Getting this backwards is why reminder apps
        # make people look unavailable all week.
        "TRANSP:OPAQUE" if attending else "TRANSP:TRANSPARENT",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    # CRLF, not \n. RFC 5545 requires it; most clients forgive it and Outlook
    # does not, which means the one you cannot test is the one that breaks.
    return "\r\n".join(_fold(x) for x in lines) + "\r\n"


def ics_path(key: str) -> Path | None:
    """Where the .ics for this key lives, or None if the key is not one of ours."""
    return ICS_DIR / f"{key}.ics" if KEY_RE.match(key or "") else None


def gcal_link(event: dict) -> str:
    """A Google Calendar "add event" URL for this event, prefilled.

    A .ics attachment is the correct, universal artifact -- but a chat app opens
    it however it likes, and "however it likes" is often a text preview with no
    add-to-calendar prompt. A link sidesteps the file handler entirely: one tap
    opens Google's own event screen with a Save button, the same on phone and
    desktop. We send both -- the link for the common case, the file for whoever
    lives in Apple Calendar or Outlook.

    All-day, and `dates` is start/end with the end EXCLUSIVE -- the same rule the
    .ics follows, and the same one Google's own export uses. A single date for
    both renders as a zero-length event some clients drop.
    """
    from datetime import date, timedelta
    from urllib.parse import urlencode

    start = date.fromisoformat(event["date"])
    end = start + timedelta(days=1)
    attending = event.get("kind") == "attending"
    with_whom = (event.get("person_name") or "").strip()
    details = (
        (f"With {with_whom}. " if with_whom else "") + "Captured by Recall."
        if attending
        else f"Follow up owed to {with_whom}. Captured by Recall."
    )
    params = urlencode(
        {
            "action": "TEMPLATE",
            "text": event.get("title", "Follow-up"),
            "dates": f"{start.strftime('%Y%m%d')}/{end.strftime('%Y%m%d')}",
            "details": details,
        }
    )
    return f"https://calendar.google.com/calendar/render?{params}"


def write_proposed(event: dict) -> dict:
    """Write an event already built by `propose_event`. Never raises.

    Takes the built event rather than the arguments so that what gets written
    is the object the human saw, not a rebuild of it.
    """
    try:
        backend = backend_name()
        if backend == "mcp":
            return _write_mcp(event)
        if backend == "ics":
            return _write_ics(event)
        if backend == "google":
            return _write_google(event)
        return _write_local(event)
    except Exception as exc:  # noqa: BLE001
        return {**event, "status": "error", "detail": f"{type(exc).__name__}: {exc}"}


def write_event(
    person_name: str,
    what: str,
    due: str | None = None,
    channel: str = "email",
    kind: str = "followup",
) -> dict:
    """Direct-call form used by the tool. Never raises -- errors come back
    in the returned dict so the caller can record them and move on."""
    return write_proposed(propose_event(person_name, what, due, channel, kind))


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


def _write_ics(event: dict) -> dict:
    """Render the event to a .ics file and report where it went.

    The file is ALWAYS written, even when the ledger already knows this event.
    Status and artifact answer different questions -- "is this new to me?" and
    "can the user get the file?" -- and suppressing the write on a re-run means
    a user who deleted the download cannot get it back without editing JSON.
    Rewriting is safe: same key, same filename, same content bar the DTSTAMP.
    """
    path = ICS_DIR / f"{event['idempotency_key']}.ics"
    path.parent.mkdir(parents=True, exist_ok=True)
    # newline="" so Python does not translate our CRLFs into CRCRLF on Windows.
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(ics_text(event))

    events = _load_ledger()
    if any(e.get("idempotency_key") == event["idempotency_key"] for e in events):
        return {**event, "status": "duplicate", "ics_path": str(path),
                "detail": f"already captured: {event['title']}"}

    events.append({**event, "ics_path": str(path)})
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEDGER_PATH.write_text(json.dumps({"events": events}, indent=2))
    return {**event, "status": "created", "ics_path": str(path),
            "detail": f"{event['date']} - {event['title']}"}


def _write_google(event: dict) -> dict:
    """Write to the connected Google account. See web/google_calendar.py.

    Ledger first, same as every other backend: a re-run should not need a round
    trip to Google to discover it already made this event. Google's own event id
    is the second guard, so a double-tap cannot duplicate even if the ledger is
    lost with the container.
    """
    events = _load_ledger()
    if any(e.get("idempotency_key") == event["idempotency_key"] for e in events):
        return {**event, "status": "duplicate", "detail": f"already on calendar: {event['title']}"}

    from web.google_calendar import create_event

    link = create_event(event)

    events.append({**event, "link": link})
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEDGER_PATH.write_text(json.dumps({"events": events}, indent=2))
    return {**event, "status": "created", "link": link,
            "detail": f"{event['date']} - {event['title']}"}


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
