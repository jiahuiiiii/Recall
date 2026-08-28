# AGENTS.md

Project instructions for Codex. Read this at the start of every session.

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

**The full pipeline works and the headline benchmark exists.** 173 tests, all offline.
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
| **EIG vs random vs uncertainty benchmark** | **Done** — see below |
| Person store, merge + consolidation, delete/patch | **Done** |
| Web UI — record, type, edit, live graph, person graph, delete | **Done**, responsive |
| Enricher / drafter / calendar tail | Done, **frozen** (outside scope) |
| **Multi-valued questions** (`questions.attribute_questions`) | **Done**, in the 32 above |
| **Demo surface** — question card in the web UI, `ask` in the diagram | **Done**, 3 server tests |
| **Answering the question** — `interrupt()`, `/api/answer`, clickable options | **Done**, 18 tests |
| **Applying the answer** (`recall/answer.py`) — Bayes, pure | **Done**, 12 tests |
| **Name matching** (`text.best_match`) — coverage, not single best pair | **Fixed**, see To fix #1 |
| `arc_godwin` fixture — 14 memos, 20 people, 11 loose references | **Done**, validated |
| AgentCore Memory backend | Written blind, **known broken**, never run |
| AgentCore deploy (`01`–`04`) | Written, never run |

### Resolution baseline (`arc_acacia`, 24 memos)

`B³ P=1.000 R=0.856 F1=0.922` · `pairwise P=1.000 R=0.667 F1=0.800`

> **⚠️ Taken before `text.best_match` changed. Re-run before quoting.** Only one
> `arc_acacia` name pair is affected (`the female Acacia OGL` / `the male OGL`,
> 1.00 → 0.88, two different people, so it moves the right way), and the change is
> projected not to move these numbers — but projected is not measured.

**Precision had been 1.000 throughout** — nothing wrongly merged, every loss a missed
recognition, which is the right direction to fail in. That claim now has a caveat:
`arc_godwin` contains same-syllable name pairs that *did* merge before the fix, and the
sentence should not be written into the submission until the re-run confirms it. See
To fix #1. Thresholds in force: `T_MATCH=3.0`, `T_NONMATCH=1.0`, `MIN_MARGIN=1.0`.
Quote them with any result.

### Fixtures

42 memos, 77 mentions, 27 recurring people across four scenarios. `uv run
eval/check_fixtures.py` exits 0.

| Scenario | memos | people | what it carries |
|---|---|---|---|
| `arc_acacia` | 24 | 12 | the original arc, source of the resolution baseline |
| `arc_godwin` | 14 | 20 | Luminia OG. **11 loose references**, 8 of which land in the ambiguous band — the EIG denominator. Four same-syllable name pairs |
| `same_first_name` | 2 | 2 | precision diagnostic — but only the *professional* case, see To fix #3 |
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

### 1. Confirm the name-matching fix against the real pipeline — **not yet measured**

`text.best_match` scored the single best token pair, so one shared syllable carried a
whole name: `best_match("Hui Ning", "Hui Wen") == 1.00`. `W_NAME_EXACT` is 3.0 and
`T_MATCH` is 3.0, so **the name channel alone crossed the threshold** — every other field
could be silent and it still merged. Two different people became one record, with no
question asked, because `_adjudicate()` only runs on the AMBIGUOUS branch and never sees
a RESOLVED verdict.

Now scores coverage of the shorter name instead of the best pair. Extra tokens on the
longer side stay silence (`Kit` still matches `Kit Yee` at 1.00); a token with no
counterpart at all now counts as disagreement. Measured, old → new:

```
Hui Ning / Hui Wen   1.00 -> 0.50     Wei Lin / Lin, Wei     1.00 -> 1.00  unchanged
Jie Yu   / Jing Yu   1.00 -> 0.50     Wei Lin / Wei Lin Tan  1.00 -> 1.00  unchanged
Jia Qi   / Jia Ying  1.00 -> 0.50     Kit / Kit Yee          1.00 -> 1.00  unchanged
DBS Bank / OCBC Bank 1.00 -> 0.50     Viktorya / Viktoria    0.60 -> 0.60  unchanged
```

End-to-end the pair moves from RESOLVED 4.55 to **AMBIGUOUS 2.30** — it asks instead of
merging, which is the thesis working. A genuine return still resolves (5.08). 173 tests
pass, `ruff` clean.

**All of that is projected from the pure resolve layer with hand-written notes.** The
real pipeline puts LLM extraction in front of it. Re-run before treating it as closed.

### 2. The residual merge window is not closed by construction

After the fix, worst case for a shared-syllable pair:

```
name 0.75 + event 1.25 + notes 1.50 = 3.50  >=  T_MATCH 3.0  -> still RESOLVED
```

With a shared `met_at`, **notes overlap ≥ 0.67 would still merge two different people.**
Hui Wen / Hui Ning measured 0.20, so the current data is clear — but by margin, not by
arithmetic. Every `arc_godwin` person shares `met_at: Luminia orientation group`, so that
1.25 is always on the table.

The consistent fix is to cap the total when the name is only partially matched, the same
way `W_DESCRIPTOR_MAX` is capped below `T_MATCH` so a description can never auto-resolve.
**Do not add it before the benchmark re-run** — two new mechanisms at once and you cannot
attribute which moved the number.

### 3. `same_first_name.yaml` does not cover the student setting

It passes only because the two Alexes have **conflicting company and role** (robotics
masters at NTU vs payments compliance at a bank), and those conflicts carry negative
weight. Uni students have neither field populated, and they all share one `met_at`, so
the same collision resolves the opposite way:

```
Alex vs Alex           name=1.00  company=0.00 conflict  role=0.00 conflict  -> -0.10  NEW  ✓
Hui Ning vs Hui Wen    name=1.00  company=—    silent    role=—    silent    ->  4.55  RESOLVED  ✗
```

The only precision diagnostic tests professional networking. Add a student-setting one —
two names sharing a syllable, no company, no role, same event.

### 4. A bare nickname resolves as a name conflict, not a description

`_is_name("big boss")` is `True` — no token is in `DESCRIPTOR_WORDS` — so it takes the
name channel, conflicts with every stored name, and lands at −1.50 → NEW. A bare nickname
therefore creates a duplicate person rather than recalling the real one. Worked around in
`arc_godwin` by phrasing as *"the guy everybody calls big boss"*, which routes to the
descriptor path. The workaround is in the fixture, not in the code.

### ~~5. Fixtures are not in version control~~ — **FIXED 25 Aug**

`.gitignore` carried a blanket `*.yaml`, which ignored **every file in
`eval/fixtures/`** — `git ls-files eval/fixtures/` returned only `README.md`. A
`!eval/fixtures/*.yaml` negation is now in place and all four scenarios show up as
untracked. **They still need an actual commit.** Once they have history,
`arc_godwin.original.yaml.bak` is redundant and should go — it exists only because
there was nowhere else to keep the previous version.

### 5b. The code default model is one this account cannot call

`_common.py` defaults `HAIKU` to `global.anthropic.Codex-haiku-4-5-...`, which is
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

1. **Re-run the benchmark.** Billable. Three things depend on it and nothing else should
   be quoted until it has run:
   - `arc_acacia` B³/pairwise — confirm the `best_match` change did not move the baseline
   - `arc_godwin` numbers — first run, expect the same-syllable pairs to be the
     interesting rows
   - **questions per resolution** — still marked SUPERSEDED in the README
2. **The backend.** `recall/memory_agentcore.py` is architecturally wrong and has never
   run; deploying with `RECALL_MEMORY=agentcore` as-is would make every known person look
   new. Read **AgentCore Memory — must fix before deploying** before starting, and test
   against a throwaway memory resource, never the live graph.
3. **Seed the demo data** — `uv run seed_demo.py --write`.
4. **The writeup.** There is a real result to report. Wait for (1) before quoting any
   questions-per-resolution number — writing prose around numbers still marked SUPERSEDED
   is how a stale table survives into a submission.
5. **The demo script**, written and timed, then rehearsed.

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

### Role-only references are not extracted

"I bumped into the male OGL... said hi... he said hi back" extracts **nobody** — not even
a non-substantive entry, which the prompt explicitly asks for. Two things overlap here:
the memo genuinely is presence-and-greeting (so `substantive: false` is the correct
label), and the model omits rather than flags. Prompt-compliance gap; the passing-mention
guard depends on the model listing people it then marks false.

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

**Deliberately not retuned**, because changing it moves the B³/pairwise baseline and the
strategy benchmark at the same time, and both are already due a re-run. If it is touched,
re-run both and quote the new thresholds. A principled value would come from how often an
ambiguous mention actually turns out to be someone new across the fixtures — which is
measurable, and is the honest way to set it.

Related fix already in: attribute probes give `outcomes[""] = "something else"`, because
holding no record of someone genuinely does predict that they will name a value we do not
have. Before that, answering "none of these" could still resolve to Kit Yee — a stranger
merged into a real contact record, the exact failure the band exists to prevent.

### The benchmark rests on one setting

`arc_godwin` added a second arc, so this is weaker than it was — but not gone. Both arcs
are **the same kind of setting**: one hall or one orientation group, where people share
schools, floors, courses and one `met_at`. That shared context is exactly what inflates
merge scores (see To fix #2), so thresholds tuned here may not generalise to a
professional graph where company and role are populated and conflict.

`same_first_name` is the only fixture from a professional setting, and it is two memos
long. State the caveat in the writeup.

## Writing eval fixtures — labelling rules learned the hard way

Getting these wrong silently corrupts the benchmark rather than erroring.

- **`cluster` is the human; `as` is what you called them this time.** A loose reference
  ("the german girl") keeps the original person's cluster id. Giving it a new cluster
  makes the ground truth assert they are different people, so the system is marked wrong
  for being right.
- **`as` must be a phrase from the transcript.** The harness maps system output back onto
  gold mentions by name overlap. An invented label matches nothing and scores as a miss.
  A trailing `(1)`/`(2)` is allowed purely to keep two keys distinct and is stripped
  before matching.
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
uv run pytest tests/ -q          # 173 tests, offline, no credentials, no spend

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
  to stop a lucky run being reported as a win.
- **Transient `ModelErrorException` kills long runs.** "The system encountered an
  unexpected error during processing" arrives with no warning and took down a
  multi-minute sweep. `chat_model()` now passes a botocore adaptive retry config, which
  also handles throttling.
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

## Do / Don't for Codex

- **Do** use `uv run`, typed structured output, and content-not-exception tool errors.
- **Do** run the offline tests before anything that spends AWS money.
- **Do** verify claims against the installed SDK or a real call rather than memory — a
  single probe is not proof, and this project has been bitten by that twice.
- **Don't** run exploratory or test memos against the user's live person graph. Twice
  now, test transcripts were written into it and later looked like the agent
  hallucinating facts the user never said — the expensive kind of bug, because it
  discredits the model instead of the process. Any throwaway run sets both:
  ```bash
  RECALL_STORE_PATH=<scratch>/graph.json RECALL_CALENDAR_PATH=<scratch>/cal.json uv run ...
  ```
- **Don't** add a framework, technique, or sub-agent unless the simpler version has
  demonstrably failed — justify the cost in a comment.
- **Don't** flatten the graph. The conditional routing and sub-agents _are_ the score.
- **Don't** extend the frozen tail (enrichment, drafts, calendar).
- **Don't** leave AgentCore running after a test session.
