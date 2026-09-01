"""The three-zone band. Pure arithmetic, so it is tested against known cases.

The middle zone is the project's contribution — it is the only place a
clarifying question can be asked. These tests exist to stop it being collapsed
back to a single threshold by accident.
"""

from __future__ import annotations

import pytest

from recall.resolve import Zone, compare, decide, score, zone

VIKTORIA = {"id": "p_vik", "name": "Viktoria", "aliases": [],
            "company": None, "role": None,
            "met_at": ["dining hall"],
            "notes": ["from Germany, and exchange here", "lives in the Tembusu College"]}
KIT_YEE = {"id": "p_kit", "name": "Kit Yee", "aliases": [],
           "company": None, "role": None,
           "met_at": ["Acacia orientation camp"],
           "notes": ["from malaysian chinese independent school", "lives at the 18th floor"]}
HUILING = {"id": "p_hui", "name": "Huiling", "aliases": [],
           "company": None, "role": None, "met_at": ["orientation"],
           "notes": ["from China", "lives on the 18th floor", "studies computer engineering"]}
GRAPH = [VIKTORIA, KIT_YEE, HUILING]


def test_exact_name_alone_is_ambiguous_not_resolved():
    """A bare name is not proof of identity.

    This assertion was inverted on 28 Aug. W_NAME_EXACT used to equal T_MATCH,
    so a name with zero corroboration auto-resolved -- and because _adjudicate()
    only runs on the AMBIGUOUS branch, nothing ever reviewed it. Two different
    people called Alex merged into one record in the real pipeline. The name
    still ranks the right candidate first; it just has to buy a question instead
    of a silent merge.
    """
    z, cands = decide({"name": "Viktoria", "notes": []}, GRAPH)
    assert z is Zone.AMBIGUOUS
    assert cands[0].record_id == "p_vik"


def test_exact_name_plus_one_corroborating_signal_resolves():
    """A genuine return still resolves without a question. If this breaks, the
    cap has been set too low and every recognition now costs a question."""
    z, cands = decide({"name": "Viktoria", "met_at": "dining hall", "notes": []}, GRAPH)
    assert z is Zone.RESOLVED
    assert cands[0].record_id == "p_vik"


def test_same_first_name_in_a_student_setting_does_not_merge():
    """The precision case that `same_first_name.yaml` could not cover.

    Uni students have no company and no role, so the conflicting-employer
    evidence that blocks the professional case is simply absent -- both fields
    are silent, contribute nothing, and the name used to carry the merge on its
    own. Everything here is empty except the shared name, which is exactly the
    shape the real extractor produces.
    """
    z, _ = decide(
        {"name": "Alex", "notes": ["doing masters in robotics at NTU"]},
        [{"id": "p_a", "name": "Alex", "company": None, "role": None, "met_at": [],
          "notes": ["in payments compliance at a bank"]}],
    )
    assert z is not Zone.RESOLVED, "a shared first name alone must not auto-merge"


def test_same_common_first_name_alone_does_not_resolve():
    """Two different people can share a first name. Resolving on that silently
    destroys a real record, which is the worst failure available here."""
    z, _ = decide({"name": "Alex", "company": "Sea", "notes": []},
                  [{"id": "p_a", "name": "Alex", "company": "GIC", "notes": [], "met_at": []}])
    assert z is not Zone.RESOLVED, "conflicting employers must block an auto-merge"


def test_conflicting_company_pushes_apart():
    same_name_diff_co = compare(
        {"name": "Wei Lin", "company": "Sea Group", "notes": []},
        {"name": "Wei Lin", "company": "GIC", "notes": [], "met_at": []},
    )
    same_name_no_co = compare(
        {"name": "Wei Lin", "notes": []},
        {"name": "Wei Lin", "company": "GIC", "notes": [], "met_at": []},
    )
    assert score(same_name_diff_co) < score(same_name_no_co), (
        "a stated disagreement must count against, while silence stays neutral"
    )


def test_a_uniquely_identifying_description_resolves():
    """'the german girl' when exactly one German is stored. Asking here would
    burn the one-question budget on something already certain."""
    z, cands = decide(
        {"name": "the german girl", "notes": ["from germany"], "met_at": None}, GRAPH
    )
    assert z is Zone.RESOLVED
    assert cands[0].record_id == "p_vik"


def test_a_description_that_fits_several_people_is_ambiguous():
    """'the girl on the 18th floor' fits Kit Yee and Huiling equally. The
    evidence identifies a type of person, not a person — that is a question."""
    z, cands = decide(
        {"name": "the girl on the 18th floor",
         "notes": ["lives on the 18th floor"], "met_at": None}, GRAPH
    )
    assert z is Zone.AMBIGUOUS
    ids = {c.record_id for c in cands}
    assert {"p_kit", "p_hui"} <= ids, "both candidates must survive as hypotheses"


def test_two_descriptions_of_different_people_never_merge():
    """Measured regression: 'the german girl' and 'the indian girl' share the
    token `girl`, which scored as an exact name match and merged strangers."""
    stored_desc = {"id": "p_x", "name": "the german girl", "aliases": [],
                   "company": None, "role": None, "met_at": [],
                   "notes": ["nice person", "had breakfast"]}
    z, _ = decide({"name": "the indian girl", "notes": ["year 2 studying econ"]},
                  [stored_desc])
    assert z is Zone.NEW


def test_a_near_tie_is_ambiguous_even_at_a_high_score():
    """Separation matters as much as absolute score."""
    twin_a = {"id": "p_1", "name": "Chen Wei", "aliases": [], "company": "Sea",
              "role": None, "met_at": [], "notes": ["works on search"]}
    twin_b = {"id": "p_2", "name": "Chen Wei", "aliases": [], "company": "Sea",
              "role": None, "met_at": [], "notes": ["works on search"]}
    z, cands = decide({"name": "Chen Wei", "company": "Sea",
                       "notes": ["works on search"]}, [twin_a, twin_b])
    assert z is Zone.AMBIGUOUS
    assert len(cands) == 2


def test_a_stranger_is_new():
    z, cands = decide(
        {"name": "Sanjay Kumar", "company": "Grab", "notes": ["runs payments infra"]}, GRAPH
    )
    assert z is Zone.NEW
    assert cands == []


def test_empty_graph_is_new():
    assert decide({"name": "Anyone", "notes": []}, [])[0] is Zone.NEW


def test_ambiguous_returns_every_live_hypothesis():
    """The question has to distinguish between candidates, so all of them come
    back — not just the top one."""
    z, cands = decide(
        {"name": "the girl on the 18th floor", "notes": ["lives on the 18th floor"]}, GRAPH
    )
    if z is Zone.AMBIGUOUS:
        assert len(cands) >= 1
        assert cands == sorted(cands, key=lambda c: -c.score), "best first"


def test_a_name_conflict_only_counts_when_both_sides_named():
    """'the german girl' has no name to conflict with. Penalising it would make
    every descriptive reference look like a different person."""
    described = compare({"name": "the german girl", "notes": []}, VIKTORIA)
    other_name = compare({"name": "Bartholomew", "notes": []}, VIKTORIA)
    assert not described.name_conflict
    assert other_name.name_conflict


@pytest.mark.parametrize("value, expected", [
    (5.0, Zone.RESOLVED), (3.0, Zone.RESOLVED),
    (2.9, Zone.AMBIGUOUS), (1.0, Zone.AMBIGUOUS),
    (0.9, Zone.NEW), (-2.0, Zone.NEW),
])
def test_zone_boundaries(value, expected):
    assert zone(value) is expected


def test_thresholds_are_tunable():
    """They must be reportable and adjustable — the benchmark quotes them."""
    assert zone(2.0, t_match=1.5, t_nonmatch=0.5) is Zone.RESOLVED
    assert zone(2.0, t_match=9.0, t_nonmatch=8.0) is Zone.NEW


def test_the_band_is_not_empty_by_construction():
    """A guard against someone 'simplifying' the two thresholds back into one.
    If T_MATCH == T_NONMATCH the ambiguous zone vanishes and with it the only
    place a question can be asked."""
    from recall.resolve import T_MATCH, T_NONMATCH
    assert T_NONMATCH < T_MATCH
