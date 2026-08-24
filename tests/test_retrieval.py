"""Candidate retrieval recall.

Retrieval gates everything downstream: when `search()` returns nothing,
`dedupe_node` files the person as new **without calling the model at all**. No
candidates means no hypotheses, no hypotheses means nothing reaches the
ambiguous band, and an empty band means EIG has no question to select. So recall
here is worth more than precision — the LLM adjudicator is the precision filter.
"""

from __future__ import annotations

import pytest

from recall.memory import LocalPersonStore


@pytest.fixture()
def store(tmp_path):
    s = LocalPersonStore(tmp_path / "graph.json")
    s.upsert({"name": "Viktoria", "notes": [
        "from Germany, and exchange here", "lives in the Tembusu College"],
        "met_at": ["dining hall"]})
    s.upsert({"name": "Kit Yee", "notes": [
        "from malaysian chinese independent school", "lives at the 18th floor",
        "studies geospatial intelligence at NUS"], "met_at": ["Acacia orientation camp"]})
    s.upsert({"name": "Marvi", "notes": [
        "an indian girl who lives in the same region as me",
        "got locked out of her room"], "met_at": []})
    s.upsert({"name": "Huiling", "notes": [
        "from China", "lives on the 18th floor",
        "studies computer engineering"], "met_at": ["orientation"]})
    return s


def names(hits):
    return [h["name"] for h in hits]


# --- these already worked; they must keep working -----------------------------

def test_exact_name_retrieves(store):
    assert "Viktoria" in names(store.search("Viktoria"))


def test_descriptive_reference_with_shared_tokens_retrieves(store):
    assert "Kit Yee" in names(store.search("the malaysian chinese girl"))
    assert "Marvi" in names(store.search("the indian girl"))


# --- the failure this step exists to fix --------------------------------------

def test_morphological_variant_retrieves(store):
    """'the german girl' must find Viktoria, whose record says 'Germany'.

    The measured failure: exact token matching compares `german` to `germany`,
    misses by one character, returns nothing, and dedupe never calls the model.
    """
    assert "Viktoria" in names(store.search("the german girl"))


@pytest.mark.parametrize("query, expected", [
    ("the german girl", "Viktoria"),
    ("that girl from germany", "Viktoria"),
    ("the exchange student", "Viktoria"),
    ("chinese girl on the 18th floor", "Huiling"),
    ("the geospatial one", "Kit Yee"),
])
def test_loose_references_retrieve_the_right_person(store, query, expected):
    assert expected in names(store.search(query)), f"{query!r} lost {expected}"


def test_whisper_style_misspelling_still_retrieves(store):
    """Names are transcribed phonetically and arrive misspelled. A retrieval
    layer that only does exact matching loses the person outright."""
    assert "Viktoria" in names(store.search("Viktorya"))
    assert "Huiling" in names(store.search("Hui Ling"))


# --- recall must not be bought with unbounded precision loss -------------------

def test_unrelated_query_does_not_match_everyone(store):
    """Generous, not indiscriminate. Returning the whole graph for any query
    would make the adjudicator's job meaningless and cost a model call per person."""
    assert names(store.search("quantum computing conference in Zurich")) == []


def test_a_different_person_is_not_returned_first(store):
    """Both live on the 18th floor; the name token must outweigh a shared note."""
    hits = names(store.search("Kit Yee"))
    assert hits[0] == "Kit Yee"
