"""extract_commitments, then the drafter sub-agent.

Two nodes, not one prompt. Commitment extraction is a temperature-0 structured
read of what was actually promised; drafting is generative writing in someone
else's voice. Fusing them makes the model invent commitments to justify the
messages it wants to write -- which is exactly the failure that looks worst on
stage.
"""

from __future__ import annotations

from datetime import date

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from recall._common import cached_system, chat_model
from recall.state import CommitmentExtraction, DraftBundle, RecallState

COMMITMENT_SYSTEM = """You extract things worth putting on a calendar from a voice \
memo recorded after a networking event.

Two kinds, and `kind` says which.

kind = "followup" -- something THE SPEAKER said they would do for, or send to, \
someone they met. "I said I'd send her the Kestrel repo." "I promised to intro him \
to Marcus." "Told her I'd follow up next week."
  `person_name` is who it is owed to. `what` is the action, short imperative.

kind = "attending" -- a named event the speaker said they are GOING to, on a date. \
"I'm going to the Acacia Welcome Night on the 18th with Crispy and Kit Yee." \
"Dinner with the GIC team on Thursday."
  `what` is the EVENT NAME as spoken -- "Acacia Welcome Night", not "go to the \
Acacia Welcome Night". `person_name` is who they are going with, or "" if nobody \
was named. `channel` is irrelevant; leave it at the default.
  ONE entry per event, never one per companion. Going somewhere with three \
people is one entry whose `person_name` lists all three, separated by ", ".

Extract neither of:
- Things the OTHER person promised to do. Those are theirs, not the speaker's.
- Vague warmth with no action: "we should catch up sometime", "great chat, will \
stay in touch".
- Things the speaker already did before recording the memo.
- An event with NO date and no way to resolve one. A calendar entry needs a day.

For `due`: resolve relative language against TODAY'S DATE, given below, and emit an \
absolute YYYY-MM-DD date. "Next week" -> the Monday of next week. "Tomorrow" -> \
tomorrow's date. For an "attending" entry this is the date of the event itself. If \
no timing was given at all, leave it null rather than guessing.

For `channel`: use what the speaker implied. Default to email when unclear."""

DRAFTER_SYSTEM = """You write follow-up messages in the user's own voice, ready to send.

You get: who they met, what they talked about, anything found publicly about that \
person, and what the user promised to do.

Voice: how a competent professional actually writes the day after meeting someone. \
Warm but not effusive. Short sentences. Contractions. No corporate throat-clearing.

Hard rules:
- Open by referencing something specific and true from the conversation. Never \
"It was great connecting with you" as the first line -- that is the sentence that \
tells the reader this was automated.
- Deliver on the commitment in the message itself, or say precisely when it is \
coming. That is the entire point of the message.
- Use enriched public facts only where they are natural and flattering. Do not \
recite someone's resume back at them; it reads as surveillance.
- Under 120 words for email. Under 60 for LinkedIn or WhatsApp.
- No placeholders like [Your Name] or [link]. If a detail is genuinely missing, \
write around it.
- Sign off with nothing but a first-name-level closing; the sender's name is added \
by their mail client."""


def commitments_node(state: RecallState) -> dict:
    """Return `commitments`: what the speaker promised, with absolute dates."""
    transcript = (state.get("transcript") or "").strip()
    people = state.get("people") or []
    if not transcript or not people:
        return {"commitments": []}

    llm = chat_model(label="commitments", temperature=0.0).with_structured_output(
        CommitmentExtraction
    )
    names = ", ".join(p["name"] for p in people)
    result: CommitmentExtraction = llm.invoke(
        [
            SystemMessage(content=cached_system(COMMITMENT_SYSTEM)),
            HumanMessage(
                content=(
                    f"TODAY'S DATE: {date.today().isoformat()}\n"
                    f"PEOPLE IN THIS MEMO: {names}\n\n"
                    f"TRANSCRIPT:\n{transcript}"
                )
            ),
        ]
    )
    commitments = _collapse_attending([c.model_dump() for c in result.commitments])
    return {
        "commitments": commitments,
        "messages": [AIMessage(content=f"Found {len(commitments)} commitments.")],
    }


def _collapse_attending(commitments: list[dict]) -> list[dict]:
    """One event, one entry -- however many people you said you were going with.

    Observed, not hypothetical: "going to the Acacia Welcome Night with Crispy
    and Kit Yee" produced TWO `attending` entries with identical name and date,
    and because `person_name` is part of the idempotency key they were not
    duplicates of each other -- so the same party landed on the calendar twice.

    A follow-up is per person and must NOT be collapsed: two promises to two
    people on the same day are two obligations. Only `attending` merges, keyed
    on the event and its date.

    The prompt asks for one entry too. This is the guard, because a model told
    to be careful was observed not being careful -- and the failure was a
    duplicate calendar entry, which is invisible until it is on your phone.
    """
    out: list[dict] = []
    seen: dict[tuple[str, str], dict] = {}
    for c in commitments:
        if c.get("kind", "followup") != "attending":
            out.append(c)
            continue
        key = (c.get("what", "").strip().lower(), c.get("due") or "")
        first = seen.get(key)
        if first is None:
            seen[key] = c
            out.append(c)
            continue
        # Keep both companions, in the order they were spoken, without repeats.
        names = [n for n in (first.get("person_name") or "").split(", ") if n]
        extra = (c.get("person_name") or "").strip()
        if extra and extra not in names:
            names.append(extra)
        first["person_name"] = ", ".join(names)
    return out


def drafter_node(state: RecallState) -> dict:
    """The drafter sub-agent. Returns `drafts`, one per person with a commitment.

    Isolated context by design: it is handed a purpose-built brief rather than
    the running message history, so the supervisor's bookkeeping chatter cannot
    bleed into the writing voice.
    """
    # Only follow-ups. There is nothing to send about a party you are going to,
    # and a drafter handed one writes a message to somebody about their own
    # plans -- fluent, confident, and addressed to nobody.
    commitments = [
        c for c in (state.get("commitments") or []) if c.get("kind", "followup") == "followup"
    ]
    if not commitments:
        return {"drafts": []}

    # The one place sampling is allowed -- identical phrasing across every
    # follow-up is what makes automated outreach obvious. Kept low so the
    # commitment details stay faithful.
    llm = chat_model(label="drafter", temperature=0.4, max_tokens=2048).with_structured_output(
        DraftBundle
    )
    result: DraftBundle = llm.invoke(
        [
            SystemMessage(content=cached_system(DRAFTER_SYSTEM)),
            HumanMessage(content=_brief(state)),
        ]
    )
    drafts = [d.model_dump() for d in result.drafts]
    return {
        "drafts": drafts,
        "messages": [AIMessage(content=f"Drafted {len(drafts)} follow-up messages.")],
    }


def _brief(state: RecallState) -> str:
    """Assemble exactly what the drafter needs and nothing else.

    Heavy payloads stay in state; this carries the relevant slice, which is what
    keeps the drafter's prompt small enough to be worth caching.
    """
    enrichments = state.get("enrichments") or {}
    people = {p["name"]: p for p in (state.get("people") or [])}
    known = {m["person"]["name"] for m in (state.get("known_matches") or [])}

    blocks: list[str] = []
    by_person: dict[str, list[dict]] = {}
    for c in state.get("commitments") or []:
        if c.get("kind", "followup") != "followup":
            continue
        by_person.setdefault(c["person_name"], []).append(c)

    for name, person_commitments in by_person.items():
        person = people.get(name, {})
        enrichment = enrichments.get(name, "")
        usable = enrichment and not enrichment.startswith(
            ("NO RELIABLE", "ENRICHMENT UNAVAILABLE")
        )
        promised = "\n".join(
            f"  - {c['what']}" + (f" (by {c['due']})" if c.get("due") else "")
            for c in person_commitments
        )
        blocks.append(
            f"PERSON: {name}\n"
            f"Company/role: {person.get('company') or 'unknown'} / {person.get('role') or 'unknown'}\n"
            f"Met at: {person.get('met_at') or 'unknown'}\n"
            f"Relationship: {'met before, already a contact' if name in known else 'first meeting'}\n"
            f"What we talked about: {'; '.join(person.get('notes') or [])}\n"
            f"Public background found: {enrichment if usable else 'none found'}\n"
            f"Channel: {person_commitments[0].get('channel', 'email')}\n"
            f"I promised to:\n{promised}"
        )

    return (
        "Write one follow-up message per person below.\n\n"
        + "\n\n---\n\n".join(blocks)
    )
