"""The eval scorer's back-mapping.

These exist because the previous rule -- "the labels share at least one token"
-- silently collapsed every descriptor mention in a memo onto one gold key. The
benchmark did not error; it reported a pairwise F1 of 0.033 for a run in which
extraction had been near-perfect. A scorer that corrupts rather than fails needs
tests of its own.
"""

from __future__ import annotations

from eval.harness import Mention, align, similarity


def _m(cluster: str, as_written: str, memo: str = "m1") -> Mention:
    return Mention(memo_id=memo, cluster=cluster, as_written=as_written,
                   substantive=True, ambiguous=False)


def test_descriptors_in_one_memo_do_not_collapse():
    """The regression. Three distinct people, extracted correctly, must stay three."""
    mentions = [
        _m("joshua", "the tennis boy with square glasses"),
        _m("vera", "the tennis girl with round gold glasses"),
        _m("zhong_ting", "badminton boy with round wire glasses"),
    ]
    people = [
        {"name": "tennis boy with square glasses"},
        {"name": "tennis girl with round gold glasses"},
        {"name": "badminton boy with round wire glasses"},
    ]
    got = align(mentions, people)
    assert len(got) == 3
    assert len(set(got.values())) == 3
    assert got["m1:the tennis boy with square glasses"] == 0
    assert got["m1:the tennis girl with round gold glasses"] == 1
    assert got["m1:badminton boy with round wire glasses"] == 2


def test_shorthand_still_matches_the_spoken_phrase():
    """The system's own shorthand is not the speaker's phrase, and must still land."""
    mentions = [
        _m("megan", "the CNM girl with clear glasses"),
        _m("esther", "The Korean girl with bangs"),
        _m("brian", "the rugby boy with no glasses"),
    ]
    people = [{"name": "CNM girl"}, {"name": "Korean girl"}, {"name": "rugby boy"}]
    got = align(mentions, people)
    assert got["m1:the CNM girl with clear glasses"] == 0
    assert got["m1:The Korean girl with bangs"] == 1
    assert got["m1:the rugby boy with no glasses"] == 2


def test_two_labels_for_one_person_may_share_when_the_cluster_agrees():
    """Alias case: "Chong Jie" and "CJ" are one human, so one record serves both."""
    mentions = [_m("chong_jie", "Chong Jie"), _m("chong_jie", "CJ")]
    people = [{"name": "Chong Jie", "aliases": ["CJ"]}]
    got = align(mentions, people)
    assert got == {"m1:Chong Jie": 0, "m1:CJ": 0}


def test_different_clusters_never_share_a_person():
    """The exemption is keyed on the cluster, so it cannot mask a wrong merge."""
    mentions = [_m("hui_ning", "Hui Ning"), _m("hui_wen", "Hui Wen")]
    people = [{"name": "Hui Ning"}]
    got = align(mentions, people)
    assert len(set(got.values())) <= 1
    assert "m1:Hui Ning" in got
    assert "m1:Hui Wen" not in got


def test_a_mention_nobody_extracted_is_absent():
    """Absence is the signal `run_scenario` turns into both a miss and a filtered
    passing mention -- it must not be papered over with a weak match."""
    mentions = [_m("shawn", "Shawn"), _m("valerie", "Valerie")]
    people = [{"name": "Shawn"}]
    got = align(mentions, people)
    assert got == {"m1:Shawn": 0}


def test_function_words_alone_are_not_a_match():
    assert similarity("the girl with the glasses", "the boy with the cap") < 0.25


def test_identical_phrasing_is_a_full_match():
    assert similarity("Joshua Tan", "Joshua Tan") == 1.0
    assert similarity("the tennis boy with square glasses", "tennis boy with square glasses") == 1.0


def test_alignment_is_deterministic_under_ties():
    """Two equally good candidates must resolve the same way every run, or the
    benchmark moves for a reason nobody would think to look for."""
    mentions = [_m("a", "the tall guy"), _m("b", "the tall guy (2)")]
    people = [{"name": "tall guy"}, {"name": "tall guy"}]
    assert align(mentions, people) == align(mentions, people)
