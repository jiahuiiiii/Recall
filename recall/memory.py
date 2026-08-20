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
import re
import uuid
from datetime import date
from pathlib import Path
from typing import Iterable, Protocol

from recall.state import PersonRecord

_STOPWORDS = {
    "the", "a", "an", "and", "at", "of", "in", "on", "for", "to", "with",
    "from", "she", "he", "they", "her", "his", "their", "is", "was", "said",
    "met", "who", "that", "it", "i",
}


def _tokens(text: str) -> set[str]:
    return {
        t for t in re.findall(r"[a-z0-9]+", (text or "").lower())
        if t not in _STOPWORDS and len(t) > 1
    }


class PersonStore(Protocol):
    """Swappable long-term memory over the person graph."""

    def search(self, query: str, *, limit: int = 5) -> list[PersonRecord]:
        """Return candidate records that might be the same human as `query`.

        Recall matters far more than precision here: this only narrows the field
        for the dedupe node, which does the actual adjudication with a model.
        """

    def get(self, record_id: str) -> PersonRecord | None: ...

    def upsert(self, record: PersonRecord) -> PersonRecord: ...

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
            overlap = len(q & h)
            if not overlap:
                continue
            # Name-token hits are worth far more than note-body hits: two people
            # can both be "hiring in Singapore", only one is "Wei Lin".
            name_hits = len(q & _tokens(rec.get("name", "")))
            score = overlap / len(q) + name_hits * 2.0
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
                list(existing.get(field, [])) + list(record.get(field, []) or [])
            )
        self._records[rid] = merged
        self._flush()
        return merged

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
