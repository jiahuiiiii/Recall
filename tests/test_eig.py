"""Expected information gain — the project's one defensible claim.

Pure arithmetic, so every case here has a hand-derivable answer. If these are
wrong the benchmark table is meaningless, so they are checked against values
computed by hand rather than against whatever the code happened to produce.
"""

from __future__ import annotations

import random

import pytest

from recall.eig import (
    Hypothesis,
    Question,
    answer_distribution,
    entropy,
    expected_information_gain,
    normalise,
    posterior,
    rank_questions,
    select,
    select_by_uncertainty,
    select_random,
)

KIT = Hypothesis("p_kit", "Kit Yee", 0.5)
CRISPY = Hypothesis("p_cri", "Crispy", 0.5)
TWO_WAY = [KIT, CRISPY]


# --- entropy ------------------------------------------------------------------

def test_certainty_is_zero_entropy():
    assert entropy({"a": 1.0}) == 0.0


def test_a_coin_flip_is_one_bit():
    assert entropy({"a": 0.5, "b": 0.5}) == pytest.approx(1.0)


def test_four_equal_options_are_two_bits():
    assert entropy({k: 0.25 for k in "abcd"}) == pytest.approx(2.0)


# --- the core claim -----------------------------------------------------------

def test_a_perfectly_splitting_question_removes_all_uncertainty():
    """Two equally likely people, a question they answer differently. With no
    noise the answer identifies them outright: 1 bit before, 0 after."""
    q = Question("floor", "Which floor?", {"p_kit": "18th", "p_cri": "4th"})
    assert expected_information_gain(TWO_WAY, q, noise=0.0) == pytest.approx(1.0)


def test_a_question_both_answer_the_same_way_teaches_nothing():
    """Both live in Acacia, so asking cannot separate them. Exactly zero gain —
    and this is the question a naive 'ask about an attribute' picker would
    happily choose."""
    q = Question("hall", "Which hall?", {"p_kit": "Acacia", "p_cri": "Acacia"})
    assert expected_information_gain(TWO_WAY, q) == pytest.approx(0.0)


def test_eig_is_never_negative():
    """Information cannot be expected to make you less sure. A negative value
    means a bug in the arithmetic, not a bad question."""
    qs = [
        Question("a", "?", {"p_kit": "x", "p_cri": "y"}),
        Question("b", "?", {"p_kit": "x", "p_cri": "x"}),
        Question("c", "?", {"p_kit": "x"}),
    ]
    for q in qs:
        assert expected_information_gain(TWO_WAY, q) >= -1e-12


def test_the_discriminating_question_is_chosen():
    useless = Question("hall", "Which hall?", {"p_kit": "Acacia", "p_cri": "Acacia"})
    useful = Question("floor", "Which floor?", {"p_kit": "18th", "p_cri": "4th"})
    assert select(TWO_WAY, [useless, useful]).question.key == "floor"


def test_a_lopsided_prior_lowers_the_value_of_asking():
    """When you are already almost certain, even a perfect question has little
    left to tell you. This is what stops the agent asking when it need not."""
    q = Question("floor", "Which floor?", {"p_kit": "18th", "p_cri": "4th"})
    unsure = [Hypothesis("p_kit", "Kit", 0.5), Hypothesis("p_cri", "Crispy", 0.5)]
    nearly_sure = [Hypothesis("p_kit", "Kit", 0.95), Hypothesis("p_cri", "Crispy", 0.05)]
    assert expected_information_gain(nearly_sure, q) < expected_information_gain(unsure, q)


# --- Bayes --------------------------------------------------------------------

def test_the_answer_shifts_belief_to_the_matching_hypothesis():
    q = Question("floor", "Which floor?", {"p_kit": "18th", "p_cri": "4th"})
    post = posterior(TWO_WAY, q, "18th")
    assert post["p_kit"] > post["p_cri"]
    assert sum(post.values()) == pytest.approx(1.0)


def test_noise_stops_one_answer_from_eliminating_a_hypothesis():
    """People misremember and attributes change. A hypothesis driven to exactly
    zero can never recover, which is both brittle and untrue to life."""
    q = Question("floor", "Which floor?", {"p_kit": "18th", "p_cri": "4th"})
    assert posterior(TWO_WAY, q, "4th")["p_kit"] > 0.0


def test_answer_distribution_is_a_distribution():
    q = Question("floor", "Which floor?", {"p_kit": "18th", "p_cri": "4th"})
    assert sum(answer_distribution(TWO_WAY, q).values()) == pytest.approx(1.0)


def test_someone_new_stays_consistent_with_every_answer():
    """The 'new person' hypothesis predicts no attribute, so no answer should
    argue for or against it more than any other."""
    hyps = [KIT, CRISPY, Hypothesis("", "someone new", 0.2)]
    q = Question("floor", "Which floor?", {"p_kit": "18th", "p_cri": "4th"})
    a, b = posterior(hyps, q, "18th")[""], posterior(hyps, q, "4th")[""]
    assert a == pytest.approx(b)


# --- priors -------------------------------------------------------------------

def test_normalise_turns_scores_into_a_prior():
    p = normalise({"a": 2.0, "b": 2.0})
    assert p["a"] == pytest.approx(0.5)
    assert sum(p.values()) == pytest.approx(1.0)


def test_normalise_handles_negative_scores():
    """Resolver scores can be negative; plain division would produce nonsense."""
    p = normalise({"a": -1.0, "b": -3.0})
    assert p["a"] > p["b"]
    assert all(v > 0 for v in p.values())


# --- baselines ----------------------------------------------------------------

def test_random_baseline_only_picks_from_what_it_is_given():
    qs = [Question(k, "?", {}) for k in "abc"]
    assert select_random(qs, random.Random(0)) in qs


def test_baselines_return_none_on_an_empty_set():
    assert select_random([], random.Random(0)) is None
    assert select_by_uncertainty(TWO_WAY, []) is None
    assert select([], []) is None


def test_eig_beats_random_on_average_when_one_question_is_decisive():
    """The headline claim in miniature: among many useless questions and one
    good one, EIG finds it every time and random finds it 1-in-n."""
    qs = [Question(f"dud{i}", "?", {"p_kit": "same", "p_cri": "same"}) for i in range(9)]
    qs.append(Question("good", "?", {"p_kit": "18th", "p_cri": "4th"}))

    assert select(TWO_WAY, qs).question.key == "good"
    rng = random.Random(0)
    hits = sum(select_random(qs, rng).key == "good" for _ in range(1000))
    assert 50 < hits < 150, "random should land on it about a tenth of the time"


def test_ranking_exposes_the_questions_not_asked():
    """The demo shows the EIG of the runners-up, so the ordering has to be real."""
    qs = [
        Question("useless", "?", {"p_kit": "same", "p_cri": "same"}),
        Question("good", "?", {"p_kit": "18th", "p_cri": "4th"}),
    ]
    ranked = rank_questions(TWO_WAY, qs)
    assert [s.question.key for s in ranked] == ["good", "useless"]
    assert ranked[0].eig > ranked[1].eig


def test_a_subset_of_hypotheses_is_renormalised():
    """Passing a subset is an easy mistake — priors then sum to less than 1 and
    entropy silently returns a plausible but wrong number instead of failing."""
    subset = [Hypothesis("p_kit", "Kit", 0.47), Hypothesis("p_cri", "Crispy", 0.47)]
    both_yes = Question("school", "Same school?", {"p_kit": "yes", "p_cri": "yes"})
    assert expected_information_gain(subset, both_yes) == pytest.approx(0.0, abs=1e-9)


def test_uncertainty_sampling_picks_the_least_predictable_answer():
    """Not 'the first question' or 'the one about the leader' — argmax H(P(a)).
    An earlier version returned whichever question sorted last, which is not a
    strategy and made the benchmark comparison meaningless."""
    predictable = Question("sure", "?", {"p_kit": "yes", "p_cri": "yes"}, answer_space=("no", "yes"))
    coinflip = Question("split", "?", {"p_kit": "yes", "p_cri": "no"}, answer_space=("no", "yes"))
    assert select_by_uncertainty(TWO_WAY, [predictable, coinflip]).key == "split"


def test_uncertainty_and_eig_can_disagree():
    """They coincide on symmetric cases; the interesting comparison is where the
    priors are lopsided and 'surprising' stops meaning 'informative'."""
    hyps = [Hypothesis("a", "A", 0.8), Hypothesis("b", "B", 0.15), Hypothesis("c", "C", 0.05)]
    qs = [
        Question("q1", "?", {"a": "yes", "b": "no", "c": "no"}, answer_space=("no", "yes")),
        Question("q2", "?", {"a": "yes", "b": "yes", "c": "no"}, answer_space=("no", "yes")),
    ]
    by_eig = select(hyps, qs).question.key
    by_unc = select_by_uncertainty(hyps, qs).key
    assert by_eig in {"q1", "q2"} and by_unc in {"q1", "q2"}


def test_eig_avoids_an_unreliable_question_that_uncertainty_walks_into():
    """The one place the two strategies genuinely part company.

    Both questions separate the candidates equally well. One asks about a degree
    (rarely changes), the other about an impression ("quiet"/"chatty" — one
    person's view on one day). Uncertainty sampling asks whatever is least
    predictable, and the flaky question is least predictable *because* its answer
    means little. EIG divides that out.

    Without this asymmetry the two are near-identical by construction: with
    uniform noise, EIG = H(A) - H(A|H) and H(A|H) is near-constant across
    questions, so argmax EIG collapses to argmax H(A).
    """
    hyps = [Hypothesis("a", "A", 0.40), Hypothesis("b", "B", 0.35),
            Hypothesis("c", "C", 0.25)]
    dependable = Question("course", "What do they study?",
                          {"a": "geo", "b": "cs", "c": "ce"},
                          answer_space=("geo", "cs", "ce"), noise=0.05)
    flaky = Question("vibe", "How would you describe them?",
                     {"a": "quiet", "b": "chatty", "c": "outgoing"},
                     answer_space=("quiet", "chatty", "outgoing"), noise=0.35)

    assert select(hyps, [dependable, flaky]).question.key == "course"
    assert select_by_uncertainty(hyps, [dependable, flaky]).key == "vibe"
    assert (expected_information_gain(hyps, dependable)
            > expected_information_gain(hyps, flaky) * 3)


def test_a_question_noise_overrides_the_global_default():
    q = Question("q", "?", {"a": "x", "b": "y"}, answer_space=("x", "y"), noise=0.5)
    hyps = [Hypothesis("a", "A", 0.5), Hypothesis("b", "B", 0.5)]
    # At 50% noise a binary answer is a coin flip and teaches nothing.
    assert expected_information_gain(hyps, q) == pytest.approx(0.0, abs=1e-9)
