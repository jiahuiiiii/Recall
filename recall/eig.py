"""Question selection by expected information gain.

When a mention lands in the ambiguous band we do not ask a model "what should I
ask?". We enumerate the candidate identities, enumerate a few questions we could
ask, and compute for each question how much it is expected to reduce our
uncertainty about which identity is right:

    EIG(q) = H(H) - E_a[ H(H | a) ]
           = H(H) - sum_a P(a) * H(H | a)

then take the argmax. Greedy, one step, no lookahead.

**Everything in this module is pure.** No model calls, no I/O, no randomness
except where a baseline explicitly asks for it. That is deliberate: the
selection is the contribution, so it has to be arithmetic that can be
unit-tested and re-derived by hand, not a model's preference on the day.

The model's role is upstream (extracting attributes) and optionally proposing
extra questions. It never chooses.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

# Probability that the user answers a question wrongly — misremembering, or an
# attribute that has changed since. Without it a single unexpected answer drives
# a hypothesis to probability zero and it can never recover, which is both
# brittle and untrue to how people answer.
ANSWER_NOISE = 0.1


@dataclass(frozen=True)
class Hypothesis:
    """One candidate identity for an ambiguous mention.

    `record_id` is "" for the "this is someone new" hypothesis, which must
    always be in the set — it is frequently the right answer and a question that
    cannot distinguish "new" from "known" is a wasted question.
    """

    record_id: str
    name: str
    prior: float


@dataclass(frozen=True)
class Question:
    """A probe, plus what each hypothesis predicts the answer would be.

    `outcomes` maps record_id -> the answer that hypothesis implies. Derived
    mechanically from stored attributes: if Kit Yee is on the 18th floor and
    Crispy on the 4th, "which floor does she live on?" has outcomes
    {kit: "18th", crispy: "4th"}.
    """

    key: str
    text: str
    outcomes: dict[str, str]
    # What the USER could answer, which is not the same as what the hypotheses
    # predict. A yes/no probe always admits "no" even when every candidate on
    # record would say "yes" -- and that "no" is exactly what argues for
    # "someone new". Deriving the answer space from `outcomes` collapses it to a
    # single option in that case, and a question with one possible answer
    # carries no information, so single-candidate ambiguities never got asked.
    answer_space: tuple[str, ...] = ()
    # The recorded fact this probe was derived from, when there is exactly one
    # (yes/no probes). Kept because matching a QUESTION back onto a record has
    # to go through the phrasing -- "lives at the 18th floor" becomes "Do they
    # live at the 18th floor?", which adds "do", loses "at the", and bends
    # "lives" to "live" -- and every one of those costs overlap. Comparing the
    # fact directly is exact where it matters.
    source: str = ""
    # How often the user's answer disagrees with the truth for THIS question.
    # Attributes are not equally dependable: a degree rarely changes, a room
    # changes every semester, and "seemed quiet" is one person's impression on
    # one day. None falls back to the global default.
    noise: float | None = None

    @property
    def answers(self) -> list[str]:
        if self.answer_space:
            return list(self.answer_space)
        return sorted(set(self.outcomes.values()))


def normalise(weights: dict[str, float], temperature: float = 1.0) -> dict[str, float]:
    """Turn raw resolver scores into a prior over hypotheses.

    Softmax rather than plain division because scores can be negative and are
    not on a probability scale. Temperature controls how sharply a small score
    difference becomes a confidence difference.
    """
    if not weights:
        return {}
    top = max(weights.values())
    exps = {k: math.exp((v - top) / max(temperature, 1e-9)) for k, v in weights.items()}
    total = sum(exps.values())
    return {k: v / total for k, v in exps.items()}


def entropy(probs: dict[str, float]) -> float:
    """Shannon entropy in bits. 0 means certain; log2(n) means no idea at all."""
    return -sum(p * math.log2(p) for p in probs.values() if p > 0)


def likelihood(question: Question, hypothesis_id: str, answer: str, noise: float = ANSWER_NOISE) -> float:
    """P(answer | hypothesis).

    The hypothesis predicts one answer; it gets 1 - noise. The remaining mass is
    spread over the other possible answers, so an unexpected answer makes a
    hypothesis unlikely but never impossible.
    """
    noise = question.noise if question.noise is not None else noise
    options = question.answers
    if not options:
        return 0.0
    predicted = question.outcomes.get(hypothesis_id)
    if predicted is None:
        # This hypothesis says nothing about the attribute — most often the
        # "someone new" case. Every answer is equally consistent with it.
        return 1.0 / len(options)
    if len(options) == 1:
        return 1.0
    return (1.0 - noise) if answer == predicted else noise / (len(options) - 1)


def answer_distribution(
    hypotheses: list[Hypothesis], question: Question, noise: float = ANSWER_NOISE
) -> dict[str, float]:
    """P(a) = sum_h P(h) P(a|h) — how likely each answer is before we ask."""
    noise = question.noise if question.noise is not None else noise
    return {
        a: sum(h.prior * likelihood(question, h.record_id, a, noise) for h in hypotheses)
        for a in question.answers
    }


def posterior(
    hypotheses: list[Hypothesis], question: Question, answer: str, noise: float = ANSWER_NOISE
) -> dict[str, float]:
    """Bayes update: P(h | a) after hearing `answer`."""
    noise = question.noise if question.noise is not None else noise
    joint = {
        h.record_id: h.prior * likelihood(question, h.record_id, answer, noise)
        for h in hypotheses
    }
    total = sum(joint.values())
    if total <= 0:
        return {h.record_id: h.prior for h in hypotheses}
    return {k: v / total for k, v in joint.items()}


def expected_information_gain(
    hypotheses: list[Hypothesis], question: Question, noise: float = ANSWER_NOISE
) -> float:
    """Bits of uncertainty this question is expected to remove.

    Never negative in exact arithmetic — information cannot be expected to make
    you less sure — so a negative result means a bug, not a bad question.

    This is where EIG and uncertainty sampling part company. Uncertainty
    sampling asks whatever is least predictable; a question about an
    undependable attribute is unpredictable precisely BECAUSE the answer means
    little, and it will happily spend the one question there. EIG divides out
    that unreliability and asks what actually resolves.
    """
    noise = question.noise if question.noise is not None else noise
    # Renormalise defensively. Passing a subset of hypotheses is an easy
    # mistake, and entropy over weights that do not sum to 1 is meaningless --
    # it silently returns a plausible-looking number instead of failing.
    hypotheses = _renormalised(hypotheses)
    prior = {h.record_id: h.prior for h in hypotheses}
    before = entropy(prior)
    after = sum(
        p_a * entropy(posterior(hypotheses, question, a, noise))
        for a, p_a in answer_distribution(hypotheses, question, noise).items()
        if p_a > 0
    )
    return before - after


def _renormalised(hypotheses: list[Hypothesis]) -> list[Hypothesis]:
    total = sum(h.prior for h in hypotheses)
    if total <= 0 or abs(total - 1.0) < 1e-9:
        return hypotheses
    return [Hypothesis(h.record_id, h.name, h.prior / total) for h in hypotheses]


@dataclass(frozen=True)
class Scored:
    question: Question
    eig: float


def rank_questions(
    hypotheses: list[Hypothesis], questions: list[Question], noise: float = ANSWER_NOISE
) -> list[Scored]:
    """All questions scored, best first. The demo shows the ones NOT chosen."""
    scored = [Scored(q, expected_information_gain(hypotheses, q, noise)) for q in questions]
    return sorted(scored, key=lambda s: (-s.eig, s.question.key))


def select(
    hypotheses: list[Hypothesis], questions: list[Question], noise: float = ANSWER_NOISE
) -> Scored | None:
    """The one question to ask. Argmax of EIG."""
    ranked = rank_questions(hypotheses, questions, noise)
    return ranked[0] if ranked else None


# --------------------------------------------------------------------------
# Baselines. The claim is that EIG beats these; they have to be implemented
# honestly rather than strawmanned.
# --------------------------------------------------------------------------


def select_random(questions: list[Question], rng: random.Random) -> Question | None:
    """Pick uniformly. The floor any strategy has to clear."""
    return rng.choice(questions) if questions else None


def select_by_uncertainty(
    hypotheses: list[Hypothesis], questions: list[Question], noise: float = ANSWER_NOISE
) -> Question | None:
    """Uncertainty sampling: ask whatever you can least predict the answer to.

    The standard active-learning baseline, adapted to question choice — pick the
    query with the most uncertain outcome, argmax H(P(a)), without modelling
    what the answer would then teach you.

    It is a genuine strategy and often close to EIG, which is what makes it the
    interesting comparison. The difference is that EIG weighs how much each
    possible answer would *resolve*, while this only asks how surprising the
    answer will be. They coincide on symmetric cases and diverge when the
    hypotheses have unequal priors.
    """
    if not questions or not hypotheses:
        return None
    hypotheses = _renormalised(hypotheses)
    return max(
        questions,
        key=lambda q: (entropy(answer_distribution(hypotheses, q, noise)), q.key),
    )
