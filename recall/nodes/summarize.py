"""summary -- what the user actually reads at the end of a run.

Deterministic formatting, no model call. This is the demo's payoff screen; it
has to render identically every time and cost nothing. A model here would add a
call, a failure mode, and a chance of hallucinating a commitment that is not in
state, in exchange for prose nobody asked for.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from recall._common import LEDGER
from recall.state import RecallState


def summarize_node(state: RecallState) -> dict:
    lines: list[str] = []

    new_people = state.get("new_people") or []
    known = state.get("known_matches") or []
    enrichments = state.get("enrichments") or {}

    lines.append("=" * 68)
    lines.append("RECALL")
    lines.append("=" * 68)

    if new_people:
        lines.append(f"\nNEW CONTACTS ({len(new_people)})")
        for p in new_people:
            where = f" - met at {p['met_at']}" if p.get("met_at") else ""
            lines.append(f"  * {p['name']}{_affil(p)}{where}")
            enrichment = enrichments.get(p["name"], "")
            if enrichment and not enrichment.startswith(("NO RELIABLE", "ENRICHMENT UNAVAILABLE")):
                for bullet in [b.strip(" -*\t") for b in enrichment.splitlines() if b.strip()]:
                    lines.append(f"      + {bullet}")

    if known:
        lines.append(f"\nALREADY KNEW ({len(known)})")
        for m in known:
            lines.append(
                f"  * {m['person']['name']} - merged into existing record "
                f"({m['confidence']:.0%} confident: {m['reasoning']})"
            )

    commitments = state.get("commitments") or []
    if commitments:
        lines.append(f"\nCOMMITMENTS ({len(commitments)})")
        for c in commitments:
            due = c.get("due") or "no date given"
            lines.append(f"  * {c['person_name']}: {c['what']}  [{due}, {c.get('channel','email')}]")

    events = state.get("calendar_events") or []
    if events:
        lines.append("\nCALENDAR")
        for e in events:
            lines.append(f"  [{e['status']}] {e.get('detail', '')}")

    drafts = state.get("drafts") or []
    if drafts:
        lines.append(f"\nDRAFTED FOLLOW-UPS ({len(drafts)})")
        for d in drafts:
            lines.append(f"\n  --- to {d['person_name']} via {d.get('channel', 'email')} ---")
            if d.get("subject"):
                lines.append(f"  Subject: {d['subject']}")
            for line in d["body"].splitlines():
                lines.append(f"  {line}")

    errors = state.get("errors") or []
    if errors:
        lines.append(f"\nISSUES ({len(errors)})")
        for e in errors:
            lines.append(f"  ! {e}")

    if not (new_people or known or commitments):
        lines.append("\nNothing found in this memo.")

    lines.append("\n" + "-" * 68)
    lines.append(LEDGER.report())

    summary = "\n".join(lines)
    return {"summary": summary, "messages": [AIMessage(content=summary)]}


def _affil(person: dict) -> str:
    bits = [b for b in (person.get("role"), person.get("company")) if b]
    return f" ({' at '.join(bits)})" if bits else ""
