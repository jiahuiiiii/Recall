"""dedupe -- RAG over the stored person graph, then the conditional edge.

This node plus `route_after_dedupe` are the load-bearing agentic part of the
graph: the same memo can produce both new and known people, and each takes a
different path. Do not collapse this into the extraction prompt -- extraction
sees only the memo, dedupe sees the memo AND everything remembered from previous
sessions, which is the only reason the agent can claim to remember anyone.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from recall._common import cached_system, chat_model
from recall.memory import get_store
from recall.state import MatchDecision, RecallState

MATCH_THRESHOLD = 0.7

SYSTEM = """You decide whether a person just mentioned in a voice memo is someone \
already in the user's contact history, or a new person.

You are given one newly-extracted person and a short list of stored records that \
share some words with them. Decide if the new person is the SAME HUMAN as one of \
the stored records.

Treat as the same person:
- Same name spelled differently, or a speech-recognition variant ("Wei Lin" / "Way Lin").
- A nickname or shortened form paired with a matching employer, role, or event.
- Same distinctive employer and role even when the name is only partially given \
("the GIC quant infra woman" vs a stored "Wei Lin, GIC, quant infrastructure").

Treat as different people:
- Same common first name with nothing else in common. Two different "Alex"es are \
two people until something corroborates.
- Same employer but a clearly different name or role. Big companies have many staff.

Bias toward `is_match: false` when nothing but a common name lines up. A wrong merge \
silently destroys a real contact record; a wrong split is visible and easy to fix."""


def dedupe_node(state: RecallState) -> dict:
    """Split `people` into `new_people` and `known_matches`."""
    people = state.get("people") or []
    if not people:
        return {"new_people": [], "known_matches": []}

    store = get_store()
    # temperature=0: routing decision. This chooses which branch of the graph
    # runs, so it has to be reproducible.
    llm = chat_model(label="dedupe", temperature=0.0).with_structured_output(MatchDecision)

    new_people: list[dict] = []
    known_matches: list[dict] = []

    for person in people:
        query = " ".join(
            filter(
                None,
                [
                    person.get("name", ""),
                    person.get("company") or "",
                    person.get("role") or "",
                    " ".join(person.get("aliases") or []),
                ],
            )
        )
        candidates = store.search(query, limit=5)

        if not candidates:
            # Nothing in memory even lexically close -- no model call needed.
            # Skipping the LLM here is most of the dedupe cost on a fresh graph.
            new_people.append(person)
            continue

        decision: MatchDecision = llm.invoke(
            [
                SystemMessage(content=cached_system(SYSTEM)),
                HumanMessage(content=_prompt(person, candidates)),
            ]
        )

        matched_id = decision.candidate_id if decision.is_match else None
        valid = matched_id is not None and store.get(matched_id) is not None
        if valid and decision.confidence >= MATCH_THRESHOLD:
            known_matches.append(
                {
                    "person": person,
                    "record_id": matched_id,
                    "confidence": decision.confidence,
                    "reasoning": decision.reasoning,
                }
            )
        else:
            new_people.append(person)

    return {
        "new_people": new_people,
        "known_matches": known_matches,
        "messages": [
            AIMessage(
                content=(
                    f"Dedupe: {len(new_people)} new, {len(known_matches)} already known "
                    f"({', '.join(m['person']['name'] for m in known_matches) or 'none'})."
                )
            )
        ],
    }


def _prompt(person: dict, candidates: list[dict]) -> str:
    lines = ["NEWLY MENTIONED PERSON:", _fmt_person(person), "", "STORED RECORDS:"]
    for rec in candidates:
        lines.append(
            f"- id: {rec['id']}\n"
            f"  name: {rec.get('name')}\n"
            f"  company: {rec.get('company')}\n"
            f"  role: {rec.get('role')}\n"
            f"  aliases: {', '.join(rec.get('aliases', [])) or 'none'}\n"
            f"  met at: {'; '.join(rec.get('met_at', [])) or 'unknown'}\n"
            f"  notes: {' | '.join(rec.get('notes', []))[:400]}"
        )
    lines.append("\nIs the newly mentioned person one of these stored records?")
    return "\n".join(lines)


def _fmt_person(person: dict) -> str:
    return (
        f"  name: {person.get('name')}\n"
        f"  company: {person.get('company')}\n"
        f"  role: {person.get('role')}\n"
        f"  aliases: {', '.join(person.get('aliases') or []) or 'none'}\n"
        f"  met at: {person.get('met_at')}\n"
        f"  notes: {(person.get('notes') or '')[:400]}"
    )


def route_after_dedupe(state: RecallState) -> list[str]:
    """The conditional edge. New people get enriched, known people get merged.

    Returns a LIST because one memo routinely contains both -- LangGraph fans out
    to every named node and the join waits for all of them. Returning a single
    branch here would silently drop half the memo.
    """
    targets: list[str] = []
    if state.get("new_people"):
        targets.append("enrich")
    if state.get("known_matches"):
        targets.append("merge")
    return targets or ["commitments"]
