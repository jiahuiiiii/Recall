"""The simulated user the benchmark plays against.

This is the piece that decides whether the headline table means anything. The
strategies are compared on how many questions they need; if the answerer replies
with something outside a question's answer space, every hypothesis scores as
having predicted wrongly, the Bayes update is noise, and EIG gets credited or
blamed for arithmetic that never ran. So the answerer is tested directly.
"""

from __future__ import annotations

import random

from eval.strategies import build_hypotheses, play, truthful_answer
from recall.eig import Hypothesis, Question
from recall.questions import SOMETHING_ELSE, derive

KIT = {"id": "p_kit", "name": "Kit Yee", "met_at": ["Acacia orientation camp"],
       "notes": ["lives at the 18th floor", "studies geospatial intelligence at NUS"]}
CRISPY = {"id": "p_cri", "name": "Crispy", "met_at": [],
          "notes": ["lives on the 4th floor", "studies computer science at NUS"]}
RECORDS = {"p_kit": KIT, "p_cri": CRISPY}
HYPS = [Hypothesis("p_kit", "Kit Yee", 0.47),
        Hypothesis("p_cri", "Crispy", 0.47),
        Hypothesis("", "someone new", 0.06)]


def _multivalued(text_contains: str) -> Question:
    hits = [q for q in derive(HYPS, RECORDS)
            if len(q.answer_space) > 2 and text_contains in q.text.lower()]
    assert len(hits) == 1, [q.text for q in hits]
    return hits[0]


def test_a_multivalued_question_is_answered_with_a_value_not_yes_or_no():
    q = _multivalued("study")
    assert truthful_answer(q, KIT) == "geospatial intelligence"
    assert truthful_answer(q, CRISPY) == "computer science"


def test_every_answer_lands_inside_the_question_answer_space():
    """The invariant the whole benchmark rests on."""
    for q in derive(HYPS, RECORDS):
        for record in (KIT, CRISPY, {}):
            assert truthful_answer(q, record) in q.answers


def test_a_record_holding_none_of_the_offered_values_says_something_else():
    """Which is the answer that argues for a person we have not met -- the
    honest outcome, and the one a closed answer space cannot express."""
    stranger = {"id": "p_x", "name": "X", "met_at": [], "notes": ["studies law at SMU"]}
    assert truthful_answer(_multivalued("study"), stranger) == SOMETHING_ELSE


def test_yes_no_questions_still_get_yes_or_no():
    binary = next(q for q in derive(HYPS, RECORDS)
                  if len(q.answer_space) == 2 and "18th floor" in q.text)
    assert truthful_answer(binary, KIT) == "yes"
    assert truthful_answer(binary, CRISPY) == "no"


def test_eig_resolves_the_right_person_from_a_multivalued_answer():
    """End to end through the strategy loop: ask, answer, update, converge."""
    trial = play("eig", HYPS, RECORDS, "p_cri", random.Random(0))
    assert trial.resolved and trial.correct
    assert trial.questions_asked >= 1


def test_a_multivalued_answer_settles_it_in_one_question():
    """The point of the attribute probe. A yes/no chain needs a confirmation
    round; naming the value does not."""
    trial = play("eig", HYPS, RECORDS, "p_kit", random.Random(0))
    assert trial.correct
    assert trial.questions_asked == 1


def test_build_hypotheses_makes_a_prior_that_sums_to_one():
    entry = {"hypotheses": [{"record_id": "p_kit", "name": "Kit Yee", "score": 2.5},
                            {"record_id": "p_cri", "name": "Crispy", "score": 2.4},
                            {"record_id": "", "name": "someone new", "score": 0.0}]}
    hyps = build_hypotheses(entry)
    assert abs(sum(h.prior for h in hyps) - 1.0) < 1e-9
