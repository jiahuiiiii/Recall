# Where else this could go

Post-hackathon thinking. **Nothing here gets built before 7 Sep 2026** — the submission
scope is fixed in [CLAUDE.md](../CLAUDE.md) and adding to it now weakens the one claim we
can actually defend. This file exists so the question "does this have legs" has a written
answer instead of a vibe.

---

## The honest starting position

**"Voice notes for networking" is not a business.** It is a crowded, low-willingness-to-pay
category. Every note-taking app, every CRM, and every phone OS already owns part of it. If
Recall is pitched as a nicer contacts app, the correct read is: no moat, no pricing power,
one feature away from being absorbed.

That is not what was built, though. What was built is:

> a system that **holds uncertainty about which entity a messy reference points to**, and
> **spends human attention on the single highest-value question** instead of guessing or
> escalating everything.

Networking memos are the *demo domain*. They were chosen because they produce genuinely
ambiguous references cheaply and because the demo is legible in five minutes. The
transferable asset is the layer underneath.

### Why that layer is worth something

Every system that ingests messy human-generated text about entities hits the same fork,
and there are only two answers in common use:

| Common answer | Failure mode |
|---|---|
| **Auto-merge above a threshold** | Silent corruption. Two people become one record and nobody finds out until the record is used for something that matters. This project hit exactly that bug — see To fix #1 in CLAUDE.md, where one shared syllable merged two different people with no question asked. |
| **Route everything uncertain to a human queue** | Unbounded labour. The queue grows with volume; the reviewer sees a raw pair of records with no guidance on *what would settle it*; throughput becomes a headcount line item. |

Recall's third path: keep the ambiguity explicit, derive the questions that could resolve
it, **score them in bits**, and ask the one that buys the most. The metric that falls out
— **questions per resolution** — is not an academic score. It is a cost metric, because
the resource being spent is human attention, and human attention has a price per minute in
every organisation that has an ops team.

That reframe is the whole business argument: *EIG converts directly into analyst-minutes
saved per thousand records.*

### What the competition does not do

Zep/Graphiti, Mem0 and A-MEM all do contradiction detection. None of them select their
clarifying questions by information gain — they either don't ask, or they ask an LLM what
to ask. Asking an LLM what to ask produces questions that *sound* reasonable and buy
almost nothing; the README's own example is a question worth 0.038 bits that reads
perfectly sensible to a human. **The arithmetic knows; a prompt doesn't.**

---

## Tier 1 — same code, different fixtures

These reuse `resolve.py`, `eig.py`, `questions.py` and `answer.py` essentially as-is. The
work is a new extraction schema, a new fixture set, and re-tuned thresholds. Weeks, not
months.

### 1. CRM / deal-flow deduplication

**Who:** sales ops, VC platform teams, anyone with a Salesforce or HubSpot instance older
than two years.

**Why it fits so well:** the comparison channels already implemented — name, company,
role, where-you-met, free-text notes — *are* CRM fields. `compare()` needs almost no
change. The three-zone band maps onto what admins already do by hand.

**The product:** duplicate detection that, instead of dumping a 4,000-row "possible
duplicates" report on an admin, sends **one Slack question to the rep who owns the
record** — "Is the Wei Lin you met at the GIC roundtable the same Wei Lin you logged from
SuperReturn?" — and merges on the answer. The rep is the only person who knows, they
answer in three seconds, and the audit trail records why.

**Why it's the strongest Tier 1 bet:** the buyer already believes duplicates cost them
money, so no market education is needed, and the value is measurable in the customer's own
system on day one.

### 2. Recruiting / ATS candidate matching

The same person applies through a referral, a job board and an agency over three years,
under a shortened name, a married name, and a romanised spelling variant. ATS dedupe today
is fuzzy string matching plus a recruiter's memory.

Precision matters more here than anywhere else in Tier 1: merging two candidates is not
just messy data, it can be a fairness and compliance problem. **Recall's failure direction
is the right one** — the baseline held `precision = 1.000` throughout, every loss a missed
recognition rather than a wrong merge. That is exactly the trade a recruiting buyer wants,
and it is a sentence worth putting in a deck once To fix #1's re-run confirms it still
holds.

### 3. Qualitative research, journalism, field notes

Interview transcripts and field notes are full of loose references — "the guy from the
ministry", "the older woman from the second focus group". Researchers resolve these by
hand, hours per project, and the resolution is usually undocumented.

This is the closest neighbour to the current build: **voice-first ingest already exists**,
the reference style is identical, and the user is the same person who recorded the audio,
so they can answer a clarifying question authoritatively. Low revenue per seat, but a very
short distance from the current code — a plausible first real-user deployment.

### 4. Clinical and social-services intake

Highest value per correct resolution, and the heaviest compliance ceiling. Patient/client
matching errors are a documented source of real harm, and duplicate medical records are a
known, expensive problem.

**Flag honestly:** this is a regulated setting. Voice capture of third-party personal data
in a clinical context is a far bigger legal surface than a networking app — and the
project already refuses biometrics on PDPA grounds, so the same reasoning applies with
more force here. Do not treat this as a near-term move; treat it as evidence the
underlying problem is valuable, and revisit only with a partner who owns the compliance
work.

---

## Tier 2 — same architecture, new extraction layer

Reuses the *shape* — hold uncertainty, derive questions, score in bits, apply the answer
with the same Bayes update that scored it — but needs new comparison channels and a
domain-specific fact model.

### 5. Identity resolution / MDM as an add-on

Master data management platforms (Reltio, Informatica, Tamr and friends) already produce a
**stewardship queue**: the pairs the automatic matcher wouldn't commit to. Stewards work
that queue by hand.

The pitch is not "replace your MDM". It is: *"your stewardship queue, shortened and
ranked — and each item arrives with the one question that settles it."* Selling into an
existing budget line beats creating one.

### 6. KYC / AML screening adjudication

Sanctions and PEP screening generates enormous false-positive volume, and analysts clear
alerts by hand. The core task is the same task: given a messy name and thin attributes,
decide whether this is the same entity, and figure out what evidence would settle it.

Two properties matter more here than the accuracy:

- **The decision path is arithmetic, not a prompt.** Every merge decision decomposes into
  named channels with fixed weights and a stated threshold. That is auditable in a way an
  LLM adjudication is not — and this is a market where "explain this decision to a
  regulator" is a hard requirement, not a nice-to-have.
- **The failure direction is defensible.** Failing towards "ask a human" rather than
  "silently merge" is the posture a compliance function wants.

Long sales cycles, heavy procurement, real budgets.

### 7. Supplier / vendor master deduplication

Procurement data has the same shape (name variants, legal entity vs trading name, shared
addresses) and the same measurable pain: duplicate suppliers mean duplicate payments. Less
interesting technically, easy to quantify in currency.

### 8. Voice-logged field operations

Inspection and maintenance logs are dictated and refer to assets loosely — "the pump on
the north side", "the same valve as last month". Same problem, different entity type: a
loose reference to a known entity in a shared context. **Note the parallel risk:** the
benchmark caveat in CLAUDE.md — that a shared context inflates merge scores — applies
doubly on a site where every asset shares a location.

---

## Tier 3 — the general capability

This is where the actual company would be, if there is one.

### 9. The clarifying-question layer, as a library

Today an agent that isn't sure does one of two bad things: guesses (and the wrong guess
propagates silently), or asks the user about everything (and the user stops reading).
There is no principled middle.

The offer: **give it hypotheses with priors and the records behind them; get back the one
question worth asking, in bits.** `eig.py` and `questions.py` are already pure functions
with no I/O and no model dependency in the scoring path — that is not an accident of style,
it is what makes them liftable.

Strongest technically, weakest commercially: a thin, elegant layer is exactly what a
framework absorbs. If this is the direction, the answer is to open-source the library, own
the benchmark and the vocabulary, and sell the hosted evaluation and tuning around it.

### 10. Ambiguity-aware memory for agent frameworks

Ship the three-zone band and EIG questioning as a memory backend that competes with
Zep/Mem0/A-MEM on the single axis none of them cover. The pipeline already runs against a
swappable backend (`recall/memory.py` vs `recall/memory_agentcore.py`), so the interface
exists — though note that the AgentCore backend is written-blind and known broken, so
"pluggable" is currently a claim about the interface, not a tested property.

### 11. Active learning for labelling and annotation

Choosing the highest-EIG query *is* active learning. The novel part here is that the
questions are **derived mechanically from record content** — via word-level prefix/suffix
alignment — rather than selected from a fixed pool. That is a real difference and a
publishable one; whether it is a business is a separate question.

---

## What actually transfers, and what doesn't

Being precise about this is what separates a strategy note from a wish list.

**Transfers cleanly**

- `recall/eig.py` — entropy, likelihood, posterior, EIG, the three selection strategies.
  Pure, domain-free, 23 tests.
- `recall/resolve.py` — the three-zone band and near-tie margin. The *structure* is
  domain-free; the weights are not.
- `recall/questions.py` — mechanical derivation, prefix/suffix alignment, per-question
  reliability tiers.
- `recall/answer.py` — the discipline that the answer is applied with **the same Bayes
  update and the same noise model that scored the question**. Break that and the bits a
  question promised are not the bits it delivers.
- `eval/` — fixtures, B³/pairwise scoring, the validator, the strategy sweep. Genuinely
  the hardest part to rebuild, and the part that makes any claim checkable.

**Does not transfer**

- The frozen tail — enrichment, drafts, calendar. It was plumbing here and it is plumbing
  anywhere.
- Groq Whisper ingest, in any domain that isn't spoken.
- **Every threshold.** `T_MATCH=3.0`, `T_NONMATCH=1.0`, `MIN_MARGIN=1.0` and the channel
  weights were tuned on one setting, and CLAUDE.md already states the benchmark rests on
  two arcs of the *same kind* of setting. Assume they must be re-derived per domain, and
  budget the fixture-writing time that implies.
- The fixtures themselves, obviously.

**Assumptions that will break somewhere else**

1. **Facts are short natural-language statements in similar phrasing.** The alignment that
   makes multi-valued questions work pairs facts that are "the same statement with a
   different middle". Structured fields, numeric ranges and codes need a different pairing
   rule entirely.
2. **Answer noise is hand-set per reliability tier.** Three constants chosen by judgement.
   In a domain where answers come from a system rather than a person, they should be
   measured, not assumed.
3. **The "someone new" prior is a placeholder at ~1.5%** and is documented as such. A
   domain with a high genuine rate of new entities will be badly served until that is
   derived from data.
4. **The answer space must stay open.** Every attribute probe carries "something else",
   because a closed answer space can only pick among entities already known — which is how
   a stranger gets merged into a real record. Any port must keep that.
5. **Few hypotheses.** EIG is computed over a small candidate set. Scaling to thousands of
   candidates is a blocking/retrieval problem this project has not solved.

---

## Where the money would come from

| Shape | Fit | Honest read |
|---|---|---|
| Consumer per-seat app | Poor | Crowded, low ARPU, no moat. This is the version of Recall that isn't a business. |
| Per-resolution API | Good alignment | You charge exactly when you create value. Risk: volumes may be small, and buyers dislike unpredictable line items. |
| Enterprise MDM / compliance add-on | Real budgets | Tier 2. Long cycles, procurement, security review. Where the money actually is. |
| OSS library + hosted tuning/eval | Defensible | Own the benchmark and the vocabulary; sell the thing that's hard to copy — the evaluation harness and domain tuning — not the 200 lines of arithmetic. |

---

## What would have to be true

Cheap experiments that would move this from "plausible" to "supported", roughly in order
of information per dollar:

1. **Cross-domain generalisation of the headline result.** Run the EIG vs random vs
   uncertainty comparison on a public entity-resolution benchmark (the Magellan/
   DeepMatcher family — Abt-Buy, Amazon-Google, DBLP-ACM — is the usual starting point).
   If EIG wins on questions-per-resolution *outside* this fixture set, the claim is about
   the method. If it doesn't, the claim is about `arc_godwin`. **This is the single most
   valuable follow-up experiment in the entire document.**
2. **Does a stranger answer as well as the author?** Every result so far assumes the
   person answering the question is the person who recorded the memo. A CRM admin, an AML
   analyst or a data steward is not. Measure answer accuracy for a non-author, because the
   whole Bayes update assumes the answer is mostly right.
3. **Is the interruption budget real?** Ask three sales ops or compliance leads what they
   currently spend clearing a duplicate queue. If the answer is "we ignore it", there is no
   sale regardless of how good the arithmetic is.
4. **Does EIG still win when candidates number in the hundreds?** Blocking has to come
   first, and the interaction between blocking and EIG is unmeasured.
5. **Would a buyer accept an arithmetic decision path as an audit trail?** Cheap to test —
   it's a conversation, not a build — and it is the crux of the Tier 2 pitch.

---

## Risks worth stating out loud

- **The wedge is thin.** A few hundred lines of well-tested arithmetic. The defensibility
  is in the eval harness and the domain tuning, not the formula — so any plan that treats
  the formula as the product is wrong.
- **Incumbents can add it.** Nothing stops Zep or an MDM vendor implementing EIG selection.
  The lead is in having measured it, and measurement leads decay.
- **Models keep improving.** If frontier models get reliably good at choosing clarifying
  questions, the gap narrows. The counter is that EIG is *auditable and cheap* — no model
  call in the scoring path — which is a durable advantage in regulated settings even if
  the accuracy gap closes.
- **Cold start.** With no prior records there is nothing to be ambiguous about, so the
  differentiating behaviour doesn't appear until a user has history. Every demo and every
  trial has to be seeded, and that is a real friction in sales.
- **One-setting benchmark.** Already documented as a limitation of the project; it is also
  the biggest single caveat on every claim in this file.

---

## If exactly one thing gets picked up after 7 Sep

**Experiment 1 above, then Tier 1 use case 1.**

Prove the question-selection advantage survives a domain change on a public benchmark —
that is what turns "a nice hackathon result" into "a method". Then port to CRM
deduplication, because the comparison channels already match the field schema, the buyer
already believes the problem is expensive, and the value is measurable inside the
customer's own system without them taking anything on faith.

Everything else in this document is downstream of those two.
