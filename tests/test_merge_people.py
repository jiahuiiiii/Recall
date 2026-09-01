"""Merging two records into one human.

The counterpart to `delete()`. Resolution misses returns -- a nickname it did
not recognise, a name spelled differently -- and without merge the user can only
delete one duplicate and lose its notes. Measured on the real graph: "Crispy"
and "Tiu Chuei Enn" sat as two records for exactly this reason.
"""

from __future__ import annotations

import json

import pytest

from recall.memory import LocalPersonStore


@pytest.fixture()
def store(tmp_path):
    s = LocalPersonStore(tmp_path / "graph.json")
    s.upsert({"id": "p_full", "name": "Tiu Chuei Enn", "met_at": ["Acacia College"],
              "notes": ["studies computer science at NUS", "lives on the 4th floor"],
              "first_seen": "2026-08-24"})
    s.upsert({"id": "p_nick", "name": "Crispy", "met_at": ["the pool"],
              "notes": ["I offered her my dessert"], "first_seen": "2026-08-31"})
    return s


def test_the_absorbed_name_becomes_an_alias(store):
    """The whole point. Without it the merge only tidies the display: `compare()`
    reads `name` and `aliases`, so the next memo saying "Crispy" duplicates her
    again."""
    merged = store.merge("p_nick", "p_full")
    assert "Crispy" in merged["aliases"]


def test_notes_and_places_are_kept_from_both(store):
    merged = store.merge("p_nick", "p_full")
    assert "I offered her my dessert" in merged["notes"]
    assert "studies computer science at NUS" in merged["notes"]
    assert {"Acacia College", "the pool"} <= set(merged["met_at"])


def test_the_source_is_gone_and_the_target_survives(store):
    store.merge("p_nick", "p_full")
    assert store.get("p_nick") is None
    assert store.get("p_full") is not None
    assert len(store.all()) == 1


def test_dates_span_both_records(store):
    """The person was first seen when the EARLIER record was, not whenever the
    survivor happened to be created."""
    merged = store.merge("p_nick", "p_full")
    assert merged["first_seen"] == "2026-08-24"


def test_the_discarded_record_is_recoverable(store):
    """A merge is irreversible and the graph is a JSON file with no history."""
    store.merge("p_nick", "p_full")
    trash = store.path.with_name(store.path.stem + ".trash.json")
    assert trash.exists()
    saved = json.loads(trash.read_text())
    assert saved[-1]["record"]["name"] == "Crispy"
    assert saved[-1]["record"]["notes"] == ["I offered her my dessert"]


def test_note_dates_survive_the_merge(store):
    """Merging must not re-stamp notes with today. `upsert` dates a note when it
    is RECORDED, so both fixtures share today's date -- set them apart first,
    then check the merge carries each one through rather than flattening them."""
    for rid, day in (("p_full", "2026-08-24"), ("p_nick", "2026-08-31")):
        rec = dict(store.get(rid))
        rec["note_log"] = [{"text": n, "at": day} for n in rec["notes"]]
        store.replace(rec)

    merged = store.merge("p_nick", "p_full")
    log = {e["text"]: e["at"] for e in merged["note_log"]}
    assert log["studies computer science at NUS"] == "2026-08-24"
    assert log["I offered her my dessert"] == "2026-08-31"
    assert len(merged["note_log"]) == len(merged["notes"])


def test_unknown_and_self_merges_are_refused(store):
    with pytest.raises(KeyError):
        store.merge("p_nope", "p_full")
    with pytest.raises(ValueError):
        store.merge("p_full", "p_full")


def test_editing_a_record_does_not_change_when_you_last_saw_them(store):
    """`replace` is an edit, not an occasion -- the same rule `times_met` follows.

    It used to stamp today unconditionally, so deleting a note or re-tagging the
    graph rewrote the meeting history. One tag refresh flattened every person to
    the same date and made "recently seen" sorting useless.
    """
    rec = dict(store.get("p_full"))
    rec["last_seen"] = "2026-08-24"
    store.replace(rec)

    store.replace({**store.get("p_full"), "tags": ["computer science"]})
    assert store.get("p_full")["last_seen"] == "2026-08-24"


def test_a_real_occasion_still_updates_last_seen(store):
    """The other half: meeting someone again must move the date, or the sidebar
    stops reflecting what actually happened."""
    from datetime import date
    store.replace({**store.get("p_full"), "last_seen": "2026-08-24"})
    store.upsert({"id": "p_full", "notes": ["saw her at the pool"]})
    assert store.get("p_full")["last_seen"] == date.today().isoformat()
