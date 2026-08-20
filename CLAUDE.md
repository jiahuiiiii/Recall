# CLAUDE.md

## What we're building

**Recall** — a relationship-capture agent. You talk into your phone after an event
("met Wei Lin from GIC, she's hiring for a quant infra role, said I'd send her the
Kestrel repo"), and the agent turns that into structured, deduped, enriched contact
notes, drafts your follow-ups, and puts commitments on your calendar.

The point is that this is **agentic**, not a transcription-plus-database toy. The
demo has to _visibly_ exercise orchestration, tool use, memory, and conditional
routing — that's what the track is scored on (tool access + orchestration + autonomy,
not model capability). If a change makes the agent loop thinner, push back.

This is a SimplifyNext Agentic AI hackathon project. Stack is fixed by the track:
Bedrock + LangGraph + DeepAgents/Claude Agent SDK + AgentCore + MCP.

## Pipeline (this is the whole thing)

```
voice memo
  → transcribe (Groq Whisper — audio is NOT a Bedrock capability, keep it a tool)
  → extract_people        (structured output: who, where met, raw notes)
  → dedupe                (RAG over stored notes) ──► conditional edge
        │ new person                                   │ known person
        ▼                                              ▼
     enrich (sub-agent, web tool)                  merge into existing record
        └──────────────┬───────────────────────────────┘
                       ▼
     extract_commitments + draft_followups (sub-agent)
                       ▼
     calendar_write (MCP)  →  persist to memory  →  return summary
```

The **dedupe → new/known** conditional edge and the **enrich** + **drafter**
sub-agents are the load-bearing agentic parts. Do not collapse them into one prompt.

## Architecture rules

- **Supervisor + sub-agents.** The main graph orchestrates. `enricher` (web/browser
  tool, "return concise facts only") and `drafter` (writes in the user's voice) run
  as isolated sub-agents so raw web results and trial-and-error don't pollute the
  main context. This is the Deep Agent supervisor pattern — keep it.
- **State is the single source of truth.** One `TypedDict`. Heavy payloads
  (full transcript, raw enrichment results) live in state; prompts carry references,
  not the blobs. Fields roughly: `messages`, `transcript`, `people`,
  `new_people` / `known_matches`, `enrichments`, `commitments`, `drafts`,
  `calendar_events`.
- **Nodes return partial updates only** — just the keys that changed. An unmatched
  key is dropped silently, so field names must match the schema exactly.
- **Memory is the demo.** AgentCore Memory (long-term) holds the person graph across
  sessions; that's what makes dedupe possible and what proves the agent "remembers."
  For local dev before deploy, a simple local vector store is fine — keep the
  interface swappable.

## Stack conventions (from the hackathon repo — follow these)

- **Package manager is `uv`, never bare pip.** `uv sync`, `uv run <script>`.
- **Models via `chat_model()` from `_common`** — don't hardcode client classes.
- **Bedrock model default: Claude Haiku 4.5** —
  `global.anthropic.claude-haiku-4-5-20251001-v1:0`. Haiku is the default for
  everything. Only reach for Sonnet if Haiku is _measurably_ wrong on a step, and
  say why in a comment. Opus is out for a hackathon budget.
- **Structured output via `with_structured_output(PydanticModel)`**, not
  "reply in JSON" prompting. The model wraps JSON in a code fence eventually and
  `json.loads` dies. Typed object in, typed object out.
- **`temperature=0` for all extraction/dedupe/routing.** Sampling is for the drafter
  only, and even there keep it low.
- **Tool docstrings are the prompt.** The model picks tools off the docstring, not
  the code. A vague docstring is the #1 cause of the wrong tool firing. Write them
  like prompts.
- **Tool errors return as `ToolMessage`, never raise.** Missing tool or bad args →
  write the error into the result and append it. The model reads what broke and
  self-corrects on the next step. The step cap is the safety net, not exceptions.

## Commands

```bash
uv sync --extra aws
uv run 00_check_bedrock.py     # must print OK before every Bedrock lab/run

# AgentCore lifecycle (section 6 pattern)
uv run 01_run_local.py         # localhost:8080, FREE — always test here first
uv run 02_deploy.py            # configure + launch, BILLABLE from here
uv run 04_call_agent.py        # hit the live endpoint
uv run 03_teardown.py          # tears down runtime — run this when done
```

## Bedrock / AWS gotchas (these eat hours)

- `body` on `invoke_model` is a **JSON string**, not a dict. The response `body` is a
  **stream you can read once** — read it into a var immediately.
- **`finish_reason == "length"` means the reply is cut**, not that the model failed.
  Truncated JSON looks like a model bug but it's the token ceiling. Check it.
- **Region is set twice** (SSO region vs. CLI default client region). Bedrock follows
  the CLI default — `ap-southeast-1`. A blank one is why it works for one person and
  404s for another.
- **SSO login expires every 8–12h.** Day 2 starts with `aws sso login --profile workshop`.
- **Model access is per-model, per-region, off by default.** Haiku 4.5 must be
  enabled in the Bedrock console for `ap-southeast-1`. Valid creds ≠ working call.
- **AgentCore teardown is incomplete** — `destroy` leaves S3 / ECR / CloudWatch behind.
  Don't assume billing stopped.

## Cost discipline

- Haiku is $1/$5 per M tokens (in/out); an agent loop calls the model 5–15× per task
  and resends the whole history each step, so **log `usage` per call** and keep it
  visible. Cost is measured per prompt, not discovered at month-end.
- The system prompt is resent every step — **prompt-cache it** (it's >1k tokens once
  the sub-agent instructions are in). Up to ~90% off cache reads.
- Reach for few-shot / heavier prompting **only after** the zero-shot version is shown
  to fail — every example is paid on every step.

## Integrations

- **Transcription:** Groq `whisper-large-v3` (free tier, fast). Bedrock/Claude can't
  take audio — keep transcription a discrete tool at the front of the graph.
- **Calendar:** Google Calendar MCP for writing commitment follow-ups. Guard against
  duplicate events on re-runs (idempotency key off the commitment text).
- **Enrichment:** web/browser tool inside the `enricher` sub-agent only.

## Priorities (rank order — use this to break ties)

1. **Demo-ability in the window.** Every feature must be showable live by 7 Sep.
   If it can't be demoed, it doesn't exist. Cut ruthlessly toward a clean 3-min run.
2. **Real pain, real data.** The person graph and commitments must feel real in the
   demo, not lorem-ipsum.
3. **Novelty** — the enrich + auto-follow-up loop is the differentiator vs. "notes app."
4. **Infra polish** — clean state design, cost logging, graceful tool failures.

## Dates

- Solution submission: **7 Sep 2026**
- Semi-finals: **9–11 Sep 2026**
- Grand finale: **18 Sep 2026 @ NUS**

## Do / Don't for Claude Code

- **Do** default to Haiku, `uv run`, typed structured output, and `ToolMessage` error
  handling.
- **Do** run `01_run_local.py` before anything that spends AWS money.
- **Don't** add a framework, technique, or sub-agent unless the simpler version has
  demonstrably failed — justify the cost in a comment.
- **Don't** flatten the graph. The conditional routing and sub-agents _are_ the score.
- **Don't** leave AgentCore running after a test session.
