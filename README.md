# Recall

A relationship-capture agent. Talk into your phone after an event — *"met Wei Lin from
GIC, she's hiring for a quant infra role, said I'd send her the Kestrel repo"* — and it
turns that into a structured, deduped contact record, drafts your follow-ups, and puts
the commitments on your calendar.

The thing it does that a notes app cannot: **it remembers people across sessions, and it
knows when it isn't sure.** Record a second memo weeks later and it recognises who you've
met before. When a reference is genuinely ambiguous it asks **one** question — chosen by
expected information gain, not by asking a model what to ask.

```
mention: "the malaysian chinese girl"
  hypotheses:  Kit Yee 0.49 | Crispy 0.47 | someone new 0.06

  ASKS  0.500 bits : Do they live on the 4th floor?
  skip  0.038 bits : Does this sound right — also from malaysian chinese independent school?
```

That second question sounds perfectly reasonable and is worth almost nothing — both
candidates went to that school. The arithmetic knows; a prompt doesn't.

## Pipeline

```
voice memo
  → transcribe (Groq Whisper)
  → extract_people        (structured output + substantive filter)
  → resolve               (three-zone band, pure arithmetic)
  → ask                   (one question, chosen by expected information gain)
        │ new person                                       │ known person
        ▼                                                  ▼
     enrich (sub-agent, web tools)                     merge into record
        └──────────────┬────────────────────────────────────┘
                       ▼
            extract_commitments → draft_followups (sub-agent)
                       ▼
        calendar_write → persist to memory → summary
```

The **dedupe → new/known** branch and the **enricher** / **drafter** sub-agents are the
agentic core. A memo containing both a stranger and an old contact fans out to *both*
branches in one pass and joins before drafting — `tests/test_graph.py` pins that.

## Setup

> **Full walkthrough:** [Recall Setup guide](https://claude.ai/code/artifact/1e213dda-a559-494d-b76e-79c1b97d6734)
> — step-by-step for both SSO and personal AWS accounts, plus a troubleshooting
> table and the complete environment reference. What follows is the short version.

```bash
uv sync                      # core
uv sync --extra audio        # + Groq transcription
uv sync --extra aws          # + AgentCore (deploy only)

cp .env.example .env
```

Only `AWS_REGION` and a callable `RECALL_MODEL_ID` are needed. The enricher falls back
to keyless search and the calendar falls back to a local ledger.

### AWS credentials

**Workshop account (SSO):**

```bash
aws sso login --profile workshop     # expires every 8-12h, redo each morning
```

**Personal AWS account (no SSO)** — three things, in this order:

1. **An IAM user with access keys.** IAM console → Users → your user → Security
   credentials → Create access key → *Command Line Interface (CLI)*. Then
   `aws configure` (region `ap-southeast-1`, output `json`). Leave `AWS_PROFILE`
   unset so the `default` profile is used.

2. **Bedrock permissions on that user.** Attach the managed policy
   `AmazonBedrockFullAccess`. Valid credentials with no Bedrock policy fail with
   `AccessDenied`, which reads like a model-access problem but is not.

3. **Model access** — per-model, per-region, off by default. Bedrock console →
   Model access → Modify model access.

Then:

```bash
uv run 00_check_bedrock.py
```

It detects which credential style you're on and prints the fix for *that* one.

### Picking a model

The project default is Claude Haiku 4.5. **New AWS accounts often can't use it** —
Anthropic and OpenAI models on Bedrock are third-party marketplace subscriptions, and
they're gated behind an *Anthropic use case details* form that a fresh account has not
submitted. The symptom is a `ValidationException` about an invalid model identifier,
which reads like a typo.

Find out what your account can actually call:

```bash
uv run 00_check_bedrock.py --list-models
uv run 00_check_bedrock.py --list-models --verbose   # show why each one is blocked
```

This **probes** — it calls each candidate twice for one token rather than trusting what
the console lists. Listing is not proof of callability, and while a marketplace gate is
outstanding Bedrock's answers are inconsistent: the same id can pass one call and fail
the next. Two consecutive passes are required before an id is reported usable.

**If Anthropic models are blocked, use Amazon Nova.** It's first-party, so there's no
marketplace gate, and it supports the tool-calling the pipeline needs:

```bash
# in .env
RECALL_MODEL_ID=global.amazon.nova-2-lite-v1:0
```

| Model | Notes |
|---|---|
| `global.amazon.nova-2-lite-v1:0` | Start here — newest, cheap, tool-capable |
| `apac.amazon.nova-pro-v1:0` | ~13x the price, and no better on this workload |
| `apac.amazon.nova-lite-v1:0` | Older Lite |
| `apac.amazon.nova-micro-v1:0` | Too weak for the dedupe judgement call |

Longer term, unblocking Haiku 4.5 is worth it — submit the Anthropic use case form in
the Bedrock console. It's the cheapest capable option and the only one here that
supports prompt caching.

### Cost

Bedrock has no free tier, so on a personal account this is your card.

- **The tests cost nothing.** `uv run pytest tests/ -q` never touches AWS.
- **A demo run is cents.** Watch `LEDGER.report()` at the end of each run rather than
  trusting an estimate — it breaks tokens and cost down per graph node.
- **Unpriced models report `$0.0000`.** `PRICING` in [recall/_common.py](recall/_common.py)
  only carries rates worth trusting; an unlisted model prints its token counts and
  declines to invent a cost. Nova 2 Lite is currently unpriced — add its rate there if
  you need a real figure.
- **The enricher dominates spend** — typically 80–90% of tokens, since it's the only
  node running a multi-step tool loop.
- **AgentCore deploy (`02_deploy.py`) is the one to watch.** It bills for the runtime
  *existing*, not per call, and `destroy` leaves S3, ECR, and CloudWatch behind. Run
  `03_teardown.py` when done and actually check the three resources it lists. Build
  against `01_run_local.py`, which is free.

## Run

### Web UI (record a memo in the browser)

```bash
uv sync --extra audio --extra web
uv run web/server.py            # http://localhost:8000
```

Record → the transcript comes back **editable** (fix any misheard names before
spending tokens) → Run → watch it execute.

The page shows four things:

- **The graph itself**, drawn to match [recall/graph.py](recall/graph.py) — nodes light
  up as they run, and the branch that never fires stays dim. On a memo containing only
  people you already know, `enrich` and its edges stay dark while `merge` lights. That
  dimming *is* the conditional edge, on screen.
- **Live token and cost counters**, diffed per run rather than cumulative.
- **The result** — new contacts, already-knew with the dedupe reasoning, commitments,
  drafts, calendar.
- **"People I know"** — the person graph itself, read from storage. It survives
  restarts, accumulates notes and meeting counts per person, and highlights whoever the
  run just matched. This is the memory claim made checkable rather than asserted.
  Click a person to open their full record, delete individual notes or meeting places,
  or forget them entirely. The agent will occasionally record someone it shouldn't, and
  a contact book you can't correct is one you stop trusting.
- **Connections** (`/graph`) — the same people laid out by how they relate to each other
  rather than as a grid. Drag, zoom, **Recenter** to fit it all back on screen, click
  someone to read their edges and the note each one rests on. See
  [The relationship graph](#the-relationship-graph).

Use Chrome. Microphone access needs `localhost` or HTTPS, so don't demo off a LAN IP.

### CLI

```bash
uv run pytest tests/ -q         # 312 tests, offline, no credentials, no spend
uv run 00_check_bedrock.py      # must print OK before any Bedrock run

uv run run_demo.py              # built-in demo memo
uv run run_demo.py data/memos/day2.txt
uv run run_demo.py data/audio/memo.m4a     # needs GROQ_API_KEY
uv run run_demo.py --reset      # wipe the person graph first
```

### The demo, in order

```bash
uv run run_demo.py --reset data/memos/day1.txt
uv run run_demo.py data/memos/day2.txt
```

Day 1 logs three new contacts, extracts what you promised each of them, drafts the
follow-ups, and books the commitments. It also *skips* two people who were only
mentioned in passing.

Day 2 is the point. The agent has never been told who Wei Lin is, and recognises her
from the previous session — along with Arjun, on evidence like this:

> *Arjun — merged into existing record (80% confident): the new mention references
> completing an intro to Marcus, which matches the stored note about needing to
> introduce Arjun Menon to Marcus at Grab.*

That's the person graph doing its job, and it works the same whether the contact is a
fund partner or a friend from uni.

### On enrichment

The enricher is **opportunistic, and silent by default.** Most people you meet at an
event have no findable public presence, so "found nothing" is the common and correct
outcome — see the guards below. Treat any hit as a bonus, not the headline.

### AgentCore lifecycle

```bash
uv run 01_run_local.py     # localhost:8080 — FREE, always test here first
uv run 02_deploy.py        # BILLABLE from here
uv run 04_call_agent.py "met someone at ..."
uv run 03_teardown.py      # run this when done
```

## Layout

| Path | What it is |
|---|---|
| [recall/graph.py](recall/graph.py) | The supervisor graph — nodes, conditional edge, fan-in |
| [recall/state.py](recall/state.py) | The one `TypedDict` + every structured-output model |
| [recall/memory.py](recall/memory.py) | The person graph. `PersonStore` protocol, local + AgentCore backends |
| [recall/resolve.py](recall/resolve.py) | The three-zone band — pure scoring, no model |
| [recall/eig.py](recall/eig.py) | Expected information gain, the Bayes update, and the two baselines |
| [recall/questions.py](recall/questions.py) | Candidate questions derived mechanically from stored attributes |
| [recall/answer.py](recall/answer.py) | Applying one answer, with the same likelihood EIG scored it under |
| [recall/text.py](recall/text.py) | Token matching shared by retrieval and resolution |
| [recall/relations.py](recall/relations.py) | Relationship edges between people — derived post-hoc, display-only |
| [recall/_common.py](recall/_common.py) | `chat_model()`, cost ledger, pricing table, cache helper |
| [recall/nodes/](recall/nodes/) | One file per graph node |
| [recall/tools/](recall/tools/) | Transcription, web search, calendar |
| [tests/test_graph.py](tests/test_graph.py) | Graph wiring end to end, against scripted fake models |
| [tests/test_guards.py](tests/test_guards.py) | The two filters that keep wrong data out of the person graph |
| [tests/test_relations.py](tests/test_relations.py) | The grounding guard, and that edges stay out of resolution |
| [tests/test_metering.py](tests/test_metering.py) | Token accounting and pricing |
| [eval/harness.py](eval/harness.py) | Fixture loading + the resolution sweep behind the B³/pairwise numbers |
| [eval/run_questions.py](eval/run_questions.py) | EIG vs random vs uncertainty — the headline benchmark |
| [eval/fixtures/](eval/fixtures/) | The five hand-written scenarios every number here comes from |
| [web/server.py](web/server.py) | FastAPI transport — transcribe + streamed graph run |
| [web/index.html](web/index.html) | Record a memo and watch the run — one file, no framework |
| [web/people.html](web/people.html) | Everyone, as a filterable grid |
| [web/graph.html](web/graph.html) | Connections — the relationship graph, hand-rolled force layout |

## Resolving identity

Resolution is a three-zone Fellegi–Sunter-style band, not a single cutoff:

```
score >= T_MATCH        -> RESOLVED    auto-link
T_NONMATCH .. T_MATCH   -> AMBIGUOUS   ask about it
score <  T_NONMATCH     -> NEW
```

Plus a **margin rule**: a high score whose runner-up is nearly as good is still
ambiguous. "the malaysian chinese girl" fits Kit Yee and Crispy within 0.03 of each
other — resolving on that is a coin flip dressed as a decision.

Scoring lives in [recall/resolve.py](recall/resolve.py) and is **pure** — no model call
decides which band a mention falls in, so it is reproducible and unit-tested. The model
extracts attributes; the arithmetic decides.

Names are compared by **coverage of the shorter name**, not by the single best token
pair. Extra tokens on the longer side are silence — a family name the speaker dropped, so
`Kit` still matches `Kit Yee` at 1.00 — but a token with no counterpart at all counts as
disagreement, so `Hui Ning` scores 0.50 against `Hui Wen` rather than 1.00. Taking the
best pair meant one shared syllable carried a whole name, and since `W_NAME_EXACT` equals
`T_MATCH`, that alone auto-merged two different people.

Current thresholds: `T_MATCH=3.0`, `T_NONMATCH=1.0`, `MIN_MARGIN=1.0`. Hand-set, not
fitted from labelled pairs — quote them with any result.

## Asking the question

| Module | Job |
|---|---|
| [recall/questions.py](recall/questions.py) | Derives yes/no probes **mechanically** from stored attributes. Guaranteed answerable, free, testable |
| [recall/eig.py](recall/eig.py) | `EIG(q) = H(H) − Σ P(a)·H(H\|a)`, argmax. Pure. Per-question noise so unreliable attributes are discounted |
| [recall/questions.py](recall/questions.py) | Candidate questions, derived mechanically. Yes/no probe per fact, plus a **multi-valued probe per attribute the records disagree about** — paired by word-level prefix/suffix alignment, never token overlap |
| [recall/answer.py](recall/answer.py) | What the human's answer *means*. The same Bayes update, with the same per-question noise, that EIG scored the question with — so the bits promised are the bits delivered |
| [recall/nodes/ask.py](recall/nodes/ask.py) | One question per memo, plus the rejected alternatives and their measured value |

Questions that carry zero information are **kept** in the candidate set, not filtered.
Showing what the agent declined to ask, with numbers, is what demonstrates the choice was
computed rather than tasteful.

## Benchmark

```bash
uv run eval/check_fixtures.py          # validate fixtures — free, no model calls
uv run eval/run_eval.py [--repeats N] [--scenario ID]
uv run eval/from_audio.py memo.m4a --scenario arc_acacia   # record instead of typing
```

Entity resolution is scored as a clustering problem: **B³** (per-mention, the headline)
and **pairwise** P/R/F1, plus a binary score for the substantive filter. Fixtures are
hand-written YAML scenarios in [eval/fixtures/](eval/fixtures/) — ordered memos run
against a fresh graph, so recognising someone in a later memo is the test.

Every scenario is repeated and the spread reported: Bedrock is not deterministic at
`temperature=0`, so a single run is an anecdote. **The whole pipeline is re-run each
repeat, not just the scoring** — extraction varies, so the set of ambiguous mentions
itself moves between runs (4–5 on identical fixtures). Replaying strategies over a case
set collected once looks rigorous and hides the dominant source of noise.

Fixtures: 53 memos, 108 mentions, 40 recurring people across `arc_acacia` (24 memos),
`arc_godwin` (14 memos, 20 people, 11 loose references), `ehoc_c4` (11 memos, 14 people,
13 recurring — four memos of descriptor-only references), `same_first_name` and
`genuinely_ambiguous`.

Measured 31 Aug, `repeats=3`, thresholds `T_MATCH=3.0 T_NONMATCH=1.0 MIN_MARGIN=1.0`,
`W_NAME_EXACT=2.5`. Quote the thresholds with any number here.

```
scenario                B3 F1    B3 P    B3 R  pair F1   subst   covrg
ehoc_c4                 0.926   0.989   0.874    0.837   0.971   0.977
arc_godwin              0.896   0.947   0.851    0.718   0.956   0.956
arc_acacia              0.810   1.000   0.681    0.632   0.873   0.857
same_first_name         1.000   1.000   1.000    1.000   1.000   1.000
genuinely_ambiguous     1.000   1.000   1.000    1.000   1.000   1.000

B-cubed F1 across all scenarios: 0.927 ±0.095 (n=15)
```

**This is a new baseline, not a delta.** Three things changed since the previous
`arc_acacia` figure (`B³ F1=0.922`, pairwise 0.800): `W_NAME_EXACT` dropped from 3.0 to
2.5, the name and descriptor channels were separated in `compare()`, and the eval
scorer's back-mapping was rewritten. Each is unit-tested in isolation, but no run
separates their effect on these numbers, so the old figure is superseded rather than
compared against.

Precision is 1.000 on `arc_acacia` and `ehoc_c4` — nothing wrongly merged, every loss a
missed recognition, which is the right direction to fail in: a wrong merge silently
destroys a real record, a missed one is visible and fixable. **State the claim at the
scenario level, not globally.** It was briefly false: before the channel fix, a
description stored in a record's `aliases` came back as name evidence and merged two
different people in `arc_acacia`. `arc_godwin` still sits at 0.947, so it holds a wrong
merge that has not been diagnosed.

### Questions per resolution

```bash
uv run eval/run_questions.py [--repeats N]
```

Measured 31 Aug, `repeats=3`, same thresholds as above.

```
strategy       questions/resolution                       <=1 question
eig            0.985 ±0.111  (n=3, min 0.839  max 1.061)       68%
uncertainty    1.359 ±0.093  (n=3, min 1.242  max 1.429)       57%
random         1.323 ±0.079  (n=3, min 1.258  max 1.417)       60%
```

Case sets of 37/33/35 per run; budget cap 5 questions; unresolved excluded from the mean.
EIG's max (1.061) sits below both baselines' minimums (1.242, 1.258), which is the check
that stops a lucky run being reported as a win. 10 of 37 questions were multi-valued.

**The claim is "EIG beats both baselines", not an ordering between them.** Uncertainty and
random swapped when the nickname path landed and their ranges now overlap heavily — at
this n they are indistinguishable from each other.

Two caveats that belong next to the table:

1. **The denominator moved with the resolver.** Dropping `W_NAME_EXACT` to 2.5 pushed
   bare-name returns into the ambiguous band, so cases like `'Yixin' -> Yixin` are now
   scored here. All three strategies draw from the same case set, so the comparison is
   sound, but resolution quality and question efficiency are **coupled** and must not be
   presented as independent results.
2. **`ehoc_c4` supplies roughly a third of the cases**, so one fixture carries much of
   the number. One `ehoc_c4/m10` extraction still fails per sweep; its cases are lost but
   the run survives, which is what got this table to n=3.

**Why EIG beats uncertainty sampling.** Attributes differ in how dependable an answer
is, and EIG divides that out. Uncertainty sampling asks whatever is least predictable —
and an unreliable attribute is unpredictable *because* its answer means little, so it
spends the one question there.

```
noise 0.05   studies computer science at NUS     a degree rarely changes
noise 0.18   lives at the 18th floor             rooms change each semester
noise 0.35   a quiet person but friendly         one impression, one day
```

Without that asymmetry the two strategies are near-identical by construction: with
uniform noise, `EIG = H(A) − H(A|H)` and `H(A|H)` is near-constant across questions, so
argmax EIG collapses to argmax `H(A)`, which *is* uncertainty sampling. An earlier
version of this benchmark reported a tie for exactly that reason.

**Report honestly.** The reliability values are hand-set from what actually changes about
a person, not fitted — quote them with any result. n is small. The claim these numbers
support is "EIG beats a strategy that ignores reliability", not a general superiority.


## The relationship graph

A `PersonRecord` is an island: it says who someone is and nothing about how they stand to
anyone else. [recall/relations.py](recall/relations.py) holds the edges — `partner`,
`colleague`, `classmate`, `friend`, `family`, `mentor` (the only directed one),
`competitor`, `knows` — and `/graph` draws them.

**It cannot move the benchmark, and that is structural rather than measured.**
`resolve.compare` reads six fields off a record (name/aliases, company, role, met_at,
notes) and `LocalPersonStore.search` builds its candidate haystack from the same six. An
edge is not one of them, and edges live in their own file rather than on the record, so
there is no path by which one reaches the resolver. Two tests hold that:
`test_relations_are_not_a_field_resolve_reads` and
`test_relations_stay_out_of_candidate_retrieval`. The B³ and question-efficiency numbers
below are unaffected and did not need re-running.

Edges are kept out of retrieval for a second reason beyond the benchmark: a note naming
two people is evidence they are **different** humans, so retrieving one as a candidate
for the other is exactly backwards. Same argument as contact handles, one step stronger.

**A separate model call, never a field on `Person`.** Adding `relationships` to the
extraction schema would change the call that also emits `name`, `notes` and `company` —
fields `compare()` *does* read — and `temperature=0` is not determinism, so both headline
tables would have to be re-measured. Reading the stored notes afterwards costs one call
and cannot touch a score.

**The model proposes; code proves.** A model asked who relates to whom across one
university hall returns an edge for every pair, because everyone shares a course, a floor
and an event — the same failure mode as lexically-derived tags, except that here an edge
is an assertion about *two* real people nobody made. So the model supplies only the kind
and a short phrase, and code supplies the citation: an edge survives only if a stored note
on one of the two records **names the other person outright**, whole label, on word
boundaries.

That is deliberately stricter than the resolver's own name matching, which scores partial
agreement — right when deciding whether a spoken name is a stored person, wrong here,
because four `Jia*` people in one orientation group would each "name" the others on a
shared syllable. On a six-person graph, five plausible proposals grounded to two:

```
Marcus   partner    Wei Han   <- 'runs a supper club with Marcus'
Jia En   classmate  Jia Ying  <- 'did the handover with Jia Ying'
DROPPED  Priya / Marcus       -- no note names the other
DROPPED  Jia En / Priya       -- no note names the other
DROPPED  Marcus / Tiu Chuei Enn
```

Most proposals dying is the design working. The panel shows the note behind every edge,
because a relationship you cannot check is one you have to take on trust.

The graph is correctable, for the same reason the person panel is. `POST /api/relations`
draws an edge by hand with no grounding check — you *are* the evidence — and a refresh
never withdraws one you drew. Merging two people repoints their edges onto the survivor
and drops the edge between them, which after a merge is the duplicate that was just fixed
rather than a relationship. Forgetting a person forgets their edges.

The optional dashed "shared tag" links are a display layer, never stored. Two people
studying computer science are not classmates. They carry the tag as a label and get their
own card in the side panel, kept visually and structurally apart from recorded
relationships — one list would quietly promote a coincidence of vocabulary into something
the notes said.

## What's left

### To fix

1. **The residual merge window is not closed by construction.** Now measured rather
   than projected: `"indian girl"` resolves onto Marvi at `desc=1.00 (2.0) + notes=1.00
   (1.5) = 3.50`, crossing `T_MATCH` **with no name involved at all**. The
   `W_DESCRIPTOR_MAX` cap does what it claims — a description alone cannot reach 3.0 —
   but description *plus* notes overlap can. It was the right person in that case;
   nothing in the arithmetic guarantees the next one will be. The consistent fix is to
   cap the total when no name channel fired.
2. **A bare nickname still creates a duplicate person.** `_is_name` now treats a leading
   article as marking a description, so `"the Catholic Indian"` routes correctly — but
   `"big boss"` has no article and no descriptor word, so it still takes the name
   channel, conflicts with every stored name, and files a new record. Phrasing it as
   *"the guy everybody calls big boss"* works, and that workaround still lives in the
   fixture, not in the code.
3. **`with_structured_output` sometimes returns a JSON string, not a list.**
   `PeopleExtraction.people` arrived as `str` and raised `ValidationError`, killing one
   memo in `run_eval` and an entire run of `run_questions` — which is why the headline
   table is n=2. Not a fixture problem; it needs a retry or a coercing validator.
4. **`arc_godwin`'s precision loss is the adjudicator, not the resolver.** `jia_en` and
   `jia_ying` share a record, but all four of their mentions scored **AMBIGUOUS**
   (1.27–2.19) — nothing auto-resolved. With four `Jia*` people in one orientation group,
   coverage-based name matching scores them 0.50 on the shared syllable and the band
   flags every one. The merge came from `_adjudicate()`, the LLM fallback that settles
   the band on non-interactive runs because nobody is there to answer. So this number
   measures the fallback guesser, not the path the product actually takes — interactively
   those mentions are held and one buys a question.
5. ~~**Fixtures are not in version control.**~~ Fixed — `.gitignore` carried a blanket
   `*.yaml` that ignored every file in `eval/fixtures/`. The negation is in; the fixtures
   still need their first commit.
6. **The code default model is one a personal account cannot call.** `_common.py` defaults
   to a `global.anthropic.*` id, which is the marketplace-gated path. It works only
   because `.env` overrides it, and `.env` is not in the repo — so a fresh clone fails
   with `ValidationException: invalid model identifier`, which reads like a typo.

### To do

1. **Re-run the headline at n≥3.** The 30 Aug table is n=2 because one run died on the
   structured-output bug above. Fix that first, or the same run will keep dropping out.
2. **The AgentCore Memory backend.** `recall/memory_agentcore.py` was written blind and
   has never run; as written it would make every known person look new. Test against a
   throwaway memory resource, never the live graph.
3. **Seed the demo data**, write and time the demo script, then the writeup.

### Known limitations

"the two X girls" extracts as one entity, not two — `Person` emits one record per person,
and plural-mention expansion is out of scope. Role-only references with no content
("bumped into the male OGL, said hi") extract nobody. A Whisper mis-hear that changes the
*first* token of a name (`Zhong Xuan` → `Jong Shuen`) scores 0.00 and does not match at
all. And both arcs come from the same kind of setting — one hall, one orientation group —
where everyone shares an event and nobody has a company, so thresholds tuned here may not
generalise to a professional graph.

Relationship edges are sparse by construction: one is drawn only when a stored note names
the other person outright, so a relationship the memos never recorded is not shown. A
nickname that was never saved as an alias breaks that check — a note saying *"Marc calls
her Crispy"* does not ground an edge to a record named `Marcus` unless `Marc` is in its
`aliases`. Same class as the nickname-in-the-wrong-field failure, and the same remedy:
merge the records, or draw the edge by hand.

## The three guards

Both exist because a model *told* to be careful is still sometimes not careful, and both
failure modes are invisible in the output.

**Passing-mention filter.** *"Ran into Daniel again, nothing new, just said hi"* is not a
contact record. The model must set an explicit `substantive` boolean — does the memo
state a fact, plan, opinion, or promise about this person? — and **code** does the
filtering. Asking a model to silently omit borderline people made the decision invisible
and unstable; the same memo produced different name lists run to run.

**Consolidation safety net.** Meeting someone repeatedly used to pile up near-duplicate
notes — four entries each restating "studies computer science", two `met_at` values for
one occasion. Exact-string dedupe can't catch a paraphrase, so `merge` now runs a
bounded LLM pass to deduplicate. That reverses this file's earlier "merge makes no model
call" rule, on the grounds that the no-model version shipped and observably failed —
which is the bar CLAUDE.md sets before adding cost. The original objection (a model here
can rewrite history) is handled by
[`_safe_consolidation()`](recall/nodes/merge.py): the result is discarded if the model
summarised instead of deduplicated, emptied the notes, or invented entries. A repetitive
record beats one that silently lost what you said. Runs only past 3 notes or 2 places,
so short records cost nothing.

**Enricher corroboration gate.** Search for a first name plus a big employer and you will
always find *a* plausible stranger. Left ungated, the agent produced a fluent, specific,
entirely wrong biography for a "Daniel at Stripe". So the enricher must end its answer
with a `CONFIRMED BY:` line naming a detail from your own memo, and
[`_verify()`](recall/nodes/enrich.py) checks that detail actually overlaps the company,
role, or event you recorded. No corroboration, no enrichment. People with neither a
company nor a role are skipped without searching at all.

## Conventions worth not relearning

- **Models come from `chat_model()`**, never a hardcoded client. `RECALL_MODEL_ID`
  overrides the default without touching code.
- **`temperature=0` is not reproducibility.** It's set everywhere except the drafter, and
  you should keep it — but Bedrock still returns different extractions for the same input
  across runs. Don't build a demo that depends on identical output twice, and don't debug
  a "flaky" node before confirming it isn't just this.
- **Structured output via `with_structured_output(Model)`.** Never "reply in JSON" —
  the model eventually wraps it in a code fence and `json.loads` dies.
- **Nodes return partial updates.** An unmatched key is dropped silently, so a field
  name typo looks like a node that did nothing. Suspect `state.py` first.
- **Metering is a callback, not a wrapper.** A wrapper object looks simpler right up
  until something type-checks the model — `create_react_agent` rejects anything that
  isn't a real Runnable, and the enricher dies at runtime while every unit test that
  stubbed the agent still passes. `UsageCallback` rides along on the real model and
  survives `with_structured_output`, `bind_tools`, and the react loop untouched.
- **Prompt caching is Anthropic-only.** `cached_system()` checks the active model and
  returns plain text elsewhere — a cache point sent to Nova is a hard
  `ValidationException`, not a silent no-op.
- **Tool errors return as content, never raise.** The model reads what broke and
  self-corrects; the step cap is the safety net.
