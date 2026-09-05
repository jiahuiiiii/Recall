# CLAUDE.md

Project instructions for Claude Code. Read this at the start of every session.

---

## What this is

**Recall** — a voice-first relationship-memory agent for event networking. You record a
messy ~90-second memo after an event. The system extracts the people mentioned, resolves
them against people it already knows **while holding uncertainty explicitly**, and asks
**one** well-chosen clarifying question when a mention is genuinely ambiguous.

SimplifyNext Agentic AI hackathon. Submission **7 Sep 2026**.

**Scope decision (21 Aug):** this project is the uncertainty/question direction, built on
the working pipeline that already exists. It is _not_ the full research spec — bi-temporal
graphs, contradiction sweeps and calibration curves are cut (see Future work). It is also
no longer the enrich-and-follow-up pipeline; that tail is frozen, not extended.

## The one defensible claim

**Question selection by expected information gain.** When a mention is ambiguous we do
not ask an LLM "what should I ask?". We compute, over candidate hypotheses:

```
EIG(q) = H(H) − E_a[ H(H | a) ]
```

and pick the argmax. Existing agent-memory systems (Zep/Graphiti, Mem0, A-MEM) do
contradiction detection; none select their clarifying questions by information gain.
That gap is the contribution.

**The headline result is a benchmark table, not a UI.** EIG vs random vs
uncertainty-sampling on questions-per-resolution. Build toward that.

If a change would weaken this, stop and flag it rather than proceeding.

## Non-goals — do not implement

- **No facial recognition, no photos.** PDPA exposure on biometric data about
  non-consenting third parties. Not negotiable.
- **No attendee recommendation / "people worth meeting" scoring.**
- **No auto-sending.** We draft; the human sends. Always.
- **No new email/LinkedIn work.** Plumbing, not differentiation.
- **No new web-enrichment work.** Out of scope, and measured to be silent for most real
  contacts anyway.
- **No POMDP solver, no AGM belief revision, no ASR fine-tuning.** Cite; don't build.

If asked to add a feature, default to no. Five minutes of demo cannot show breadth.

---

## Current status

**The full pipeline works and the headline benchmark exists.** 418 tests, all offline.
Runs from the CLI, the web UI, or Telegram.

```
transcribe -> extract -> dedupe(3-zone band) -> ask(EIG, pauses) -> (enrich | merge) -> ...
```

The pause is real: on an interactive run `dedupe` holds ambiguous mentions, `ask`
suspends the graph on `interrupt()`, and **the human's answer decides which branch the
person takes**.

| Piece                                                                        | State                                                 |
| ---------------------------------------------------------------------------- | ----------------------------------------------------- |
| LangGraph supervisor, conditional edge, fan-in                               | **Done**, tested                                      |
| Transcription (Groq `whisper-large-v3`)                                      | **Done**, ~1.2s for a 20s memo                        |
| Extraction → typed `Person`, atomic `notes`, substantive filter              | **Done**                                              |
| Candidate retrieval — stem/substring/misspelling tolerant                    | **Done**, 11 tests                                    |
| **Three-zone band** (`recall/resolve.py`) — pure, + near-tie margin          | **Done**, 19 tests                                    |
| **EIG selection** (`recall/eig.py`) — pure, per-question reliability         | **Done**, 23 tests                                    |
| **Question derivation** (`recall/questions.py`) — mechanical                 | **Done**, 32 tests                                    |
| **`ask_node`** — one question per memo, rejected set carried in state        | **Done**                                              |
| Eval harness — fixtures, B³/pairwise, validator, audio→fixture               | **Done** (`eval/`)                                    |
| Simulated answerer (`eval/strategies.py`)                                    | **Done**, 7 tests — was untested, and was wrong       |
| **EIG vs random vs uncertainty benchmark**                                   | **Done**, re-run 3 Sep, 11 scenarios — EIG 0.86 < unc 1.03 < rand 1.13, ranges disjoint |
| Person store, merge + consolidation, delete/patch                            | **Done**                                              |
| **User merge of two people** (`store.merge`, `/api/people/{id}/merge`, UI)   | **Done 31 Aug**, 7 tests, trash file for undo         |
| **Contact handles** (`recall/contacts.py`, `PATCH /api/people/{id}`, UI)     | **Done 1 Sep**, 36 tests, user-typed only — see below |
| — the panel's contact fields commit on blur/Enter, no Save button            | **Done 1 Sep**                                        |
| **Relationship edges** (`recall/relations.py`, `/graph`)                     | **Done 2 Sep**, 42 tests, display-only — see below    |
| **`.ics` calendar backend** (`RECALL_CALENDAR=ics`) — no credentials, works for anyone | **Done 3 Sep**, 26 tests |
| **One-tap "Add to Google Calendar"** (`gcal_link`, web card + bot button) — a chat app mishandles a `.ics`, a link does not | **Done 3 Sep** |
| **Attending events** (`Commitment.kind`) — events you go to, not just follow-ups you owe | **Done 3 Sep**, in the 26 + confirm tests |
| **Google Calendar over OAuth** (`web/google_calendar.py`, `RECALL_CALENDAR=google`) | **Done 3 Sep**, 16 tests, single-tenant |
| **Hostable on Render** (`render.yaml`, `/healthz`, `00_check_deploy.py`) | **Done 3 Sep**, one service, never deployed |
| Web UI — record, type, edit, live graph, person graph, delete                | **Done**, responsive                                  |
| **Telegram bot** (`telegram_bot.py`) — voice note in, question as a keyboard | **Done 2 Sep**, 13 tests, transport only              |
| Enricher / drafter tail                                                      | Done, **frozen** (outside scope)                      |
| **Calendar confirmation** (`calendar_node` pauses, you tick what to add)     | **Done 2 Sep**, 27 tests                              |
| Google Calendar over MCP (`RECALL_CALENDAR=mcp`)                             | Built, **needs your OAuth** — see Commands            |
| **Multi-valued questions** (`questions.attribute_questions`)                 | **Done**, in the 32 above                             |
| **Demo surface** — question card in the web UI, `ask` in the diagram         | **Done**, 3 server tests                              |
| **Answering the question** — `interrupt()`, `/api/answer`, clickable options | **Done**, 18 tests                                    |
| **Applying the answer** (`recall/answer.py`) — Bayes, pure                   | **Done**, 12 tests                                    |
| **Name matching** (`text.best_match`) — coverage, not single best pair       | **Fixed**, see To fix #1                              |
| `arc_godwin` fixture — 14 memos, 20 people, 11 loose references              | **Done**, validated                                   |
| `ehoc_c4` fixture — 11 memos, 14 people, 13 recurring                        | **Done**, validated, best-scoring arc                 |
| **Eval scorer back-mapping** (`harness.align`) — one-to-one                  | **Fixed 30 Aug**, 8 tests                             |
| **Name/descriptor channel separation** (`resolve.compare`)                   | **Fixed 30 Aug**, 5 tests                             |
| **Writeup** — plain-language, artifact + `recall-writeup.pdf`                | **Drafted 2 Sep**, states both caveats                |
| Demo script, written and timed                                               | **Not started** — the main gap                        |
| AgentCore Memory backend                                                     | Written blind, **known broken**, never run            |
| AgentCore deploy (`01`–`04`)                                                 | Written, never run                                    |

### Resolution baseline — re-measured 3 Sep (11 scenarios), `repeats=3`

Thresholds in force: `T_MATCH=3.0`, `T_NONMATCH=1.0`, `MIN_MARGIN=1.0`, `W_NAME_EXACT=2.5`,
`NAMELESS_CEILING=2.5`. Quote them with any result.

| scenario              | B³ F1        | B³ P  | B³ R  | pair F1 | subst | covrg |
| --------------------- | ------------ | ----- | ----- | ------- | ----- | ----- |
| `partner_notes`       | 0.968 ±0.000 | 1.000 | 0.938 | 0.933   | 0.970 | 0.938 |
| `account_notes`       | 0.962 ±0.000 | 1.000 | 0.926 | 0.929   | 0.944 | 0.944 |
| `ehoc_c4`             | 0.924 ±0.059 | 0.989 | 0.870 | 0.850   | 0.959 | 0.954 |
| `conference_notes`    | 0.916 ±0.022 | 1.000 | 0.846 | 0.859   | 0.944 | 0.944 |
| `arc_godwin`          | 0.877 ±0.000 | 0.947 | 0.816 | 0.667   | 0.952 | 0.947 |
| `site_visit_notes`    | 0.870 ±0.025 | 1.000 | 0.771 | 0.719   | 0.971 | 0.941 |
| `arc_sales`           | 0.865 ±0.000 | 1.000 | 0.762 | 0.615   | 0.933 | 0.929 |
| `client_followups`    | 0.865 ±0.034 | 1.000 | 0.763 | 0.682   | 0.946 | 0.939 |
| `arc_acacia`          | 0.775 ±0.026 | 1.000 | 0.633 | 0.493   | 0.873 | 0.857 |
| `same_first_name`     | 1.000        | 1.000 | 1.000 | 1.000   | 1.000 | 1.000 |
| `genuinely_ambiguous` | 1.000        | 1.000 | 1.000 | 1.000   | 1.000 | 1.000 |

`B³ F1 across all scenarios: 0.911 ±0.121 (n=33)` — no extraction failures this run.

**Precision is 1.000 on eight of eleven scenarios, and — the headline — on all five new
professional fixtures.** The B2B set was written with deliberate name collisions (two
Aarons at different banks, two Alexes, Cheryl Ng/Cheryl Wong, Darren Chia/Darren Chew,
Elena Loh/Elaine Low, Alisha Rahman/Alicia Yap); **none merged.** The only sub-1.000
precision is `ehoc_c4` (0.989) and `arc_godwin` (0.947), both the LLM adjudicator on
non-interactive runs, not the band (To fix #5d). This is the strongest evidence yet that
the resolver's precision is a property of the method, not of one student setting.

**Two things moved from the prior `0.918 ±0.095 (n=18)` baseline, and both are expected:**

- **The spread widened (±0.095 → ±0.121).** More scenarios, more range: the diagnostics
  sit at 1.000, `arc_acacia` at 0.775. Not a regression, just a wider sample.
- **`arc_acacia` recall fell (0.681 → 0.633).** This is the `NAMELESS_CEILING` policy
  (To fix #2) doing exactly what it was chosen to do: `arc_acacia` leans on descriptor-only
  references that now go to a question instead of auto-resolving. Recall is the cost of
  the "always ask when no name" trade, paid where descriptions carry the most weight.
  Precision there stayed 1.000.

**`arc_sales` and the B2B fixtures carry the professional-setting claim now.** B³ P = 1.000
across all of them — the case no student arc can test, because nobody in them has an
employer. Recall in the 0.76–0.94 band is the loose-reference half: company/role-only
mentions (`"the DBS transformation guy"`, `"the Axiata CRM director"`) are missed
recognitions, not wrong merges — the right direction to fail in, and the direction the
question path exists to fix. Quote `arc_sales`/`client_followups` with their memo counts —
both are ~10 memos, below `run_eval`'s ~20-memo "anecdote" warning, so cite the count.

The runtime ambiguous band flagged **294 mentions across the sweep**, far above the
9 labelled ambiguous. Names plus companies produce partial matches everywhere, and
`NAMELESS_CEILING` now holds every nameless match in the band too, so a professional
setting feeds the EIG denominator much harder than a hall does.

#### `arc_sales` question efficiency — a 4-way case, re-measured 3 Sep

`run_questions.py --scenario arc_sales --repeats 3`, after adding the three-way memo
(m12/m13: Wei Lin plus two GIC colleagues, then a nameless "someone from the GIC team"):

```
eig            0.750 ±0.000  (n=3)   100% <=1 question
uncertainty    0.750 ±0.000  (n=3)   100%
random         1.167 ±0.375  (n=3, min 0.750 max 1.500)   83%
```

Scorable cases per run: `[4, 4, 4]` — m2/m7/m10 at 2 hypotheses and **m13 at 4**. That
fourth case is the point: **EIG now beats random (0.75 vs 1.17)**, where the earlier
all-2-way version was a dead three-way tie (0.722 across the board). EIG still **ties
uncertainty sampling**, which is honest and expected — on a flat prior (all four GIC
records cap at `NAMELESS_CEILING`, so entropy is maximal) the two strategies often pick
the same question. Quote it as "EIG beats random, ties uncertainty here", never as EIG
losing.

**Why two hypotheses can never separate the strategies.** With exactly two candidates
every discriminating question is worth identical bits, so the argmax has nothing to
choose and all three strategies agree by construction — the same property that makes
`_spread()` show the worst question, not a plain top-N. A fixture needs a **3+**-hypothesis
case to exercise selection at all; m13 is that case, built by giving three people one
shared employer and then referring to them by it with no name.

`arc_sales` still is not the headline on its own (one fixture, four cases). The headline
stays the all-fixture table. But it now contributes to the question claim rather than only
the resolution one, and it is B³ P held while doing so — see the baseline table.

**A new baseline, not a delta.** The old `arc_acacia` figure (`B³ P=1.000 R=0.856
F1=0.922`, pairwise 0.800) is superseded and must not be compared against: three things
changed between the two measurements — `W_NAME_EXACT` 3.0 → 2.5, the name/descriptor
channel separation in `compare()`, and the eval scorer rewrite. Each is unit-tested
alone; no run separates their contribution to these numbers.

**Precision is a per-scenario claim, not a global one.** `arc_acacia` and `ehoc_c4` are
at 1.000 — nothing wrongly merged, every loss a missed recognition, the right direction
to fail in. The old blanket sentence _"precision had been 1.000 throughout"_ was **false
when written**: `arc_acacia` held a real wrong merge (`marvi`+`shiny`, see Hard-won
findings) that the broken scorer hid. `arc_godwin` sits at 0.947, and that loss is
**the LLM adjudicator, not the band** — see To fix #5d.

### Question efficiency — re-measured 3 Sep (11 scenarios), `repeats=3`

```
strategy       questions/resolution                       <=1 question
eig            0.862 ±0.037  (n=3, min 0.824  max 0.897)       78%
uncertainty    1.033 ±0.072  (n=3, min 0.985  max 1.129)       75%
random         1.129 ±0.008  (n=3, min 1.118  max 1.134)       69%
```

**The strongest version of the headline the project has produced.** ~69 scorable cases
across the three runs (~23/run), budget cap 5. **EIG's maximum (0.897) sits below both
baselines' minimums (uncertainty 0.985, random 1.118)** — the ranges do not overlap at
all, so `_verdict()` passes decisively. 26/69 of the chosen questions are multi-valued,
43/69 yes/no.

**Why this run separates the strategies where earlier ones barely did.** The B2B fixtures
supply many **3- and 4-hypothesis** ambiguous cases — e.g. `partner_notes/m6 'Fortinet
channel guy'` against four candidates, `client_followups/m8 'OCBC procurement guy'`
against three. With two candidates every discriminating question is worth the same bits
and all strategies tie; with three or four, the argmax has something to choose, and EIG's
choice is measurably better. The near-homophone name pairs are what manufacture those
multi-way ties. This is the result the enlarged fixture set was for.

**Claim "EIG beats both baselines."** Here it also beats them in order (EIG < uncertainty
< random) with clean separation, but keep the conservative claim — uncertainty and random
have swapped before at smaller n. What is solid and repeatable is that **EIG is first and
its range clears both.**

One caveat still travels with this table:

- **The denominator is coupled to the resolver.** `W_NAME_EXACT=2.5` and now
  `NAMELESS_CEILING=2.5` push bare-name and nameless returns into the ambiguous band, so
  resolution quality and question efficiency are **not independent results** and must not
  be written up as if they were. Fair across strategies (one case set per run), which is
  what the comparison rests on.

No extraction failures took down a run this sweep — the per-memo isolation (To fix #5a)
held across all 11 scenarios.

### Fixtures

**The default sweep is the eleven scenarios below: 114 memos, 234 mentions, 83 recurring
people.** The five-arc business bundle is a further 50 memos and lives in
`eval/fixtures/bundles/`, deliberately OUT of the default glob so the published tables
stay reproducible by the bare `run_eval.py` / `run_questions.py` commands printed beside
them — reach it with `--fixture`. `uv run eval/check_fixtures.py` validates all sixteen
(164 memos, 384 mentions, 119 recurring) and exits 0.

| Scenario              | memos | people | what it carries                                                                                                                                                       |
| --------------------- | ----- | ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `arc_acacia`          | 24    | 12     | the original arc, source of the resolution baseline                                                                                                                   |
| `arc_sales`           | 13    | 7      | **the first professional setting.** `company`/`role` populated and CONFLICTING, not silent. Two Alexes at different firms, one job change, three GIC people for a 4-way ambiguous case (m13), dated commitments in most memos |
| `arc_godwin`          | 14    | 20     | Luminia OG. **11 loose references**, 8 of which land in the ambiguous band — the EIG denominator. Four same-syllable name pairs                                       |
| `ehoc_c4`             | 11    | 14     | Eusoff Hall orientation. **13 recurring of 14** — the densest recognition test. Four memos of descriptor-only references, and the fixture that exposed the scorer bug |
| `account_notes`       | 10    | 8      | **B2B accounts.** Two Aarons at different banks (Goh/DBS vs Lim/StanChart), heavy role/company loose refs, a job change (Sophia: Oceanic→NexPort), one 2-way Aaron ambiguity |
| `client_followups`    | 10    | 11     | customer follow-ups. Two Alexes again, densest cast (11 people), 3 passing mentions                                                                                    |
| `conference_notes`    | 10    | 8      | three-day conference. **Near-homophone pairs** Raymond Lee/Ray Lim, Cheryl Ng/Cheryl Wong, Farid Hassan/Farah Aziz — the precision landmines                          |
| `partner_notes`       | 9     | 9      | MY/SG partners. Four near-collision pairs (Vikram/Victor, Ben Lim/Bernard Low, Nur Aisyah/Noor Aziz, Alisha Rahman/Alicia Yap)                                         |
| `site_visit_notes`    | 9     | 9      | site visits. Darren Chia/Darren Chew, Elena Loh/Elaine Low — same/near-same names that must not merge                                                                  |
| `same_first_name`     | 2     | 2      | precision diagnostic. Merged two Alexes until 28 Aug; now 1.000                                                                                                       |
| `genuinely_ambiguous` | 2     | 1      | two memos, one scored mention                                                                                                                                         |

**The five `*_notes` / `*_followups` fixtures are a professional B2B set added 3 Sep**
(banks, logistics, insurance, regional partners). They are the direct answer to the
"benchmark rests on one kind of setting" caveat: real employers that agree AND conflict,
and deliberate near-homophone name pairs that stress precision in a way the student arcs
cannot. `account_notes` measured B³ P=1.000 on its first run — the two Aarons did not merge.

The `ambiguous` counter in `check_fixtures.py` reads the **label**, not the runtime band.
`arc_godwin`'s eight scorable references are labelled `ambiguous: false` on purpose — you
know the answer, the resolver does not. Do not chase that progress bar by adding
`UNRESOLVED` mentions; those cannot separate EIG from random.

---

## Done — how the uncertainty/question work landed

Kept because the reasoning is load-bearing, not because the work is outstanding.

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
per-question noise, that EIG scored the question with.** If the answer were applied by
text-matching instead, the bits the question promised would not be the bits it delivered
and the headline claim would measure something the system does not do.

Gotchas worth remembering:

- **`interrupt()` re-executes the node from the top on resume.** Everything above the
  call must be pure. Nothing may be written to the store before it — verified against the
  installed SDK, not assumed.
- **State lives in the checkpointer, not the compiled graph.** The server recompiles per
  request and resumes fine; only the saver is a singleton.
- **`InMemorySaver` does not survive a server restart.** Restart mid-demo and the pending
  question is gone. Fine for a local demo, worth knowing before it happens on stage.

## To fix

Ordered by how much damage each one does if it ships unnoticed.

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

### 4. A bare nickname resolves as a name conflict — **half closed, rest deferred to Future work**

`_is_name` now treats a leading article as marking a description, so `"the Catholic
Indian"` routes to the descriptor path. `"big boss"` still does not: no article, no token
in `DESCRIPTOR_WORDS`, so it takes the name channel, conflicts with every stored name,
and files a duplicate. The `arc_godwin` workaround — phrasing it _"the guy everybody
calls big boss"_ — still lives in the fixture, not the code.

Narrower than it reads: a bare nickname resolves **fine** once it is a stored alias
(`"big boss"` vs a record whose aliases hold it scores name=1.00). The failure is only the
**unlinked** bare nickname — first sight, or never captured as an alias.

**Deferred to Future work, not fixed here.** The clean fix is an extraction flag marking a
mention an informal label rather than a formal name (the extractor can see it is an
epithet), routing it through the capped descriptor channel into the ambiguous band. That
is a `Person` schema change to the same model call that emits `name`/`notes`/`company`,
so it moves both benchmark tables — the same cost that defers contact handles, relations,
and the opportunity field. The cheap alternative (growing `DESCRIPTOR_WORDS`) cannot cover
an open-ended nickname space. Not demo-blocking; left documented. See Future work.

### 5. Ignore rules for private data must be globs — **lesson, item closed**

The fixtures are tracked and the blanket `*.yaml` negation works. The same blind spot
cost something elsewhere, which is why this stays: `data/person_graph.json` was a
_literal_ ignore rule, so the `.backup-*` and `.trash` siblings it existed to protect
were never covered, and four of them are committed. The rule is now a glob
(`data/person_graph*.json`). Write ignore rules for private data as globs from the
start — a literal only protects the one filename you thought of.

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

### 5d. `arc_godwin`'s precision loss is the adjudicator, not the resolver

Diagnosed 31 Aug. `jia_en` and `jia_ying` land on one record — but **nothing
auto-resolved**:

```
m3   Jia En                        AMBIGUOUS 1.27  name=0.50 notes=0.34  top=Jia Qi
m6   Jia Ying                      AMBIGUOUS 1.45  name=0.50 notes=0.47  top=Jia En
m11  the golden hair girl          AMBIGUOUS 2.15  desc=1.00 notes=0.10  top=Jia En
m14  the computer engineering girl AMBIGUOUS 2.19  desc=1.00 notes=0.12  top=Jia En
```

All four sit in the band. With four `Jia*` people in one OG (`Jia En`, `Jia Ying`,
`Jia Qi`, `Jia Yaw`), coverage-based `best_match` scores them 0.50 on the shared `jia`
instead of 1.00, which is exactly the behaviour To fix #1 bought. The merge was made by
**`_adjudicate()`** — the LLM fallback that settles the ambiguous band on non-interactive
runs because nobody is there to answer.

**So `arc_godwin` B³ P=0.947 measures the fallback guesser, not the product's main
path.** On an interactive run those mentions are held and one of them buys a question.
This is the mirror image of the `arc_acacia` merge: there the band failed and the merge
was silent; here the band worked and the component that exists only because the human is
absent got it wrong. Say so in the writeup — the cost of _not_ asking is visible in that
0.947, which cuts toward the claim rather than against it.

Do not "fix" this by tightening the adjudicator prompt before the writeup. It is
currently the cleanest evidence that the ambiguous band is identifying the right cases.

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

### 6. Already documented, unchanged

Plural references yield one entity; the "someone new" prior is a placeholder at 1.5%; the
benchmark rests on one setting. See **Known limitations**. A Whisper mis-hear that changes the _first_ token
(`Zhong Xuan` → `Jong Shuen`) scores 0.00 and does not match at all — this is unchanged
by the fix and is exercised by `arc_godwin` m14.

---

## To do

Measurement and words, not building. Nothing here needs a new feature.

1. **The demo script**, written and timed, then rehearsed. Build it backwards from
   the demo arc below; the money shot is the EIG of the questions it did not ask.
2. **Seed the demo data** — `uv run seed_demo.py --write`. Cold start is real: with no
   prior records nothing is ambiguous, so the differentiating behaviour never fires.
3. ~~Fix the structured-output string bug (To fix #5a).~~ **Done 3 Sep** — coercing
   validators on every model list output, plus per-memo isolation in both harnesses.
4. **The backend, only if deploying.** `recall/memory_agentcore.py` is architecturally
   wrong and has never run; deploying with `RECALL_MEMORY=agentcore` as-is would make
   every known person look new. Read **AgentCore Memory — must fix before deploying**
   first, and test against a throwaway memory resource, never the live graph.

**The writeup is drafted** — plain-language, published as an artifact and exported to
`recall-writeup.pdf`. It states both caveats plainly: question efficiency is coupled to
`W_NAME_EXACT` rather than independent of it, and the benchmark rests on one kind of
setting. Keep those two sentences in any version of it.

---

## `docs/business.md` — the sales framing, sorted into tasks

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

---

## Demo arc (build backwards from this)

1. Record a live messy memo mentioning three people, one ambiguous.
2. Show extraction, confidence values visible.
3. **The agent picks and asks its one question — display the EIG of the questions it
   didn't ask.** This is the money shot.
4. Answer it; show the resolution land in the person graph.
5. Fuzzy recall: three vague words, right person.
6. Close on the benchmark table.

If a feature doesn't appear here or in the eval, it doesn't get built.

---

## Architecture

```
voice memo (or typed text)
  → transcribe (Groq Whisper — audio is NOT a Bedrock capability, keep it a tool)
  → extract_people        (structured output + substantive filter)
  → resolve               (three zones) ──────────┐
        │ new          │ known                    │ AMBIGUOUS
        ▼              ▼                          ▼
     persist        merge into record        EIG question → interrupt()
        └──────────────┴──────────────┬───────────┘
                                      ▼
         [commitments → drafts → calendar: confirm(interrupt) → write]
                                      ▼
                                   summary
```

- **Supervisor + sub-agents.** The main graph orchestrates; sub-agents keep noisy work
  out of the main context.
- **State is the single source of truth.** One `TypedDict` in `recall/state.py`. Nodes
  return **partial updates only**. An unmatched key is dropped silently — if a node's
  output "vanishes", suspect a typo in `state.py` first.
- **Memory is the demo.** Cross-session recognition is what proves the agent remembers.
  It works identically for a uni friend and a fund partner.
- **The person graph is user-correctable.** `PersonStore` has `delete()`; the UI removes
  individual notes. Edits go through `replace()`, never `upsert()` — upsert accumulates
  list fields, so a shortened list written through it re-adds what the user just deleted.
- **Guards belong in code, not prompts.** Where a model must be careful, make the
  pipeline not require carefulness.

## Repository layout

Verified against the tree on 2 Sep 2026. `uv run pytest tests/ -q` → 352 passed.

```
recall/                     the pipeline
  __init__.py               loads .env — must happen here, not in a submodule
  _common.py                chat_model(), UsageCallback, LEDGER, PRICING, cached_system()
  state.py                  the one TypedDict + every structured-output model
  graph.py                  supervisor graph: nodes, conditional edge, fan-in
  agent.py                  AgentCore entrypoint — translates payloads, same graph
  resolve.py                three-zone band, pure scoring, no model call        [19 tests]
  eig.py                    entropy, posterior, EIG, the two baselines. Pure    [23 tests]
  questions.py              questions derived mechanically from stored facts    [32 tests]
  answer.py                 applies one answer under the SAME Bayes update      [12 tests]
  text.py                   token matching shared by retrieval and resolution
  memory.py                 PersonStore protocol + LocalPersonStore (JSON)
  memory_agentcore.py       AgentCore backend — WRITTEN BLIND, NEVER RUN, BROKEN
  contacts.py               phone/Instagram/Telegram/LinkedIn, user-typed only  [36 tests]
  relations.py              relationship edges, derived post-hoc, display-only  [42 tests]
  tags.py                   tags for filtering — model-derived, not lexical
  mcp_client.py             minimal stdio MCP client, only what calendar needs
  nodes/                    one file per graph node
    transcribe · extract · dedupe · ask · merge · persist · summarize
    calendar                 <- proposes, pauses to confirm, then writes
    enrich · followups       <- the frozen tail, outside scope
  tools/                    transcribe (Groq) · web (search) · calendar
                            calendar: local | ics | google | mcp; .ics + gcal_link;
                            Commitment.kind branches followup vs attending

eval/                       the benchmark — the hardest part to rebuild
  harness.py                fixture loading, the sweep, align() back-mapping
  metrics.py                B³ and pairwise clustering scores. Pure
  strategies.py             EIG vs random vs uncertainty + simulated answerer   [7 tests]
  run_eval.py               resolution baseline      → the B³ table
  run_questions.py          question efficiency      → the headline table
  check_fixtures.py         validator — free, no model calls, exits 0
  from_audio.py             record a memo straight into a fixture
  fixtures/                 the default sweep — 11 scenarios: arc_acacia · arc_godwin
                            arc_ehoc (ehoc_c4) · arc_sales · account_notes
                            client_followups · conference_notes · partner_notes
                            site_visit_notes · same_first_name · genuinely_ambiguous
    bundles/                opt-in via --fixture, NOT in the default glob:
                            recall_business_guideline_50 (5 arcs, 50 memos)

tests/                      418 tests, offline, no credentials, no spend
  fakes.py                  scripted fake models — how the graph is tested
  test_ics · test_telegram · test_google_oauth · test_calendar_confirm  (+ 20 more)

web/                        the demo UI — no framework, no build step
  server.py                 FastAPI: transcribe + streamed graph run + /api/*
  index.html                record a memo and watch the run
  people.html               everyone, as a filterable grid
  graph.html                connections — hand-rolled force layout
  app.css · shared.js       shared styling and the client-side haystack filter

data/                       gitignored — the user's real people
  person_graph.json         the person graph (+ .backup-* and .trash siblings)
  relations.json            relationship edges
  memos/ · audio/           sample input
  demo_seed.json            committed seed cast (sales); demo_graph.json is its
                            gitignored working copy — see Demo hosting below

web/google_calendar.py      OAuth flow + encrypted token, for RECALL_CALENDAR=google
render.yaml                 Render blueprint — free-tier demo config + paid appendix

00_check_bedrock.py         must print OK before any Bedrock run
01_run_local.py             localhost:8080, FREE — test here first
02_deploy.py                BILLABLE from here
03_teardown.py              run this when done
04_call_agent.py            call the deployed runtime
00_check_calendar.py        probes the calendar backend — free, writes nothing
00_check_deploy.py          preflight for hosting — config only, spends nothing
telegram_bot.py             Telegram front-end — long-poll, transport only
run_demo.py                 CLI: one memo through the pipeline
seed_demo.py                --write seeds the demo graph
backfill_times_met.py       one-off migration, already applied

docs/                       secondary docs, out of the root
  business.md               the sales framing (positioning, not a spec)
  DEMO.md                   demo-recording runbook
  upgrade.md                the hosting how-to this session's deploy work followed
  USE_CASES.md              post-hackathon parking lot
recall-writeup.pdf          the writeup, kept at root as the submission artifact
```

**The fixture filename and its scenario id differ**: the file is `arc_ehoc.yaml`, the id
inside it — the one `--scenario` takes and every table prints — is `ehoc_c4`. Both names
are correct; neither is a typo to fix.

## Known limitations

### Contact handles are typed, not extracted

Phone, Instagram, Telegram and LinkedIn live in `contacts` on the record
(`recall/contacts.py`), edited in the person panel. **Nothing in the pipeline
populates them.** A memo saying "her Instagram is @kangling" extracts a note,
not a handle -- adding a field to `Person` changes the extraction schema, and
`temperature=0` is not determinism here, so it would move the resolution
benchmark for a value the user can type in four seconds.

Three things it deliberately does not do, each for a reason worth keeping:

- **`resolve.compare` never reads it, and `LocalPersonStore.search` keeps it out
  of the retrieval haystack.** A shared handle is a data-entry mistake, not
  evidence of a shared identity, and a resolver that trusted one would merge two
  people silently. `test_contacts_stay_out_of_candidate_retrieval` is the guard.
  Filtering by handle on `/people` is client-side (`shared.js::haystack`), which
  is a different question -- "which card am I looking for", not "who is this".
- **It is not an integration.** Nothing sends, fetches or logs in; a handle is a
  string and a link the browser opens. The "no new calendar/email/LinkedIn work"
  non-goal is about plumbing, and this is a text field.
- **Normalisation happens once, at the store boundary**, the same shape as
  `as_list`: a pasted `https://www.instagram.com/kangling/?hl=en` becomes
  `kangling`, so a record cannot hold four spellings of one profile. Handles are
  undecorated, never rewritten -- a wrong handle stays wrong and visible rather
  than becoming a different, plausible one.

`upsert` merges contacts per channel (so a later write carrying only a phone
number cannot clear an Instagram handle); `replace` is wholesale, which is what
makes the UI's delete work; a merge lets the survivor's own handle win a clash
and takes the source's only where the survivor had none.

### Relationship edges are derived post-hoc, and deliberately sparse

`recall/relations.py` holds the edges between people — partner, colleague,
classmate, friend, family, mentor (directed), competitor, knows — in their own
file (`data/relations.json`), never on a `PersonRecord`. `/graph` draws them.

**It cannot move the resolution benchmark, and the guarantee is structural, not
measured.** `resolve.compare` reads six fields off a record and
`LocalPersonStore.search` builds its haystack from the same six; an edge is not
one of them and does not live on the record at all.
`test_relations_are_not_a_field_resolve_reads` and
`test_relations_stay_out_of_candidate_retrieval` are the guards. Edges are kept
out of retrieval for a second reason beyond the benchmark: a note naming two
people is evidence they are **different** humans, so retrieving one as a
candidate for the other is exactly backwards.

**A separate model call, not a field on `Person`.** Adding `relationships` to
the extraction schema would change the call that also emits `name`, `notes` and
`company` — fields `compare()` does read — and `temperature=0` is not
determinism, so the B³ and question-efficiency tables would both need
re-running. Reading the stored notes afterwards costs one call and cannot touch
a score. Same reasoning as contact handles. **Do not fold it into `extract`.**

**The model proposes; code proves.** An edge survives only if a stored note on
one of the two records **names the other person outright** — whole label, on
word boundaries, checked in `names_in()`. Not `best_match`: partial matching
scores `Jia En` against `Jia Ying` at 0.50 on the shared `jia`, which is right
for the resolver and would fill this graph with edges nobody said. The model
supplies only the kind and a short `what`, and `what` is dropped if it does not
overlap the evidence note.

Consequences worth knowing before calling it broken:

- **Most proposals die, and that is the design.** On a six-person scratch graph,
  five plausible proposals grounded to two. The dropped three were pairs whose
  notes never mention each other — the `tags.py` failure mode (predicates true
  of everyone), which here would be an assertion about two real people.
- **An unrecorded nickname breaks grounding.** A note saying _"Marc calls her
  Crispy"_ does not ground an edge to a record named `Marcus` unless `Marc` is
  in its `aliases`. Same class as the "nickname in the wrong field" finding
  below, and the same remedy: the user merges, or draws the edge by hand.
- **User-drawn edges are never withdrawn by a refresh** (`replace_derived`
  keeps `source: "user"`). The graph will miss relationships, and a graph you
  cannot correct is one you stop trusting.
- **Edges follow people.** `POST /api/people/{id}/merge` repoints them onto the
  survivor and drops the edge between the two merged records; `DELETE` drops
  every edge touching the person. An edge outliving its endpoint does not
  error — the line just stops being drawn.
- **The "shared tag" links on `/graph` are a display layer, never stored.** Two
  people studying computer science are not classmates. They are drawn dashed,
  behind their own switch, and no refresh writes them. They carry the tag as a
  label and get their own "Shares a tag" card in the side panel — unlabelled,
  a dashed line said only _that_ two people were linked, never _why_ — and both
  are kept visually and structurally apart from recorded relationships, because
  merging the two lists would quietly promote a coincidence of vocabulary into
  something the notes said.

### Role-only and descriptor-only references are not extracted

**Role aliases strengthened 3 Sep; extraction remains probabilistic.** The extraction
prompt now requires each definite role or description to be kept as an alias when a
person is also named (for example, `Alex Morgan` + `the Stripe engineer`), and the
offline suite pins that output in `tests/test_guards.py`. A targeted
`arc_recruiting`, `repeats=3` re-run moved coverage from **0.790 to 0.840** and the
substantive score from **0.870 to 0.959**. B3 recall only moved **0.523 to 0.545**
(B3 F1 **0.687 ±0.032 to 0.704 ±0.039**), so this is evidence the extraction hole
narrowed, not a reportable general improvement: each run has only ten memos and two
post-fix repeats lost `m10` to malformed structured output after all retries.

The remaining recall loss is the non-interactive fallback: shortened names and job
changes land in the ambiguity band, then the LLM often selects "someone new" instead
of the prior record. Do not lower the threshold to improve this number; it would undo
the protection against the two different Alexes.

The separate interactive-style question sweep (`arc_recruiting`, `repeats=3`) did now
surface **[14, 11, 11]** scorable cases per run, including the role aliases above. EIG
used **1.223 ±0.045** questions per resolution versus uncertainty **1.385 ±0.091** and
random **1.392 ±0.136**; its one-question rate was 64% versus 61% and 52%. However, the
overall spread (0.27) exceeds the observed gap, and two `m10` extractions failed again,
so report this as **inconclusive**. It is a useful regression signal, not a headline.

#### Post-fix business-fixture resolution sweep — 3 Sep, `repeats=3`

`uv run eval/run_eval.py --fixture eval/fixtures/bundles/recall_business_guideline_50.yaml`
now runs the five-scenario YAML bundle directly. The fixture has **50 memos** in five
independent, ten-memo professional arcs; its result is a post-fix regression measurement,
not a replacement for the existing 11-scenario headline table.

| scenario | B3 F1 | B3 P | B3 R | pair F1 | substantive | coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `arc_consulting` | 0.846 ±0.107 | 1.000 | 0.745 | 0.795 | 0.955 | 0.827 |
| `arc_enterprise_sales` | 0.905 ±0.000 | 1.000 | 0.827 | 0.881 | 0.920 | 0.923 |
| `arc_founder_investor` | 0.884 ±0.060 | 1.000 | 0.796 | 0.823 | 0.935 | 0.905 |
| `arc_partnership_events` | 0.839 ±0.018 | 0.971 | 0.739 | 0.760 | 0.943 | 0.919 |
| `arc_recruiting` | 0.849 ±0.045 | 1.000 | 0.739 | 0.753 | 0.964 | 0.963 |

**B3 F1 across the 15 scenario/repeat measurements: 0.865 ±0.117** (min 0.704, max
0.937). Four arcs held 1.000 precision; the `arc_partnership_events` loss is a
non-interactive adjudicator outcome, not an automatic resolver merge. The runtime band
flagged 241 mentions against five labelled ambiguities, and two malformed extractions
(`arc_consulting/m10`, `arc_founder_investor/m10`) were isolated rather than taking down
their repeats. The suite proves the post-fix pipeline runs on professional arcs; it does
not replace the existing 11-scenario resolution baseline.

#### Post-fix business-fixture question sweep — 4 Sep, `repeats=3`

`uv run eval/run_questions.py --fixture eval/fixtures/bundles/recall_business_guideline_50.yaml`
collected **[64, 63, 64]** scorable ambiguous cases across the three full pipeline runs
(191 total). No memos dropped during this sweep; 36 of the first run's 64 selected
questions were multi-valued.

| strategy | questions / resolution | resolved in ≤1 question |
| --- | ---: | ---: |
| EIG | **1.069 ±0.041** (min 1.016, max 1.097) | **74%** |
| uncertainty | 1.261 ±0.076 (min 1.188, max 1.339) | 71% |
| random | 1.353 ±0.097 (min 1.226, max 1.419) | 60% |

EIG is first and its displayed range clears both baselines. However, `_verdict()` uses
the **largest** strategy spread (0.19, from random) against the EIG-to-baseline mean
gap and therefore printed **inconclusive**. Preserve both statements: the observed
ordering and ranges are encouraging, while the harness's conservative, pre-existing
verdict does not authorize a stronger new claim without more repeats.

"I bumped into the male OGL... said hi... he said hi back" extracts **nobody** — not even
a non-substantive entry, which the prompt explicitly asks for. Two things overlap here:
the memo genuinely is presence-and-greeting (so `substantive: false` is the correct
label), and the model omits rather than flags. Prompt-compliance gap; the passing-mention
guard depends on the model listing people it then marks false.

**Wider than "role-only" suggests.** The 31 Aug `arc_godwin` diagnostic lost four
mentions at extraction, and only one was the documented plural case:

```
m8   the senior with the ring on his ear             NOT-EXTRACTED
m9   one of the Jia girls from my OG                 NOT-EXTRACTED   (plural)
m10  the girl who always got a smile for everyone    NOT-EXTRACTED
m13  the quiet one from my OG who drops a joke on…   NOT-EXTRACTED
```

Three are substantive descriptor-only references — a distinguishing physical detail or
habit, no name. `ehoc_c4` extracts this shape reliably (coverage 1.000), so it is not a
capability limit; the difference is that `ehoc_c4`'s descriptors are short noun phrases
("the CNM girl with clear glasses") while these are relative clauses. Worth a fixture
note before blaming the model.

### Plural references

`Person` extraction emits one record per person, so a plural phrase naming nobody —
"the two malaysian chinese independent school girls" — yields **one** entity, not two.
Real users talk this way constantly, so this is a genuine product gap, not a fixture
artifact. It needs plural-mention expansion, which is a separate feature from EIG.

**Out of scope for now; parked in Future work.** In fixtures, keep plural references rare
and expect them to fail — each one costs a recognition test that can never pass. The fix
is plural-mention expansion, a separate feature from EIG — see Future work.

### The "someone new" prior is a placeholder, not a considered number

`dedupe_node` hands the new-person hypothesis `score: 0.0` while real candidates score
~3.5. Softmax at temperature 1.0 turns that into a **1.5% prior** — so a person the user
has genuinely never mentioned before starts out nearly ruled out.

The effect is visible: answer "something else" to a clarifying question and the right
answer wins, but only at **36% confidence**, because one answer has to drag 1.5% up past
two candidates sitting at 49%. It resolves correctly and honestly reports that it is not
sure, which is the right direction to fail in, but the number is soft.

**That deferral has expired.** The reason not to retune was that it moves the
B³/pairwise baseline and the strategy benchmark at once and both were due a re-run —
both were re-run on 30 Aug, so there is now a clean baseline to attribute against. It
also matters more than it did: `W_NAME_EXACT=2.5` pushes more mentions into the ambiguous
band, which is exactly where this prior competes. If it is touched, re-run both and quote
the new thresholds. A principled value would come from how often an
ambiguous mention actually turns out to be someone new across the fixtures — which is
measurable, and is the honest way to set it.

Related fix already in: attribute probes give `outcomes[""] = "something else"`, because
holding no record of someone genuinely does predict that they will name a value we do not
have. Before that, answering "none of these" could still resolve to Kit Yee — a stranger
merged into a real contact record, the exact failure the band exists to prevent.

### The benchmark rests on one setting

`ehoc_c4` makes it a third arc, and **does not weaken this caveat — it strengthens it.**
All three are the same kind of setting: one hall or one orientation group, where people
share schools, floors, courses and one `met_at`. That shared context is exactly what
inflates merge scores (see To fix #2), so thresholds tuned here may not generalise to a
professional graph where company and role are populated and conflict. Adding a fourth
hall fixture would add memos without adding coverage.

`same_first_name` is the only fixture from a professional setting, and it is two memos
long. State the caveat in the writeup.

## Writing eval fixtures — labelling rules learned the hard way

Getting these wrong silently corrupts the benchmark rather than erroring.

- **`cluster` is the human; `as` is what you called them this time.** A loose reference
  ("the german girl") keeps the original person's cluster id. Giving it a new cluster
  makes the ground truth assert they are different people, so the system is marked wrong
  for being right.
- **`as` must be a phrase from the transcript.** The harness maps system output back onto
  gold mentions by **Jaccard over content words, assigned one-to-one** (`harness.align`).
  An invented label matches nothing and scores as a miss. A trailing `(1)`/`(2)` is
  allowed purely to keep two keys distinct and is stripped before matching. Two mentions
  in one memo may share an extracted person **only if they share a gold cluster** — that
  is the alias case ("Chong Jie" / "CJ"); different clusters are exclusive, so a collapse
  still costs.
- **Three things look like "I don't know who this is" and only one is ambiguous:**
  - _new person, described not named_ → own cluster, `ambiguous: false`
  - _known person, described not named_ → their cluster, `ambiguous: false` (tests retrieval)
  - _genuinely cannot tell between 2+ known people_ → `UNRESOLVED` + `ambiguous: true`
    — **only this is EIG's job**
- **`substantive: false` + `ambiguous: true` is incoherent.** Non-substantive mentions are
  filtered before resolution runs, so `ambiguous` is never acted on.
- **`substantive: false` hides a mention from the resolver entirely.** Marking a real
  contact false throws away a recognition test.

## The three guards (do not remove without a replacement)

Each exists because a model _told_ to be careful was observed not being careful, and each
failure was invisible in the output.

1. **Passing-mention filter** (`extract`). The model sets an explicit `substantive`
   boolean; **code** filters. Asking a model to silently omit people made the decision
   invisible and unstable — the same memo produced different name lists run to run.
2. **Enricher corroboration gate** (`enrich._verify`). Must end with a `CONFIRMED BY:`
   line naming a detail from the memo; code checks it overlaps the recorded
   company/role/event. Ungated, it produced a fluent, specific, entirely wrong biography
   for a "Daniel at Stripe".
3. **Consolidation safety net** (`merge._safe_consolidation`). Merge uses a model to
   deduplicate accumulated notes; the result is discarded if it summarised instead of
   deduplicated, emptied the notes, or invented entries. Only runs past 3 notes or 2
   places.

## Stack conventions

- **`uv`, never bare pip.** `uv sync`, `uv run <script>`.
- **Models via `chat_model()` from `_common`** — never a hardcoded client.
  `RECALL_MODEL_ID` overrides without touching code.
- **Model:** benchmarks and the personal-account `.env` use
  `global.amazon.nova-2-lite-v1:0`; the judges' path (hackathon account, `us-east-1`)
  uses `us.anthropic.claude-sonnet-4-6`, with `us.amazon.nova-2-lite-v1:0` one commented
  line away. Nova Pro is ~13x the price and measurably no better here.
- **Structured output via `with_structured_output(PydanticModel)`**, never "reply in JSON".
- **`temperature=0` for extraction/resolution/routing.** Sampling is for the drafter only.
- **Tool docstrings are the prompt.**
- **Tool errors return as content, never raise.** The step cap is the safety net.
- **Metering is a callback, not a wrapper.** A wrapper breaks anything that type-checks
  the model — `create_react_agent` rejects non-Runnables — while stubbed tests still pass.
- Python, type hints, `ruff` clean.
- Prompts that grow beyond a screen move to `prompts/` as files.
- Commit small and often; visible iteration history is worth something.

## Commands

```bash
uv sync --extra audio --extra web --extra aws
uv run pytest tests/ -q          # 418 tests, offline, no credentials, no spend

uv run 00_check_bedrock.py       # must print OK before any Bedrock run
uv run 00_check_bedrock.py --list-models [--verbose]   # probes, doesn't just list

uv run web/server.py             # http://localhost:8000 — the demo UI
uv run run_demo.py [file] [--reset]

# Telegram front-end. Needs no public URL — it long-polls getUpdates.
#   1. @BotFather -> /newbot -> TELEGRAM_BOT_TOKEN=... in .env
#   2. uv run telegram_bot.py, message the bot; it prints the chat id
#   3. TELEGRAM_ALLOWED_CHAT_IDS=<that id> in .env, restart
# The allowlist is load-bearing, not politeness: get_store() is process-global
# on one RECALL_STORE_PATH, so a second chat resolves against your contacts.
uv run telegram_bot.py

uv run 00_check_calendar.py      # probes the calendar backend, writes nothing

# Google Calendar over MCP. Local JSON ledger is the default and needs nothing.
#   1. in .env:  RECALL_CALENDAR=mcp
#                GCAL_MCP_COMMAND=npx -y @cocal/google-calendar-mcp
#                GCAL_MCP_TOOL=create-event
#   2. Google Cloud: OAuth client (Desktop), Calendar API on, you as a test user
#   3. GOOGLE_OAUTH_CREDENTIALS=/abs/path/gcp-oauth.keys.json — the SERVER's own
#      credential, nothing to do with Bedrock. Without it the server exits during
#      startup and `mcp_client` reports only "closed the connection"; it captures
#      stderr and never reads it, so the actual reason is invisible. Confirmed
#      2 Sep by probing.
#   4. first run opens a browser once to consent; the server caches the token
# The confirmation gate runs either way — the backend only decides where an
# approved event lands.

uv run 00_check_deploy.py        # preflight before hosting; --new-key for the token key
# Hosted (Render): ONE service, not two. A Render disk attaches to a single
# service, so a separate Telegram worker cannot read the OAuth token the web
# service writes. RECALL_TELEGRAM=1 runs the poller in-process.
#   uv run uvicorn web.server:app --host 0.0.0.0 --port $PORT
# Free tier has NO disk and spins down: the person graph and the Google token
# are wiped on every redeploy. A memory product that forgets is not demoable.

uv run 01_run_local.py           # localhost:8080, FREE — test here first
uv run 02_deploy.py              # BILLABLE from here
uv run 03_teardown.py            # run this when done
```

## This account's AWS situation (read before debugging model errors)

**Two accounts, measured 5 Sep 2026.** The judges run the project locally on the
hackathon account, so that path is the one `.env.example`, the README and the code
defaults now describe (decided 5 Sep: `AWS_REGION=us-east-1`,
`RECALL_MODEL_ID=us.anthropic.claude-sonnet-4-6`).

- **Hackathon SSO account (`441008218937`).** Temporary keys from the access portal
  (`AWS_ACCESS_KEY_ID`/`SECRET`/`SESSION_TOKEN`), expire in hours. An **organisation
  SCP denies every model in `ap-southeast-1`** — all 28 visible ids, Nova included —
  and denies even `ListInferenceProfiles` in the non-US regions. **`us-east-1`** is
  open: `us.amazon.nova-2-lite-v1:0`, Nova Lite/Micro/Pro, `us.anthropic.claude-sonnet-4-6`,
  `us.anthropic.claude-opus-4-6-v1` — those passed every probe. **Haiku 4.5, Sonnet 4.5
  and Opus 4.5 answered inconsistently in `us-east-1`** (absent on one sweep, callable on
  the next hour's; always callable in `us-west-2`), so do not build the judges' path on
  them. `00_check_bedrock.py` now recognises the SCP message and `--list-models` falls
  back to the US regions by itself.
- **Personal account (`206677902269`).** IAM user + access keys, no SSO, region
  `ap-southeast-1`, `global.amazon.nova-2-lite-v1:0` — the model every benchmark table
  was measured on. The rest of this section is about this account.
- **Sonnet 4.6 is not Nova, and the demo memos show it.** One CLI run of the three
  `demo.py` memos on Sonnet 4.6: it filled Priya's `company` with
  `"Antler or Jungle (uncertain)"`, which put Rachel Sim in the band against Priya on
  day 2 and the non-interactive adjudicator **merged Rachel into Priya**; and it named
  the day-3 mention `<UNKNOWN>` instead of "Jungle partner". Nova produced the clean
  4-way case. The prompts were tuned on Nova; **rehearse on whichever model the demo
  will actually run on**, and switch `.env` to Nova (`us.amazon.nova-2-lite-v1:0`) if
  the Sonnet behaviour repeats.
- **Anthropic and OpenAI models are blocked** — third-party marketplace subscriptions
  gated behind an unsubmitted _Anthropic use case details_ form. Symptom is
  `ValidationException: invalid model identifier`, which reads like a typo. Amazon Nova
  is first-party and works.
- **While that gate is outstanding, Bedrock's answers are inconsistent** — the same model
  id can pass one call and fail the next. `--list-models` probes each id twice.
- **Listing is not proof of callability.**
- **`AmazonBedrockFullAccess` does NOT cover AgentCore.** `bedrock-agentcore` is a
  separate service with its own permissions.
- `body` on `invoke_model` is a JSON string; the response `body` is a stream you read once.
- **`finish_reason == "length"` means the reply was cut**, not that the model failed.

## Hard-won findings

- **`temperature=0` is not determinism.** Bedrock returns different extractions for the
  same input across runs. Don't build a demo that depends on identical output twice, and
  don't debug a "flaky" node before ruling this out. **This matters for the eval** —
  report variance, not a single run.
- **Re-run the WHOLE pipeline per repeat, not just the scoring.** The first version of
  `run_questions.py` collected the ambiguous cases once and replayed the strategies over
  them many times. A high repeat count looked rigorous while hiding the dominant noise
  source: the case set itself moves (4–6 mentions on identical fixtures). It reported a
  lucky single sample as a result.
- **The simulated answerer was confirming facts the gold person did not hold.**
  Found 24 Aug. `truthful_answer` matched the _phrased question_ against the record at
  an overlap of 0.55. "Do they live at the 18th floor?" scored **0.583** against "lives
  on the 4th floor" — the verb and the noun `floor` are shared, only the value differs —
  so the simulated user on the 4th floor said **yes** to the 18th. Every strategy was
  updating on a lie, and because it hurt all three roughly equally the table still looked
  reasonable. Now matches `Question.source` (the recorded fact, not the question) at
  `SAME_FACT`, the same threshold `derive()` uses to decide two facts are the same fact.
  **The answerer must be consistent with the derivation by construction**, not by a
  separately-tuned number.
- **Any benchmark number produced before 24 Aug predates that fix.** Re-run before
  quoting. The resolution numbers (B³/pairwise) are unaffected — they do not use the
  answerer.
- **`_verdict()` in `run_questions.py` was never called.** `main()` ended on
  `results = per_run` and the function below it was dead. The sweep printed a table and
  silently skipped the "is this spread bigger than the gap?" check that exists precisely
  to stop a lucky run being reported as a win. **Wired since**; it passed on the 30 Aug
  run (EIG's range does not overlap either baseline).
- **Transient `ModelErrorException` kills long runs.** "The system encountered an
  unexpected error during processing" arrives with no warning and took down a
  multi-minute sweep. `chat_model()` now passes a botocore adaptive retry config, which
  also handles throttling.
- **Three different bugs all present as "it made a duplicate".** Found on the user's
  own graph, and each needs a different fix:
  1. **Nickname in the wrong field.** The extractor wrote "everyone calls her Crispy"
     into `notes`; `compare()` reads only `name` + `aliases`, so the nickname was in the
     record and structurally invisible. Fixed: an unrecognised label that appears
     ANYWHERE in the record routes through the capped descriptor channel instead of
     conflicting at −1.5, so it buys a question.
  2. **Homophone with a different first letter.** `best_match("Kayla", "Cayla") = 0.00`
     while `("Viktorya", "Viktoria") = 0.60` — token matching is prefix-anchored, so a
     mis-hear at position 0 scores nothing and one in the middle scores fine. This is the
     documented Whisper limitation, seen in real data. **The nickname fix does NOT cover
     it** — "kayla" genuinely is not in the record. Attacking the class needs phonetic
     matching (Metaphone), which brings its own false positives and its own benchmark run.
  3. **Genuinely absent evidence.** A bare name with nothing corroborating it. No system
     can link this; `NEW` is correct, and the user merges.

  The remedy for (2) and (3) is not better scoring, it is **user merge** — which is why
  `PersonStore.merge()` exists and why the absorbed name must become an alias. The user
  teaches the resolver once and the duplicate does not recur.

- **A wrong merge in the eval is not automatically a resolver bug.** Two were found on
  30–31 Aug and they had opposite causes. In `arc_acacia` the band failed: a description
  laundered through `aliases` reached `T_MATCH` and merged silently, with `_adjudicate()`
  never invoked because it only runs on the AMBIGUOUS branch. In `arc_godwin` the band
  **worked** — all four `Jia*` mentions scored 1.27–2.19, squarely in the band — and
  `_adjudicate()`, the fallback that exists only because non-interactive runs have nobody
  to ask, merged two of them anyway. **Always read the zone before blaming the
  arithmetic.** The eval runs non-interactive, so any precision loss inside the band is
  measuring the guesser, not the product's question path.

- **A broken scorer corrupts a benchmark instead of failing it.** `eval/harness.py`
  matched system output to gold mentions on `_overlap` — _any_ shared token, stopwords
  included. In a memo of descriptor references ("the tennis boy with square glasses" /
  "the tennis girl with round gold glasses") every mention matched every other, so
  `_assign`'s first-match-wins walk collapsed three correctly-extracted people onto one
  gold key and reported the rest as misses. `ehoc_c4` scored **pairwise F1 0.033 on a run
  where extraction had been near-perfect**; the same bug was quietly depressing
  `arc_godwin` (22% of its mentions collide) and hiding a real wrong merge in
  `arc_acacia`. Fixed by scoring Jaccard over content words and assigning one-to-one,
  greedily, strongest pair first. **When a benchmark number is absurd, suspect the
  scorer before the pipeline.**

- **A description laundered through `aliases` comes back as a name.** `compare()` asked
  "does this side have _any_ real name?" and then compared every name×alias pair. So
  merging "the indian girl" into Marvi stored that phrase in her aliases, and four memos
  later "the Catholic Indian" matched it at 1.00 on `indian`, took the **uncapped** name
  channel, and merged a second stranger. `W_DESCRIPTOR_MAX` exists precisely so a
  description can never auto-resolve — it holds only on first contact. The cascade was
  order-dependent: the identical mention scores −1.35 → NEW if the earlier descriptor had
  not merged first. Fixed by splitting names from descriptions **entry by entry**. Same
  function also fed `_descriptor_match` the _record's own_ labels when the mention was
  named, comparing a record against itself for a free `desc=1.00`.

- **Arithmetic projected from the pure resolve layer has now disagreed with the real
  pipeline twice.** To fix #1 (`Hui Ning`/`Hui Wen`) and To fix #3 (the two Alexes) were
  both worked out with hand-written `Person` dicts. The second was wrong in a way that
  inverted its conclusion: the doc assumed `company` and `role` carried _conflicting_
  values, but the extractor leaves both `None` and puts the content in `notes` as prose.
  Silent (`-`) versus conflicting (`0.00`) is a **3.25-point swing** and decided the case.
  The pure layer is the right place to _unit-test_ a rule and the wrong place to
  _predict_ an outcome — what reaches it is whatever the LLM chose to populate. Write
  projections as "projected", and run the pipeline before believing them.

- **A shared syllable is not a shared name.** `best_match` scored the single best token
  pair, so `"Hui Ning"` matched `"Hui Wen"` at 1.00 on `hui`. `W_NAME_EXACT` equals
  `T_MATCH` exactly, so the name channel alone auto-resolved and two different people
  merged with no question asked — `_adjudicate()` only runs on AMBIGUOUS and never sees a
  RESOLVED verdict. **A field weight equal to the threshold makes that field a single
  point of failure**; check the others for the same shape. Fixed by scoring coverage of
  the shorter name. See To fix #1 and #2.
- **A precision test only tests the setting it was written in.** `same_first_name.yaml`
  passed for two years' worth of runs and never covered the student case, because it
  relies on company/role _conflict_ to push the score down and students have neither
  field. A guard that passes because the data happens to supply a conflicting field is
  not a guard. See To fix #3.
- **`notes` is `list[str]`, one atomic fact per entry** — never one jammed string.
  Compound notes lose qualifiers ("computer science, same major as me" →
  "studies computer science").

  **Atomicity serves the QUESTIONS, not the matching.** `resolve.compare` does
  `tokens(" ".join(notes))` — it joins everything before tokenising, so entry
  boundaries have _zero_ effect on the resolution score. What depends on them is
  `questions.py`, which reads notes per entry: one note becomes one candidate
  fact becomes one question, and a compound entry yields a compound question
  that is unanswerable yet still scores in bits and still gets asked. Plus
  per-note deletion in the UI. Do not justify atomicity by matching quality;
  that was asserted once without reading `compare()` and is false.

  **The current prompt over-fragments.** "Split on meaning" atomises a single
  episode into beats — "was hungry and wanted to buy something to eat at fair
  price" / "I offered her my dessert" / "came to my room" are one story in three
  entries, and a record reads as rubble. Durable attributes are fine as a list;
  narrative is not. The fix is to **label** each atomic note with a key
  (`school`, `residence`, `course`) and group on the key at display time —
  never to merge the text, which breaks question derivation and is
  irreversible. That is the `attribute_edge(key, value)` in Future work.
  A regex shortcut does not work: the fact-shaped pattern in `questions.py`
  matches "was hungry" and misses "came to my room", so it mislabels in both
  directions. A real split needs the model.

- **`el.hidden` does nothing against an author `display` rule, and fails silently.**
  The `hidden` attribute hides an element only through the UA rule
  `[hidden]{display:none}`, which ANY author `display` declaration outranks. The
  `/graph` empty-state overlay was `position:absolute; inset:0; display:flex`, so
  `box.hidden = true` set the attribute, changed nothing, and left an
  invisible-looking overlay across the whole canvas eating every `pointerdown`.
  Nodes could not be selected and the cause was nowhere near the click handler.
  Needs `.empty[hidden]{display:none}` **and** `pointer-events:none` — the
  overlay legitimately shows on an empty graph, where its own text invites the
  click it would then swallow. `test_the_graph_overlay_cannot_swallow_a_click`
  is the tripwire.
- **A colour token can be invisible in one theme and fine in the other.** The
  shared-tag links were `--line2` at .30 alpha: `#CFC3B6` on the light theme's
  `#E9E2D9` ground is a difference you cannot see. The switch appeared dead
  while the links were in fact there, pulling the layout about — which is what
  "it wiggles and nothing changes" was. Check both themes before trusting a
  dimmed token, and prefer `--muted` as the dimmest that still reads in both.
- **Normalise list fields with `as_list()` at every boundary.** `list("a string")`
  silently explodes into per-character entries that then persist and consolidate without
  raising.
- **Prompt caching is Anthropic-only.** A cache point sent to Nova is a hard
  `ValidationException`.
- **Load `.env` in `recall/__init__.py`**, not a submodule.
- **Enrichment is silent by default and that is correct.** Most people you meet have no
  findable public presence.
- **Whisper on Singlish / code-switched speech:** degrades badly, and names sit exactly
  at code-switch boundaries — the worst case. Reported mixed error rates for baseline
  `whisper-large-v3` on **SEAME: ~54–61%**. Never treat a transcribed name as ground
  truth; every name is a candidate with a confidence, which is what the architecture
  already does.
- **Never trust a hotword-biased spelling.** Biasing transcription toward a known contact
  list can make the model _insert a name that was never spoken_. If hotwords are ever
  added, the output is still a candidate, never ground truth.

## Cost discipline

- **Log `usage` per call.** `LEDGER.report()` prints tokens and cost per node.
- **`PRICING` in `_common.py` only carries rates worth trusting.** An unlisted model
  reports tokens and declines to invent a cost — Nova 2 Lite is unpriced, hence `$0.0000`.
- **The enricher dominates spend** — 80–90% of tokens, the only multi-step tool loop.
- **AgentCore bills for the runtime existing**, not per call, and `destroy` leaves
  S3 / ECR / CloudWatch behind.
- Reach for few-shot only after zero-shot is shown to fail.

---

## Future work (cut from scope — cite, don't build)

- **Unlinked bare-nickname routing (To fix #4).** An extraction flag marking a mention an
  informal label rather than a formal name, so `"big boss"` with no article and no
  descriptor word routes through the capped descriptor channel into the ambiguous band
  instead of filing a duplicate. A `Person` schema change that moves both benchmark
  tables, so batched with the other schema-touching deferrals below. Resolves fine today
  once the nickname is a stored alias; only the unlinked first-sight case fails.
- **Plural-mention expansion.** A phrase naming nobody individually — "the two malaysian
  chinese independent school girls" — yields ONE `Person` today, not two. Real users talk
  this way constantly, so it is a genuine product gap. The fix is to let extraction emit
  N records from one plural phrase (a count + shared descriptor per head), then let each
  land in the resolver independently. Separate feature from EIG, and it changes the
  extraction call, so it re-baselines the tables. See Known limitations.
- **Bi-temporal belief graph.** Copy Graphiti's schema (arXiv:2501.13956). Currently a
  flat `PersonRecord`. The intended model:

  ```
  person(id, canonical_name, created_at)
  mention(id, memo_id, raw_text, transcript_span, extracted_at)
  mention_link(mention_id, person_id, match_probability, status)
      status ∈ {resolved, ambiguous, new}
  attribute_edge(id, person_id, key, value,
                 confidence,       -- calibrated [0,1]
                 valid_from,       -- when the fact held in the world
                 valid_to,         -- NULL = still believed
                 recorded_at,      -- when we learned it
                 source_memo_id,
                 evidence_span)    -- required; no ungrounded attributes
  ```

  Rules: **invalidate, never delete** — set `valid_to`, keep the row; history is the
  point. A person is a _cluster of mentions_, not a row that gets overwritten. Every
  attribute needs an `evidence_span` — if the model can't point at the transcript, it's
  a hallucination, drop it.

- **Contradiction sweep.** Background job (Letta sleep-time pattern); sequential conflict
  (robotics → fintech, months apart) = life change, auto-update; overlapping conflict =
  one is wrong, queue for a question.
- **Calibration measurement.** ECE, Brier, reliability diagram. **Deliberately cut as a
  headline claim:** ~20–50 hand-written memos yields too few predictions per bin to
  assert calibration honestly, and a judge who knows statistics will ask about the n.
  Keep the confidence values; let EIG carry the novelty.
- **MERaLiON-2** as primary ASR with Whisper as fallback.
- **OpenTelemetry** spans per decision, with confidence and EIG as attributes.
- **SQLite/Postgres store** in place of JSON.
- **AgentCore Memory** — see below.

### AgentCore Memory — must fix before deploying

`recall/memory_agentcore.py` exists but is **architecturally wrong** and has never run.
Deploying with `RECALL_MEMORY=agentcore` as-is would silently break resolution — every
known person would look new.

How the service actually works (verified against the installed SDK):

- **Events = short-term.** `create_event(memory_id, actor_id, session_id, messages)`
  stores raw `(text, role)` turns, retained `event_expiry_days` (default 90).
- **Extracted records = long-term.** Attach **strategies** (`semantic`, `summary`,
  `user_preference`, `episodic`, custom); AgentCore runs _its own LLM_ over your events
  **asynchronously** into path-like namespaces (`/actor/Jane/`). `retrieve_memories()`
  searches _those_.

What the current implementation gets wrong: it writes a JSON blob via `create_event` and
reads it back with `retrieve_memories` expecting the same JSON; attaches no strategy, so
nothing is extracted; ignores that extraction is async when resolution needs
read-after-write within one run; and uses a namespace that doesn't match the path shape.

**Recommended fix — durable storage, not extraction engine.** Keep our `PersonRecord`
schema and our resolution logic; store records as events and read them back with
`list_events` (synchronous, raw). Optionally _also_ attach a semantic strategy for bonus
fuzzy recall, with local lexical search as fallback.

Setup order: attach `bedrock-agentcore` IAM permissions → `create_memory_and_wait`
(minutes to ACTIVE) → set `AGENTCORE_MEMORY_ID` + `RECALL_MEMORY=agentcore` → rewrite the
backend → test against a throwaway memory resource.

---

## Pitch framing (keep out of the code, keep in mind)

People who care about the people they meet and lose them anyway, because the details
evaporate in the ten minutes after meeting someone. **Never** frame as extracting value
from contacts later. The brief asks for solutions that leave people genuinely better off.

## Do / Don't for Claude Code

- **Do** use `uv run`, typed structured output, and content-not-exception tool errors.
- **Do** run the offline tests before anything that spends AWS money.
- **Do** verify claims against the installed SDK or a real call rather than memory — a
  single probe is not proof, and this project has been bitten by that twice.
- **Don't** run exploratory or test memos against the user's live person graph. Twice
  now, test transcripts were written into it and later looked like the agent
  hallucinating facts the user never said — the expensive kind of bug, because it
  discredits the model instead of the process. Any throwaway run sets both:
  ```bash
  RECALL_STORE_PATH=<scratch>/graph.json RECALL_CALENDAR_PATH=<scratch>/cal.json \
  RECALL_RELATIONS_PATH=<scratch>/relations.json uv run ...
  ```
- **Don't** add a framework, technique, or sub-agent unless the simpler version has
  demonstrably failed — justify the cost in a comment.
- **Don't** flatten the graph. The conditional routing and sub-agents _are_ the score.
- **Don't** extend the frozen tail (enrichment, drafts). The calendar's confirmation
  gate was a deliberate exception on 2 Sep — see Non-goals; it does not reopen the tail.
- **Don't** leave AgentCore running after a test session.
