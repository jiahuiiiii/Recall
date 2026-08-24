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

Use Chrome. Microphone access needs `localhost` or HTTPS, so don't demo off a LAN IP.

### CLI

```bash
uv run pytest tests/ -q         # 122 tests, offline, no credentials, no spend
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
| [recall/_common.py](recall/_common.py) | `chat_model()`, cost ledger, pricing table, cache helper |
| [recall/nodes/](recall/nodes/) | One file per graph node |
| [recall/tools/](recall/tools/) | Transcription, web search, calendar |
| [tests/test_graph.py](tests/test_graph.py) | Graph wiring end to end, against scripted fake models |
| [tests/test_guards.py](tests/test_guards.py) | The two filters that keep wrong data out of the person graph |
| [tests/test_metering.py](tests/test_metering.py) | Token accounting and pricing |
| [web/server.py](web/server.py) | FastAPI transport — transcribe + streamed graph run |
| [web/index.html](web/index.html) | The whole UI, one file, no framework |

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

Current baseline (`arc_acacia`, 18 memos): **B³ P=1.000 R=0.856 F1=0.922**, pairwise
F1 0.800. Precision has held at 1.000 throughout — nothing is ever wrongly merged, and
every loss is a missed recognition. That is the right direction to fail in: a wrong merge
silently destroys a real record, a missed one is visible and fixable.

### Questions per resolution

```bash
uv run eval/run_questions.py [--repeats N]
```

> **⚠️ SUPERSEDED — re-run before quoting. Measured 23 Aug, invalidated 24 Aug.**
> Two changes landed after these numbers were taken, and both move them:
>
> 1. **The simulated answerer was wrong.** It matched the phrased question against the
>    gold record at an overlap of 0.55, so "Do they live at the 18th floor?" scored 0.583
>    against "lives on the 4th floor" and the person on the 4th floor answered **yes**.
>    All three strategies were updating on false answers.
> 2. **Multi-valued attribute probes now exist**, so every strategy draws from a richer
>    candidate pool and should need fewer questions.
>
> The direction of (1) is not predictable from the armchair — it corrupted all three
> strategies, not just the baselines — so the table below is quoted as history, not as a
> result. Re-run `uv run eval/run_questions.py --repeats 5` and replace it.

```
strategy       questions/resolution                       <=1 question
eig            1.460 ±0.050  (n=5, min 1.400  max 1.500)       31%
uncertainty    2.103 ±0.267  (n=5, min 1.800  max 2.333)       23%
random         1.690 ±0.250  (n=5, min 1.500  max 2.000)       23%
```

5 full pipeline runs, 4–5 scorable mentions each. EIG's range did not overlap
uncertainty sampling's, and it was also the most *stable* — ±0.05 against ±0.25.

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


**Known limitations.** "the two X girls" extracts as one entity, not two — `Person` emits
one record per person, and plural-mention expansion is out of scope. Role-only references
with no content ("bumped into the male OGL, said hi") extract nobody. And the real data
comes from a single setting, so thresholds tuned to it may not generalise.

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
