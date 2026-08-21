# Recall

A relationship-capture agent. Talk into your phone after an event — *"met Wei Lin from
GIC, she's hiring for a quant infra role, said I'd send her the Kestrel repo"* — and it
turns that into a structured, deduped contact record, drafts your follow-ups, and puts
the commitments on your calendar.

The thing it does that a notes app cannot: **it remembers people across sessions.**
Record a second memo weeks later and it recognises who you've met before, merges the new
context into their existing record, and connects a promise you made last time to you
discharging it this time.

## Pipeline

```
voice memo
  → transcribe (Groq Whisper)
  → extract_people        (structured output + substantive filter)
  → dedupe                (RAG over the person graph) ──► conditional edge
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
uv run pytest tests/ -q         # 52 tests, offline, no credentials, no spend
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
