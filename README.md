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
        calendar_write  (confirm what to add, then write)
                       ▼
              persist to memory → summary
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

### Telegram (send a voice note from your phone)

```bash
uv sync --extra audio            # `--extra web` is not needed; httpx is a core dep
uv run telegram_bot.py
```

Three steps of setup, once:

1. Message [@BotFather](https://t.me/botfather), `/newbot`, copy the token into `.env`
   as `TELEGRAM_BOT_TOKEN=`.
2. Run the bot and message it. It refuses you and **prints your chat id**.
3. Put that id in `.env` as `TELEGRAM_ALLOWED_CHAT_IDS=` and restart.

Then hold the mic button, talk for ninety seconds, and send. The bot transcribes, echoes
the transcript back so a misheard name is visible before any tokens are spent, runs the
graph, and — if a mention is genuinely ambiguous — **asks its one question as a
keyboard**, with the bits it bought and the questions it turned down printed underneath.
Tap an answer and the run resumes where it paused.

```
❓ What do they study at NUS?

about the malaysian chinese girl
worth 0.803 bits of the 1.270 outstanding

who it might be:
  Kit Yee — 49%
  Crispy — 47%

questions it did not ask:
  0.038 — Also from malaysian chinese independent school?
  0.000 — Same school as you?

[ computer science ] [ business analytics ] [ something else ]
```

Why a chat client when the web UI already records memos: a chat is the **natural shape
for `interrupt()`**. The graph pauses on one question, Telegram renders it as a keyboard,
the tap resumes the run. The browser has to fake that with a streamed response body and a
second endpoint. It is also the only surface where the memo gets recorded where memos
actually happen — walking out of the event, on your phone.

Three things worth knowing before you demo it:

- **The allowlist is load-bearing, not politeness.** `get_store()` is process-global on
  one `RECALL_STORE_PATH`, so an unlisted chat would resolve its people against *your*
  contacts. Per-user stores is a rewrite of [recall/memory.py](recall/memory.py), not a
  flag, so until then the bot answers the chats you name and nobody else.
- **A pending question does not survive a restart.** The paused run lives in an
  `InMemorySaver`, same trade-off as the web UI. Tap a stale button and you get *"that
  question has expired"* rather than a stack trace, but the run is gone.
- **One pause per chat**, because the thread id *is* the chat. Send a second memo while a
  question is open and it tells you to answer it or `/cancel`.

Long polling, not a webhook — `getUpdates` needs no public HTTPS URL, no tunnel and no
certificate, which is what you want running off a laptop on stage.

### CLI

```bash
uv run pytest tests/ -q         # 411 tests, offline, no credentials, no spend
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

```
recall/          the pipeline          eval/         the benchmark
  state.py       one TypedDict           harness.py    fixtures, sweep, align()
  graph.py       supervisor graph        metrics.py    B³ + pairwise. Pure
  resolve.py     three-zone band         strategies.py EIG vs the two baselines
  eig.py         EIG + baselines         run_eval.py       → the B³ table
  questions.py   derived questions       run_questions.py  → the headline table
  answer.py      applying an answer      check_fixtures.py validator, free
  text.py        token matching          from_audio.py     memo → fixture
  memory.py      the person graph        fixtures/         5 scenarios
  relations.py   relationship edges
  contacts.py    handles, user-typed   web/          the demo UI, no framework
  tags.py        filter tags             server.py     FastAPI + /api/*
  _common.py     chat_model(), ledger    index.html    record and watch a run
  agent.py       AgentCore entrypoint    people.html   everyone, filterable
  mcp_client.py  stdio MCP client        graph.html    connections
  nodes/         one file per node       app.css       shared styling
  tools/         transcribe, web, cal    shared.js     client-side filtering

telegram_bot.py  Telegram front-end — long-poll, voice note in, keyboard out
```

| Path | What it is |
|---|---|
| [recall/graph.py](recall/graph.py) | The supervisor graph — nodes, conditional edge, fan-in |
| [recall/state.py](recall/state.py) | The one `TypedDict` + every structured-output model |
| [recall/resolve.py](recall/resolve.py) | The three-zone band — pure scoring, no model |
| [recall/eig.py](recall/eig.py) | Expected information gain, the Bayes update, and the two baselines |
| [recall/questions.py](recall/questions.py) | Candidate questions derived mechanically from stored attributes |
| [recall/answer.py](recall/answer.py) | Applying one answer, with the same likelihood EIG scored it under |
| [recall/text.py](recall/text.py) | Token matching shared by retrieval and resolution |
| [recall/memory.py](recall/memory.py) | The person graph. `PersonStore` protocol, local + AgentCore backends |
| [recall/relations.py](recall/relations.py) | Relationship edges between people — derived post-hoc, display-only |
| [recall/contacts.py](recall/contacts.py) | Phone, Instagram, Telegram, LinkedIn. Storage and display only |
| [recall/tags.py](recall/tags.py) | Tags for filtering — read off the notes by a model, never lexically |
| [recall/agent.py](recall/agent.py) | AgentCore entrypoint. Translates payloads; the graph is the same one |
| [recall/_common.py](recall/_common.py) | `chat_model()`, cost ledger, pricing table, cache helper |
| [recall/nodes/](recall/nodes/) | One file per graph node. `enrich`/`followups`/`calendar` are the frozen tail |
| [recall/tools/](recall/tools/) | Transcription, web search, calendar |
| [eval/harness.py](eval/harness.py) | Fixture loading + the resolution sweep behind the B³/pairwise numbers |
| [eval/metrics.py](eval/metrics.py) | B³ and pairwise clustering scores. Pure functions, no model |
| [eval/strategies.py](eval/strategies.py) | The three strategies and the simulated answerer |
| [eval/run_questions.py](eval/run_questions.py) | EIG vs random vs uncertainty — the headline benchmark |
| [eval/fixtures/](eval/fixtures/) | The eleven hand-written scenarios every number here comes from |
| [web/server.py](web/server.py) | FastAPI transport — transcribe + streamed graph run |
| [web/index.html](web/index.html) | Record a memo and watch the run — one file, no framework |
| [web/people.html](web/people.html) | Everyone, as a filterable grid |
| [web/graph.html](web/graph.html) | Connections — the relationship graph, hand-rolled force layout |
| [telegram_bot.py](telegram_bot.py) | Telegram transport — long-polls, renders the pause as a keyboard |
| [tests/fakes.py](tests/fakes.py) | Scripted fake models — how the graph is tested without credentials |
| [tests/test_graph.py](tests/test_graph.py) | Graph wiring end to end, against those fakes |
| [tests/test_guards.py](tests/test_guards.py) | The filters that keep wrong data out of the person graph |
| [tests/test_relations.py](tests/test_relations.py) | The grounding guard, and that edges stay out of resolution |

Numbered scripts run the AWS lifecycle: `00_check_bedrock.py` (must print OK first),
`01_run_local.py` (free), `02_deploy.py` (billable), `03_teardown.py`, `04_call_agent.py`.
`run_demo.py` puts one memo through the pipeline from the CLI; `seed_demo.py --write`
seeds the demo graph; `telegram_bot.py` is the phone front-end.

**Three front-ends, one pipeline.** `web/server.py`, `telegram_bot.py` and `run_demo.py`
all import the same graph and do nothing but translate payloads. If a behaviour differs
between them, the difference is `configurable.interactive` — with it the graph holds
ambiguous mentions and pauses for a human; without it the adjudicator settles them and
the question is a read-out. None of the three may grow a second copy of the pipeline.

**One naming trap:** the fixture file is `arc_ehoc.yaml` but the scenario id inside it —
what `--scenario` takes and what every table below prints — is `ehoc_c4`. Both are
correct.

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

Fixtures: **114 memos, 234 mentions, 83 recurring people across eleven scenarios** — the
three student arcs (`arc_acacia`, `arc_godwin`, `ehoc_c4`), one professional sales arc
(`arc_sales`), five B2B account/partner/conference fixtures (`account_notes`,
`client_followups`, `conference_notes`, `partner_notes`, `site_visit_notes`), and two
tiny diagnostics (`same_first_name`, `genuinely_ambiguous`).

Measured 3 Sep, `repeats=3`, thresholds `T_MATCH=3.0 T_NONMATCH=1.0 MIN_MARGIN=1.0`,
`W_NAME_EXACT=2.5 NAMELESS_CEILING=2.5`. Quote the thresholds with any number here.

```
scenario                B3 F1    B3 P    B3 R  pair F1   subst   covrg
partner_notes           0.968   1.000   0.938    0.933   0.970   0.938
account_notes           0.962   1.000   0.926    0.929   0.944   0.944
ehoc_c4                 0.924   0.989   0.870    0.850   0.959   0.954
conference_notes        0.916   1.000   0.846    0.859   0.944   0.944
arc_godwin              0.877   0.947   0.816    0.667   0.952   0.947
site_visit_notes        0.870   1.000   0.771    0.719   0.971   0.941
arc_sales               0.865   1.000   0.762    0.615   0.933   0.929
client_followups        0.865   1.000   0.763    0.682   0.946   0.939
arc_acacia              0.775   1.000   0.633    0.493   0.873   0.857
same_first_name         1.000   1.000   1.000    1.000   1.000   1.000
genuinely_ambiguous     1.000   1.000   1.000    1.000   1.000   1.000

B-cubed F1 across all scenarios: 0.911 ±0.121 (n=33)
```

**Precision is 1.000 on eight of eleven scenarios — including all five professional B2B
fixtures**, which were written with deliberate name collisions (two Aarons at different
banks, two Alexes, Cheryl Ng/Cheryl Wong, Darren Chia/Darren Chew, Elena Loh/Elaine Low).
None merged. The only sub-1.000 precision is `ehoc_c4` (0.989) and `arc_godwin` (0.947),
both the LLM adjudicator on non-interactive runs, not the resolution band. This is the
strongest evidence that precision is a property of the method, not of one student setting
— **state the claim at the scenario level, not globally**, since it was briefly false
before the channel fix (a description laundered through `aliases` once merged two people
in `arc_acacia`).

Recall is the softer half — 0.63 on `arc_acacia`, 0.76–0.94 on the professional set. Those
losses are loose references (company/role-only, no name) that the `NAMELESS_CEILING` policy
now sends to a clarifying question rather than auto-resolving. That is a deliberate trade:
a little recall for the guarantee that a nameless mention never silently merges into the
wrong person. A missed recognition is visible and fixable; a wrong merge destroys a real
record.

### Questions per resolution

```bash
uv run eval/run_questions.py [--repeats N]
```

Measured 3 Sep, `repeats=3`, same thresholds as above.

```
strategy       questions/resolution                       <=1 question
eig            0.862 ±0.037  (n=3, min 0.824  max 0.897)       78%
uncertainty    1.033 ±0.072  (n=3, min 0.985  max 1.129)       75%
random         1.129 ±0.008  (n=3, min 1.118  max 1.134)       69%
```

~69 scorable cases across the three runs; budget cap 5 questions; unresolved excluded from
the mean. **EIG's max (0.897) sits below both baselines' minimums (0.985, 1.118)** — the
ranges do not overlap, which is the check that stops a lucky run being reported as a win.
26 of 69 chosen questions were multi-valued.

This is the strongest version of the result the project has produced, and the enlarged
fixture set is why: the B2B fixtures supply many **3- and 4-hypothesis** ambiguous cases
(`'Fortinet channel guy'` against four candidates, `'OCBC procurement guy'` against three).
With only two candidates every discriminating question is worth the same bits and all
strategies tie; with three or four, the argmax has something to choose and EIG's choice is
measurably better. The deliberate near-homophone name pairs are what manufacture those
multi-way ties.

**The claim is "EIG beats both baselines."** Here it also beats them in clean order (EIG <
uncertainty < random, disjoint ranges), but keep the conservative wording — uncertainty
and random have swapped at smaller n before. What is solid is that EIG is first and its
range clears both.

One caveat belongs next to the table: **the denominator moves with the resolver.**
`W_NAME_EXACT=2.5` and `NAMELESS_CEILING=2.5` push bare-name and nameless returns into the
ambiguous band, so resolution quality and question efficiency are **coupled** and must not
be presented as independent results. All three strategies draw from the same case set per
run, which is what makes the comparison sound.

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


## Putting it on your calendar

A memo that says *"told Wei Lin I'd send the Kestrel repo"* contains a promise, and
`extract_commitments` picks it up. What happens next is the one place the pipeline
touches something outside itself, so it asks first.

**It proposes, you approve, then it writes.** On an interactive run `calendar_node`
builds the events, stops on `interrupt()` — the same pause the clarifying question uses,
not a second mechanism — and shows you exactly what it wants to add. Tick what you want.
Nothing reaches the calendar until you answer, and an event you decline is recorded as
`declined` rather than dropped, so "nothing appeared on my calendar" is answerable from
the run instead of a mystery.

The ordering is load-bearing rather than stylistic. `interrupt()` re-executes the node
from the top on resume, so anything above it runs twice — which for a calendar write
means a declined event lands anyway. `propose_event()` is therefore pure and
`write_proposed()` is the only thing that touches a calendar;
`test_interactive_pauses_and_writes_nothing_before_the_answer` is the tripwire. What the
confirmation shows is the built event, not a paraphrase of it, so approving the title you
read is approving the one that lands.

**An unrecognised reply approves nothing.** Defaulting to "write everything" would mean a
malformed answer silently puts events on a real calendar, which is what the gate exists to
prevent. Declining is visible and costs one re-run; the other way round is invisible.

Non-interactive runs — the CLI, the eval harness, the tests — write without stopping,
exactly as before. The switch is `configurable.interactive`, never the presence of a
checkpointer, so the benchmark cannot deadlock waiting for a person who is not there.

### Three backends, and only one of them works for other people

`RECALL_CALENDAR` picks where an approved event lands. The confirmation gate runs either
way — the backend only decides the destination.

| | Setup for a new user | Reaches |
|---|---|---|
| `local` *(default)* | none | a JSON file. A demo ledger, not a calendar |
| **`ics`** | **none** | **Google, Apple, Outlook — everything** |
| `google` | one-time consent in a browser | the connected account. For the hosted build |
| `mcp` | a Google Cloud project **each** | one machine, yours |

**`ics` is the one to reach for.** Each approved item is written as an iCalendar file, and
both surfaces offer two ways to take it: a one-tap **Add to Google Calendar** link and the
`.ics` file itself. The link is there because a chat app opening a `.ics` is unreliable —
it often previews the file as text with no add-to-calendar prompt — so one tap on the link
opens Google's own event screen with a **Save** button, while the file stays for whoever
imports into Apple Calendar or Outlook. Either way we propose and the human commits, the
same bargain as the drafts. No credentials, no API, no account, nothing to authorise. The
link is built server-side by `gcal_link()` in [recall/tools/calendar.py](recall/tools/calendar.py),
so the web card and the Telegram message can't drift.

```bash
RECALL_CALENDAR=ics uv run run_demo.py data/memos/sales_day1.txt
```

**The calendar records two kinds of thing.** A *follow-up* you owe someone ("send the deck
by Friday" → a transparent reminder that does not block your day) and an *event you said
you'd attend* ("going to the Welcome Night on the 18th with Crispy and Kit Yee" → one
opaque, all-day entry that does). The distinction is a `kind` field the commitment
extractor sets; the calendar branches the title and the free/busy state on it, and the
drafter skips *attending* entries because there is nothing to send about your own plans.
One event with several companions collapses to one entry, not one per person.

Four details in [`ics_text`](recall/tools/calendar.py) that are the difference between a
file that works and one that silently doesn't:

- **`DTEND` is exclusive** — an all-day event on the 11th ends on the 12th. Same date for
  both and Google renders it, Apple renders it, Outlook drops it.
- **Commas are escaped.** A comma is a field separator, so *"send the deck, the pricing,
  and a demo"* would arrive as an event called *"send the deck"*, with no error anywhere.
- **CRLF line endings, folded at 75 octets** on character boundaries — bytes are the
  limit, characters are the unit, and names are exactly where that bites.
- **The UID is the idempotency key**, so re-importing the same file updates the event
  instead of duplicating it — the ledger's guarantee, enforced by the calendar client.

`mcp` stays as the "I have Google credentials on this laptop" option. It cannot be handed
to anyone else: the `gcp-oauth.keys.json` is *your* Cloud project, tokens cache to one
path on one machine, and the server is a local subprocess. The multi-user version needs
one OAuth client that you own plus per-user consent, and Calendar is a **sensitive scope**
— unverified apps are capped at ~100 test users behind a warning screen until Google
reviews them. Roadmap, not hackathon.

### Hosting it (Render)

`render.yaml` is a blueprint — commit it, then **New → Blueprint** in Render. Check the
config first; it costs nothing and reads no secrets:

```bash
uv run 00_check_deploy.py            # blocks on anything fatal
uv run 00_check_deploy.py --new-key  # generates RECALL_TOKEN_KEY
```

**One service, not two.** `upgrade.md` proposes a web service plus a Telegram worker; a
Render disk attaches to exactly **one** service, so a separate worker could not read the
OAuth token the web service writes at the end of consent. `RECALL_TELEGRAM=1` runs the
poller in a daemon thread inside the web process — shared disk, shared memory for the
pending question, and nothing lost for a single-tenant deployment.

**The free tier cannot host this.** Persistent disks need a paid instance, and a free
service spins down after ~15 minutes idle. Without a disk, every redeploy and every idle
period wipes `person_graph.json` — everyone becomes a stranger — and `google_token.json`,
so you redo the Google consent flow on stage. A relationship-memory product that forgets
on redeploy is not demoable.

**It is single-tenant, and the Telegram allowlist is the only thing enforcing that.**
`get_store()` is process-global on one `RECALL_STORE_PATH` and takes no user argument.
`upgrade.md` scopes *calendar connections* per Telegram user but says nothing about the
graph — so hosted open, a stranger's memo would resolve against your contacts and two
people named Alex would merge. `00_check_deploy.py` refuses to pass with an empty
allowlist for exactly that reason.

Order of operations, because two of these have to be done twice:

1. Deploy. Copy the Render URL.
2. Set `PUBLIC_BACKEND_URL` and `GOOGLE_REDIRECT_URI` to it, add the callback to the
   Google OAuth client's authorised redirect URIs, restart.
3. `GET /healthz` — it reports the backend, whether OAuth is configured, whether a
   calendar is connected, and whether the poller is running. No secrets.
4. Message the bot `/connect_calendar`, consent, then send a memo.

`/healthz` deliberately reports what is *configured* rather than just `ok`: a health check
that passes while the model id is wrong and the calendar is unreachable hides the two
things that actually break a deploy.

### Testing the MCP backend

`00_check_calendar.py` probes it and writes nothing. Four things break independently and
it reports each one alone: the server not starting, starting but not speaking MCP,
speaking MCP but having no tool by the configured name, and — the quiet one — having the
tool but wanting different argument names than `_write_mcp` sends.

```bash
uv run 00_check_calendar.py
```

It deliberately reimplements the MCP handshake rather than importing
[recall/mcp_client.py](recall/mcp_client.py): a diagnostic that shares code with the thing
it diagnoses fails identically and tells you nothing.

The first thing it will catch is that **the MCP server needs its own Google credential**,
unrelated to anything else in `.env`:

```bash
GOOGLE_OAUTH_CREDENTIALS=/abs/path/to/gcp-oauth.keys.json
```

Without it the server exits during startup, and `mcp_client` reports only *"MCP server
closed the connection"* — it captures stderr and never reads it, so the real reason never
reaches you. The probe prints that stderr.

Two things to know before concluding it's broken:

- **A second identical write returns `DUPLICATE` without contacting MCP at all.** The
  idempotency check runs against the local ledger *before* the call, so re-running the
  same memo tells you nothing about whether the calendar works. Change the promise text
  or delete `data/calendar.json` between attempts.
- **A failed write never raises.** It comes back as `status: error`, gets recorded, and
  the run finishes looking successful. Read the summary rather than trusting the exit
  code.

A clean probe proves the protocol, the tool name and the argument names. It does not
prove OAuth is authorised or that the event lands on the calendar you expect — for that,
do one real write against a scratch ledger and go look at your calendar:

```bash
RECALL_CALENDAR_PATH=/tmp/cal-test.json uv run run_demo.py
```

### Two backends

```bash
RECALL_CALENDAR=local     # default: append to data/calendar.json. Free, offline
RECALL_CALENDAR=mcp       # Google Calendar through an MCP server
GCAL_MCP_COMMAND="npx -y @cocal/google-calendar-mcp"
GCAL_MCP_TOOL=create-event
```

Google Calendar needs a one-time OAuth setup on your side: a Desktop OAuth client in
Google Cloud, the Calendar API enabled, your own account added as a test user. The first
run opens a browser to consent and the server caches the token. Until that is done, leave
`RECALL_CALENDAR=local` — the gate behaves identically, the events just land in a JSON
file, which is also what you want on stage.

Both backends share the idempotency key, derived from the commitment text, so re-running
the same memo during a demo updates nothing instead of stacking duplicates.

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
   memo in `run_eval` and once an entire run of `run_questions`. The 31 Aug headline
   reached n=3 in spite of it, so it no longer blocks the table — but it still costs a
   memo per sweep. Not a fixture problem; it needs a retry or a coercing validator.
4. **`arc_godwin`'s precision loss is the adjudicator, not the resolver.** `jia_en` and
   `jia_ying` share a record, but all four of their mentions scored **AMBIGUOUS**
   (1.27–2.19) — nothing auto-resolved. With four `Jia*` people in one orientation group,
   coverage-based name matching scores them 0.50 on the shared syllable and the band
   flags every one. The merge came from `_adjudicate()`, the LLM fallback that settles
   the band on non-interactive runs because nobody is there to answer. So this number
   measures the fallback guesser, not the path the product actually takes — interactively
   those mentions are held and one buys a question.
5. **The code default model is one a personal account cannot call.** `_common.py` defaults
   to a `global.anthropic.*` id, which is the marketplace-gated path. It works only
   because `.env` overrides it, and `.env` is not in the repo — so a fresh clone fails
   with `ValidationException: invalid model identifier`, which reads like a typo.

### To do

1. **Write and time the demo script**, then rehearse it. This is the main gap.
2. **Seed the demo data** — `uv run seed_demo.py --write`. With no prior records nothing
   is ambiguous, so the behaviour worth showing never fires.
3. **The AgentCore Memory backend**, only if deploying. `recall/memory_agentcore.py` was
   written blind and has never run; as written it would make every known person look new.
   Test against a throwaway memory resource, never the live graph.

The writeup is drafted — plain-language, exported to `recall-writeup.pdf`.

### The sales framing (`business.md`)

[business.md](docs/business.md) pitches Recall as a sales-productivity product. It is a
**positioning document, not a spec** — most of what it describes already ships, one item
is genuinely worth building, and a few would cost more than they return.

**Six of its seven MVP steps are already built**, in the tail this repo otherwise leaves
frozen: transcribe, extract company and role, decide new-or-known, ask when unsure,
persist the history, detect the promise, gate the calendar write, draft the follow-up.
The gap between that document and this repo is narrative, not code.

Worth doing:

1. **A professional-setting fixture** (`eval/fixtures/arc_sales.yaml`). The highest-value
   item in the document, and the only one that improves the benchmark. Every current arc
   is one hall or one orientation group — everyone shares an event, nobody has a company,
   and the `company`/`role` channels sit silent instead of *conflicting*. That is exactly
   the caveat under [Known limitations](#known-limitations), and a sales arc is how you
   attack it rather than restate it. Expect both tables to move.
2. **Re-skin the demo memos** to the sales scenario. Zero code — the pipeline does not
   care what setting a memo comes from.
3. **`GET /api/export`** — the person graph as a download. About ten lines, since the
   store is already JSON, and a contact book you cannot get out of is one you stop
   trusting.

Deliberately not doing, with the reason:

- **"Opportunity" or "needs" as a field on `Person`.** Third time this shape has come up
  after contact handles and relationship edges, and the answer has not changed: a new
  field changes the same extraction call that emits `name`, `notes` and `company`, and
  `temperature=0` is not reproducible, so both benchmark tables need re-running — for
  content that is already in `notes` as prose. If it must exist, it is a separate
  post-hoc pass like [recall/relations.py](recall/relations.py), never folded into
  `extract`.
- **Ranking follow-ups by urgency.** One step from scoring which people are worth your
  time, which is a non-goal here.
- **Freemium quotas, team workspaces, HubSpot/Salesforce.** All need multi-tenancy, and
  the store is structurally single-tenant: `get_store()` is process-global on one
  `RECALL_STORE_PATH` — the same wall the Telegram allowlist exists to hold. Roadmap, not
  hackathon.

One thing in `business.md` needed a decision rather than a commit: it used to close on
*"prevents valuable sales opportunities from being lost"*, and this project's own framing
rule is never to sell Recall as extracting value from contacts later. Settled 2 Sep in
favour of **"you keep the promises you made"** — a sales outcome and a decent one at the
same time, and what the frozen tail already does. `business.md` now closes on that line,
so the two documents no longer disagree.

### Known limitations

"the two X girls" extracts as one entity, not two — `Person` emits one record per person,
and plural-mention expansion is out of scope. Role-only references with no content
("bumped into the male OGL, said hi") extract nobody. A Whisper mis-hear that changes the
*first* token of a name (`Zhong Xuan` → `Jong Shuen`) scores 0.00 and does not match at
all. And all three arcs come from the same kind of setting — one hall, one orientation
group — where everyone shares an event and nobody has a company, so thresholds tuned here
may not generalise to a professional graph.

Relationship edges are sparse by construction: one is drawn only when a stored note names
the other person outright, so a relationship the memos never recorded is not shown. A
nickname that was never saved as an alias breaks that check — a note saying *"Marc calls
her Crispy"* does not ground an edge to a record named `Marcus` unless `Marc` is in its
`aliases`. Same class as the nickname-in-the-wrong-field failure, and the same remedy:
merge the records, or draw the edge by hand.

## The three guards

All three exist because a model *told* to be careful is still sometimes not careful, and
each failure mode is invisible in the output.

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
