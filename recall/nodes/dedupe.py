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
from recall.resolve import Zone, confidence_from, decide
from recall.state import MatchDecision, RecallState, is_interactive

CANDIDATE_LIMIT = 5
MAX_HYPOTHESES = 5      # cap from the spec: enumerate at most 5 for a question

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


def dedupe_node(state: RecallState, config=None) -> dict:
    """Split `people` into `new_people`, `known_matches` and `ambiguous`.

    The zone is decided by pure arithmetic in `recall.resolve` — no model call.
    That is deliberate: which band a mention falls in is the project's central
    decision, so it has to be reproducible and unit-testable rather than a
    model's mood on the day.

    The AMBIGUOUS band is where a clarifying question belongs, and **who settles
    it depends on whether a human is reachable**:

    - **Interactive** (`configurable.interactive`, i.e. the web UI): the mention
      is HELD. It goes into `ambiguous` and into neither `new_people` nor
      `known_matches`, so nothing downstream acts on it. `ask_node` places it,
      using the human's answer for the one it asks about. Without this the
      question is decorative — the adjudicator would have already decided, and
      the answer could only ever agree or be overruled after the fact.
    - **Non-interactive** (CLI, eval, tests): the LLM adjudicator settles it
      immediately, exactly as before. Nobody is there to ask.

    `_adjudicate` runs either way. In the interactive case its verdict is the
    fallback for the ambiguous mentions the one-question budget did not cover —
    an unasked mention still has to go somewhere, and a model's guess beats
    filing a known person as a stranger.
    """
    interactive = is_interactive(config)
    people = state.get("people") or []
    if not people:
        return {"new_people": [], "known_matches": [], "ambiguous": []}

    store = get_store()
    new_people: list[dict] = []
    known_matches: list[dict] = []
    ambiguous: list[dict] = []

    for person in people:
        candidates = store.search(_query(person), limit=CANDIDATE_LIMIT)
        if not candidates:
            new_people.append(person)
            continue

        band, ranked = decide(person, candidates)

        if band is Zone.RESOLVED:
            top = ranked[0]
            known_matches.append(_match(person, top.record_id, top.score,
                                        band, top.agreement.explain()))
            continue

        if band is Zone.NEW:
            new_people.append(person)
            continue

        # AMBIGUOUS. Hypotheses are the live candidates plus "this is someone
        # new", which is always a possibility and must be in the set a question
        # discriminates over.
        entry = {
            "person": person,
            "hypotheses": [
                {"record_id": c.record_id, "name": c.name,
                 "score": round(c.score, 3), "explain": c.agreement.explain()}
                for c in ranked[:MAX_HYPOTHESES - 1]
            ] + [{"record_id": "", "name": "someone new", "score": 0.0, "explain": "no prior record"}],
            "resolved_to": None,
        }

        record_id = _adjudicate(person, ranked, store)
        entry["resolved_to"] = record_id
        # Carry the score the adjudicator's pick had, so `ask_node` can place
        # this mention later without re-running the band.
        if record_id:
            top = next((c for c in ranked if c.record_id == record_id), ranked[0])
            entry["fallback"] = _match(person, record_id, top.score, band,
                                       top.agreement.explain())
        ambiguous.append(entry)

        if interactive:
            # Held. `ask_node` decides where this goes.
            continue

        if record_id:
            known_matches.append(entry["fallback"])
        else:
            new_people.append(person)

    note = (
        f"Resolve: {len(new_people)} new, {len(known_matches)} known, "
        f"{len(ambiguous)} ambiguous"
        + (" (held for the question)" if interactive and ambiguous else "")
    )
    if known_matches:
        note += f" ({', '.join(m['person']['name'] for m in known_matches)})"
    return {
        "new_people": new_people,
        "known_matches": known_matches,
        "ambiguous": ambiguous,
        "messages": [AIMessage(content=note + ".")],
    }


def _query(person: dict) -> str:
    return " ".join(
        filter(None, [
            person.get("name", ""),
            person.get("company") or "",
            person.get("role") or "",
            " ".join(person.get("aliases") or []),
            " ".join(person.get("notes") or [])[:200],
        ])
    )


def _match(person: dict, record_id: str, score: float, band: Zone, why: str) -> dict:
    return {
        "person": person,
        "record_id": record_id,
        "confidence": confidence_from(score),
        "reasoning": why,
        "score": round(score, 3),
        "zone": band.value,
    }


def _adjudicate(person: dict, ranked, store) -> str | None:
    """Interim tie-break for the ambiguous band, replaced by the EIG question.

    Returns a record id, or None for "new person". A failure here must not kill
    the run — an unresolved ambiguous mention is simply treated as new, which is
    the recoverable direction.
    """
    llm = chat_model(label="dedupe", temperature=0.0).with_structured_output(MatchDecision)
    records = [store.get(c.record_id) for c in ranked]
    records = [r for r in records if r]
    try:
        decision: MatchDecision = llm.invoke([
            SystemMessage(content=cached_system(SYSTEM)),
            HumanMessage(content=_prompt(person, records)),
        ])
    except Exception:  # noqa: BLE001
        return None
    if decision.is_match and decision.candidate_id and store.get(decision.candidate_id):
        return decision.candidate_id
    return None


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
        f"  notes: {' | '.join(person.get('notes') or [])[:400]}"
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
