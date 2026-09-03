"""calendar_write -- commitments become dated reminders, once you approve them.

Every write goes through an idempotency key derived from the commitment text,
because a demo gets re-run five times in a row and a calendar with five copies
of the same reminder is the thing the audience remembers.

**The confirmation.** On an interactive run this node stops and shows what it is
about to put on your calendar; nothing is written until you say which of them to
add. That is the same shape as the clarifying question -- `interrupt()`, resumed
through `/api/answer` -- reused rather than reinvented, so there is one pause
mechanism in the graph and not two.

Non-interactive runs (CLI, eval, tests) write everything, exactly as before.
The switch is `configurable.interactive`, never the presence of a checkpointer.

**Everything above the `interrupt()` call must be pure**, because LangGraph
re-executes the node from the top on resume. `propose_event` is pure for that
reason; `write_proposed` is the only thing that touches the calendar and it runs
strictly after the pause. Get that backwards and a declined event still lands.
"""

from __future__ import annotations

import re

from langchain_core.messages import AIMessage
from langgraph.types import interrupt

from recall.state import RecallState, is_interactive
from recall.tools.calendar import backend_name, propose_event, write_proposed

# Replies that mean "all of them" and "none of them". Generous on purpose: this
# value arrives from a browser, and a confirmation that only accepts one exact
# spelling fails closed on a typo.
_YES = {"all", "yes", "y", "ok", "okay", "add", "create", "*"}
_NO = {"none", "no", "n", "skip", "cancel", "nothing"}


def approved_indices(reply, count: int) -> set[int]:
    """Which proposed events the human approved.

    Accepts what the UI sends and what a person might reasonably type: `"all"`,
    `"none"`, a list of ints, or `"0,2"` / `"0 2"`.

    **An unrecognised reply approves nothing.** The alternative -- defaulting to
    "write everything" -- would mean a malformed answer silently puts events on
    someone's real Google Calendar, which is the exact outcome this gate exists
    to prevent. Declining is visible in the summary and costs one re-run; the
    other way round is not visible at all.
    """
    if reply is None:
        return set()
    if isinstance(reply, bool):
        return set(range(count)) if reply else set()
    if isinstance(reply, (list, tuple, set)):
        return {i for i in (_as_index(x) for x in reply) if i is not None and 0 <= i < count}

    text = str(reply).strip().lower()
    if text in _YES:
        return set(range(count))
    if text in _NO or not text:
        return set()
    return {
        i
        for tok in re.split(r"[,\s]+", text)
        if (i := _as_index(tok)) is not None and 0 <= i < count
    }


def _as_index(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def calendar_node(state: RecallState, config=None) -> dict:
    """Return `calendar_events`, one per commitment, each with a status.

    Statuses: `created`, `duplicate`, `error`, and `declined` -- the last one
    meaning you were asked and said no. A declined event is recorded rather than
    dropped, because "nothing appeared on my calendar" should be answerable from
    the run, not a mystery.
    """
    commitments = state.get("commitments") or []
    if not commitments:
        return {"calendar_events": []}

    # ---- pure: this all runs again on resume -------------------------------
    proposals = [
        propose_event(
            person_name=c["person_name"],
            what=c["what"],
            due=c.get("due"),
            channel=c.get("channel", "email"),
            # Older runs and hand-built commitments have no `kind`; they are
            # follow-ups, which is what the field defaulted to before it existed.
            kind=c.get("kind", "followup"),
        )
        for c in commitments
    ]

    if is_interactive(config):
        # ---- the pause ----
        reply = interrupt(
            {
                "type": "confirm_events",
                "backend": backend_name(),
                "events": [{"index": i, **p} for i, p in enumerate(proposals)],
            }
        )
        approved = approved_indices(reply, len(proposals))
    else:
        # Nobody to ask. Unchanged behaviour: the CLI, the eval harness and the
        # tests all depend on this path writing without stopping.
        approved = set(range(len(proposals)))

    # ---- effects: strictly after the pause ---------------------------------
    events: list[dict] = []
    errors: list[str] = []
    for i, proposal in enumerate(proposals):
        if i not in approved:
            events.append(
                {**proposal, "status": "declined",
                 "detail": f"not added - you declined: {proposal['title']}"}
            )
            continue
        result = write_proposed(proposal)
        events.append(result)
        if result["status"] == "error":
            errors.append(f"calendar write failed: {result['detail']}")

    return {
        "calendar_events": events,
        "errors": errors,
        "messages": [AIMessage(content=_summary(events))],
    }


def _summary(events: list[dict]) -> str:
    counts = {k: sum(1 for e in events if e["status"] == k)
              for k in ("created", "duplicate", "declined", "error")}
    parts = [f"{counts['created']} created"]
    if counts["duplicate"]:
        parts.append(f"{counts['duplicate']} already present")
    if counts["declined"]:
        parts.append(f"{counts['declined']} declined")
    if counts["error"]:
        parts.append(f"{counts['error']} failed")
    return "Calendar: " + ", ".join(parts) + "."
