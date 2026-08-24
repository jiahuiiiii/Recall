"""EIG vs the baselines, played against a simulated answerer.

The claim is that choosing questions by expected information gain resolves an
ambiguous mention in fewer questions than the alternatives. To measure that we
need three things, and the honesty of the result depends on all three:

1. **A case with a known answer.** The band must be uncertain while the fixture
   holds the truth. A mention labelled UNRESOLVED cannot be scored -- nothing
   converges, so every strategy ties at infinity and the comparison says nothing.
2. **A simulated user** who answers from the gold person's record, the way the
   real user would. Answers carry the same noise the model assumes.
3. **The same candidate questions for every strategy.** Otherwise the comparison
   is of question generation, not of selection -- and selection is the claim.

A tie is a legitimate result and gets reported as one. Tuning until EIG wins
would make the number worthless.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from recall.eig import (
    Hypothesis,
    Question,
    normalise,
    posterior,
    rank_questions,
    select_by_uncertainty,
    select_random,
)
from recall.questions import SAME_FACT, SOMETHING_ELSE, derive
from recall.text import overlap_ratio, tokens

# Stop asking once one hypothesis is this likely. Matches the point at which a
# person would stop wanting to be quizzed.
CONFIDENT = 0.9

# Hard cap. Without it a strategy that keeps choosing uninformative questions
# runs forever; with it, "did not resolve" is a reportable outcome.
MAX_QUESTIONS = 5

# How much of an offered value has to appear in the gold record before the
# simulated user claims it. Below this they say "something else", which is the
# honest answer and the one that argues for a person we have not met.
VALUE_MATCH = 0.6


@dataclass
class Trial:
    strategy: str
    resolved: bool
    correct: bool
    questions_asked: int
    asked: list[str]


def truthful_answer(question: Question, gold_record: dict) -> str:
    """What the user would say, given who they actually meant.

    Answers from the gold person's own record rather than from the hypothesis
    set, so the simulated user is not simply confirming the system's guess.

    Multi-valued probes are answered by naming the value the gold record holds,
    falling back to "something else" when it holds none of the offered values.
    Answering a multi-valued question yes/no would be worse than a bug: the
    answer is outside the question's answer space, so every hypothesis scores as
    having predicted wrongly and the update is noise. EIG would be credited or
    blamed for arithmetic that never ran.
    """
    fact_tokens = [tokens(f) for f in _facts(gold_record)]
    if _is_multivalued(question):
        return _matching_value(question, fact_tokens)

    # SAME_FACT, and the question's source fact rather than its text. Both
    # matter, and the old loose match on the phrased question was wrong in the
    # direction that flatters every strategy equally and so hides itself: at
    # 0.55, "Do they live at the 18th floor?" scored 0.583 against "lives on the
    # 4th floor" and the simulated user said yes. The person on the 4th floor
    # was confirming the 18th, every strategy was updating on a lie, and the
    # table still looked reasonable.
    probe = tokens(question.source or question.text)
    if any(overlap_ratio(probe, key_tokens) >= SAME_FACT for key_tokens in fact_tokens):
        return "yes"
    return "no"


def _is_multivalued(question: Question) -> bool:
    return set(question.answers) != {"yes", "no"}


def _matching_value(question: Question, fact_tokens: list[set[str]]) -> str:
    """Which offered value the gold record actually holds.

    Scored rather than first-match: "computer science" and "geospatial
    intelligence" can both partially match a note, and taking whichever came
    first alphabetically would hand the strategies a coin flip dressed as data.
    """
    best, score = SOMETHING_ELSE, 0.0
    for value in question.answers:
        if value == SOMETHING_ELSE:
            continue
        value_tokens = tokens(value)
        if not value_tokens:
            continue
        hit = max((overlap_ratio(value_tokens, f) for f in fact_tokens), default=0.0)
        if hit >= VALUE_MATCH and hit > score:
            best, score = value, hit
    return best


def _facts(record: dict) -> list[str]:
    out = []
    if record.get("company"):
        out.append(str(record["company"]))
    if record.get("role"):
        out.append(str(record["role"]))
    out += [str(m) for m in record.get("met_at") or []]
    out += [str(n) for n in record.get("notes") or []]
    return out


def play(
    strategy: str,
    hypotheses: list[Hypothesis],
    records: dict[str, dict],
    gold_record_id: str,
    rng: random.Random,
    max_questions: int = MAX_QUESTIONS,
) -> Trial:
    """Ask until confident or out of budget. Returns what it cost."""
    beliefs = {h.record_id: h.prior for h in hypotheses}
    pool = derive(hypotheses, records)
    gold_record = records.get(gold_record_id, {})
    asked: list[str] = []

    for _ in range(max_questions):
        leader, confidence = max(beliefs.items(), key=lambda kv: kv[1])
        if confidence >= CONFIDENT:
            break
        remaining = [q for q in pool if q.text not in asked]
        if not remaining:
            break

        current = [Hypothesis(k, records.get(k, {}).get("name", "someone new"), v)
                   for k, v in beliefs.items()]
        question = _choose(strategy, current, remaining, rng)
        if question is None:
            break

        asked.append(question.text)
        answer = truthful_answer(question, gold_record)
        beliefs = posterior(current, question, answer)

    leader, confidence = max(beliefs.items(), key=lambda kv: kv[1])
    resolved = confidence >= CONFIDENT
    return Trial(
        strategy=strategy,
        resolved=resolved,
        correct=resolved and leader == gold_record_id,
        questions_asked=len(asked),
        asked=asked,
    )


def _choose(
    strategy: str, hypotheses: list[Hypothesis], pool: list[Question], rng: random.Random
) -> Question | None:
    if strategy == "eig":
        ranked = rank_questions(hypotheses, pool)
        return ranked[0].question if ranked else None
    if strategy == "random":
        return select_random(pool, rng)
    if strategy == "uncertainty":
        return select_by_uncertainty(hypotheses, pool)
    raise ValueError(f"unknown strategy: {strategy}")


def build_hypotheses(entry: dict) -> list[Hypothesis]:
    """Turn a band entry's scores into a prior over identities."""
    prior = normalise({h["record_id"]: float(h["score"]) for h in entry["hypotheses"]})
    return [Hypothesis(h["record_id"], h["name"], prior[h["record_id"]])
            for h in entry["hypotheses"]]
