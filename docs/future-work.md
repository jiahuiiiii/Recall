# Future work — cut from scope

**Cite these; do not build them.** Each entry is deliberately out of scope for the
hackathon submission. The prohibition itself lives in `CLAUDE.md` under Non-goals.

- **Unlinked bare-nickname routing (To fix #4).** An extraction flag marking a mention an
  informal label rather than a formal name, so `"big boss"` with no article and no
  descriptor word routes through the capped descriptor channel into the ambiguous band
  instead of filing a duplicate. A `Person` schema change that moves both benchmark
  tables, so batched with the other schema-touching deferrals below. Resolves fine today
  once the nickname is a stored alias; only the unlinked first-sight case fails.
- **Plural-mention expansion.** A phrase naming nobody individually — "the two malaysian
  chinese independent school girls" — yields ONE `Person` today, not two. Real users talk
  this way constantly, so it is a genuine product gap. The fix is to let extraction emit
  N records from one plural phrase (a count + shared descriptor per head), then let each
  land in the resolver independently. Separate feature from EIG, and it changes the
  extraction call, so it re-baselines the tables. See Known limitations.
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
  point. A person is a _cluster of mentions_, not a row that gets overwritten. Every
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
  `user_preference`, `episodic`, custom); AgentCore runs _its own LLM_ over your events
  **asynchronously** into path-like namespaces (`/actor/Jane/`). `retrieve_memories()`
  searches _those_.

What the current implementation gets wrong: it writes a JSON blob via `create_event` and
reads it back with `retrieve_memories` expecting the same JSON; attaches no strategy, so
nothing is extracted; ignores that extraction is async when resolution needs
read-after-write within one run; and uses a namespace that doesn't match the path shape.

**Recommended fix — durable storage, not extraction engine.** Keep our `PersonRecord`
schema and our resolution logic; store records as events and read them back with
`list_events` (synchronous, raw). Optionally _also_ attach a semantic strategy for bonus
fuzzy recall, with local lexical search as fallback.

Setup order: attach `bedrock-agentcore` IAM permissions → `create_memory_and_wait`
(minutes to ACTIVE) → set `AGENTCORE_MEMORY_ID` + `RECALL_MEMORY=agentcore` → rewrite the
backend → test against a throwaway memory resource.
