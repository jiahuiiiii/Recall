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
from datetime import date
from pathlib import Path
from typing import Iterable, Protocol

from recall.state import PersonRecord, as_list
from recall.text import match_strength as _match_strength, tokens as _tokens

# A query token must match something at least this well before a record is even
# considered a candidate. One contained match (0.75) clears it; incidental
# similarity does not.
MIN_MATCH_STRENGTH = 0.6


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
        deepens their record rather than replacing last time's notes."""

    def replace(self, record: PersonRecord) -> PersonRecord:
        """Overwrite a record wholesale, list fields included.

        Needed by consolidation, which rewrites `notes` and `met_at` to a shorter
        deduplicated set. Routing that through `upsert` would append the tidied
        version to the untidy one and double the record instead of fixing it."""

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
        today = date.today().isoformat()
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
        self._records[rid] = merged
        self._flush()
        return merged

    def replace(self, record: PersonRecord) -> PersonRecord:
        rid = record.get("id")
        if not rid or rid not in self._records:
            raise KeyError(f"cannot replace unknown record {rid!r}")
        merged: PersonRecord = {**record, "id": rid, "last_seen": date.today().isoformat()}
        self._records[rid] = merged
        self._flush()
        return merged

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
