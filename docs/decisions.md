# Decision history — closed items

Case histories for work that is finished and problems that are closed. Kept because the
reasoning is load-bearing, not because anything here is outstanding.

**The lessons these taught are already promoted into `CLAUDE.md`** (Hard-won findings,
the three guards, Stack conventions). This file is the evidence behind them — read it
when you need the case, not the rule.

---

## How the uncertainty/question work landed

### ~~A. Multi-valued questions~~ — **DONE 24 Aug**

`attribute_questions()` in `recall/questions.py`. Facts across hypotheses are paired by
**word-level prefix/suffix alignment**, not token overlap: two facts are the same
attribute when they are the same statement with a different middle. Measured:

```
"Do they live on the 4th floor?"          binary     0.301 bits
"Which floor do they live at?"            3-valued   0.475 bits
"Do they study computer science at NUS?"  binary     0.671 bits
"What do they study at NUS?"              3-valued   0.803 bits
```

**The "roughly twice" estimate above was wrong** and is corrected here. EIG is capped by
`H(prior)`, which is 1.27 bits for three hypotheses, so no question can double 0.67. The
real lift is **1.2–1.6x**, which is still the single biggest arithmetic gain available.
Quote 1.2–1.6x, not 2x.

Alignment is strict on purpose. A token-overlap rule pairs "from malaysian chinese
independent school" with "studies computer science at NUS" on the strength of
school/science, and an **unanswerable question is worse than no question** — it still
scores in bits and still gets asked.

Every attribute probe carries `"something else"` in its answer space. A closed answer
space can only choose between people already in the graph, which is how a stranger gets
merged into an acquaintance.

### ~~B. Demo surface~~ — **DONE 24 Aug**

Question card in `web/index.html` (`questionCard()`), first in the results column: the
mention, candidate priors as bars, the chosen question big, bits bought as a share of
bits outstanding, the answer options, and **the questions it did not ask with their
measured value**. `ask` now appears in the pipeline diagram — it was missing, and the
diagram claimed `dedupe` branched straight to `enrich`/`merge`.

`unaskedCard()` covers the case where the band flagged an ambiguity but every derived
question scored zero. Silence there looks like the ambiguity was never noticed.

### ~~C. Answering the question~~ — **DONE 24 Aug**

The graph genuinely suspends. `ask_node` calls `interrupt()`, the run is stored in a
checkpointer, and `POST /api/answer` resumes it with `Command(resume=answer)`.

**The change that made the question load-bearing was not the pause.** It was stopping
`dedupe_node` from settling the ambiguity before the question was even chosen. On an
interactive run ambiguous mentions are now **held** — in `ambiguous`, in neither
`new_people` nor `known_matches` — and `ask_node` places them from the answer. Before
this, an LLM adjudicator had already decided and the question could only ever agree with
it. Non-interactive runs (CLI, eval, tests) keep the adjudicator, so nothing regressed.

Switched by `configurable.interactive`, not by the presence of a checkpointer —
`recall/state.py::is_interactive`. The flag is explicit so the CLI and eval never
discover the difference by raising inside `interrupt()`.

`recall/answer.py` applies the answer: **the same Bayes update, with the same

---

## Closed `To fix` items

### ~~1. Confirm the name-matching fix against the real pipeline~~ — **CONFIRMED 30 Aug**

`text.best_match` scoring coverage instead of the single best token pair is confirmed
end-to-end. `arc_godwin` B³ P=0.947 with the same-syllable pairs no longer merging on a
shared syllable, and no legitimate match regressed. The projection held.

### 2. ~~The residual merge window~~ — **CLOSED 3 Sep (`NAMELESS_CEILING`)**

No longer arithmetic-in-a-comment. Measured on the real pipeline:

```
"indian girl" vs Marvi:  desc=1.00 (2.0) + notes=1.00 (1.5) = 3.50  >= T_MATCH  RESOLVED
```

**No name channel fired at all.** `W_DESCRIPTOR_MAX` does exactly what it promises — a
description alone cannot reach 3.0 — but description _plus_ notes overlap can, and every
person in a single-hall fixture shares vocabulary. It was the right person here; the
arithmetic does not guarantee the next one.

**Fixed** by `NAMELESS_CEILING` in `resolve.score()`: when the name channel contributes
nothing (name 0.0, no conflict — the pure-descriptor path and the nickname-routed path
both), the whole total is capped at 2.5, below `T_MATCH`. A nameless match now lands in
the ambiguous band and buys a question instead of auto-merging. This was a **policy call,
not just arithmetic** (decided 3 Sep): the same cap also stops a *uniquely*-identifying
description from auto-resolving ("the german girl" with one German stored now asks too),
because the resolver cannot tell a unique description from one that merely happens to be
top — they score identically. The chosen trade is "always ask when no name," which costs
a little recall to guarantee no silent nameless merge. Re-baselined: overall B³ unchanged
(0.918 vs 0.927, both ±0.095), precision held at 1.000 everywhere the cap applies. Two
tests moved from RESOLVED to AMBIGUOUS to encode the new policy
(`test_resolve.py`, `test_resolve_channels.py`).

### 3. ~~`same_first_name.yaml` does not cover the student setting~~ — **the premise was wrong**

The documented arithmetic was `name=1.00 company=0.00 conflict role=0.00 conflict →
-0.10 NEW ✓`. **The extractor never populates `company` or `role` for this transcript** —
it puts "masters in robotics at NTU" and "payments compliance at a bank" into `notes` as
prose. Both fields are silent, `_field()` correctly returns `None`, and there is no
negative weight to apply:

```
as the extractor actually emits them:   name=1.00 company=- role=-  -> 3.17  RESOLVED  ✗
as this section assumed:                name=1.00 company=0 role=0  -> -0.08 NEW       ✓
```

So the fixture was not "passing only in the professional setting" — it was **failing**,
end-to-end, deterministically, and the proposed remedy (add a student-setting fixture)
would not have caught it. Fixed 28 Aug by capping `W_NAME_EXACT` at 2.5; `same_first_name`
now scores 1.000.

**The lesson generalises:** `company=-` (silent) versus `company=0.00` (conflict) is a
3.25-point swing, and which one you get is decided by the extractor, not the resolver.
See Hard-won findings on projecting from the pure layer.


### 5a. ~~`with_structured_output` sometimes returns a JSON string, not a list~~ — **CLOSED 3 Sep**

```
PeopleExtraction.people: Input should be a valid list, input_type=str
```

Killed one `arc_godwin/m13` extraction in `run_eval` and once an **entire run** of
`run_questions`. Not a fixture problem and not deterministic.

Closed on three fronts, all now in place:

1. **Coercing validators on every model-filled list field.** `decode_list` was already
   on `PeopleExtraction.people` and `Person.notes/aliases`; it is now also on
   `CommitmentExtraction.commitments`, `DraftBundle.drafts`, and
   `ConsolidatedRecord.notes/met_at`. A correctly-encoded-but-stringified list is decoded
   rather than rejected. Tested in `test_state_coercion.py`.
2. **Retry first; salvage only once every attempt has failed, and say so.**
   `extract_people_node` re-asks 3× with an explicit structured-output repair request —
   a resample recovers the WHOLE memo, where a salvage recovers only its head, so
   salvaging early would trade recall for one saved model call in exactly the case the
   retry exists for. Only when all three come back corrupt does `salvage_object_list`
   scan the string with Python's JSON decoder one object at a time and keep the complete
   dictionaries ahead of the break; they still go through `Person` validation, and a
   broken FIRST object is not guessed at and raises.

   **It stops at the break and does not resync past it** — a heuristic resync can lift a
   brace out of a broken string and manufacture a person nobody mentioned — so a complete
   object *after* a mid-array break is lost. That loss is reported: the function returns
   the abandoned text alongside the objects, and the node appends `Salvaged N person(s)
   … abandoned M unparseable characters` to its summary message. A partial extraction
   that reads like a clean one is the failure this path exists to avoid; it is the same
   reason the passing-mention filter is code with an explicit boolean rather than a
   silently-obedient model.
3. **Per-memo isolation in both harnesses.** `run_eval` and `run_questions` each wrap a
   memo in try/except and skip on failure, so one bad extraction costs its cases, never
   the run. This is what the "entire run" note refers to; it can no longer happen.


### ~~5b. The code default model is one this account cannot call~~ — **CLOSED 5 Sep**

`_common.py` defaulted `HAIKU` to `global.anthropic.claude-haiku-4-5-...` in
`ap-southeast-1`, callable on neither account. Decided with the judges' path: the code
default is now `us.anthropic.claude-sonnet-4-6` and `DEFAULT_REGION` falls back to
`us-east-1`, matching `.env.example`, so a fresh clone with no `.env` lands on something
the hackathon account can call. The personal-account `.env` overrides both, so nothing
changed there. The variable is still named `HAIKU`; everything reads it.

Related, smaller: `SONNET` / `_DEFAULT_SONNET` are defined and never used anywhere, and
`cached_system()` asks `supports_cache_point(HAIKU)` — the module default — rather than
the model the call is actually being built for. Latent only while nothing passes
`model=` to `chat_model()`, which nothing currently does.

### 5c. ~~`answer.rebuild_question` / `rebuild_hypotheses` are dead~~ — **DELETED 3 Sep**

They described an out-of-graph answer path — resolving from the payload the UI holds,
without resuming the graph — that nothing used. The live path resumes the graph
(`Command(resume=...)`), which re-executes `ask_node` and rebuilds the `Question` by
re-deriving it, so these were never called. They also carried a latent bug: the payload
they read (`ask._shown()`) has no `key` or `noise`, so a rebuilt `Question` would fall
back to the global `ANSWER_NOISE` rather than the per-question reliability EIG scored it
under — the exact mismatch `answer.py`'s docstring forbids. Wiring them up would have
meant building a parallel resolution path that still could not persist without resuming
the graph anyway, so they were deleted. `resolve_with_answer` (the real Bayes update,
called from inside the node) is untouched.

