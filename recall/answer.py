"""Turning the user's answer back into a resolution.

`ask_node` chooses a question; this decides what the answer *means*. Kept
separate and pure for the same reason `eig` and `resolve` are: the path from
"human said computer science" to "this is Crispy" is arithmetic, and arithmetic
should be unit-testable without a graph, a checkpointer or a model.

The update is Bayes, using the same likelihood the question was scored with.
That matters more than it looks. If EIG scored a question under one noise model
and the answer were then applied under another -- say, by taking whichever
hypothesis "matches" the answer text -- the bits it promised would not be the
bits it delivered, and the headline claim would be measuring something the
system does not actually do.

**One question per memo.** After a single answer we take the argmax and record
how confident it leaves us, rather than asking again until certain. The budget
is the user's attention, not the arithmetic's appetite.
"""

from __future__ import annotations

from dataclasses import dataclass

from recall.eig import Hypothesis, Question, entropy, posterior

# Below this, the answer moved belief but did not settle it. We still act on the
# argmax -- refusing to decide helps nobody -- but the caller is told, so the UI
# can say "probably" instead of asserting, and the record can be revisited.
CONFIDENT = 0.75


@dataclass(frozen=True)
class Resolution:
    """What one answer settled.

    `record_id` is "" for "this is someone new", which is a real answer and not
    a failure -- it is frequently correct, and a system that cannot conclude it
    will merge strangers into acquaintances forever.
    """

    record_id: str
    name: str
    confidence: float
    confident: bool
    posterior: dict[str, float]
    bits_remaining: float
    answer: str


def resolve_with_answer(
    hypotheses: list[Hypothesis], question: Question, answer: str
) -> Resolution | None:
    """Apply one answer and report which identity it leaves in front.

    `None` when there is nothing to decide over. An answer outside the
    question's answer space is passed through to the update untouched: the
    likelihood already treats an unpredicted answer as evidence against every
    hypothesis that predicted otherwise, which is the honest reading of "the
    user said something none of these people would have said".
    """
    if not hypotheses:
        return None

    beliefs = posterior(hypotheses, question, answer)
    if not beliefs:
        return None

    names = {h.record_id: h.name for h in hypotheses}
    # Ties break toward the hypothesis with the higher prior, then by id, so the
    # same answer always produces the same resolution. A demo that resolves to a
    # different person on the second run of the same input is unusable.
    priors = {h.record_id: h.prior for h in hypotheses}
    winner = max(beliefs, key=lambda k: (beliefs[k], priors.get(k, 0.0), k))
    confidence = beliefs[winner]

    return Resolution(
        record_id=winner,
        name=names.get(winner, "someone new"),
        confidence=round(confidence, 4),
        confident=confidence >= CONFIDENT,
        posterior={k: round(v, 4) for k, v in beliefs.items()},
        bits_remaining=round(entropy(beliefs), 4),
        answer=answer,
    )


def rebuild_question(payload: dict) -> Question:
    """Reconstruct the Question a stored `state["question"]` describes.

    The graph resumes by re-executing the node from the top, so in the normal
    path the Question object is simply derived again. This exists for the other
    path -- a resolution applied outside the graph, from what the UI was handed
    -- and pins that both routes score the answer with the same object.
    """
    return Question(
        key=payload.get("key", "resumed"),
        text=payload.get("question", ""),
        outcomes=dict(payload.get("outcomes") or {}),
        answer_space=tuple(payload.get("answers") or ()),
        noise=payload.get("noise"),
    )


def rebuild_hypotheses(payload: dict) -> list[Hypothesis]:
    """The hypothesis set a stored `state["question"]` describes."""
    return [
        Hypothesis(h.get("record_id", ""), h.get("name", ""), float(h.get("prior", 0.0)))
        for h in payload.get("hypotheses") or []
    ]
