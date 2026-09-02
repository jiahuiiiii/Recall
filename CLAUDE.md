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
the working pipeline that already exists. It is *not* the full research spec — bi-temporal
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
- **No new calendar/email/LinkedIn work.** Plumbing, not differentiation. The calendar
  writer already exists — freeze it, don't extend it.
- **No new web-enrichment work.** Out of scope, and measured to be silent for most real
  contacts anyway.
- **No POMDP solver, no AGM belief revision, no ASR fine-tuning.** Cite; don't build.

If asked to add a feature, default to no. Five minutes of demo cannot show breadth.

---

## Current status

**The full pipeline works and the headline benchmark exists.** 311 tests, all offline.
Runs from CLI or the web UI.

```
transcribe -> extract -> dedupe(3-zone band) -> ask(EIG, pauses) -> (enrich | merge) -> ...
```

The pause is real: on an interactive run `dedupe` holds ambiguous mentions, `ask`
suspends the graph on `interrupt()`, and **the human's answer decides which branch the
person takes**.

| Piece | State |
|---|---|
| LangGraph supervisor, conditional edge, fan-in | **Done**, tested |
| Transcription (Groq `whisper-large-v3`) | **Done**, ~1.2s for a 20s memo |
| Extraction → typed `Person`, atomic `notes`, substantive filter | **Done** |
| Candidate retrieval — stem/substring/misspelling tolerant | **Done**, 11 tests |
| **Three-zone band** (`recall/resolve.py`) — pure, + near-tie margin | **Done**, 19 tests |
| **EIG selection** (`recall/eig.py`) — pure, per-question reliability | **Done**, 23 tests |
| **Question derivation** (`recall/questions.py`) — mechanical | **Done**, 32 tests |
| **`ask_node`** — one question per memo, rejected set carried in state | **Done** |
| Eval harness — fixtures, B³/pairwise, validator, audio→fixture | **Done** (`eval/`) |
| Simulated answerer (`eval/strategies.py`) | **Done**, 7 tests — was untested, and was wrong |
| **EIG vs random vs uncertainty benchmark** | **Done**, re-run 30 Aug — see below |
| Person store, merge + consolidation, delete/patch | **Done** |
| **User merge of two people** (`store.merge`, `/api/people/{id}/merge`, UI) | **Done 31 Aug**, 7 tests, trash file for undo |
| **Contact handles** (`recall/contacts.py`, `PATCH /api/people/{id}`, UI) | **Done 1 Sep**, 36 tests, user-typed only — see below |
| — the panel's contact fields commit on blur/Enter, no Save button | **Done 1 Sep** |
| **Relationship edges** (`recall/relations.py`, `/graph`) | **Done 2 Sep**, 42 tests, display-only — see below |
| Web UI — record, type, edit, live graph, person graph, delete | **Done**, responsive |
| Enricher / drafter / calendar tail | Done, **frozen** (outside scope) |
| **Multi-valued questions** (`questions.attribute_questions`) | **Done**, in the 32 above |
| **Demo surface** — question card in the web UI, `ask` in the diagram | **Done**, 3 server tests |
| **Answering the question** — `interrupt()`, `/api/answer`, clickable options | **Done**, 18 tests |
| **Applying the answer** (`recall/answer.py`) — Bayes, pure | **Done**, 12 tests |
| **Name matching** (`text.best_match`) — coverage, not single best pair | **Fixed**, see To fix #1 |
| `arc_godwin` fixture — 14 memos, 20 people, 11 loose references | **Done**, validated |
| `ehoc_c4` fixture — 11 memos, 14 people, 13 recurring | **Done**, validated, best-scoring arc |
| **Eval scorer back-mapping** (`harness.align`) — one-to-one | **Fixed 30 Aug**, 8 tests |
| **Name/descriptor channel separation** (`resolve.compare`) | **Fixed 30 Aug**, 5 tests |
| AgentCore Memory backend | Written blind, **known broken**, never run |
| AgentCore deploy (`01`–`04`) | Written, never run |

### Resolution baseline — measured 31 Aug (post-nickname-fix), `repeats=3`

Thresholds in force: `T_MATCH=3.0`, `T_NONMATCH=1.0`, `MIN_MARGIN=1.0`, `W_NAME_EXACT=2.5`.
Quote them with any result.

| scenario | B³ F1 | B³ P | B³ R | pair F1 | subst | covrg |
|---|---|---|---|---|---|---|
| `arc_godwin` | 0.896 ±0.015 | 0.947 | 0.851 | 0.717 | 0.956 | 0.965 |
| `ehoc_c4` | 0.926 ±0.045 | 0.989 | 0.874 | 0.837 | 0.971 | 0.977 |
| `arc_godwin` | 0.896 ±0.007 | 0.947 | 0.851 | 0.718 | 0.956 | 0.956 |
| `arc_acacia` | 0.810 ±0.000 | 1.000 | 0.681 | 0.632 | 0.873 | 0.857 |
| `same_first_name` | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| `genuinely_ambiguous` | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |

`B³ F1 across all scenarios: 0.927 ±0.095 (n=15)` — no extraction failures this run.

**A new baseline, not a delta.** The old `arc_acacia` figure (`B³ P=1.000 R=0.856
F1=0.922`, pairwise 0.800) is superseded and must not be compared against: three things
changed between the two measurements — `W_NAME_EXACT` 3.0 → 2.5, the name/descriptor
channel separation in `compare()`, and the eval scorer rewrite. Each is unit-tested
alone; no run separates their contribution to these numbers.

**Precision is a per-scenario claim, not a global one.** `arc_acacia` and `ehoc_c4` are
at 1.000 — nothing wrongly merged, every loss a missed recognition, the right direction
to fail in. The old blanket sentence *"precision had been 1.000 throughout"* was **false
when written**: `arc_acacia` held a real wrong merge (`marvi`+`shiny`, see Hard-won
findings) that the broken scorer hid. `arc_godwin` sits at 0.947, and that loss is
**the LLM adjudicator, not the band** — see To fix #5d.

### Question efficiency — measured 31 Aug, `repeats=3`

```
strategy       questions/resolution                       <=1 question
eig            0.985 ±0.111  (n=3, min 0.839  max 1.061)       68%
uncertainty    1.359 ±0.093  (n=3, min 1.242  max 1.429)       57%
random         1.323 ±0.079  (n=3, min 1.258  max 1.417)       60%
```

Case sets of 37/33/35 per run, budget cap 5. EIG's max (1.061) sits below BOTH baselines'
minimums (1.242, 1.258) — `_verdict()` passes at full repeats. 10/37 multi-valued, 27/37
yes/no.

**Claim "EIG beats both baselines", never an ordering between them.** Uncertainty and
random swapped places when the nickname path landed (they were 1.093 / 1.183, now 1.359 /
1.323) and their ranges overlap heavily. At this n they are indistinguishable from each
other. Only EIG separates.

**Absolute numbers rose for every strategy** (EIG 0.881 → 0.985) because the band grew
from 136 to 150 runtime flags and the arrivals are hard cases — unrecognised labels with
weak corroboration. That is the nickname fix working, not a regression, but it shows the
headline is sensitive to band size. See caveat 1.

Two caveats that must travel with this table:

1. **The denominator is coupled to the resolver.** `W_NAME_EXACT=2.5` pushes bare-name
   returns into the ambiguous band, so `'Yixin' -> Yixin` is now a scored case. Fair
   across strategies (one case set), but resolution quality and question efficiency are
   **not independent results** and must not be written up as if they were.
2. **`ehoc_c4` supplies roughly a third of the cases** — one fixture carries much of
   the number.

`run_eval` still logs one `ehoc_c4/m10` extraction failure per sweep. Its cases are lost;
the run is not. That is the fix that got this table to n=3 — see To fix #5a.

### Fixtures

53 memos, 108 mentions, 40 recurring people across five scenarios. `uv run
eval/check_fixtures.py` exits 0.

| Scenario | memos | people | what it carries |
|---|---|---|---|
| `arc_acacia` | 24 | 12 | the original arc, source of the resolution baseline |
| `arc_godwin` | 14 | 20 | Luminia OG. **11 loose references**, 8 of which land in the ambiguous band — the EIG denominator. Four same-syllable name pairs |
| `ehoc_c4` | 11 | 14 | Eusoff Hall orientation. **13 recurring of 14** — the densest recognition test. Four memos of descriptor-only references, and the fixture that exposed the scorer bug |
| `same_first_name` | 2 | 2 | precision diagnostic. Merged two Alexes until 28 Aug; now 1.000 |
| `genuinely_ambiguous` | 2 | 1 | two memos, one scored mention |

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

### 2. The residual merge window — **now measured, still open**

No longer arithmetic-in-a-comment. Measured on the real pipeline:

```
"indian girl" vs Marvi:  desc=1.00 (2.0) + notes=1.00 (1.5) = 3.50  >= T_MATCH  RESOLVED
```

**No name channel fired at all.** `W_DESCRIPTOR_MAX` does exactly what it promises — a
description alone cannot reach 3.0 — but description *plus* notes overlap can, and every
person in a single-hall fixture shares vocabulary. It was the right person here; the
arithmetic does not guarantee the next one.

The fix is to cap the total when no name channel fired, the same shape as
`W_DESCRIPTOR_MAX`. The old reason for deferring — "not before the benchmark re-run" —
has expired; the re-run is done and there is now a clean baseline to attribute against.

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

### 4. A bare nickname resolves as a name conflict — **half closed**

`_is_name` now treats a leading article as marking a description, so `"the Catholic
Indian"` routes to the descriptor path. `"big boss"` still does not: no article, no token
in `DESCRIPTOR_WORDS`, so it takes the name channel, conflicts with every stored name,
and files a duplicate. The `arc_godwin` workaround — phrasing it *"the guy everybody
calls big boss"* — still lives in the fixture, not the code.

### ~~5. Fixtures are in `.gitignore`'s negation but still uncommitted~~ — **DONE**

All five scenarios are tracked (`git ls-files eval/fixtures/`), so the negation did its
job. `arc_godwin.original.yaml.bak` is deleted — the history is the backup now.

**What the same blind spot cost elsewhere:** `data/person_graph.json` was a *literal*
ignore rule, so the `.backup-*` and `.trash` siblings it was written to protect were
never covered, and four of them are committed. The rule is now a glob
(`data/person_graph*.json`). Ignore rules for private data should be globs from the
start — a literal only protects the one filename you thought of.

### 5a. `with_structured_output` sometimes returns a JSON string, not a list

```
PeopleExtraction.people: Input should be a valid list, input_type=str
```

Killed one `arc_godwin/m13` extraction in `run_eval` and an **entire run** of
`run_questions`, which is why the headline table is n=2 rather than n=3. Not a fixture
problem and not deterministic. Needs a retry or a coercing validator before the headline
is re-run, or the same run keeps dropping out.

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
absent got it wrong. Say so in the writeup — the cost of *not* asking is visible in that
0.947, which cuts toward the claim rather than against it.

Do not "fix" this by tightening the adjudicator prompt before the writeup. It is
currently the cleanest evidence that the ambiguous band is identifying the right cases.

### 5b. The code default model is one this account cannot call

`_common.py` defaults `HAIKU` to `global.anthropic.claude-haiku-4-5-...`, which is
exactly the gated path described under **This account's AWS situation**. It only works
because `.env` sets `RECALL_MODEL_ID=global.amazon.nova-2-lite-v1:0`, and `.env` is
gitignored — so a fresh clone, a teammate, or the AgentCore runtime without that env var
gets `ValidationException: invalid model identifier` and reads it as a typo. `.env.example`
now sets the Nova id uncommented; changing the code default is the remaining half and is
a behaviour change, so it is left as a decision rather than done quietly.

Related, smaller: `SONNET` / `_DEFAULT_SONNET` are defined and never used anywhere, and
`cached_system()` asks `supports_cache_point(HAIKU)` — the module default — rather than
the model the call is actually being built for. Latent only while nothing passes
`model=` to `chat_model()`, which nothing currently does.

### 5c. `answer.rebuild_question` / `rebuild_hypotheses` are dead, and would lose noise

Nothing calls either — not the graph, not the server, not the tests. Worse, the payload
they read from is what `ask._shown()` emits, and that carries neither `key` nor `noise`,
so a rebuilt `Question` silently falls back to the global `ANSWER_NOISE` instead of the
per-question reliability EIG scored it under. That is precisely the mismatch
`recall/answer.py`'s own module docstring says must not happen. Either wire the
out-of-graph path up and add `noise` to `_shown()`, or delete both functions.

### 6. Already documented, unchanged

Role-only references are not extracted; plural references yield one entity; the
"someone new" prior is a placeholder at 1.5%; the benchmark rests on one setting. See
**Known limitations**. A Whisper mis-hear that changes the *first* token
(`Zhong Xuan` → `Jong Shuen`) scores 0.00 and does not match at all — this is unchanged
by the fix and is exercised by `arc_godwin` m14.

---

## To do

Measurement and words, not building. Nothing here needs a new feature.

1. **Fix the structured-output string bug, then re-run the headline at n≥3.** The
   30 Aug table is n=2 because one run died on it (To fix #5a). Fixing it first is the
   cheaper order — otherwise the same run keeps dropping out and every re-run costs a
   third of its value.
2. **Commit the fixtures.** They are untracked; `arc_godwin.original.yaml.bak` goes once
   they have history.
3. **The backend.** `recall/memory_agentcore.py` is architecturally wrong and has never
   run; deploying with `RECALL_MEMORY=agentcore` as-is would make every known person look
   new. Read **AgentCore Memory — must fix before deploying** before starting, and test
   against a throwaway memory resource, never the live graph.
4. **Seed the demo data** — `uv run seed_demo.py --write`.
5. **The writeup.** There is a real result to report, and it is now measured rather than
   projected. Two things must be said plainly: the headline is n=2, and question
   efficiency is coupled to `W_NAME_EXACT` rather than independent of it.
6. **The demo script**, written and timed, then rehearsed.

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
                        [frozen tail: commitments → drafts → calendar]
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
- **An unrecorded nickname breaks grounding.** A note saying *"Marc calls her
  Crispy"* does not ground an edge to a record named `Marcus` unless `Marc` is
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
  a dashed line said only *that* two people were linked, never *why* — and both
  are kept visually and structurally apart from recorded relationships, because
  merging the two lists would quietly promote a coincidence of vocabulary into
  something the notes said.

### Role-only and descriptor-only references are not extracted

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

**Out of scope; do not build it.** In fixtures, keep plural references rare and expect
them to fail — each one costs a recognition test that can never pass.

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
  - *new person, described not named* → own cluster, `ambiguous: false`
  - *known person, described not named* → their cluster, `ambiguous: false` (tests retrieval)
  - *genuinely cannot tell between 2+ known people* → `UNRESOLVED` + `ambiguous: true`
    — **only this is EIG's job**
- **`substantive: false` + `ambiguous: true` is incoherent.** Non-substantive mentions are
  filtered before resolution runs, so `ambiguous` is never acted on.
- **`substantive: false` hides a mention from the resolver entirely.** Marking a real
  contact false throws away a recognition test.

## The three guards (do not remove without a replacement)

Each exists because a model *told* to be careful was observed not being careful, and each
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
- **Model:** currently `global.amazon.nova-2-lite-v1:0`. Anthropic is blocked on this
  account (below). Nova Pro is ~13x the price and measurably no better here.
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
uv run pytest tests/ -q          # 311 tests, offline, no credentials, no spend

uv run 00_check_bedrock.py       # must print OK before any Bedrock run
uv run 00_check_bedrock.py --list-models [--verbose]   # probes, doesn't just list

uv run web/server.py             # http://localhost:8000 — the demo UI
uv run run_demo.py [file] [--reset]

uv run 01_run_local.py           # localhost:8080, FREE — test here first
uv run 02_deploy.py              # BILLABLE from here
uv run 03_teardown.py            # run this when done
```

## This account's AWS situation (read before debugging model errors)

- Personal account, IAM user + access keys. No SSO. Region `ap-southeast-1`.
- **Anthropic and OpenAI models are blocked** — third-party marketplace subscriptions
  gated behind an unsubmitted *Anthropic use case details* form. Symptom is
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
  Found 24 Aug. `truthful_answer` matched the *phrased question* against the record at
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
  matched system output to gold mentions on `_overlap` — *any* shared token, stopwords
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
  "does this side have *any* real name?" and then compared every name×alias pair. So
  merging "the indian girl" into Marvi stored that phrase in her aliases, and four memos
  later "the Catholic Indian" matched it at 1.00 on `indian`, took the **uncapped** name
  channel, and merged a second stranger. `W_DESCRIPTOR_MAX` exists precisely so a
  description can never auto-resolve — it holds only on first contact. The cascade was
  order-dependent: the identical mention scores −1.35 → NEW if the earlier descriptor had
  not merged first. Fixed by splitting names from descriptions **entry by entry**. Same
  function also fed `_descriptor_match` the *record's own* labels when the mention was
  named, comparing a record against itself for a free `desc=1.00`.

- **Arithmetic projected from the pure resolve layer has now disagreed with the real
  pipeline twice.** To fix #1 (`Hui Ning`/`Hui Wen`) and To fix #3 (the two Alexes) were
  both worked out with hand-written `Person` dicts. The second was wrong in a way that
  inverted its conclusion: the doc assumed `company` and `role` carried *conflicting*
  values, but the extractor leaves both `None` and puts the content in `notes` as prose.
  Silent (`-`) versus conflicting (`0.00`) is a **3.25-point swing** and decided the case.
  The pure layer is the right place to *unit-test* a rule and the wrong place to
  *predict* an outcome — what reaches it is whatever the LLM chose to populate. Write
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
  relies on company/role *conflict* to push the score down and students have neither
  field. A guard that passes because the data happens to supply a conflicting field is
  not a guard. See To fix #3.
- **`notes` is `list[str]`, one atomic fact per entry** — never one jammed string.
  Compound notes lose qualifiers ("computer science, same major as me" →
  "studies computer science").

  **Atomicity serves the QUESTIONS, not the matching.** `resolve.compare` does
  `tokens(" ".join(notes))` — it joins everything before tokenising, so entry
  boundaries have *zero* effect on the resolution score. What depends on them is
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
  list can make the model *insert a name that was never spoken*. If hotwords are ever
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
  point. A person is a *cluster of mentions*, not a row that gets overwritten. Every
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
  `user_preference`, `episodic`, custom); AgentCore runs *its own LLM* over your events
  **asynchronously** into path-like namespaces (`/actor/Jane/`). `retrieve_memories()`
  searches *those*.

What the current implementation gets wrong: it writes a JSON blob via `create_event` and
reads it back with `retrieve_memories` expecting the same JSON; attaches no strategy, so
nothing is extracted; ignores that extraction is async when resolution needs
read-after-write within one run; and uses a namespace that doesn't match the path shape.

**Recommended fix — durable storage, not extraction engine.** Keep our `PersonRecord`
schema and our resolution logic; store records as events and read them back with
`list_events` (synchronous, raw). Optionally *also* attach a semantic strategy for bonus
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
- **Don't** extend the frozen tail (enrichment, drafts, calendar).
- **Don't** leave AgentCore running after a test session.
