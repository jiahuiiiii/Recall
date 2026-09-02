"""Relationship edges between people.

Two things matter and neither is "the model proposed something plausible". The
guard has to hold -- an edge survives only if a stored note names the other
person outright -- and the edges have to stay structurally out of resolution, so
adding them cannot move the B3 or question-efficiency numbers.
`test_relations_stay_out_of_candidate_retrieval` and
`test_relations_are_not_a_field_resolve_reads` are the guards on that second
claim, and they are the load-bearing tests in this file.
"""

from __future__ import annotations

import pytest

import recall.relations as rel_mod
from recall.memory import LocalPersonStore
from recall.relations import (
    KINDS,
    ProposedRelation,
    RelationProposal,
    RelationStore,
    canonical,
    evidence_for,
    generate_relations,
    ground,
    names_in,
    supported,
)
from recall.resolve import compare

WEI_HAN = {
    "id": "p1", "name": "Wei Han", "aliases": [],
    "notes": ["runs a supper club with Marcus", "studies computer science at NUS"],
}
MARCUS = {
    "id": "p2", "name": "Marcus", "aliases": ["Marc"],
    "notes": ["quit his internship in May"],
}
# Named only by a nickname, to prove aliases count as naming.
CHUEI = {
    "id": "p3", "name": "Tiu Chuei Enn", "aliases": ["Crispy"],
    "notes": ["Marc calls her Crispy and they were in the same OG"],
}
# The trap. Four Jia* people in one OG is the arc_godwin shape: partial name
# matching makes each of them "name" the others on a shared syllable.
JIA_EN = {"id": "p4", "name": "Jia En", "aliases": [], "notes": ["did the Jia Ying handover with her"]}
JIA_YING = {"id": "p5", "name": "Jia Ying", "aliases": [], "notes": ["golden hair"]}
JIA_QI = {"id": "p6", "name": "Jia Qi", "aliases": [], "notes": ["plays tennis"]}

ALL = [WEI_HAN, MARCUS, CHUEI, JIA_EN, JIA_YING, JIA_QI]


def _prop(a, b, kind, what=""):
    return ProposedRelation(a=a, b=b, kind=kind, what=what)


def _fake(monkeypatch, payload):
    class _S:
        def invoke(self, _m, **_k): return payload
    class _M:
        def with_structured_output(self, *_a, **_k): return _S()
    monkeypatch.setattr(rel_mod, "chat_model", lambda **_: _M())


# ------------------------------------------------------------------ the guard


def test_an_edge_survives_when_a_note_names_the_other_person():
    got = ground([_prop("p1", "p2", "partner", "runs a supper club")], ALL)
    assert len(got) == 1
    assert got[0]["kind"] == "partner"
    assert got[0]["evidence"] == "runs a supper club with Marcus"


def test_an_edge_is_dropped_when_neither_record_mentions_the_other():
    """THE guard. A model asked who relates to whom over one hall will return an
    edge per pair, because everyone shares a course and a floor. Marcus and Jia
    Qi are both real people whose notes never once name each other."""
    assert ground([_prop("p2", "p6", "friend", "close friends")], ALL) == []


def test_a_shared_syllable_is_not_naming_the_other_person():
    """The arc_godwin trap. `best_match` scores `Jia En` against `Jia Ying` at
    0.50 on the shared `jia`, which is right for the resolver and wrong here --
    it would fill the graph with edges nobody said."""
    assert names_in("did the Jia Ying handover with her", JIA_YING) is True
    assert names_in("did the Jia Ying handover with her", JIA_QI) is False
    assert ground([_prop("p4", "p6", "classmate")], ALL) == []
    assert len(ground([_prop("p4", "p5", "classmate")], ALL)) == 1


def test_an_alias_counts_as_naming():
    """Merging teaches the resolver a nickname; an edge has to see it too, or a
    note saying "Marc" fails to ground an edge to the person called Marcus."""
    got = ground([_prop("p2", "p3", "classmate", "same OG")], ALL)
    assert len(got) == 1
    assert got[0]["evidence"] == "Marc calls her Crispy and they were in the same OG"


def test_evidence_is_found_on_either_record():
    """The memo could have introduced either person first."""
    assert evidence_for(MARCUS, WEI_HAN) == "runs a supper club with Marcus"
    assert evidence_for(WEI_HAN, MARCUS) == "runs a supper club with Marcus"
    assert evidence_for(MARCUS, JIA_QI) is None


def test_a_kind_outside_the_vocabulary_is_dropped():
    """Closed on purpose: an open one gives three colours in the legend for one
    idea. `knows` was available for anything unclear."""
    assert ground([_prop("p1", "p2", "collaborator")], ALL) == []
    assert len(ground([_prop("p1", "p2", "knows")], ALL)) == 1


def test_an_invented_person_id_belongs_to_nobody():
    assert ground([_prop("p1", "p99", "friend")], ALL) == []
    assert ground([_prop("p1", "p1", "friend")], ALL) == []


def test_embroidery_is_stripped_but_the_edge_and_its_citation_survive():
    """`evidence` is found in code so it cannot be fabricated; `what` is free
    text and drifts into a nicer story than the note tells."""
    got = ground([_prop("p1", "p2", "partner", "co-founded a venture-backed startup")], ALL)
    assert len(got) == 1
    assert got[0]["what"] == ""
    assert got[0]["evidence"] == "runs a supper club with Marcus"


def test_wording_drawn_from_the_note_is_kept():
    got = ground([_prop("p1", "p2", "partner", "runs a supper club together")], ALL)
    assert got[0]["what"] == "runs a supper club together"


@pytest.mark.parametrize("what,evidence,ok", [
    ("", "anything at all", True),
    ("runs a supper club", "runs a supper club with Marcus", True),
    ("co-founded a startup", "runs a supper club with Marcus", False),
])
def test_support_threshold(what, evidence, ok):
    assert supported(what, evidence) is ok


# ------------------------------------------------------------- canonical form


def test_a_symmetric_pair_is_stored_one_way_round():
    """Without this, (A,B,friend) on one refresh and (B,A,friend) on the next
    are two rows that render as two edges and disagree when one is deleted."""
    assert canonical({"a": "p2", "b": "p1", "kind": "friend"})["a"] == "p1"
    assert canonical({"a": "p1", "b": "p2", "kind": "friend"})["b"] == "p2"


def test_a_directed_pair_keeps_its_direction():
    """Swapping a mentor and their mentee is a different claim, not a
    normalisation."""
    r = canonical({"a": "p2", "b": "p1", "kind": "mentor"})
    assert (r["a"], r["b"]) == ("p2", "p1")


def test_the_same_pair_can_hold_two_different_kinds():
    """The case the whole feature was asked for: C is A's friend and B's
    competitor, and a pair really can be both partner and competitor."""
    got = ground([_prop("p1", "p2", "partner"), _prop("p2", "p1", "competitor")], ALL)
    assert {r["kind"] for r in got} == {"partner", "competitor"}


def test_the_same_pair_and_kind_proposed_twice_collapses():
    got = ground([_prop("p1", "p2", "friend"), _prop("p2", "p1", "friend")], ALL)
    assert len(got) == 1


# -------------------------------------------------------------------- the call


def test_generate_relations_grounds_what_the_model_returns(monkeypatch):
    _fake(monkeypatch, RelationProposal.model_validate({"relations": [
        {"a": "p1", "b": "p2", "kind": "partner", "what": "runs a supper club"},
        {"a": "p2", "b": "p6", "kind": "friend", "what": "close friends"},
    ]}))
    got = generate_relations(ALL)
    assert [(r["a"], r["b"], r["kind"]) for r in got] == [("p1", "p2", "partner")]


def test_a_graph_too_small_to_have_edges_skips_the_call(monkeypatch):
    def _boom(**_):
        raise AssertionError("should not have called the model")
    monkeypatch.setattr(rel_mod, "chat_model", _boom)
    assert generate_relations([WEI_HAN]) == []


# ------------------------------------------------------------------- the store


@pytest.fixture
def store(tmp_path):
    return RelationStore(tmp_path / "relations.json")


def test_edges_survive_a_restart(store, tmp_path):
    store.add({"a": "p1", "b": "p2", "kind": "partner", "source": "derived"})
    assert len(RelationStore(tmp_path / "relations.json").all()) == 1


def test_adding_the_same_edge_twice_is_one_edge(store):
    first = store.add({"a": "p1", "b": "p2", "kind": "partner"})
    again = store.add({"a": "p2", "b": "p1", "kind": "partner"})
    assert first["id"] == again["id"]
    assert len(store.all()) == 1


def test_a_merge_repoints_edges_onto_the_survivor(store):
    """`PersonStore.merge` deletes the source, so an edge left pointing at it
    references a person who no longer exists and vanishes from the picture."""
    store.add({"a": "p1", "b": "p2", "kind": "partner"})
    assert store.repoint("p2", "p3") == 1
    assert [(r["a"], r["b"]) for r in store.all()] == [("p1", "p3")]


def test_a_merge_drops_the_edge_between_the_two_people_merged(store):
    """After a merge, "A partners with B" where A and B turned out to be one
    human is the duplicate that was just fixed, not a relationship."""
    store.add({"a": "p1", "b": "p2", "kind": "partner"})
    store.repoint("p2", "p1")
    assert store.all() == []


def test_a_merge_collapses_two_edges_that_became_the_same_edge(store):
    store.add({"a": "p1", "b": "p2", "kind": "friend"})
    store.add({"a": "p1", "b": "p3", "kind": "friend"})
    store.repoint("p3", "p2")
    assert len(store.all()) == 1


def test_forgetting_a_person_forgets_their_edges(store):
    store.add({"a": "p1", "b": "p2", "kind": "partner"})
    store.add({"a": "p2", "b": "p3", "kind": "friend"})
    assert store.drop_person("p2") == 2
    assert store.all() == []


def test_a_refresh_replaces_derived_edges_but_never_user_drawn_ones(store):
    """The graph will get relationships wrong, and a graph you cannot correct is
    one you stop trusting -- the same principle as the person panel."""
    store.add({"a": "p1", "b": "p2", "kind": "friend", "source": "user"})
    store.add({"a": "p1", "b": "p3", "kind": "knows", "source": "derived"})
    store.replace_derived([{"a": "p4", "b": "p5", "kind": "classmate", "source": "derived"}])
    kinds = {(r["a"], r["b"]): r.get("source") for r in store.all()}
    assert kinds == {("p1", "p2"): "user", ("p4", "p5"): "derived"}


def test_a_user_edge_wins_over_a_derived_one_for_the_same_pair(store):
    store.add({"a": "p1", "b": "p2", "kind": "friend", "source": "user"})
    store.replace_derived([{"a": "p1", "b": "p2", "kind": "friend", "source": "derived"}])
    assert [r.get("source") for r in store.all()] == ["user"]


def test_removing_an_edge(store):
    r = store.add({"a": "p1", "b": "p2", "kind": "partner"})
    assert store.remove(r["id"]) is True
    assert store.remove(r["id"]) is False


# ------------------------------------------------- the load-bearing guards


def test_relations_stay_out_of_candidate_retrieval(tmp_path):
    """`search` feeds dedupe, so anything reaching its haystack moves the
    resolution benchmark. A shared relationship is also the WRONG evidence: a
    note naming both people means they are two different humans, so retrieving
    one as a candidate for the other is exactly backwards."""
    people = LocalPersonStore(tmp_path / "graph.json")
    people.upsert({"id": "p1", "name": "Wei Han", "notes": []})
    people.upsert({"id": "p2", "name": "Marcus", "notes": []})
    edges = RelationStore(tmp_path / "relations.json")
    edges.add({"a": "p1", "b": "p2", "kind": "partner", "what": "runs a supper club"})

    # The edge exists, and the store that feeds dedupe cannot see it.
    assert len(edges.all()) == 1
    assert people.search("supper club") == []
    assert people.search("partner") == []


def test_relations_are_not_a_field_resolve_reads(tmp_path):
    """The structural claim behind shipping this without a re-run: `compare`
    reads six fields, and an edge is not one of them. Attaching relationship
    data to a record must not move a single channel of the agreement."""
    bare = {"id": "p1", "name": "Wei Han", "notes": ["studies computer science"]}
    with_edges = {**bare, "relations": [{"b": "p2", "kind": "partner",
                                         "what": "runs a supper club together"}]}
    mention = {"name": "Wei Han", "notes": ["runs a supper club"]}
    assert compare(mention, bare) == compare(mention, with_edges)


def test_the_kind_vocabulary_is_closed_and_the_ui_agrees():
    """Cheap tripwire: the graph page colours edges by kind, and a kind with no
    colour renders as an invisible line."""
    assert KINDS == ("partner", "colleague", "classmate", "friend", "family",
                     "mentor", "competitor", "knows")
