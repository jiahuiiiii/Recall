"""calendar_write -- commitments become dated reminders.

Every write goes through an idempotency key derived from the commitment text,
because a demo gets re-run five times in a row and a calendar with five copies
of the same reminder is the thing the audience remembers.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from recall.state import RecallState
from recall.tools.calendar import write_event


def calendar_node(state: RecallState) -> dict:
    """Return `calendar_events`, one per commitment, each with a status."""
    commitments = state.get("commitments") or []
    if not commitments:
        return {"calendar_events": []}

    events = []
    errors = []
    for c in commitments:
        result = write_event(
            person_name=c["person_name"],
            what=c["what"],
            due=c.get("due"),
            channel=c.get("channel", "email"),
        )
        events.append(result)
        if result["status"] == "error":
            errors.append(f"calendar write failed: {result['detail']}")

    created = sum(1 for e in events if e["status"] == "created")
    dupes = sum(1 for e in events if e["status"] == "duplicate")
    return {
        "calendar_events": events,
        "errors": errors,
        "messages": [
            AIMessage(
                content=f"Calendar: {created} created, {dupes} already present, "
                f"{len(events) - created - dupes} failed."
            )
        ],
    }
