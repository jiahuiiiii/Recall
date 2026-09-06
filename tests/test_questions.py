"""Mechanical question derivation.

Questions come from the stored records, not from a model. These tests pin that
a derived question is (a) answerable, (b) correctly labelled with what each
hypothesis implies, and (c) natural enough to say out loud.
"""

from __future__ import annotations

import pytest

from recall.eig import Hypothesis, rank_questions
from recall.questions import (
    MUTABLE,
    SOMETHING_ELSE,
    attribute_questions,
    derive,
    facts_for,
    needs_model,
    phrase,
)

KIT = {"id": "p_kit", "name": "Kit Yee", "company": None, "role": None,
       "met_at": ["Acacia orientation camp"],
       "notes": ["from malaysian chinese independent school",
                 "lives at the 18th floor", "studies geospatial intelligence at NUS"]}
CRISPY = {"id": "p_cri", "name": "Tiu Chuei Enn", "company": None, "role": None,
          "met_at": [],
          "notes": ["from malaysian chinese independent school",
                    "lives on the 4th floor", "studies computer science at NUS"]}
RECORDS = {"p_kit": KIT, "p_cri": CRISPY}
HYPS = [Hypothesis("p_kit", "Kit Yee", 0.47),
        Hypothesis("p_cri", "Crispy", 0.47),
        Hypothesis("", "someone new", 0.06)]


def test_facts_cover_structured_fields_and_notes():
    facts = facts_for({"company": "GIC", "role": "quant lead",
                       "met_at": ["the mixer"], "notes": ["hiring right now"]})
    assert "works at GIC" in facts
    assert "is a quant lead" in facts
    assert "was met at the mixer" in facts
    assert "hiring right now" in facts


@pytest.mark.parametrize("fact, expected", [
    ("lives on the 4th floor", "Do they live on the 4th floor?"),
    ("studies computer science", "Do they study computer science?"),
    ("works at GIC", "Do they work at GIC?"),
    ("is a quant lead", "Are they a quant lead?"),
    ("wants the updated deck", "Do they want the updated deck?"),
    ("covers enterprise software", "Do they cover enterprise software?"),
])
def test_facts_become_natural_questions(fact, expected):
    assert phrase(fact) == expected


def test_phrasing_uses_they_them():
    """The graph records what someone said about a person, not that person's
    pronouns. Guessing from a name gets it wrong for real people."""
    for fact in ("lives on the 4th floor", "studies econ", "is friendly"):
        q = phrase(fact).lower()
        assert " they " in q or q.startswith(("do they", "are they", "were they"))
        assert " she " not in q and " he " not in q


def test_a_fact_only_one_candidate_has_splits_them():
    qs = {q.text: q for q in derive(HYPS, RECORDS)}
    floor = next(q for t, q in qs.items() if "18th floor" in t)
    assert floor.outcomes["p_kit"] == "yes"
    assert floor.outcomes["p_cri"] == "no"


def test_a_shared_fact_is_kept_but_worth_nothing():
    """Both went to the same school, so asking cannot separate them. Keeping the
    question is the point: it is the plausible-sounding one worth zero, and the
    contrast is what shows the selection is arithmetic."""
    shared = [q for q in derive(HYPS, RECORDS)
              if "malaysian chinese" in q.text.lower()]
    assert shared, "the shared fact must still be offered as a candidate"
    two_way = [h for h in HYPS if h.record_id]   # subset: priors no longer sum to 1
    gain = rank_questions(two_way, shared)[0].eig
    assert gain == pytest.approx(0.0, abs=1e-9)


def test_near_identical_facts_do_not_become_rival_questions():
    """'lives at the 18th floor' and 'lives on the 18th floor' are one fact."""
    a = {"id": "a", "name": "A", "met_at": [], "notes": ["lives at the 18th floor"]}
    b = {"id": "b", "name": "B", "met_at": [], "notes": ["lives on the 18th floor"]}
    hyps = [Hypothesis("a", "A", 0.5), Hypothesis("b", "B", 0.5)]
    floor_qs = [q for q in derive(hyps, {"a": a, "b": b}) if "floor" in q.text]
    assert len(floor_qs) == 1


def test_someone_new_predicts_no_answer_to_a_yes_no_probe():
    """A person we have never met might or might not live on the 4th floor, so
    a yes/no probe must not argue for or against them."""
    for q in derive(HYPS, RECORDS):
        if len(q.answer_space) == 2:
            assert "" not in q.outcomes


def test_someone_new_predicts_something_else_on_an_attribute_probe():
    """The opposite case, and the difference is real rather than an
    inconsistency. Holding no record of someone IS a prediction here: whatever
    value they name will not be one of the values we have on file."""
    for q in derive(HYPS, RECORDS):
        if len(q.answer_space) > 2:
            assert q.outcomes[""] == SOMETHING_ELSE


def test_answering_none_of_these_does_not_resolve_to_a_known_person():
    """The bug this pins, and it is the dangerous direction. The known
    candidates carry ~49% priors; if the new-person hypothesis gains nothing
    from the one answer that vindicates it, the user says "none of these" and is
    told it is Kit Yee anyway — a stranger merged into a real contact record."""
    from recall.answer import resolve_with_answer
    from recall.eig import normalise

    prior = normalise({"p_kit": 3.5, "p_cri": 3.5, "": 0.0})
    hyps = [Hypothesis(k, {"": "someone new"}.get(k, k), v) for k, v in prior.items()]
    course = _only(derive(HYPS, RECORDS), "study", multivalued=True)

    assert resolve_with_answer(hyps, course, SOMETHING_ELSE).record_id == ""


def test_the_chosen_question_actually_separates_the_candidates():
    ranked = rank_questions(HYPS, derive(HYPS, RECORDS))
    best = ranked[0].question
    assert len(set(best.outcomes.values())) > 1
    assert ranked[0].eig > 0


def test_needs_model_when_there_is_nothing_to_ask_about():
    """Thin or identical records: attributes cannot separate the hypotheses, so
    something outside them has to be asked. That is the model's fallback role."""
    empty = {"id": "x", "name": "X", "met_at": [], "notes": []}
    hyps = [Hypothesis("x", "X", 0.5), Hypothesis("", "someone new", 0.5)]
    assert needs_model(derive(hyps, {"x": empty}))


def test_derive_is_stable_across_runs():
    """Pure: same input, same questions, same order. The benchmark depends on it."""
    a = derive(HYPS, RECORDS)
    b = derive(HYPS, RECORDS)
    assert [q.key for q in a] == [q.key for q in b]


# --------------------------------------------------------------------------
# Multi-valued attribute probes.
#
# The lever these exist for is capacity: a yes/no answer cannot carry more than
# one bit, so when two records disagree about the VALUE of an attribute, asking
# for the value resolves in fewer questions than confirming one candidate at a
# time.
# --------------------------------------------------------------------------


def test_rival_values_become_one_multivalued_question():
    """Kit is on the 18th, Crispy on the 4th. That is one attribute, two answers,
    not two unrelated yes/no probes."""
    floor = _only(derive(HYPS, RECORDS), "floor", multivalued=True)
    assert floor.outcomes["p_kit"] == "18th"
    assert floor.outcomes["p_cri"] == "4th"
    assert set(floor.answer_space) == {"18th", "4th", SOMETHING_ELSE}


def test_the_answer_space_stays_open():
    """Every attribute probe must admit an answer no candidate holds. A closed
    answer space can only ever choose between people already in the graph, which
    is exactly how a stranger gets merged into an acquaintance."""
    for q in derive(HYPS, RECORDS):
        if len(q.answer_space) > 2:
            assert SOMETHING_ELSE in q.answer_space


def test_multivalued_beats_the_binary_probe_it_replaces():
    """The whole justification. Measured, not asserted in a comment."""
    qs = derive(HYPS, RECORDS)
    multi = _only(qs, "floor", multivalued=True)
    binary = [q for q in qs if "floor" in q.text and len(q.answer_space) == 2]
    assert binary, "the binary probes must still be offered — they are the contrast"

    scored = {s.question.key: s.eig for s in rank_questions(HYPS, qs)}
    assert scored[multi.key] > max(scored[b.key] for b in binary)


def test_both_shapes_are_offered_so_the_contrast_is_visible():
    """The cheaper-sounding question worth measurably less is what demonstrates
    the choice is arithmetic. Filtering the binaries out would hide it."""
    qs = derive(HYPS, RECORDS)
    assert any(len(q.answer_space) > 2 for q in qs)
    assert any(len(q.answer_space) == 2 for q in qs)


@pytest.mark.parametrize("a, b, expected", [
    ("studies geospatial intelligence at NUS", "studies computer science at NUS",
     "What do they study at NUS?"),
    ("lives at the 18th floor", "lives on the 4th floor",
     "Which floor do they live at?"),
])
def test_attribute_questions_are_natural_wh_questions(a, b, expected):
    q = _only(attribute_questions({"a": [a], "b": [b]}), "", multivalued=True)
    assert q.text == expected


def test_the_committed_demo_seed_has_one_unique_natural_best_question():
    """The judge demo must demonstrate an argmax, not an arbitrary top tie."""
    import json
    from pathlib import Path

    from recall.answer import resolve_with_answer
    from recall.eig import normalise
    from recall.resolve import Zone, decide

    records = json.loads(Path("data/demo_seed.json").read_text())["people"]
    mention = {
        "name": "the partner from Canopy",
        "company": "Canopy Ventures",
        "role": "partner",
        "met_at": [],
        "notes": ["asked how the raise is going", "wants the updated Recall deck"],
        "aliases": [],
    }
    zone, candidates = decide(mention, records)
    assert zone is Zone.AMBIGUOUS
    assert {candidate.name for candidate in candidates} == {
        "Priya Nair", "Rachel Tan", "Nadia Osman",
    }

    raw = {candidate.record_id: candidate.score for candidate in candidates} | {"": 0.0}
    prior = normalise(raw)
    names = {candidate.record_id: candidate.name for candidate in candidates} | {
        "": "someone new"
    }
    hypotheses = [
        Hypothesis(record_id, names[record_id], probability)
        for record_id, probability in prior.items()
    ]
    by_id = {record["id"]: record for record in records}
    ranked = rank_questions(hypotheses, derive(hypotheses, by_id))

    assert ranked[0].question.text == "What do they cover in Singapore?"
    assert ranked[0].eig > ranked[1].eig
    resolution = resolve_with_answer(
        hypotheses, ranked[0].question, "seed-stage companies"
    )
    assert resolution.name == "Rachel Tan"
    assert resolution.confident


def test_an_unphrasable_attribute_falls_back_to_listing_the_rivals():
    """No verb to build a wh-question from. The fallback must still be
    grammatical and answerable — an unanswerable question makes its EIG a lie."""
    q = _only(attribute_questions({"a": ["from Penang"], "b": ["from Ipoh"]}),
              "", multivalued=True)
    assert q.text.endswith("?")
    assert "penang" in q.text.lower() and "ipoh" in q.text.lower()


@pytest.mark.parametrize("a, b", [
    # The bug this pins: "was" is the shared verb, and the wh-template turned it
    # into "What do they was?". An unparseable question still gets scored in
    # bits and still gets asked, which is worse than a clumsy one.
    ("was met at Acacia orientation camp", "was met at Acacia College"),
    ("is a quant lead", "is a research intern"),
    ("lives at the 18th floor", "lives in Tembusu College"),
    ("from Penang", "from Ipoh"),
])
def test_every_derived_question_is_grammatical_english(a, b):
    text = _only(attribute_questions({"a": [a], "b": [b]}), "", multivalued=True).text
    assert text.endswith("?")
    assert "they was" not in text.lower()
    assert not text.lower().rstrip("?").endswith((" was", " is", " has", " had"))


def test_copulas_conjugate_in_the_listing_form():
    text = _only(attribute_questions({"a": ["was met at camp"], "b": ["was met at the hall"]}),
                 "", multivalued=True).text
    assert "they were met" in text and "they was" not in text


def test_rival_roles_are_one_question():
    """company and role are structured fields, so 'is a X' / 'is a Y' share only
    'is a' — and those two words are enough, because the values are genuinely
    alternatives."""
    q = _only(attribute_questions({"a": ["is a quant lead"], "b": ["is a research intern"]}),
              "", multivalued=True)
    assert {q.outcomes["a"], q.outcomes["b"]} == {"quant lead", "research intern"}


def test_a_single_shared_function_word_is_not_an_attribute():
    """'is a quant lead' and 'is friendly' share only 'is'. They are not rival
    values of anything, and asking the user to choose between them is a question
    with no correct answer."""
    assert attribute_questions({"a": ["is a quant lead"], "b": ["is friendly"]}) == []


def test_unrelated_facts_are_not_paired_into_a_nonsense_attribute():
    """The failure that matters. 'school' and 'science' overlap enough for a
    loose token rule to pair them, and the resulting question cannot be answered
    at all — so the bits it scores are imaginary."""
    facts = {"a": ["from malaysian chinese independent school"],
             "b": ["studies computer science at NUS"]}
    assert attribute_questions(facts) == []


def test_elaboration_is_not_disagreement():
    """'lives at the 18th floor' and 'lives at the 18th floor in Acacia' say the
    same thing with more detail. Treating that as rival values invents a
    conflict and asks the user to adjudicate it."""
    facts = {"a": ["lives at the 18th floor"],
             "b": ["lives at the 18th floor in Acacia"]}
    assert attribute_questions(facts) == []


def test_agreeing_records_produce_no_attribute_question():
    facts = {"a": ["studies computer science at NUS"],
             "b": ["studies computer science at NUS"]}
    assert attribute_questions(facts) == []


def test_attribute_noise_is_the_least_dependable_member():
    """A floor changes every semester. Overstating reliability is the dangerous
    direction: it makes EIG trust an answer it should not."""
    q = _only(attribute_questions({"a": ["lives at the 18th floor"],
                                   "b": ["lives on the 4th floor"]}), "", multivalued=True)
    assert q.noise == MUTABLE


def test_attribute_derivation_is_stable_across_runs():
    a = [q.key for q in derive(HYPS, RECORDS) if len(q.answer_space) > 2]
    b = [q.key for q in derive(HYPS, RECORDS) if len(q.answer_space) > 2]
    assert a == b and a


def _only(questions, needle: str, multivalued: bool):
    """The one question matching `needle`, asserting there is exactly one."""
    hits = [q for q in questions
            if needle.lower() in q.text.lower()
            and (len(q.answer_space) > 2) == multivalued]
    assert len(hits) == 1, f"expected one match for {needle!r}, got {[q.text for q in hits]}"
    return hits[0]
