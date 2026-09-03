# Recall

Recall is a private relationship-memory assistant. After a meeting or event, record a
short voice memo such as:

> “Met Wei Lin from GIC. She is hiring for a quant-infrastructure role, and I said I’d
> send her the Kestrel repo.”

Recall turns that into a contact record, remembers that person on later memos, captures
promises you made, and prepares follow-ups. When it cannot tell who a reference means,
it asks one useful question instead of silently guessing.

## Why it is different

Most note apps save what you said. Recall also helps answer **who** you meant.

If a later memo says, “the GIC woman asked for the repo,” Recall compares it with the
people already recorded. It takes one of three paths:

| What it knows | What Recall does |
| --- | --- |
| Strong evidence for one person | Recognises and updates that person |
| Too little evidence | Records someone new |
| More than one plausible person | Asks one clarifying question |

The question is selected with expected information gain (EIG): Recall chooses the
question expected to reduce uncertainty the most, rather than asking a language model
to improvise one. For example, knowing someone attended the same event may not help if
every candidate did; a differing employer or role may settle the question immediately.

## Agentic workflow

Recall uses one shared workflow whether the memo arrives from the web app, command line,
or Telegram. The model extracts structured facts; the workflow then makes the important
identity and question-selection decisions explicitly.

```text
voice memo
  → transcribe (audio only)
  → extract people and commitments
  → resolve against the person graph ──┬── known → merge into that record
        │                               ├── new   → optionally enrich, then record
        │                               └── ambiguous → ask one EIG-selected question
        ▼
  merge the branches → draft follow-ups → propose calendar items → persist a summary
```

A memo can contain both a new person and someone already known, so the graph deliberately
fans out to both branches and joins them before follow-ups are drafted. In the web and
Telegram experiences, an ambiguous reference pauses the workflow; the person’s answer
decides the branch. The command-line evaluator has no person to ask, so it records the
fallback separately as a limitation.

The LLM does not decide every step. It extracts people, optionally enriches public
context, and drafts follow-ups. The resolver assigns the confidence band with testable
scoring; question candidates are derived from stored facts; EIG ranks them; and the same
Bayesian likelihood model is used to apply the answer. This makes the agent’s most
important decision inspectable rather than a hidden prompt outcome.

```text
Candidate: “the GIC woman”

Ask:  “Do they lead quant infrastructure?”      high information gain
Skip: “Were they at the same event?”             low information gain; both candidates were
```

Recall does not auto-send messages. Calendar items are shown for confirmation in the
interactive app before they are added.

## Quick start

You need Python 3.11+, [uv](https://docs.astral.sh/uv/), AWS credentials with Amazon
Bedrock access, and a Bedrock model your account can call.

```bash
uv sync --extra audio --extra web
cp .env.example .env
uv run 00_check_bedrock.py
uv run web/server.py
```

Open `http://localhost:8000`, record or type a memo, check the transcript, then run it.

For a terminal demo instead:

```bash
uv run run_demo.py
uv run run_demo.py data/memos/day2.txt
uv run run_demo.py data/audio/memo.m4a   # requires GROQ_API_KEY
```

The model check must print `OK` before a Bedrock run. If it does not, it explains whether
the problem is credentials, region, permission, or model access.

### Minimum configuration

Copy `.env.example` to `.env` and set the model that works for your account. Amazon Nova
is a practical default when third-party Bedrock models are unavailable:

```dotenv
AWS_REGION=ap-southeast-1
RECALL_MODEL_ID=global.amazon.nova-2-lite-v1:0
GROQ_API_KEY=                 # only needed for audio transcription
```

`00_check_bedrock.py --list-models` probes available models with real calls. A model
appearing in the AWS console is not proof that this account can invoke it.

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

Telegram is a private front end for voice memos. Create a bot with
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

2. **Real uncertainty.** The graph holds ambiguous references for a human answer in the
   interactive app. It does not silently choose the first plausible candidate.
3. **Computed question selection.** Every candidate question has a measurable value;
   EIG selects the maximum. The app can show the alternatives it rejected.
4. **Comparable evidence.** The evaluation harness compares EIG with uncertainty sampling
   and random selection on the same cases, over repeated full pipeline runs.
5. **Safety boundaries.** Passing mentions are filtered, enrichment needs memo-grounded
   evidence, and interactive calendar writes require confirmation.

## Benchmark

Recall is evaluated as an entity-resolution system: when a person returns in a later
memo, did the system connect that mention to the correct person record?

It reports B³ precision and recall (whether references to the same real person stay
together), pairwise clustering quality, extraction coverage, and the number of
clarification questions needed. Fixtures are hand-written, ordered memos so they test
memory across time rather than a single isolated note.

The reportable 3 September baseline used 11 scenarios and three full repeats:

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
uv run pytest tests/ -q                 # 418 offline tests; no model calls
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

## Technical overview

The key design decision is that the resolver’s confidence band is arithmetic, not an
LLM judgement. Matching evidence is scored over name, employer, role, event, notes, and
descriptions:

```text
high confidence        → merge automatically
middle confidence band → ask one EIG-selected question
low confidence         → create a new record
```

The matching thresholds are deliberately conservative. A bare exact name alone does not
auto-merge, and a description without a name cannot auto-merge. Both cases may still be
good candidates for a human-confirmed answer.

| Area | Main code |
| --- | --- |
| Pipeline and state | [`recall/graph.py`](recall/graph.py), [`recall/state.py`](recall/state.py) |
| Person extraction | [`recall/nodes/extract.py`](recall/nodes/extract.py) |
| Resolution and confidence bands | [`recall/resolve.py`](recall/resolve.py) |
| EIG and question derivation | [`recall/eig.py`](recall/eig.py), [`recall/questions.py`](recall/questions.py) |
| Applying a person’s answer | [`recall/answer.py`](recall/answer.py) |
| Evaluation harness | [`eval/`](eval/) |
| Web app | [`web/`](web/) |

## Storage and optional integrations

By default, Recall stores its local graph in `data/person_graph.json` and its calendar
ledger in `data/calendar.json`. These paths can be changed with `RECALL_STORE_PATH` and
`RECALL_CALENDAR_PATH`.

Calendar backends are configured through `RECALL_CALENDAR`:

| Backend | Best for |
| --- | --- |
| `local` | A local JSON ledger; the default |
| `ics` | Portable calendar files that open in Apple, Google, or Outlook Calendar |
| `google` or `mcp` | A configured personal Google Calendar connection |

See `.env.example` for optional search, calendar, Telegram, and deployment settings.

## For maintainers

This README is the product and developer entry point. The project’s detailed decisions,
current benchmark notes, known failure modes, and operating rules live in
[`CLAUDE.md`](CLAUDE.md). Keep durable decisions there; do not turn this README into a
debugging log.
