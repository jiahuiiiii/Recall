"""The person graph -- long-term memory across sessions.

Memory is what makes dedupe possible and what proves the agent remembers, so it
gets a real interface rather than a dict tucked inside the graph.

`PersonStore` is the contract. `LocalPersonStore` (JSON on disk + lexical recall)
is what runs during local dev; `AgentCoreMemoryStore` swaps in for deploy without
any node changing. Nodes only ever see the protocol.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Protocol

from recall.contacts import as_contacts
from recall.state import PersonRecord, as_list
from recall.text import match_strength as _match_strength
from recall.text import tokens as _tokens

# A query token must match something at least this well before a record is even
# considered a candidate. One contained match (0.75) clears it; incidental
# similarity does not.
MIN_MATCH_STRENGTH = 0.6


def _log_notes(existing_log: object, notes: list[str], today: str) -> list[dict]:
    """Keep a dated line per note, alongside `notes` rather than inside it.

    The detail panel had no date to show because `notes` is a flat `list[str]`
    with no provenance, so twelve notes from two memos rendered as twelve
    separate occasions. This records when each note first appeared.

    **Deliberately parallel, not a schema change.** `notes` is read as a flat
    list of strings by `resolve.compare` (token overlap), `merge`, `persist` and
    the eval; turning its entries into objects moves the resolution benchmark.
    A display-only log costs a little duplication and cannot touch the numbers.
    The real fix is the dated `attribute_edge` in Future work.

    Notes already logged keep their original date -- a fact does not become
    newer because the person was mentioned again.
    """
    seen = {}
    for entry in (existing_log or []):
        if isinstance(entry, dict) and entry.get("text"):
            seen.setdefault(entry["text"], entry.get("at") or today)
    # Ordered by `notes`, so the log and the list can never disagree on order,
    # and a note deleted from `notes` drops out of the log by construction.
    return [{"text": n, "at": seen.get(n, today)} for n in notes]


class PersonStore(Protocol):
    """Swappable long-term memory over the person graph."""

    def search(self, query: str, *, limit: int = 5) -> list[PersonRecord]:
        """Return candidate records that might be the same human as `query`.

        Recall matters far more than precision here: this only narrows the field
        for the dedupe node, which does the actual adjudication with a model.
        """

    def get(self, record_id: str) -> PersonRecord | None: ...

    def upsert(self, record: PersonRecord) -> PersonRecord:
        """Merge a record in. List fields ACCUMULATE -- meeting someone twice
        deepens their record rather than replacing last time's notes.

        One call counts as one encounter: `times_met` goes up by one unless the
        incoming record sets it explicitly."""

    def replace(self, record: PersonRecord) -> PersonRecord:
        """Overwrite a record wholesale, list fields included.

        Needed by consolidation, which rewrites `notes` and `met_at` to a shorter
        deduplicated set. Routing that through `upsert` would append the tidied
        version to the untidy one and double the record instead of fixing it."""

    def merge(self, source_id: str, target_id: str) -> PersonRecord:
        """Fold one person into another and delete the source. Returns the
        survivor. The absorbed name must end up in the survivor's `aliases` or
        the next mention re-creates the duplicate."""

    def delete(self, record_id: str) -> bool:
        """Remove a person. Returns False if they were not there.

        The agent will occasionally record someone it should not have, and a
        contact book you cannot correct is one you stop trusting."""

    def all(self) -> list[PersonRecord]: ...


class LocalPersonStore:
    """JSON-file person graph with lexical candidate recall.

    Deliberately not a vector DB yet. Candidate recall over a few hundred people
    is a name/company string-match problem, and a real embedding index would add
    a second Bedrock model-access dependency (Titan) for no measurable gain at
    demo scale. The `search` signature is the same one an embedding store needs,
    so switching is a class swap, not a refactor.
    """

    def __init__(self, path: str | os.PathLike[str] = "data/person_graph.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, PersonRecord] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            raw = json.loads(self.path.read_text() or "{}")
            self._records = {r["id"]: r for r in raw.get("people", [])}

    def _flush(self) -> None:
        self.path.write_text(
            json.dumps({"people": list(self._records.values())}, indent=2)
        )

    def search(self, query: str, *, limit: int = 5) -> list[PersonRecord]:
        q = _tokens(query)
        if not q:
            return []
        scored: list[tuple[float, PersonRecord]] = []
        for rec in self._records.values():
            haystack = " ".join(
                filter(
                    None,
                    [
                        rec.get("name", ""),
                        rec.get("company") or "",
                        rec.get("role") or "",
                        " ".join(rec.get("aliases", [])),
                        " ".join(rec.get("met_at", [])),
                        " ".join(rec.get("notes", [])),
                        # `contacts` is deliberately NOT here. This haystack
                        # feeds candidate retrieval for dedupe, so anything
                        # added to it moves the resolution benchmark -- and a
                        # handle is the wrong evidence anyway: two records
                        # sharing a phone number is a data-entry mistake, not a
                        # reason to believe they are one person. Searching by
                        # handle is a UI filter (`shared.js::haystack`), not a
                        # resolver input.
                    ],
                )
            )
            h = _tokens(haystack)
            if not h:
                continue
            strength = _match_strength(q, h)
            # One decent token match minimum. Generous is the goal -- the model
            # adjudicates afterwards -- but returning every record for every
            # query costs a model call per person and tells the adjudicator
            # nothing.
            if strength < MIN_MATCH_STRENGTH:
                continue
            # Name hits are worth far more than note-body hits: two people can
            # both be "on the 18th floor", only one is "Kit Yee".
            name_strength = _match_strength(q, _tokens(rec.get("name", "")))
            score = strength / len(q) + name_strength * 2.0
            scored.append((score, rec))
        scored.sort(key=lambda s: -s[0])
        return [rec for _, rec in scored[:limit]]

    def get(self, record_id: str) -> PersonRecord | None:
        return self._records.get(record_id)

    def upsert(self, record: PersonRecord) -> PersonRecord:
        today = datetime.now().astimezone().date().isoformat()
        rid = record.get("id") or f"p_{uuid.uuid4().hex[:8]}"
        existing = self._records.get(rid, {})
        merged: PersonRecord = {**existing, **{k: v for k, v in record.items() if v is not None}}
        merged["id"] = rid
        merged.setdefault("first_seen", existing.get("first_seen", today))
        merged["last_seen"] = today
        # List fields accumulate rather than overwrite -- meeting someone twice
        # should deepen the record, not replace last time's notes with this time's.
        for field in ("aliases", "met_at", "notes"):
            merged[field] = _dedupe_keep_order(
                as_list(existing.get(field)) + as_list(record.get(field))
            )
        merged["note_log"] = _log_notes(existing.get("note_log"), merged["notes"], today)
        # Contacts merge per CHANNEL, not wholesale: `{**existing, **record}`
        # above would let a write carrying only a phone number erase a stored
        # Instagram handle. Same accumulate-don't-replace contract as the list
        # fields -- so `upsert` can add or correct a handle but can never clear
        # one. Clearing goes through `replace`, which is what the UI patches.
        merged["contacts"] = {
            **as_contacts(existing.get("contacts")),
            **as_contacts(record.get("contacts")),
        }
        # One upsert is one occasion. `persist` runs once per new person per
        # memo and `merge` once per re-encounter, so this is the only place that
        # sees every meeting -- and the only honest source for a count. The UI
        # used to show len(met_at), which is the number of distinct PLACES after
        # deduplication: three memos about the same person in the same hall
        # collapse to one entry and the card read "1 meeting" forever.
        # An explicit value on the incoming record wins, for merge and backfill.
        merged["times_met"] = (
            int(record["times_met"]) if record.get("times_met") is not None
            else int(existing.get("times_met") or 0) + 1
        )
        self._records[rid] = merged
        self._flush()
        return merged

    def replace(self, record: PersonRecord) -> PersonRecord:
        rid = record.get("id")
        if not rid or rid not in self._records:
            raise KeyError(f"cannot replace unknown record {rid!r}")
        today = datetime.now().astimezone().date().isoformat()
        merged: PersonRecord = {**record, "id": rid}
        # `replace` is an edit, never an occasion, so the count neither rises nor
        # resets. A caller that round-trips the record keeps its own value; one
        # that builds a partial record keeps the stored one instead of zeroing it.
        #
        # `last_seen` follows the same rule, and used to be stamped with today
        # unconditionally. That meant deleting a note, or re-tagging the graph,
        # rewrote when you last saw someone -- one tag refresh flattened every
        # person to the same date and made "recently seen" sorting meaningless.
        # A real occasion goes through `upsert`, which does stamp it.
        if merged.get("last_seen") is None:
            merged["last_seen"] = self._records[rid].get("last_seen") or today
        if merged.get("times_met") is None:
            merged["times_met"] = int(self._records[rid].get("times_met") or 1)
        # Deleting a note through the UI goes through replace(); the log has to
        # lose it too or the detail panel keeps rendering what the user removed.
        # Prefer the log on the INCOMING record: the UI round-trips the record it
        # fetched, and a caller rewriting the log means it. Falling back to the
        # stored one silently discarded any log the caller had just set.
        merged["note_log"] = _log_notes(
            record.get("note_log") or self._records[rid].get("note_log"),
            as_list(merged.get("notes")), today
        )
        # Wholesale, because `replace` is the edit path: a channel the caller
        # left out is a channel the user cleared. Normalised here rather than
        # trusted, so a pasted profile URL becomes a handle exactly once.
        merged["contacts"] = as_contacts(merged.get("contacts"))
        self._records[rid] = merged
        self._flush()
        return merged

    def merge(self, source_id: str, target_id: str) -> PersonRecord:
        """Fold `source` into `target` and delete it. Returns the survivor.

        The graph will get people wrong -- a nickname it did not recognise, a
        return it missed -- and a contact book you cannot correct is one you
        stop trusting. `delete()` alone cannot express "these two are the same
        human"; it just loses one of them.

        **The absorbed name becomes an alias, and that is the point.** Merging
        "Crispy" into "Tiu Chuei Enn" without recording "Crispy" tidies the
        display and changes nothing: `compare()` reads `name` and `aliases`, so
        the next memo saying "Crispy" files the duplicate all over again. The
        merge is how the user teaches the resolver.
        """
        src, tgt = self._records.get(source_id), self._records.get(target_id)
        if not src or not tgt:
            missing = source_id if not src else target_id
            raise KeyError(f"cannot merge unknown record {missing!r}")
        if source_id == target_id:
            raise ValueError("cannot merge a record into itself")

        merged: PersonRecord = {**tgt}
        merged["aliases"] = _dedupe_keep_order(
            as_list(tgt.get("aliases")) + [src.get("name", "")] + as_list(src.get("aliases"))
        )
        for field in ("met_at", "notes"):
            merged[field] = _dedupe_keep_order(as_list(tgt.get(field)) + as_list(src.get(field)))
        # Dates span both records: this person was first seen whenever the
        # earlier of the two was, not whenever the survivor happened to be.
        for field, pick in (("first_seen", min), ("last_seen", max)):
            vals = [v for v in (tgt.get(field), src.get(field)) if v]
            if vals:
                merged[field] = pick(vals)
        merged["note_log"] = _log_notes(
            (tgt.get("note_log") or []) + (src.get("note_log") or []),
            merged["notes"],
            merged.get("last_seen") or datetime.now().astimezone().date().isoformat(),
        )
        # Both records were the same human all along, so both records' occasions
        # were occasions with them. Defaults to 1 apiece for records written
        # before the counter existed.
        merged["times_met"] = int(tgt.get("times_met") or 1) + int(src.get("times_met") or 1)
        # The survivor's own handles win a clash -- two records for one human
        # can hold two numbers, and the one the user kept is the one they chose
        # to keep. The source only fills channels the survivor had empty, so a
        # merge never loses the only Telegram handle in the graph.
        merged["contacts"] = {
            **as_contacts(src.get("contacts")),
            **as_contacts(tgt.get("contacts")),
        }

        self._records[target_id] = merged
        self._trash(src)
        del self._records[source_id]
        self._flush()
        return merged

    def _trash(self, record: PersonRecord) -> None:
        """Append a record to a trash file before it is destroyed.

        A merge is irreversible and destroys more than deleting a note does. The
        graph is a JSON file with no history, so without this a mis-merge is
        gone. Best-effort: failing to write the trash must never block the merge
        the user asked for."""
        try:
            path = self.path.with_name(self.path.stem + ".trash.json")
            old = json.loads(path.read_text()) if path.exists() else []
            old.append({
                "discarded_at": datetime.now().astimezone().date().isoformat(),
                "record": record,
            })
            path.write_text(json.dumps(old, indent=2))
        except OSError:
            pass

    def delete(self, record_id: str) -> bool:
        if record_id not in self._records:
            return False
        del self._records[record_id]
        self._flush()
        return True

    def all(self) -> list[PersonRecord]:
        return list(self._records.values())


def _dedupe_keep_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip().lower()
        if item.strip() and key not in seen:
            seen.add(key)
            out.append(item.strip())
    return out


def get_store() -> PersonStore:
    """Pick the memory backend. Local for dev, AgentCore once deployed.

    Set RECALL_MEMORY=agentcore (plus AGENTCORE_MEMORY_ID) to switch.
    """
    backend = os.environ.get("RECALL_MEMORY", "local").lower()
    if backend == "agentcore":
        from recall.memory_agentcore import AgentCoreMemoryStore

        return AgentCoreMemoryStore()
    return LocalPersonStore(os.environ.get("RECALL_STORE_PATH", "data/person_graph.json"))
