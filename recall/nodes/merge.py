"""merge -- fold a re-encountered person back into their stored record.

Set union plus a consolidation pass.

The union part is pure code: filling blanks and appending notes needs no model.
The consolidation part does use one, which reverses an earlier decision in this
file. The no-model version was shipped and observably failed: meeting the same
person four times produced four notes that each restated "studies computer
science", and two `met_at` entries for one occasion ("orientation camp" and
"orientation camp hosted by <full name>"). Exact-string dedupe cannot catch a
paraphrase, and the record degrades every time you meet someone again -- which
is precisely the case this product exists to handle.

The original objection stands though: a model here can rewrite history. So the
call is bounded -- it only runs when there is enough accumulation to be worth
it, and `_safe_consolidation` throws the result away if the model compressed
away substance instead of redundancy.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from recall._common import cached_system, chat_model
from recall.memory import get_store
from recall.state import as_list, ConsolidatedRecord, RecallState

# Below this there is nothing to consolidate, and the call would be pure cost.
CONSOLIDATE_AFTER_NOTES = 3
CONSOLIDATE_AFTER_PLACES = 2

# Consolidation should remove restatement, not content. Losing more than this
# much of the text means it summarised rather than deduplicated.
MIN_RETAINED_FRACTION = 0.45

SYSTEM = """You tidy the accumulated notes on one person in someone's contact book.

These notes were dictated across several occasions, so the same fact often appears \
more than once in slightly different words. Your job is to remove that repetition \
without losing anything.

Rules:
- ONE FACT PER ENTRY. Never join two facts into one entry with a semicolon or comma. \
If an incoming entry contains several facts, SPLIT it. The output usually has a \
similar number of entries to the input -- you are removing repeats, not compressing.
- Merge entries that say the SAME thing into a single entry, keeping the version \
with the most detail. "studies computer science" and "computer science, same major \
as me" are the same fact; keep the second, because it says more.
- Keep every distinct fact, plan, promise, opinion and personal detail. If two \
entries differ at all in substance, keep both.
- Preserve the speaker's own phrasing. Do not make it more formal, do not summarise, \
do not editorialise, do not add anything that is not already there.
- Chronology matters: keep entries in the order they first appeared, since earlier \
entries came from earlier occasions.
- For `met_at`, collapse different descriptions of the same occasion into the fullest \
one. Genuinely separate occasions stay separate.

You are deduplicating, not summarising. When in doubt, keep both entries."""


def merge_node(state: RecallState) -> dict:
    """Update stored records for `known_matches`. Returns the ids touched."""
    matches = state.get("known_matches") or []
    if not matches:
        return {}

    store = get_store()
    merged_ids: list[str] = []
    errors: list[str] = []
    tidied = 0

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
            "aliases": as_list(person.get("aliases")) + as_list(person.get("name")),
            "met_at": as_list(person.get("met_at")),
            "notes": as_list(person.get("notes")),
        }
        stored = store.upsert(update)

        consolidated = _consolidate(stored)
        if consolidated is not None:
            # Replace outright rather than append: upsert accumulates list fields,
            # so appending the tidied version would double the record instead of
            # tidying it.
            stored["notes"] = consolidated["notes"]
            stored["met_at"] = consolidated["met_at"]
            store.replace(stored)
            tidied += 1

        merged_ids.append(record["id"])

    names = ", ".join(m["person"]["name"] for m in matches)
    note = f"Merged {len(merged_ids)} known contacts: {names}."
    if tidied:
        note += f" Consolidated {tidied} record(s)."
    return {
        "persisted_ids": merged_ids,
        "errors": errors,
        "messages": [AIMessage(content=note)],
    }


def _consolidate(record: dict) -> dict | None:
    """Deduplicate one record's notes and meeting places. None means leave it alone."""
    notes = as_list(record.get("notes"))
    places = as_list(record.get("met_at"))
    if len(notes) < CONSOLIDATE_AFTER_NOTES and len(places) < CONSOLIDATE_AFTER_PLACES:
        return None

    # temperature=0: this rewrites stored history, so it must be reproducible.
    llm = chat_model(label="consolidate", temperature=0.0).with_structured_output(
        ConsolidatedRecord
    )
    try:
        result: ConsolidatedRecord = llm.invoke(
            [
                SystemMessage(content=cached_system(SYSTEM)),
                HumanMessage(content=_prompt(record, notes, places)),
            ]
        )
    except Exception:  # noqa: BLE001 - tidying is optional, the record is not
        return None

    return _safe_consolidation(notes, places, result)


def _safe_consolidation(
    notes: list[str], places: list[str], result: ConsolidatedRecord
) -> dict | None:
    """Reject a consolidation that lost substance rather than repetition.

    This is the guard on the concern that stopped merge using a model at all:
    a model asked to deduplicate will sometimes summarise instead, and the loss
    is silent and permanent -- the original notes are gone. Cheaper to keep a
    slightly repetitive record than to quietly destroy what the user said.
    """
    new_notes = [n.strip() for n in (result.notes or []) if n and n.strip()]
    new_places = [p.strip() for p in (result.met_at or []) if p and p.strip()]

    if notes and not new_notes:
        return None
    if len(new_notes) > len(notes) or len(new_places) > len(places):
        return None  # invented entries

    before = len(" ".join(notes))
    after = len(" ".join(new_notes))
    if before and after / before < MIN_RETAINED_FRACTION:
        return None

    return {"notes": new_notes, "met_at": new_places or places}


def _prompt(record: dict, notes: list[str], places: list[str]) -> str:
    lines = [f"PERSON: {record.get('name')}"]
    if record.get("company") or record.get("role"):
        lines.append(f"({record.get('role') or '?'} at {record.get('company') or '?'})")
    lines.append("\nNOTES, oldest first:")
    lines += [f"{i}. {n}" for i, n in enumerate(notes, 1)]
    lines.append("\nMET AT:")
    lines += [f"- {p}" for p in places] or ["- (none recorded)"]
    return "\n".join(lines)
