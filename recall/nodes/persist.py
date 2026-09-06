"""persist -- new people enter the person graph.

Known people were already folded in by `merge`. This node handles the new ones,
attaching whatever the enricher found. After this runs, the next session's
dedupe can find them -- which is the entire proof that the agent remembers.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from recall.memory import get_store
from recall.state import RecallState, as_list


def persist_node(state: RecallState) -> dict:
    """Upsert `new_people` (+ enrichments) into long-term memory."""
    new_people = state.get("new_people") or []
    if not new_people:
        return {}

    store = get_store()
    enrichments = state.get("enrichments") or {}
    ids: list[str] = []

    for person in new_people:
        enrichment = enrichments.get(person["name"], "")
        usable = enrichment and not enrichment.startswith(
            ("NO RELIABLE", "ENRICHMENT UNAVAILABLE")
        )
        record = store.upsert(
            {
                "name": person["name"],
                "company": person.get("company"),
                "role": person.get("role"),
                "aliases": as_list(person.get("aliases")),
                "met_at": as_list(person.get("met_at")),
                "notes": as_list(person.get("notes")),
                "enrichment": enrichment if usable else None,
            }
        )
        ids.append(record["id"])

    return {
        "persisted_ids": ids,
        "messages": [AIMessage(content=f"Stored {len(ids)} new people in the person graph.")],
    }
