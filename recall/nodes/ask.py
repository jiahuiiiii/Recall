"""Pick the one question to ask about this memo.

Runs after resolution. It does not answer anything and does not change the
person graph — it selects, and records what it selected along with what it
rejected and why.

Two rules from the spec, both enforced here:

- **One question per memo.** Asking costs the user attention; the budget is 1.
  When several mentions are ambiguous we ask about the one where an answer buys
  the most information, measured in bits, not the first one encountered.
- **Selection is arithmetic.** The candidate questions come from stored
  attributes (`recall.questions`) and the choice is an argmax over expected
  information gain (`recall.eig`). No model is consulted about what to ask.

The rejected questions are kept in state on purpose: showing that the agent
considered "same school as you?" and measured it at 0.000 bits is what
demonstrates the selection is computed rather than tasteful.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage
from langgraph.types import interrupt

from recall.answer import resolve_with_answer
from recall.eig import Hypothesis, entropy, normalise, rank_questions
from recall.memory import get_store
from recall.questions import derive, needs_model
from recall.state import RecallState, is_interactive

# Softmax temperature turning resolver scores into a prior. Around 1.0 a
# one-point score gap becomes a clear favourite; much lower and near-ties look
# like certainties, which would suppress questions we should be asking.
PRIOR_TEMPERATURE = 1.0


def _spread(rest, near: int = 3, worst: int = 2) -> list[dict]:
    """Runners-up plus the least informative options, deduplicated."""
    picked = list(rest[:near])
    for s in reversed(rest[-worst:] if len(rest) > near else []):
        if all(s.question.key != p.question.key for p in picked):
            picked.append(s)
    # Descending, even though the selection is "best few plus worst few". A list
    # that jumps 0.669 -> 0.063 -> 0.300 reads as unsorted noise; the whole point
    # is that a viewer can see the numbers fall away.
    return [_shown(s) for s in sorted(picked, key=lambda s: -s.eig)]


def _shown(scored) -> dict:
    """One question as the demo surface renders it.

    `answers` is carried for every question, not just the chosen one: the
    contrast the demo rests on is partly a contrast of shape -- the rejected
    yes/no probe next to the chosen multi-valued one, with the bits beside each
    -- and that is invisible if only the text and the number are shown.
    """
    return {
        "question": scored.question.text,
        "eig": round(scored.eig, 4),
        "answers": list(scored.question.answer_space),
        "kind": "multi" if len(scored.question.answer_space) > 2 else "binary",
    }


def ask_node(state: RecallState, config=None) -> dict:
    """Choose at most one question, and — if a human is reachable — ask it.

    Two modes, and the difference is whether anything is listening:

    - **Non-interactive** (CLI, eval, tests): select the question and record it.
      The mention was already placed by `dedupe_node`'s adjudicator. Nothing
      pauses, nothing is answered; the question is a read-out.
    - **Interactive** (the web UI): `dedupe_node` HELD every ambiguous mention,
      so this node must place all of them. It asks about the one worth the most
      bits, pauses on `interrupt()`, and resolves that mention from the answer.
      The rest fall back to the adjudicator's verdict, carried on the entry.

    **This node re-executes from the top when the graph resumes** — that is how
    LangGraph's `interrupt()` works, not an accident. Everything above the
    `interrupt()` call therefore has to be pure and repeatable, and nothing may
    be written to the store before it. Reading the store and computing EIG is
    safe; persisting is not, which is why placement happens after.
    """
    ambiguous = state.get("ambiguous") or []
    interactive = is_interactive(config)
    if not ambiguous:
        return {"question": None}

    store = get_store()
    best: dict | None = None
    best_entry: dict | None = None

    for entry in ambiguous:
        hypotheses = [
            Hypothesis(h["record_id"], h["name"], 0.0) for h in entry["hypotheses"]
        ]
        prior = normalise(
            {h["record_id"]: float(h["score"]) for h in entry["hypotheses"]},
            temperature=PRIOR_TEMPERATURE,
        )
        hypotheses = [Hypothesis(h.record_id, h.name, prior[h.record_id]) for h in hypotheses]

        records = {
            h.record_id: rec
            for h in hypotheses
            if h.record_id and (rec := store.get(h.record_id)) is not None
        }
        candidates = derive(hypotheses, records)
        if needs_model(candidates):
            # Attributes cannot separate these hypotheses. A model-proposed
            # question is the documented fallback; until it exists, skip rather
            # than ask something uninformative.
            continue

        ranked = rank_questions(hypotheses, candidates)
        if not ranked or ranked[0].eig <= 0:
            continue

        proposal = {
            "mention": entry["person"].get("name", ""),
            **_shown(ranked[0]),
            # The bits still on the table after this answer. A question is not
            # good in the abstract -- it is good relative to how uncertain we
            # were, and 0.8 bits against a 1.27-bit prior is a different claim
            # from 0.8 against 3.0.
            "prior_entropy": round(entropy({h.record_id: h.prior for h in hypotheses}), 4),
            "hypotheses": [
                {"record_id": h.record_id, "name": h.name, "prior": round(h.prior, 4)}
                for h in hypotheses
            ],
            # The ones it did NOT ask, with their measured value -- the evidence
            # that the choice was computed. Deliberately the next-best few AND
            # the worst: with two candidates every discriminating question ties,
            # so a plain top-N shows five identical numbers and no contrast. The
            # cheap question worth 0.000 bits is the one that makes the point.
            "rejected": _spread(ranked[1:]),
            "outcomes": ranked[0].question.outcomes,
        }
        proposal["_question"] = ranked[0].question
        if best is None or proposal["eig"] > best["eig"]:
            best, best_entry = proposal, entry

    if best is None:
        # Nothing worth asking. Held mentions still need a home.
        return {"question": None, **_place(state, ambiguous, None, None, interactive)}

    question = best.pop("_question")
    for entry in ambiguous:
        entry.pop("_question", None)

    if not interactive:
        # Nobody to ask. `dedupe_node` already placed everything.
        return {
            "question": best,
            "messages": [AIMessage(
                content=f'Question ({best["eig"]:.3f} bits) about "{best["mention"]}": '
                        f'{best["question"]}')],
        }

    # ---- the pause ----
    # Everything above this line is pure and will run again on resume.
    answer = interrupt({"type": "question", **best})
    answer = str(answer).strip() if answer is not None else ""

    hypotheses = [Hypothesis(h["record_id"], h["name"], h["prior"])
                  for h in best["hypotheses"]]
    resolution = resolve_with_answer(hypotheses, question, answer)

    placed = _place(state, ambiguous, best_entry, resolution, interactive)
    settled = resolution.name if resolution else "nothing"
    return {
        "question": best,
        "resolution": _as_dict(resolution, best["mention"]),
        "messages": [AIMessage(
            content=f'Asked "{best["question"]}" -> {answer!r} -> {settled} '
                    f'({resolution.confidence:.0%} confident)' if resolution
            else f'Asked "{best["question"]}" -> {answer!r} -> unresolved')],
        **placed,
    }


def _as_dict(resolution, mention: str) -> dict | None:
    if resolution is None:
        return None
    return {
        "mention": mention,
        "answer": resolution.answer,
        "record_id": resolution.record_id,
        "name": resolution.name,
        "confidence": resolution.confidence,
        # Surfaced rather than hidden. One answer does not always settle a
        # three-way tie, and a UI that asserts "this is Crispy" at 46% belief is
        # lying in exactly the way the three-zone band exists to prevent.
        "confident": resolution.confident,
        "posterior": resolution.posterior,
        "bits_remaining": resolution.bits_remaining,
    }


def _place(state: RecallState, ambiguous: list[dict], asked: dict | None,
           resolution, interactive: bool) -> dict:
    """Route held mentions into `new_people` / `known_matches`.

    A no-op unless the run is interactive: only then did `dedupe_node` hold
    these people back. On any other run the lists already contain them and
    re-adding would duplicate the record.

    The mode is passed in rather than inferred from whether a person is already
    in the lists. Inferring it by name is tempting and wrong -- `same_first_name`
    is an entire fixture scenario built on two different people sharing a name,
    and the one place that must never confuse them is the resolver.

    The mention we asked about is placed by the human's answer. The others are
    placed by the adjudicator's verdict, carried on the entry as `fallback`: the
    one-question budget means most ambiguities never get asked about, and
    dropping them would silently lose people from the memo.
    """
    if not interactive:
        return {}

    new_people = list(state.get("new_people") or [])
    known_matches = list(state.get("known_matches") or [])

    for entry in ambiguous:
        person = entry.get("person", {})

        if asked is not None and entry is asked and resolution is not None:
            entry["resolved_to"] = resolution.record_id or None
            entry["answered"] = True
            if resolution.record_id:
                known_matches.append(_match_from(entry, resolution))
            else:
                new_people.append(person)
            continue

        fallback = entry.get("fallback")
        if fallback:
            known_matches.append(fallback)
        else:
            new_people.append(person)

    return {"new_people": new_people, "known_matches": known_matches,
            "ambiguous": ambiguous}


def _match_from(entry: dict, resolution) -> dict:
    """A `KnownMatch` built from the human's answer rather than a model's guess."""
    fallback = entry.get("fallback") or {}
    return {
        **fallback,
        "person": entry.get("person", {}),
        "record_id": resolution.record_id,
        "confidence": resolution.confidence,
        "reasoning": f'answered "{resolution.answer}" to the clarifying question',
    }
