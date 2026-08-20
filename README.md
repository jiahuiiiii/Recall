# Recall

A relationship-capture agent. Talk into your phone after an event — *"met Wei Lin from
GIC, she's hiring for a quant infra role, said I'd send her the Kestrel repo"* — and it
turns that into structured, deduped, enriched contact notes, drafts your follow-ups, and
puts the commitments on your calendar.

## Pipeline

```
voice memo
  → transcribe (Groq Whisper)
  → extract_people        (structured output)
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

```bash
uv sync                      # core
uv sync --extra audio        # + Groq transcription
uv sync --extra aws          # + AgentCore (deploy only)

cp .env.example .env         # fill in keys
```

Only `AWS_REGION` is strictly required; the enricher falls back to keyless search and
the calendar falls back to a local ledger.

### AWS credentials

**Workshop account (SSO):**

```bash
aws sso login --profile workshop     # expires every 8-12h, redo each morning
```

**Personal AWS account (no SSO)** — three things, in this order:

1. **An IAM user with access keys.** IAM console → Users → your user → Security
   credentials → Create access key → *Command Line Interface (CLI)*. Then:

   ```bash
   aws configure       # paste key + secret, region ap-southeast-1, output json
   ```

   Leave `AWS_PROFILE` unset in `.env` so the `default` profile is used.

2. **Bedrock permissions on that user.** IAM → Users → Permissions → Add permissions
   → attach the managed policy `AmazonBedrockFullAccess`. Valid credentials with no
   Bedrock policy fail with `AccessDenied`, which reads like a model-access problem
   but is not.

3. **Model access, which is per-model and per-region and off by default.** Bedrock
   console → Model access → Modify model access → enable Claude Haiku 4.5 → wait for
   *Access granted*.

Then:

```bash
uv run 00_check_bedrock.py
```

It detects which credential style you are on and prints the fix for *that* one. If
inference fails it also lists the Claude ids your account can actually call and gives
you the `RECALL_MODEL_ID` line to paste.

**The gotcha specific to personal accounts:** the default model id is
`global.anthropic.claude-haiku-4-5-...`, where `global.` is a cross-region inference
profile that the workshop account has and many personal accounts do not. The symptom is
a `ValidationException` on a model id that plainly exists. Fix:

```bash
uv run 00_check_bedrock.py --list-models
# then in .env:  RECALL_MODEL_ID=apac.anthropic.claude-haiku-4-5-20251001-v1:0
```

If Haiku 4.5 is not offered in `ap-southeast-1` for your account, set
`AWS_REGION=us-east-1` — it gets new models first.

### Cost on a personal account

There are no workshop credits, so this is your card. Bedrock has no free tier.

- **A demo run is cents.** Haiku is $1/$5 per M tokens in/out; one memo through the
  whole graph is roughly 5–8 model calls and lands around $0.02–0.05. `LEDGER.report()`
  prints the exact figure after every run — watch it rather than trusting this estimate.
- **The tests cost nothing.** `uv run pytest tests/ -q` never touches AWS.
- **AgentCore deploy (`02_deploy.py`) is the one to be careful with.** It provisions a
  runtime that bills while it exists, not per call, and `destroy` leaves S3, ECR, and
  CloudWatch behind. On a personal account, run `03_teardown.py` the moment you are done
  and then actually check the three resources it lists. Do the whole build against
  `01_run_local.py`, which is free.

## Run

```bash
uv run pytest tests/ -q         # offline, no credentials, no spend
uv run 00_check_bedrock.py      # must print OK before any Bedrock run

uv run run_demo.py              # built-in demo memo
uv run run_demo.py data/memos/day2.txt
uv run run_demo.py data/audio/memo.m4a     # needs GROQ_API_KEY
uv run run_demo.py --reset      # wipe the person graph first
```

### The demo, in order

```bash
uv run run_demo.py --reset data/memos/day1.txt   # 3 strangers → enriched, stored
uv run run_demo.py data/memos/day2.txt           # Wei Lin recognised → merged
```

Day 2 is the point: the agent has never been told who Wei Lin is, and recognises her
from a previous session. That is the person graph doing its job.

### AgentCore lifecycle

```bash
uv run 01_run_local.py     # localhost:8080 — FREE, always test here first
uv run 02_deploy.py        # BILLABLE from here
uv run 04_call_agent.py "met someone at ..."
uv run 03_teardown.py      # run this when done
```

`destroy` leaves S3 / ECR / CloudWatch behind — `03_teardown.py` prints what to check.

## Layout

| Path | What it is |
|---|---|
| [recall/graph.py](recall/graph.py) | The supervisor graph — nodes, conditional edge, fan-in |
| [recall/state.py](recall/state.py) | The one `TypedDict` + every structured-output model |
| [recall/memory.py](recall/memory.py) | The person graph. `PersonStore` protocol, local + AgentCore backends |
| [recall/_common.py](recall/_common.py) | `chat_model()`, cost ledger, prompt-cache helper |
| [recall/nodes/](recall/nodes/) | One file per graph node |
| [recall/tools/](recall/tools/) | Transcription, web search, calendar |

## Conventions worth not relearning

- **Models come from `chat_model()`**, never a hardcoded client. Default is Haiku 4.5.
- **`temperature=0` everywhere except the drafter.** Extraction and routing must be
  reproducible; only the writing step samples, and only at 0.4.
- **Structured output via `with_structured_output(Model)`.** Never "reply in JSON" —
  the model eventually wraps it in a code fence and `json.loads` dies.
- **Nodes return partial updates.** An unmatched key is dropped silently, so a field
  name typo looks like a node that did nothing. Suspect `state.py` first.
- **Tool errors return as content, never raise.** The model reads what broke and
  self-corrects; the step cap is the safety net.
- **Every model call is metered.** `LEDGER.report()` prints tokens and cost per node at
  the end of each run.
