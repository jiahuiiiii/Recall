# Recall

Recall is a personal relationship-memory assistant. After a meeting or event, record a
short voice memo such as:

> “Met Wei Lin from GIC. She is hiring for a quant-infrastructure role, and I said I’d
> send her the Kestrel repo.”

Recall turns that into a contact record, remembers that person on later memos, captures
promises you made, and prepares follow-ups. In interactive use, when it cannot tell who a
reference means, it can pause to ask one useful question instead of immediately guessing.

## Why it is different

Most note apps save what you said. Recall also helps answer **who** you meant.

If a later memo says, “the GIC woman asked for the repo,” Recall compares it with the
people already recorded. It takes one of three paths:

| What it knows | What Recall does |
| --- | --- |
| Strong evidence for one person | Recognises and updates that person |
| Too little evidence | Records someone new |
| The identity is still uncertain | Asks one clarifying question |

The question is selected with expected information gain (EIG): Recall chooses the
question expected to reduce uncertainty the most, rather than asking a language model
to improvise one. For example, knowing someone attended the same event may not help if
every candidate did; a differing employer or role may settle the question immediately.

## Agentic workflow

Recall uses one shared workflow whether the memo arrives from the web app, command line,
or Telegram. The model extracts structured facts; the workflow then makes the important
confidence-band and question-selection decisions explicitly.

```text
voice memo
  → transcribe (audio only)
  → extract people
  → resolve against the person graph ──┬── known → merge into that record
        │                               ├── new   → enrich when enough context is available
        │                               └── ambiguous → ask one EIG-selected question
        ▼
  merge the branches → extract commitments → draft follow-ups
                     → confirm calendar items → store new contacts → show a summary
```

A memo can contain both a new person and someone already known, so the graph deliberately
fans out to both branches and joins them before follow-ups are drafted. In the web and
Telegram experiences, the most useful ambiguous reference pauses the workflow; the
person's answer decides whether that mention belongs to a known contact or someone new.
Recall asks at most one question per memo. If several mentions are ambiguous, the others
use a model-based fallback. The command line and evaluation harness have nobody to ask,
so all ambiguous mentions use that fallback; the benchmark reports this as a limitation.

The LLM does not decide every step. The core uncertainty path is ordinary, testable
Python: the resolver scores the evidence, candidate questions are built from stored
facts, EIG ranks them, and the same probability rule used to score a question applies the
answer. Models handle the less structured language work: extracting people and
commitments, drafting, public-web enrichment for eligible new contacts, and fallback
decisions when no human answer is available.
This keeps the project's main claim—question selection by measured information gain—easy
to inspect without pretending that the whole product is model-free.

```text
Candidate: “the GIC woman”

Ask:  “Do they lead quant infrastructure?”      high information gain
Skip: “Were they at the same event?”             low information gain; both candidates were
```

Recall does not auto-send messages. Calendar items are shown for confirmation in the
interactive app before they are added.

## Quick start

You need Python 3.11+, [uv](https://docs.astral.sh/uv/), and AWS credentials that can
call one Amazon Bedrock model. Nothing else is required; transcription and search keys
are optional.

```bash
uv sync --extra audio --extra web
cp .env.example .env            # then pick your credential path inside it -- see below
uv run 00_check_bedrock.py      # must print OK
uv run web/server.py
```

Open `http://localhost:8000`, record or type a memo, check the transcript, then run it.
For the guided three-memo demo on a throwaway graph, run `uv run demo.py` instead.

For a terminal demo:

```bash
uv run run_demo.py
uv run run_demo.py data/memos/day2.txt
uv run run_demo.py data/audio/memo.m4a   # requires GROQ_API_KEY
```

### Credentials: two paths

`.env.example` carries both, ready to uncomment. The preflight detects which style is in
use and prints the fix for that style if anything fails.

| | Hackathon / organisation account (SSO) — the judges' path | Personal AWS account (IAM user) |
| --- | --- | --- |
| Sign in | `aws sso login --profile <name>` and set `AWS_PROFILE=<name>`, **or** paste the three temporary keys from the AWS access portal (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`). They expire after a few hours. | `aws configure` with an IAM access key; the user needs `AmazonBedrockFullAccess`. IAM keys do not expire automatically. |
| `AWS_REGION` | `us-east-1` — the organisation policy denies every model in `ap-southeast-1` | whatever your account uses; `ap-southeast-1` works |
| `RECALL_MODEL_ID` | `us.anthropic.claude-sonnet-4-6` (the `.env.example` default); `us.amazon.nova-2-lite-v1:0` also works | `global.amazon.nova-2-lite-v1:0` — Anthropic models are usually gated behind a marketplace form on personal accounts |

The published benchmark numbers were measured on Nova 2 Lite. The pipeline is
model-agnostic, but reproducing the tables exactly means running on that model.

If the preflight fails, its message names the layer. The three you are most likely to see:

| Message contains | Meaning | Fix |
| --- | --- | --- |
| `ExpiredToken` | temporary SSO keys have expired | `aws sso login` again, or paste a fresh set |
| `explicit deny in a service control policy` | the organisation blocks Bedrock in this region | `AWS_REGION=us-east-1` and a `us.`-prefixed model id |
| `invalid model identifier` | this account cannot call that model (usually the marketplace gate on personal accounts) | `uv run 00_check_bedrock.py --list-models` and paste the id it recommends |

A model appearing in the AWS console is not proof that the account can invoke it;
`--list-models` probes with real one-token calls.

## Ways to use Recall

### Web app

The web app is the best way to try Recall. It shows the editable transcript, live run
status, contact records, commitments, and the one-question pause when a person is
ambiguous.

```bash
uv sync --extra audio --extra web
uv run web/server.py
```

For the recorded three-beat demo—create contacts, recognise Wei Lin, then pause on an
EIG-selected Jungle-partner question—run:

```bash
uv run demo.py
```

It starts the web app with a fresh throwaway graph and prints the three memo files to
paste in order. Nothing is written to your normal contact data.

### Command line

Use the command line for a repeatable demo or a text-file memo.

```bash
uv run run_demo.py
uv run run_demo.py path/to/memo.txt
```

### Telegram (optional)

Telegram is an allowlisted, single-user front end for voice memos. Create a bot with
[@BotFather](https://t.me/botfather), set `TELEGRAM_BOT_TOKEN`, run the bot once to learn
your chat ID, then set `TELEGRAM_ALLOWED_CHAT_IDS` before restarting it.

```bash
uv sync --extra audio
uv run telegram_bot.py
```

The allowlist matters: the local person graph is single-user. Do not expose one shared
store to untrusted Telegram chats.

## Trust, privacy, and limits

- **Precision comes first.** A wrong merge can corrupt a contact record; an uncertain
  match is held for a question instead.
- **You stay in control.** Follow-ups are drafts, and interactive calendar additions
  require confirmation.
- **Storage is local by default; processing is not fully local.** Contact records are
  kept in local JSON files, but memo text is sent to the configured Amazon Bedrock model.
  Audio is sent to Groq when transcription is enabled. For an eligible new contact,
  enrichment may send the person's name, employer, or role to a public-web search provider.
- **Evaluation data is isolated.** Never run benchmarks against your real contact graph.
- **Results vary.** Bedrock extraction is not fully deterministic, even at temperature
  zero. Benchmarks are repeated and report spread.
- **This is a single-user prototype.** Local storage and the Telegram integration are
  not multi-tenant.
- **Some references remain difficult.** Shortened names, job changes, and role-only
  descriptions can reach the ambiguity path; that is safer than silently merging them.

## What a judge can verify

1. **Memory across time.** Run the two supplied demo memos in order. The second memo
   should recognise people recorded by the first, rather than creating new contacts.

   ```bash
   uv run run_demo.py --reset data/memos/day1.txt
   uv run run_demo.py data/memos/day2.txt
   ```

2. **Real uncertainty.** The graph holds the selected ambiguous reference for a human
   answer in the interactive app. The question can change which branch that mention takes.
3. **Computed question selection.** Every candidate question has a measurable value;
   EIG selects the maximum. The app can show the alternatives it rejected.
4. **Comparable evidence.** The evaluation harness compares EIG with uncertainty sampling
   and random selection on the same cases, over repeated fresh extraction-and-resolution
   runs.
5. **Safety boundaries.** Passing mentions are filtered, enrichment needs memo-grounded
   evidence, and interactive calendar writes require confirmation.

## Benchmark

Recall is evaluated as an entity-resolution system: when a person returns in a later
memo, did the system connect that mention to the correct person record?

It reports B³ precision and recall (whether references to the same real person stay
together), pairwise clustering quality, extraction coverage, and the number of
clarification questions needed. Fixtures are hand-written, ordered memos so they test
memory across time rather than a single isolated note.

The reportable 3 September baseline used 11 scenarios and three fresh repeats of the
extraction-and-resolution path:

| Measure | Result |
| --- | --- |
| B³ F1 across scenarios | 0.911 ± 0.121 |
| EIG questions per resolution | 0.862 ± 0.037 |
| Uncertainty-sampling baseline | 1.033 ± 0.072 |
| Random baseline | 1.129 ± 0.008 |

On that benchmark, precision was 1.000 in eight of the eleven scenarios, including all
five professional B2B fixtures. EIG required fewer questions than both baselines. Its
worst repeat (0.897 questions per resolution) was below the best uncertainty and random
repeats (0.985 and 1.118), so those ranges did not overlap.

The comparison is fair because all strategies receive the same ambiguous cases in each
repeat. It is not independent of the resolver: conservative matching creates more cases
for the question step, so resolution quality and question efficiency should be discussed
together. The reported thresholds are `T_MATCH=3.0`, `T_NONMATCH=1.0`,
`MIN_MARGIN=1.0`, `W_NAME_EXACT=2.5`, and `NAMELESS_CEILING=2.5`.

The resolution benchmark has no human available to answer questions. Its ambiguous cases
are therefore placed by the model-based fallback. This means the table measures that
fallback as well as the arithmetic confidence band; in an interactive run, the selected
case would instead be decided by the person's answer.

A post-fix professional regression sweep also ran on five independent business arcs
(50 memos, three repeats): B³ F1 was **0.865 ± 0.117** across 15 scenario/repeat
measurements, with 1.000 precision in four arcs. Two malformed model outputs were
isolated to their memos. Its matching question sweep collected 191 scorable cases across
three fresh runs: EIG used **1.069 ± 0.041** questions per resolution, versus **1.261 ±
0.076** for uncertainty sampling and **1.353 ± 0.097** for random selection. EIG's
displayed range cleared both baselines, but the harness's conservative spread rule marks
the comparison inconclusive; this is encouraging regression evidence, not a stronger
headline claim.

When structured output comes back malformed, extraction asks the model to repair it and
resamples, up to three attempts. Only if every attempt fails does it fall back to keeping
the complete contacts that appear before the break, and it then reports how much text it
had to abandon, so a partial extraction is never mistaken for a clean one. It never
treats corrupt output as an empty memo or invents a partial contact.

Run the checks and benchmarks yourself:

```bash
uv run pytest tests/ -q                 # 419 offline tests; no model calls
uv run eval/check_fixtures.py           # fixture validation; no model calls
uv run eval/run_eval.py --repeats 3      # the 11-scenario table above; uses Bedrock
uv run eval/run_questions.py --repeats 3  # the EIG comparison above; uses Bedrock
uv run eval/run_eval.py --fixture eval/fixtures/bundles/recall_business_guideline_50.yaml
uv run eval/run_questions.py --fixture eval/fixtures/bundles/recall_business_guideline_50.yaml
```

The two `--repeats 3` commands reproduce the published tables exactly. The business
bundle sits in `eval/fixtures/bundles/`, outside the default sweep, so it is reached only
by the `--fixture` lines and cannot quietly change a headline number.

For a targeted scenario, add `--scenario arc_sales` (or another fixture ID, including one
inside a bundle alongside `--fixture`). A small
scenario is useful for diagnosis but is not a headline result; the scripts warn when
there are fewer than about 20 memos.

### Keep benchmark data separate

Benchmarks must never write into your live person graph. Use fresh paths for every
throwaway run:

```bash
scratch_dir=$(mktemp -d)
RECALL_STORE_PATH="$scratch_dir/graph.json" \
RECALL_CALENDAR_PATH="$scratch_dir/calendar.json" \
RECALL_RELATIONS_PATH="$scratch_dir/relations.json" \
uv run eval/run_eval.py --scenario arc_sales --repeats 3
```

## Architecture

### Layers

The web app, command line, and Telegram bot all call the same workflow. Their adapters
translate input and display results; the web and Telegram adapters also keep the saved
checkpoint needed to pause and resume a question. The identity logic itself is not
reimplemented in each front end.

```text
   web app             command line             Telegram bot
 web/server.py          run_demo.py            telegram_bot.py
      └──────────────────────┴───────────────────────┘
                             ▼
             one shared 11-step LangGraph workflow
                  recall/graph.py + recall/state.py
                             │
             ┌───────────────┴────────────────┐
             ▼                                ▼
      computed in code                  uses an AI model
      • retrieve candidates             • extract people
      • score identity evidence         • place ambiguities when no one can answer
      • choose the confidence band      • extract commitments
      • derive and rank questions       • enrich eligible contacts and tidy notes
      • apply the human's answer        • draft follow-ups
             │                                │
             └───────────────┬────────────────┘
                             ▼
              local person graph + calendar backend
```

The split down the middle is the point. The project's main decision—what question to
ask—is computed in code rather than improvised by a model. Candidate retrieval, identity
scores, confidence bands, question derivation, EIG ranking, and answer application are
covered by 103 focused unit tests. Models are still used where judgement over free text
is useful, and as a documented fallback when the system cannot ask a person.

### The pipeline graph

`build_graph()` in [`recall/graph.py`](recall/graph.py) wires eleven steps. These names
match the node names shown while the app is running:

```text
transcribe → extract → dedupe → ask
                                │
                    ┌───────────┴───────────┐
                    ▼                       ▼
               new → enrich           known → merge
                    └───────────┬───────────┘
                                ▼
       commitments → drafts → calendar → persist → summary
```

Two structural details carry most of the behaviour:

- **One memo can take both branches.** It may mention a stranger and someone already
  known. The workflow therefore sends the stranger through `enrich` and the known person
  through `merge`, waits for both branches, and then continues to `commitments`.
- **`ask` can pause the whole run.** In the web and Telegram experiences, LangGraph saves
  a checkpoint and calls `interrupt()`. The run resumes after the person answers, and that
  answer decides whether the selected mention belongs to a stored contact or to someone
  new.

`dedupe` deliberately does *not* settle an ambiguous mention on an interactive run. It
holds it — in neither the new nor the known bucket — so the question is chosen while the
ambiguity is still live rather than annotating a decision already made. Every question
also keeps “someone new” as a possible answer; it never has to force a stranger into one
of the existing records.

The attention budget is one question per memo. If several mentions are ambiguous, `ask`
chooses the mention and question with the highest information gain. Other ambiguous
mentions use the model-based fallback prepared by `dedupe`. In non-interactive CLI and
evaluation runs, there is no pause, so the fallback places every ambiguous mention while
the chosen question is kept only as an inspectable read-out.

### State

The workflow carries one shared state object from step to step. `RecallState`, a Python
`TypedDict` in [`recall/state.py`](recall/state.py), defines every field it may contain.
Each node returns only the fields it changed. The same module also defines the structured
shapes expected from the model (`Person`, `Commitment`, `Draft`, and others), keeping the
model and workflow contract in one place. If a node's output seems to vanish, first check
that its field name matches a key in `RecallState`; unknown keys are silently dropped.

### Resolution bands

The resolver's confidence band is arithmetic, not an LLM judgement. Matching evidence is
scored over name, employer, role, event, notes, and descriptions:

```text
high confidence        → merge automatically
middle confidence band → ask one EIG-selected question
low confidence         → create a new record
```

The thresholds are deliberately conservative. A bare exact name alone does not auto-merge,
and a description without a name cannot auto-merge. Both cases may still be good
candidates for a human-confirmed answer.

### Repository layout

```text
recall/                 the pipeline
  graph.py              supervisor graph: nodes, conditional edge, fan-in
  state.py              the one state TypedDict + every structured-output schema
  _common.py            model factory, usage metering, pricing ledger
  resolve.py            evidence scoring and the three-zone band        pure
  eig.py                entropy, posterior, EIG, the two baselines      pure
  questions.py          candidate questions derived from stored facts   pure
  answer.py             applies an answer under the same Bayes update   pure
  text.py               token matching shared by retrieval and resolution
  memory.py             PersonStore protocol + local JSON store
  contacts.py           phone/Instagram/Telegram/LinkedIn, user-typed
  relations.py          relationship edges, derived post-hoc, display-only
  tags.py               model-derived tags for filtering
  agent.py              AgentCore entrypoint — same graph, payload translation
  nodes/                one file per graph node
  tools/                transcription (Groq), web search, calendar backends

eval/                   the benchmark
  harness.py            fixture loading, the sweep, mention back-mapping
  metrics.py            B³ and pairwise clustering scores               pure
  strategies.py         EIG vs random vs uncertainty + simulated answerer
  run_eval.py           resolution baseline  → the B³ table
  run_questions.py      question efficiency  → the EIG comparison table
  check_fixtures.py     fixture validator; no model calls
  fixtures/             11 hand-written scenarios; bundles/ is opt-in

web/                    the demo UI — no framework, no build step
  server.py             FastAPI: transcribe, streamed run, /api/*
  index.html            record a memo and watch the run
  people.html           contacts as a filterable grid
  graph.html            connections, hand-rolled force layout

tests/                  offline, no credentials, no spend
data/                   gitignored: your real person graph, memos, audio
```

Root scripts are entry points and preflights: `demo.py` (guided three-memo demo),
`run_demo.py` (one memo from the CLI), `seed_demo.py`, `telegram_bot.py`, and the
numbered `00_check_*` / `0N_*` scripts for credential, calendar, and deployment checks.

### Code map

| Area | Main code |
| --- | --- |
| Pipeline and state | [`recall/graph.py`](recall/graph.py), [`recall/state.py`](recall/state.py) |
| Person extraction | [`recall/nodes/extract.py`](recall/nodes/extract.py) |
| Resolution and confidence bands | [`recall/resolve.py`](recall/resolve.py) |
| EIG and question derivation | [`recall/eig.py`](recall/eig.py), [`recall/questions.py`](recall/questions.py) |
| Applying a person’s answer | [`recall/answer.py`](recall/answer.py) |
| The pause and its resume | [`recall/nodes/ask.py`](recall/nodes/ask.py), [`web/server.py`](web/server.py) |
| Person storage | [`recall/memory.py`](recall/memory.py) |
| Evaluation harness | [`eval/`](eval/) |
| Web app | [`web/`](web/) |

## Storage and optional integrations

By default, Recall stores people in `data/person_graph.json`, relationship edges in
`data/relations.json`, and its calendar ledger in `data/calendar.json`. Redirect them
with `RECALL_STORE_PATH`, `RECALL_RELATIONS_PATH`, and `RECALL_CALENDAR_PATH`. Use all
three variables when creating an isolated demo or throwaway run.

Calendar backends are configured through `RECALL_CALENDAR`:

| Backend | Best for |
| --- | --- |
| `local` | A local JSON ledger; the default |
| `ics` | Portable calendar files that open in Apple, Google, or Outlook Calendar |
| `google` | Google Calendar through the web app's OAuth flow; intended for a hosted deployment |
| `mcp` | Google Calendar through a locally launched MCP subprocess |

Interactive web and Telegram runs pause before writing calendar items. The command-line
workflow has no confirmation screen and writes every proposed item automatically. Keep
`RECALL_CALENDAR=local` for CLI experiments unless that is the behaviour you want.

See `.env.example` for optional search, calendar, Telegram, and deployment settings.

## For maintainers

This README is the product and developer entry point. The project’s detailed decisions,
current benchmark notes, known failure modes, and operating rules live in
[`CLAUDE.md`](CLAUDE.md). Keep durable decisions there; do not turn this README into a
debugging log.
