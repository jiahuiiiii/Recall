"""merge -- fold a re-encountered person back into their stored record.

Deliberately no model call. Merging is set union over notes, aliases and events
plus filling in fields that were previously unknown; a model here would cost a
call per known contact and would occasionally rewrite history. The record's own
`upsert` already accumulates list fields, so this node's job is just deciding
what to hand it.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from recall.memory import get_store
from recall.state import RecallState


def merge_node(state: RecallState) -> dict:
    """Update stored records for `known_matches`. Returns the ids touched."""
    matches = state.get("known_matches") or []
    if not matches:
        return {}

    store = get_store()
    merged_ids: list[str] = []
    errors: list[str] = []

    for match in matches:
        record = store.get(match["record_id"])
        if record is None:
            errors.append(f"merge target {match['record_id']} disappeared from the store")
            continue

        person = match["person"]
        update = {
            "id": record["id"],
            # Fill blanks only. A memo saying nothing about employer must not
            # erase an employer we already knew.
            "company": record.get("company") or person.get("company"),
            "role": record.get("role") or person.get("role"),
            "aliases": list(person.get("aliases") or []) + ([person["name"]] if person.get("name") else []),
            "met_at": [person["met_at"]] if person.get("met_at") else [],
            "notes": [person["notes"]] if person.get("notes") else [],
        }
        store.upsert(update)
        merged_ids.append(record["id"])

    names = ", ".join(m["person"]["name"] for m in matches)
    return {
        "persisted_ids": merged_ids,
        "errors": errors,
        "messages": [
            AIMessage(content=f"Merged {len(merged_ids)} known contacts: {names}.")
        ],
    }
