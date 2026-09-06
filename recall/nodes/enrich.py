"""enricher -- an isolated sub-agent with web access.

Runs as its own agent loop, not as a tool call on the main graph, because search
results are long, noisy, and mostly wrong on the first query. Keeping that
trial-and-error inside a sub-agent means the supervisor's context only ever sees
the three-line answer. This is the Deep Agent supervisor pattern; flattening it
puts several thousand tokens of scraped HTML into every subsequent step.
"""

from __future__ import annotations

import os
import re

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

Output format, exactly:
- At most four short bullet points, each verifiable from what you found. No preamble,
  no "I searched for", no speculation, no restating what the user already told you.
- Then a final line naming the ONE detail from the user's own notes that proves these
  results are the same human:

    CONFIRMED BY: <employer, role, or event from the user's notes that the sources match>

The confirming detail must come from the user's notes and must actually appear in the
sources you found. "Same first name" is not confirmation. "Works at a big company that
employs thousands" is not confirmation. If the user only gave you a first name and a
well-known employer, you almost certainly found a different person -- say so.

If you cannot produce that line honestly, reply with exactly:
NO RELIABLE PUBLIC INFORMATION FOUND.

Reporting nothing is a correct and useful answer. Attaching a stranger's biography to
the user's contact is the worst outcome available to you."""


def enrich_node(state: RecallState) -> dict:
    """Enrich every person in `new_people`. Returns `enrichments` keyed by name."""
    new_people = state.get("new_people") or []
    if not new_people:
        return {}

    # Synthetic demo identities can collide with real people in public search.
    # The demo is about resolution and EIG, not enrichment, so it opts out
    # explicitly rather than risking a stranger's biography or a slow tool loop.
    if os.environ.get("RECALL_SKIP_ENRICHMENT", "").strip().lower() in {
        "1", "true", "yes",
    }:
        return {
            "enrichments": {
                person["name"]: "NO RELIABLE PUBLIC INFORMATION FOUND."
                for person in new_people
            },
            "messages": [AIMessage(content="Public enrichment skipped for this demo.")],
        }

    from langgraph.prebuilt import create_react_agent

    agent = create_react_agent(
        chat_model(label="enricher", temperature=0.0, max_tokens=1024),
        tools=[web_search, fetch_page],
        prompt=SYSTEM,
    )

    enrichments: dict[str, str] = {}
    errors: list[str] = []

    for person in new_people:
        # Nothing to disambiguate on -- a bare first name matches thousands of
        # people and the search will always surface a confident-looking wrong one.
        # Skipping is strictly better than enriching badly.
        if not (person.get("company") or person.get("role")):
            enrichments[person["name"]] = "NO RELIABLE PUBLIC INFORMATION FOUND."
            continue

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
            enrichments[person["name"]] = _verify(person, (answer or "").strip())
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


def _verify(person: dict, answer: str) -> str:
    """Discard enrichment that cannot name a corroborating detail from the memo.

    The prompt asks for a CONFIRMED BY line; this checks it is real rather than
    decorative. A model told to be careful is still sometimes not careful, and the
    failure is invisible -- a fluent, specific, entirely wrong biography. So the
    contract is enforced in code: no verifiable corroboration, no enrichment.
    """
    if not answer or answer.startswith("NO RELIABLE"):
        return "NO RELIABLE PUBLIC INFORMATION FOUND."

    marker = "CONFIRMED BY:"
    if marker not in answer.upper():
        return "NO RELIABLE PUBLIC INFORMATION FOUND."

    idx = answer.upper().rindex(marker)
    body, evidence = answer[:idx].strip(), answer[idx + len(marker):].strip()
    if not body or not evidence:
        return "NO RELIABLE PUBLIC INFORMATION FOUND."

    # The cited evidence must actually echo what the user told us. This is what
    # rules out "confirmed by: his first name is Daniel".
    known = " ".join(
        filter(None, [person.get("company") or "", person.get("role") or "", person.get("met_at") or ""])
    ).lower()
    known_tokens = _significant(known)
    evidence_tokens = _significant(evidence.lower())
    if not (known_tokens & evidence_tokens):
        return "NO RELIABLE PUBLIC INFORMATION FOUND."

    return body


# Short filler that would otherwise create a bogus overlap between the memo and
# whatever the model wrote on the CONFIRMED BY line.
_FILLER = {
    "the", "and", "for", "his", "her", "its", "was", "who", "she", "they", "them",
    "same", "person", "name", "named", "works", "work", "role", "met", "with",
    "this", "that", "from", "at", "in", "on", "of", "a", "an", "is", "are",
}


def _significant(text: str) -> set[str]:
    """Content words worth matching on.

    The length floor has to stay at 3 characters, not 4: GIC, DBS, AWS and IBM are
    exactly the distinctive employers that corroborate an identity, and excluding
    them would silently reject every correct enrichment for people at three-letter
    companies. Filler is removed by name instead of by length.
    """
    return {t for t in re.findall(r"[a-z0-9]+", text) if len(t) >= 3 and t not in _FILLER}


def _brief(person: dict) -> str:
    return (
        f"Person: {person.get('name')}\n"
        f"Company: {person.get('company') or 'unknown'}\n"
        f"Role: {person.get('role') or 'unknown'}\n"
        f"Met at: {person.get('met_at') or 'unknown'}\n"
        f"What the user said about them: {'; '.join(person.get('notes') or [])}"
    )
