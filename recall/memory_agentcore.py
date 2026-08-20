"""AgentCore Memory backend for the person graph.

Same `PersonStore` contract as `LocalPersonStore`, so nothing in the graph
changes when this is switched on via RECALL_MEMORY=agentcore.

NOT YET EXERCISED AGAINST A LIVE MEMORY RESOURCE -- it is written against the
AgentCore Memory API but has only been run through the local backend's tests.
Verify it with a throwaway memory resource before relying on it in a demo, and
keep RECALL_MEMORY=local as the fallback that is known to work.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import date

from recall.state import PersonRecord

NAMESPACE = "recall/person-graph"


class AgentCoreMemoryStore:
    """Long-term memory backed by an AgentCore Memory resource.

    Records are stored as JSON events in a single namespace and retrieved with
    the service's semantic search, which is the one real upgrade over the local
    store: it matches "the GIC quant infra woman" to a stored "Wei Lin" without
    a shared token, which lexical recall cannot do.
    """

    def __init__(self, memory_id: str | None = None, actor_id: str | None = None) -> None:
        from bedrock_agentcore.memory import MemoryClient

        from recall._common import DEFAULT_REGION

        self.memory_id = memory_id or os.environ["AGENTCORE_MEMORY_ID"]
        self.actor_id = actor_id or os.environ.get("RECALL_ACTOR_ID", "default-user")
        self.session_id = os.environ.get("RECALL_SESSION_ID", "person-graph")
        self._client = MemoryClient(region_name=DEFAULT_REGION)

    def search(self, query: str, *, limit: int = 5) -> list[PersonRecord]:
        try:
            hits = self._client.retrieve_memories(
                memory_id=self.memory_id,
                namespace=NAMESPACE,
                query=query,
                top_k=limit,
            )
        except Exception:  # noqa: BLE001 - memory is an optimisation, not a hard dep
            return []
        return [rec for rec in (_decode(h) for h in hits) if rec is not None]

    def get(self, record_id: str) -> PersonRecord | None:
        for rec in self.search(record_id, limit=10):
            if rec.get("id") == record_id:
                return rec
        return None

    def upsert(self, record: PersonRecord) -> PersonRecord:
        today = date.today().isoformat()
        rid = record.get("id") or f"p_{uuid.uuid4().hex[:8]}"
        existing = self.get(rid) or {}

        merged: PersonRecord = {**existing, **{k: v for k, v in record.items() if v is not None}}
        merged["id"] = rid
        merged.setdefault("first_seen", existing.get("first_seen", today))
        merged["last_seen"] = today
        for field in ("aliases", "met_at", "notes"):
            seen: set[str] = set()
            out: list[str] = []
            for item in list(existing.get(field, [])) + list(record.get(field, []) or []):
                key = item.strip().lower()
                if item.strip() and key not in seen:
                    seen.add(key)
                    out.append(item.strip())
            merged[field] = out

        self._client.create_event(
            memory_id=self.memory_id,
            actor_id=self.actor_id,
            session_id=self.session_id,
            messages=[(json.dumps(merged), "ASSISTANT")],
        )
        return merged

    def all(self) -> list[PersonRecord]:
        """Not supported -- AgentCore Memory is a retrieval surface, not a table.

        Only the summary/debug paths want a full listing, and they can run against
        the local backend.
        """
        return []


def _decode(hit: object) -> PersonRecord | None:
    text = hit
    if isinstance(hit, dict):
        text = hit.get("content") or hit.get("text") or ""
        if isinstance(text, dict):
            text = text.get("text", "")
    try:
        rec = json.loads(text)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return rec if isinstance(rec, dict) and "id" in rec else None
