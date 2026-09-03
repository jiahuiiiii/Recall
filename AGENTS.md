# AGENTS.md

**The project instructions live in [CLAUDE.md](CLAUDE.md). Read that file, not this one.**

Everything that was here — status, benchmark tables, known limitations, hard-won
findings, conventions — is in CLAUDE.md, kept current in one place.

## Why this is a pointer

This file used to be a near-copy of CLAUDE.md for a different agent. The two drifted:
by 2 Sep 2026 this copy still claimed 311 tests, a headline benchmark at n=2, and
uncommitted fixtures — all three wrong, and all three already corrected in CLAUDE.md.

Two documents describing one project will always diverge, and the stale one is
indistinguishable from the current one until you check a number against the code. One
source of truth, and a pointer to it.

**Do not re-fork this file.** If something needs saying to agents, say it in CLAUDE.md.

## The short version

Enough to avoid the expensive mistakes before you have read CLAUDE.md in full.

**Recall** — a voice-first relationship-memory agent. You record a messy ~90-second memo
after an event; it extracts the people mentioned, resolves them against people it already
knows **while holding uncertainty explicitly**, and asks **one** clarifying question when
a mention is genuinely ambiguous. SimplifyNext Agentic AI hackathon, submission
**7 Sep 2026**.

The one defensible claim is **question selection by expected information gain** — we
compute `EIG(q) = H(H) − E_a[H(H|a)]` and take the argmax, rather than asking a model
what to ask. The headline deliverable is a benchmark table, not a UI. If a change would
weaken that, stop and flag it.

Hard rules, each with a section in CLAUDE.md that explains why:

- **Never run test memos against the user's live person graph.** Set
  `RECALL_STORE_PATH`, `RECALL_CALENDAR_PATH` and `RECALL_RELATIONS_PATH` to scratch
  paths for any throwaway run. This has gone wrong twice and it looks like the model
  hallucinating facts the user never said.
- **`uv`, never bare pip.** `uv sync`, `uv run <script>`.
- **Run `uv run pytest tests/ -q` before anything that spends AWS money.** 312 tests,
  offline, no credentials.
- **Default to no on new features.** See *Non-goals* — no facial recognition, no
  auto-sending, no new calendar/email/LinkedIn work, and do not extend the frozen
  enrichment/drafts/calendar tail.
- **`temperature=0` is not determinism.** Bedrock returns different extractions for the
  same input. Report variance; never build a demo that needs identical output twice.
- **Verify against the installed SDK or a real call, not memory.** A single probe is not
  proof — this project has been bitten by that twice.

Everything else — the current numbers, the three guards, the fixture labelling rules, the
AWS situation on this account, and the findings that cost real debugging time — is in
[CLAUDE.md](CLAUDE.md).
