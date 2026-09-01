"""Counting occasions, not places.

The person card read `len(met_at)` and called it a meeting count. `met_at` is a
deduplicated set of LOCATIONS -- and consolidation actively collapses different
descriptions of one occasion into the fullest one -- so recording the same
person three times in the same hall left the card reading "1 meeting" forever.
The counter has to be incremented where the encounters happen, in the store.
"""

from __future__ import annotations

import pytest

from recall.memory import LocalPersonStore


@pytest.fixture()
def store(tmp_path):
    return LocalPersonStore(tmp_path / "graph.json")


def test_first_sighting_counts_once(store):
    rec = store.upsert({"name": "Kit Yee", "met_at": ["Acacia orientation camp"]})
    assert rec["times_met"] == 1


def test_same_place_three_times_still_counts_three(store):
    """The exact bug: one place, three occasions."""
    rec = store.upsert({"name": "Kit Yee", "met_at": ["Acacia orientation camp"],
                        "notes": ["studies law"]})
    for note in ("plays tennis", "lives on the 4th floor"):
        rec = store.upsert({"id": rec["id"], "met_at": ["Acacia orientation camp"],
                            "notes": [note]})
    assert rec["met_at"] == ["Acacia orientation camp"]   # deduplicated, as designed
    assert rec["times_met"] == 3                          # what the card must show


def test_an_edit_is_not_an_occasion(store):
    """`replace` is how the UI deletes a note. It must not bump the count."""
    rec = store.upsert({"name": "Harold", "met_at": ["dining hall"],
                        "notes": ["keeps a sketchbook", "from Penang"]})
    store.replace({**rec, "notes": ["from Penang"]})
    assert store.get(rec["id"])["times_met"] == 1


def test_replace_without_the_field_keeps_the_stored_count(store):
    """A caller that rebuilds a partial record must not silently zero it."""
    rec = store.upsert({"name": "Harold", "met_at": ["dining hall"]})
    store.upsert({"id": rec["id"], "notes": ["from Penang"]})
    partial = {k: v for k, v in store.get(rec["id"]).items() if k != "times_met"}
    store.replace(partial)
    assert store.get(rec["id"])["times_met"] == 2


def test_merging_two_records_sums_their_occasions(store):
    """Both records were the same human, so both counts were meetings with them."""
    a = store.upsert({"name": "Tiu Chuei Enn", "met_at": ["Acacia College"]})
    store.upsert({"id": a["id"], "notes": ["studies computer science"]})
    b = store.upsert({"name": "Crispy", "met_at": ["the pool"]})
    survivor = store.merge(b["id"], a["id"])
    assert survivor["times_met"] == 3


def test_merge_defaults_pre_counter_records_to_one_each(store):
    """Records written before the counter existed have no field to sum."""
    store._records["p_old"] = {"id": "p_old", "name": "Viktoria", "met_at": ["dining hall"]}
    store._records["p_dup"] = {"id": "p_dup", "name": "Viktorya", "met_at": ["dining hall"]}
    assert store.merge("p_dup", "p_old")["times_met"] == 2


def test_an_explicit_count_overrides_the_increment(store):
    """The backfill sets the field directly; upsert must not add one on top."""
    rec = store.upsert({"name": "Pin Rui", "met_at": ["CS1231S tutorial"]})
    assert store.upsert({"id": rec["id"], "times_met": 7})["times_met"] == 7
