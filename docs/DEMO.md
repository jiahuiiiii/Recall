# Recording the demo

A runbook for recording the submission demo. Follow it top to bottom at record
time — it is written to be copy-pasted under pressure, not read.

**Record locally.** The video does not show where it runs, and local has no cold
starts, no spin-down, and no Google consent screen on camera. Deploying to Render
only adds risk (see [the deployment caveats](#if-you-must-show-it-hosted)) and
gains nothing the camera can see except a URL bar.

**Test the web UI or the Telegram bot — never `run_demo.py`.** Only the
interactive paths actually *pause and ask the clarifying question*. The CLI
auto-adjudicates, so it cannot show the one thing the demo exists to show.

---

## Before anything: one rule

Every command below points the store at a **throwaway copy** of the seed:

```bash
cp data/demo_seed.json /tmp/demo.json
```

Running a memo writes to the store — it adds people and records merges. Point it
at `/tmp/demo.json` and the committed seed you are about to ship stays pristine.
Re-copy any time you want a clean slate.

This also honours the standing rule (see CLAUDE.md): **never run a demo memo
against `data/person_graph.json`.** A test memo written into the real graph later
looks exactly like the agent hallucinating a fact you never said.

---

## Prerequisites

```bash
uv sync --extra web --extra audio       # web UI + transcription
```

`.env` needs `GROQ_API_KEY` (transcription) and `RECALL_MODEL_ID` — both already
set. The Telegram path needs a bot token; step 2 covers it.

---

## 1. Web UI — the fastest check, and the one that shows the question card

```bash
cp data/demo_seed.json /tmp/demo.json

RECALL_STORE_PATH=/tmp/demo.json \
RECALL_CALENDAR=ics RECALL_ICS_DIR=/tmp/ics \
RECALL_CALENDAR_PATH=/tmp/cal.json RECALL_RELATIONS_PATH=/tmp/rel.json \
uv run web/server.py
```

Open <http://localhost:8000>. In the text box (skip recording — typing is fine),
paste:

> Ran into the partner from Jungle again at the founders thing. She asked how the
> raise is going and wants the updated deck by end of month.

Three things must land:

1. **The question card** — the mention, the candidate priors as bars, the chosen
   question with its bits, and the questions it *did not* ask with their measured
   value. This is the money shot.
2. **The resolution** — after you answer, it drops into the person graph on the
   right, with the confidence shown.
3. **Add to calendar** — the Calendar card shows a link that downloads a real
   `.ics`. Open it; your calendar app should fill in the event.

Then paste the Acacia memo to confirm the *attending* path:

> Going to the Acacia Welcome Night at 18 Sept with Crispy and Kit Yee.

You should get **one** event titled `Acacia Welcome Night` — not a "Follow up
with…" per person. That is the `kind=attending` behaviour working.

Sanity check in the browser: <http://localhost:8000/healthz> should report
`"calendar_backend": "ics"`.

---

## 2. Telegram — the actual demo surface

### Make a bot (once, ~2 minutes)

Message **@BotFather** on Telegram → `/newbot` → follow the prompts → copy the
token.

### Learn your chat id

```bash
cp data/demo_seed.json /tmp/demo.json

TELEGRAM_BOT_TOKEN=<your-token> \
RECALL_STORE_PATH=/tmp/demo.json \
RECALL_CALENDAR=ics RECALL_ICS_DIR=/tmp/ics \
RECALL_CALENDAR_PATH=/tmp/cal.json RECALL_RELATIONS_PATH=/tmp/rel.json \
uv run telegram_bot.py
```

Message the bot anything. It **refuses you and prints your chat id** to the
console — this is the setup step, not a failure. Ctrl-C.

### Run it for real

Add the id and restart:

```bash
TELEGRAM_BOT_TOKEN=<your-token> \
TELEGRAM_ALLOWED_CHAT_IDS=<your-chat-id> \
RECALL_STORE_PATH=/tmp/demo.json \
RECALL_CALENDAR=ics RECALL_ICS_DIR=/tmp/ics \
RECALL_CALENDAR_PATH=/tmp/cal.json RECALL_RELATIONS_PATH=/tmp/rel.json \
uv run telegram_bot.py
```

Send a **voice note** with the Jungle line. You should get, in order:

1. the transcript echoed back (so a misheard name is visible before any tokens
   are spent);
2. the clarifying question as **tappable buttons**, with the bits and the
   rejected questions in the message;
3. after you tap, the resolution, then the `.ics` as a **file attachment** — tap
   it and your phone's calendar opens with the event.

Notes worth knowing while filming:

- **One question open per chat.** Send a second memo before answering the first
  and the bot tells you to answer or `/cancel`. Finish one thread at a time.
- **`/cancel`** drops a pending question if you fluff a take.
- The bot only answers the chat id you allowlisted; anyone else is refused.

---

## 3. Preflight (only if you decide to deploy)

```bash
uv run 00_check_deploy.py
```

It blocks on an empty `TELEGRAM_ALLOWED_CHAT_IDS` by design — that allowlist is
the only thing keeping the deployment single-tenant. Green means deployable.

---

## The recording, start to finish

Build the take around the [demo arc in CLAUDE.md](CLAUDE.md). A clean run:

1. Send a messy voice memo naming three people, one ambiguous ("the partner from
   Jungle").
2. Show the transcript and the extracted people.
3. **The agent asks its one question — show the bits, and the questions it did
   not ask.** The money shot.
4. Tap the answer; show the resolution land.
5. (Optional) A second memo with a plain promise, to show the `.ics` follow-up.
6. Close on the benchmark table.

The seed (`data/demo_seed.json`) is what makes step 3 possible: on an empty graph
nothing is ambiguous, so the question never fires. The seeded cast — Priya
recorded as "Antler or Jungle, wasn't sure" against Rachel Sim who really is at
Jungle — is what makes "the partner from Jungle" a question the graph honestly
cannot answer.

---

## If you must show it hosted

`render.yaml` ships a free-tier demo config (seed baked in, `.ics` calendar, no
disk). Two spin-down traps to plan around, both from Render's free tier:

- **Using the bot does not keep it awake.** The poller makes *outbound* calls to
  Telegram; Render only resets the idle timer on *inbound* HTTP. The container
  can sleep mid-conversation. Keep it warm for the recording window: point a free
  pinger (cron-job.org) at `/healthz` every ~10 minutes.
- **Cold start is ~30–60s.** Open `/healthz` in a browser and wait for it to
  answer *before* the first memo, so the audience never sees the wait.

Writes during the demo vanish on the next cold start and the seed is restored —
fine for a recording, not for real users. The paid config (persistent disk,
Google Calendar over OAuth) is the commented appendix at the bottom of
`render.yaml`.
