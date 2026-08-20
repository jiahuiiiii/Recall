"""enricher -- an isolated sub-agent with web access.

Runs as its own agent loop, not as a tool call on the main graph, because search
results are long, noisy, and mostly wrong on the first query. Keeping that
trial-and-error inside a sub-agent means the supervisor's context only ever sees
the three-line answer. This is the Deep Agent supervisor pattern; flattening it
puts several thousand tokens of scraped HTML into every subsequent step.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from recall._common import chat_model
from recall.state import RecallState
from recall.tools.web import fetch_page, web_search

# Hard cap on the sub-agent loop. Enrichment is nice-to-have; it must never be
# the reason a demo run hangs. The cap is the safety net, not exception handling.
MAX_STEPS = 8

SYSTEM = """You are a research assistant. You are given one person that the user \
just met, with whatever context the user recorded about them.

Find publicly available professional background on this person: current employer, \
role, notable prior work, public writing or talks.

Method:
- Search for the name together with the company or field. A bare common name \
returns the wrong human -- if you cannot tell whether a result is the same person, \
it is not usable.
- Two or three searches maximum. Fetch a page only if a snippet is promising but \
too short to confirm.
- Stop as soon as you can either confirm facts or conclude nothing reliable exists.

Output: RETURN CONCISE FACTS ONLY. At most four short bullet points, each one \
verifiable from what you found. No preamble, no "I searched for", no speculation, \
no restating what the user already told you. If you found nothing you can attribute \
to this specific person with confidence, reply with exactly:
NO RELIABLE PUBLIC INFORMATION FOUND."""


def enrich_node(state: RecallState) -> dict:
    """Enrich every person in `new_people`. Returns `enrichments` keyed by name."""
    new_people = state.get("new_people") or []
    if not new_people:
        return {}

    from langgraph.prebuilt import create_react_agent

    agent = create_react_agent(
        chat_model(label="enricher", temperature=0.0, max_tokens=1024),
        tools=[web_search, fetch_page],
        prompt=SYSTEM,
    )

    enrichments: dict[str, str] = {}
    errors: list[str] = []

    for person in new_people:
        brief = _brief(person)
        try:
            result = agent.invoke(
                {"messages": [HumanMessage(content=brief)]},
                config={"recursion_limit": MAX_STEPS * 2},
            )
            answer = result["messages"][-1].content
            if isinstance(answer, list):  # Bedrock returns content blocks
                answer = " ".join(
                    b.get("text", "") for b in answer if isinstance(b, dict)
                ).strip()
            enrichments[person["name"]] = (answer or "").strip()
        except Exception as exc:  # noqa: BLE001
            # A failed sub-agent degrades the record, it does not fail the run.
            msg = f"enrichment failed for {person['name']}: {type(exc).__name__}: {exc}"
            errors.append(msg)
            enrichments[person["name"]] = "ENRICHMENT UNAVAILABLE"

    found = sum(
        1
        for v in enrichments.values()
        if v and not v.startswith(("NO RELIABLE", "ENRICHMENT UNAVAILABLE"))
    )
    return {
        "enrichments": enrichments,
        "errors": errors,
        "messages": [
            AIMessage(
                content=f"Enriched {found}/{len(new_people)} new contacts from public sources."
            )
        ],
    }


def _brief(person: dict) -> str:
    return (
        f"Person: {person.get('name')}\n"
        f"Company: {person.get('company') or 'unknown'}\n"
        f"Role: {person.get('role') or 'unknown'}\n"
        f"Met at: {person.get('met_at') or 'unknown'}\n"
        f"What the user said about them: {person.get('notes') or ''}"
    )
