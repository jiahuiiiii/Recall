# Recall: An AI Relationship Assistant for Sales Teams

## Overview

Recall helps salespeople turn informal conversations into organised, actionable customer relationships.

After a networking event, sales meeting, or casual introduction, a salesperson can immediately record a voice memo such as:

> “I met Sarah from GIC. She is hiring for a quant infrastructure role and asked me to send her the Kestrel product deck next week.”

Recall converts this unstructured memo into a structured contact record, remembers what was actually said, detects the follow-ups that were promised, and helps ensure those promises are kept.

## The Problem

Salespeople break promises they fully intended to keep, because:

- Follow-ups happen too late.
- Contact details and conversation context are not properly recorded.
- Important promises are forgotten.
- Existing contacts are accidentally duplicated.
- CRM systems are too time-consuming to update immediately after an event.
- Salespeople do not know which follow-up actions are most urgent.

The problem is not simply remembering who someone is. It is maintaining the relationship and acting at the right time.

## The Solution

Recall is a voice-first relationship memory for sales professionals.

Immediately after meeting someone, the salesperson records a short voice memo. Recall then:

1. Transcribes the voice recording.
2. Extracts the person, company, role, needs, interests, and commitments.
3. Determines whether the person is a new lead or an existing contact.
4. Asks a clarification question if the identity or information is uncertain.
5. Stores the information in a persistent relationship history.
6. Detects promised follow-up actions.
7. Creates a calendar reminder after user confirmation.
8. Drafts a personalised follow-up message.

## Example Workflow

A salesperson records:

> “I met Alex from Deloitte at the technology conference. He was interested in our data platform and asked me to send a demo link on Friday. I think I may have met him before, but I’m not sure.”

Recall may respond:

> “Is this the same Alex from Deloitte you met at the NUS networking event?”

After the user confirms, Recall updates the existing contact instead of creating a duplicate. It then identifies the commitment:

> “You promised to send Alex a demo link on Friday. Add a reminder to your calendar?”

Once confirmed, the calendar reminder is created and Recall prepares a follow-up draft using the conversation context.

## What Makes Recall Different

Recall is more than a voice-to-CRM tool.

Its key innovation is uncertainty-aware relationship memory. Instead of confidently making a potentially incorrect decision, Recall knows when it is unsure and asks the most useful clarification question.

For example, if two contacts have similar names, Recall does not automatically merge them. It evaluates the possible candidates and selects the question that would provide the most information.

This helps prevent:

- Incorrect contact merges.
- Duplicate customer records.
- Forgotten promises.
- Irrelevant or hallucinated customer information.

The system follows the principle:

> The model proposes; code verifies.

The AI extracts and interprets information, while deterministic logic handles identity matching, ambiguity detection, commitment extraction, and calendar confirmation.

## Freemium Business Model

Recall can begin as a personal relationship assistant and gradually become a professional sales productivity platform.

### Free Plan

The free plan helps users build the habit of recording conversations:

- Up to 50 contacts.
- Limited voice memos per month.
- Basic contact extraction.
- Basic duplicate detection.
- Limited clarification questions.
- Basic follow-up drafts.
- Calendar reminders with confirmation.
- Personal relationship timeline.

### Professional Plan

Once users have built a valuable relationship memory, they can upgrade for professional usage:

- Higher or unlimited contact capacity.
- More voice recordings.
- Full relationship history and search.
- Automatic commitment detection.
- Advanced follow-up tracking.
- Calendar integration.
- Web-based contact enrichment.
- Data export and backup.
- Priority processing.

The upgrade trigger is based on accumulated value rather than an arbitrary paywall:

> “Recall has remembered 47 people for you. Upgrade to continue building your professional relationship memory.”

Users should still be able to view and export their existing data even if they reach the free-plan limit.

### Team Plan

For sales teams, Recall can expand into a shared workspace with:

- Shared customer records.
- Lead ownership.
- Team follow-up visibility.
- Sales activity tracking.
- CRM integrations such as HubSpot or Salesforce.
- Administrative controls.
- Team-level analytics.

## Hackathon MVP

The MVP should focus on one complete and convincing scenario:

1. A salesperson records a post-event voice memo.
2. Recall extracts the person, what they need, and what was promised to them.
3. Recall identifies an existing contact or asks a clarification question.
4. Recall detects a specific promise.
5. The user confirms a calendar reminder.
6. Recall generates a personalised follow-up draft.
7. The relationship timeline is updated.

This demonstrates a clear outcome, and it is deliberately phrased as the outcome for
the person on the other side of the conversation:

> You keep the promises you made.

That is a sales result and a decent one at the same time, which is why it is the framing
used throughout. Recall is never positioned as a way to extract value from contacts
later; the pitch is that the follow-up you promised actually arrives.

## Long-Term Vision

Recall can become a lightweight relationship operating system for sales professionals.

It starts with remembering people, then helps users understand their relationships, prioritise follow-ups, and consistently act on their commitments.

The long-term vision is:

> Every meaningful business conversation becomes remembered, understood, and followed up at the right time.

---

# How this document maps to the repo

_Moved out of `CLAUDE.md` so it loads with the document it is about._

`business.md` is a **positioning document, not a spec.** Read it that way before
building anything from it: most of what it describes is already built, one item is
genuinely valuable, several would move the benchmark, and the pitch framing contradicts
this file. Sorted by what each one actually costs.

### ~~One conflict that needs a human decision~~ — **DECIDED 2 Sep: promise-keeping**

`business.md` used to close on _"Recall prevents valuable sales opportunities from being
lost."_ **Pitch framing** in this file says never frame Recall as extracting value from
contacts later, because the brief asks for solutions that leave people genuinely better
off. Those were not the same story, and a judge reading the writeup after hearing the
pitch would have noticed.

**Settled the honest way: _"you keep the promises you made."_** A sales outcome and a
decency outcome at once, and what the frozen tail already does. `business.md` now closes
on that line and says outright that Recall is not positioned as a way to extract value
from contacts later; the README paragraph that flagged the conflict records the same
decision. The two documents agree, so **the conflict is closed — do not re-raise it, and
do not reintroduce opportunity-capture language into either one.**

The writeup never carried the old framing (checked: no occurrence of "sales",
"opportunity" or "promise" in `recall-writeup.pdf`), so nothing there needed changing.

### A. Already built — the task is to say so, not to build it

`business.md`'s "Hackathon MVP" is seven steps and **six of them ship today**, in the
tail this file freezes. Nothing here is a to-do:

| business.md step                         | Where it already lives                                 |
| ---------------------------------------- | ------------------------------------------------------ |
| Transcribe the memo                      | `nodes/transcribe.py`, Groq Whisper                    |
| Extract person, company, role, needs     | `nodes/extract.py` → `Person`                          |
| New lead or existing contact             | `resolve.py`, the three-zone band                      |
| Ask a clarification question when unsure | `eig.py` + `questions.py` + `ask_node` — **the claim** |
| Persistent relationship history          | `memory.py`, `note_log`, `times_met`                   |
| Detect promised follow-ups               | `nodes/followups.py::commitments_node` (frozen)        |
| Calendar reminder after confirmation     | `nodes/calendar.py`, `interrupt()` gate (frozen)       |
| Personalised follow-up draft             | `nodes/followups.py::drafter_node` (frozen)            |

The gap between `business.md` and the repo is **narrative, not code.** Do not re-derive
any of the above; do not "extend" the frozen tail to make it look more sales-shaped.

### B. Worth doing — cheap, and each one helps the defensible claim

1. **A professional-setting fixture** (`eval/fixtures/arc_sales.yaml`, ~10 memos, 8–10
   people). **The highest-value item in `business.md`,** and the only one that touches
   the benchmark in the right direction. All three current arcs are one hall or one OG,
   where everyone shares an event and nobody has a `company` — which is exactly the
   caveat under **The benchmark rests on one setting**. A sales arc populates `company`
   and `role`, so those channels finally _conflict_ rather than sitting silent, and
   `same_first_name` stops being the only professional data point in the whole eval.
   Validate with `check_fixtures.py`, then re-run both tables and quote the thresholds.
   Expect the numbers to move; that is the point of writing it.
2. **Re-skin the demo memos to the sales scenario** — `seed_demo.py`, `data/memos/`.
   Zero code. Day 1 logs Alex from Deloitte, day 2 is the ambiguous second Alex. The
   pipeline does not care what setting the memo is from, so this is text.
3. **`GET /api/export`** — the store as a JSON download. `business.md` promises users can
   export even at the free-plan limit, and that promise costs about ten lines because
   `LocalPersonStore` is already JSON. Do it for the principle (a contact book you
   cannot get out of is one you stop trusting), not for the plan tier.

### C. Would move the benchmark — do not build before the writeup

4. **"Sales opportunity" / "needs" as a field on `Person`.** This is the third time this
   shape has come up (contact handles, relationship edges, now this) and the answer is
   the same: adding a field changes the extraction call that also emits `name`, `notes`
   and `company` — fields `compare()` reads — and `temperature=0` is not determinism, so
   **both tables need re-running for a value that is already sitting in `notes` as
   prose.** If it must exist, it is a separate post-hoc call over the stored notes,
   exactly like `relations.py`. Never folded into `extract`.
5. **Ranking follow-ups by urgency.** One step from the "no attendee recommendation /
   people worth meeting scoring" non-goal, and it is scoring people either way. Cut.
6. **Auto-sending the draft.** Explicit non-goal, and `business.md` agrees with this file
   without noticing — every one of its flows ends in a human confirming.

### D. Business-model plumbing — out of scope, and blocked on the same wall

7. **Freemium quotas** (50 contacts, memos per month) and **the upgrade trigger.** Needs
   accounts, which the repo does not have.
8. **Team plan, shared records, lead ownership, HubSpot/Salesforce.** All of it needs
   multi-tenancy, and the store is **structurally single-tenant**: `get_store()` is
   process-global on one `RECALL_STORE_PATH`, which is the same wall
   `telegram_bot.py`'s chat allowlist exists to hold. Per-user stores is a rewrite of
   `memory.py`, not a flag. Cite as roadmap; build none of it.

**If a demo minute is spent on the business model it is a minute not spent on the
question card.** The benchmark table is still the headline.
