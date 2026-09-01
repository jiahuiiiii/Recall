"""LLM-assigned tags for filtering.

Two things matter and neither is "the model said something reasonable": the
vocabulary has to be SHARED across people or the dropdown fragments into
one-person filters, and a tag is an assertion about a real person, so it has to
be supported by what the notes actually say.
"""

from __future__ import annotations

import pytest

import recall.tags as tags_mod
from recall.tags import TagAssignment, corroborated, generate_tags

CHUEI = {"id": "p1", "name": "Tiu Chuei Enn", "aliases": ["Crispy"], "met_at": ["Acacia College"],
         "notes": ["studies computer science at NUS", "lives on the 4th floor"]}
VARUN = {"id": "p2", "name": "Varun", "aliases": [], "met_at": ["NUS Hackers Workshop"],
         "notes": ["straight from India", "studied computer science"]}


def _fake(monkeypatch, payload):
    class _S:
        def invoke(self, _m, **_k): return payload
    class _M:
        def with_structured_output(self, *_a, **_k): return _S()
    monkeypatch.setattr(tags_mod, "chat_model", lambda **_: _M())


def test_tags_are_kept_when_the_notes_support_them(monkeypatch):
    _fake(monkeypatch, TagAssignment.model_validate({"people": [
        {"id": "p1", "tags": ["computer science", "lives in acacia"]},
        {"id": "p2", "tags": ["computer science", "from india"]},
    ]}))
    got = generate_tags([CHUEI, VARUN])
    assert got["p1"] == ["computer science", "lives in acacia"]
    assert "computer science" in got["p2"]


def test_an_unsupported_tag_is_dropped(monkeypatch):
    """The guard. A model asked to categorise will infer a nationality from a
    name; a tag is an assertion about a real person the user never made."""
    _fake(monkeypatch, TagAssignment.model_validate({"people": [
        {"id": "p1", "tags": ["computer science", "malaysian", "works at stripe"]},
    ]}))
    got = generate_tags([CHUEI])
    assert got["p1"] == ["computer science"]


def test_tags_are_normalised_and_deduped(monkeypatch):
    _fake(monkeypatch, TagAssignment.model_validate({"people": [
        {"id": "p1", "tags": ["Computer   Science", "computer science", "COMPUTER SCIENCE"]},
    ]}))
    assert generate_tags([CHUEI])["p1"] == ["computer science"]


def test_a_tag_for_a_person_who_does_not_exist_is_ignored(monkeypatch):
    _fake(monkeypatch, TagAssignment.model_validate({"people": [
        {"id": "p_nope", "tags": ["computer science"]},
    ]}))
    assert generate_tags([CHUEI]) == {}


def test_at_most_five_tags_survive(monkeypatch):
    many = ["computer science", "lives on the 4th floor", "acacia", "nus", "crispy", "studies"]
    _fake(monkeypatch, TagAssignment.model_validate({"people": [{"id": "p1", "tags": many}]}))
    assert len(generate_tags([CHUEI])["p1"]) <= 5


def test_an_empty_graph_costs_no_call(monkeypatch):
    def _boom(**_):
        raise AssertionError("must not call a model for an empty graph")
    monkeypatch.setattr(tags_mod, "chat_model", _boom)
    assert generate_tags([]) == {}
    assert generate_tags([{"id": "x", "name": "", "notes": []}]) == {}


@pytest.mark.parametrize("tag,expected", [
    ("computer science", True),
    ("acacia", True),
    ("crispy", True),          # aliases count -- it is in the record
    ("investment banking", False),
    ("", False),
])
def test_corroboration(tag, expected):
    assert corroborated(tag, CHUEI) is expected


def test_a_tag_spelled_two_ways_collapses_to_the_common_one():
    """Measured on the real graph: the model produced "malaysian" for three
    people and "malaysia" for a fourth, quietly costing that person the filter.
    A consistency property cannot live in the prompt."""
    from recall.tags import canonicalise
    got = canonicalise({"a": ["malaysian"], "b": ["malaysian"],
                        "c": ["malaysian"], "d": ["malaysia"]})
    assert got["d"] == ["malaysian"]
    assert {t for v in got.values() for t in v} == {"malaysian"}


def test_canonicalising_does_not_swallow_short_distinct_tags():
    from recall.tags import canonicalise
    got = canonicalise({"a": ["cs"], "b": ["cs1231s"]})
    assert got["a"] == ["cs"] and got["b"] == ["cs1231s"]


def test_collapsing_never_duplicates_within_a_person():
    from recall.tags import canonicalise
    got = canonicalise({"a": ["india", "indian"], "b": ["indian"]})
    assert got["a"] == ["indian"]
