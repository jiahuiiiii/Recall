"""Contact handles: normalisation, storage, and what must NOT read them.

The last of those is the point of the file. `contacts` is user-entered display
data, and the one way it could do damage is by leaking into resolution -- two
records sharing a number is a data-entry mistake, not evidence they are one
human. `test_contacts_stay_out_of_candidate_retrieval` is the guard on that.
"""

from __future__ import annotations

import pytest

from recall.contacts import (
    CHANNELS,
    as_contacts,
    link,
    links,
    normalise,
    unknown_channels,
)
from recall.memory import LocalPersonStore

# ---------------------------------------------------------------- normalising


@pytest.mark.parametrize(
    "raw",
    [
        "https://www.instagram.com/kangling/?hl=en",
        "instagram.com/kangling",
        "@kangling",
        "  kangling  ",
        "//instagram.com/kangling/",
    ],
)
def test_every_way_of_writing_one_instagram_profile_stores_the_same_handle(raw):
    """People paste the URL as often as they type the handle. A record holding
    four spellings of one profile cannot be linked to or compared with itself."""
    assert normalise("instagram", raw) == "kangling"


@pytest.mark.parametrize(
    "raw", ["https://t.me/kangling", "t.me/kangling", "@kangling", "telegram.me/kangling"]
)
def test_telegram_urls_and_handles_agree(raw):
    assert normalise("telegram", raw) == "kangling"


def test_linkedin_keeps_the_path_because_the_path_carries_the_type():
    """`in/x` is a person and `company/x` is not. Storing the bare handle would
    make both link to /in/, so a company page would 404."""
    assert normalise("linkedin", "https://sg.linkedin.com/in/kang-ling-9?trk=x") == "in/kang-ling-9"
    assert normalise("linkedin", "kang-ling-9") == "in/kang-ling-9"
    assert normalise("linkedin", "linkedin.com/company/gic") == "company/gic"


def test_a_phone_number_keeps_the_shape_the_user_typed():
    assert normalise("phone", "  +65 9123-4567 ") == "+65 9123-4567"
    assert normalise("phone", "(65) 9123 4567") == "(65) 9123 4567"


def test_prose_is_not_a_phone_number():
    """Fewer than five digits is not a number in any country, so it is a
    mis-paste -- and storing it gives the record a dial button that dials
    nowhere."""
    assert normalise("phone", "call me lah") == ""
    assert normalise("phone", "9123") == ""


def test_a_handle_is_never_rewritten_only_undecorated():
    """A wrong handle should stay wrong and visible. Stripping characters to
    make it look valid turns it into a different, plausible profile."""
    assert normalise("instagram", "@kang.ling_98") == "kang.ling_98"


def test_a_bare_domain_carries_no_handle():
    assert normalise("instagram", "https://instagram.com") == ""
    assert normalise("telegram", "t.me/") == ""


def test_an_unknown_channel_raises_rather_than_being_invented():
    with pytest.raises(ValueError):
        normalise("whatsapp", "9123 4567")


# ------------------------------------------------------------------- the map


def test_as_contacts_drops_unknown_channels_and_empty_values():
    """The boundary guard, same job as `as_list`: a record never holds a key the
    UI has no field for, and "absent" has exactly one spelling."""
    got = as_contacts({"instagram": " @kangling ", "whatsapp": "9123 4567",
                       "telegram": "   ", "phone": None})
    assert got == {"instagram": "kangling"}


def test_as_contacts_is_ordered_so_two_equal_records_serialise_alike():
    a = as_contacts({"linkedin": "in/x", "phone": "+65 9123 4567"})
    b = as_contacts({"phone": "+65 9123 4567", "linkedin": "in/x"})
    assert list(a) == list(b) == ["phone", "linkedin"]


def test_as_contacts_survives_junk_instead_of_raising():
    assert as_contacts(None) == {} and as_contacts("nope") == {} and as_contacts([]) == {}


def test_unknown_channels_names_what_would_be_dropped():
    """Dropping is right when loading an old record and wrong on a write, so the
    API can tell a caller that typed `whatsapp` instead of swallowing it."""
    assert unknown_channels({"whatsapp": "x", "wechat": "y", "phone": "+65 91234567"}) == [
        "wechat", "whatsapp"
    ]


# ------------------------------------------------------------------- linking


def test_links_are_built_from_the_stored_handle():
    assert link("instagram", "kangling") == "https://instagram.com/kangling"
    assert link("telegram", "kangling") == "https://t.me/kangling"
    assert link("linkedin", "in/kang-ling") == "https://www.linkedin.com/in/kang-ling"
    assert link("phone", "+65 9123-4567") == "tel:+6591234567"


def test_nothing_stored_means_nothing_to_open():
    assert link("instagram", "") is None
    assert links({"phone": "nope", "instagram": "kangling"}) == {
        "instagram": "https://instagram.com/kangling"
    }


# --------------------------------------------------------------- in the store


@pytest.fixture
def store(tmp_path):
    return LocalPersonStore(tmp_path / "graph.json")


def _id(store, name):
    return next(r["id"] for r in store.all() if r["name"] == name)


def test_a_handle_survives_a_round_trip_to_disk(store, tmp_path):
    store.upsert({"name": "Kang Ling", "contacts": {"instagram": "instagram.com/kangling"}})
    reopened = LocalPersonStore(tmp_path / "graph.json")
    assert reopened.all()[0]["contacts"] == {"instagram": "kangling"}


def test_upsert_adds_a_channel_without_clearing_the_others(store):
    """`{**existing, **record}` would replace the map wholesale, so a later memo
    carrying only a phone number would silently drop the Instagram handle."""
    store.upsert({"name": "Kang Ling", "contacts": {"instagram": "kangling"}})
    rid = _id(store, "Kang Ling")
    store.upsert({"id": rid, "contacts": {"phone": "+65 9123 4567"}})
    assert store.get(rid)["contacts"] == {"phone": "+65 9123 4567", "instagram": "kangling"}


def test_upsert_can_correct_a_handle(store):
    store.upsert({"name": "Kang Ling", "contacts": {"telegram": "kangling"}})
    rid = _id(store, "Kang Ling")
    store.upsert({"id": rid, "contacts": {"telegram": "@kang.ling"}})
    assert store.get(rid)["contacts"]["telegram"] == "kang.ling"


def test_replace_is_the_only_way_to_clear_one(store):
    """Same split as `notes`: upsert accumulates, replace is the edit path. The
    UI patches through replace, which is why deleting a number works there and
    would not through upsert."""
    store.upsert({"name": "Kang Ling", "contacts": {"phone": "+65 9123 4567",
                                                   "instagram": "kangling"}})
    rid = _id(store, "Kang Ling")
    record = dict(store.get(rid))
    record["contacts"] = {"instagram": "kangling"}
    store.replace(record)
    assert store.get(rid)["contacts"] == {"instagram": "kangling"}


def test_replace_normalises_rather_than_trusting_its_caller(store):
    store.upsert({"name": "Kang Ling"})
    rid = _id(store, "Kang Ling")
    store.replace({**store.get(rid), "contacts": {"linkedin": "https://www.linkedin.com/in/kl/"}})
    assert store.get(rid)["contacts"] == {"linkedin": "in/kl"}


def test_merging_two_records_keeps_every_channel(store):
    """The duplicate is where the handle usually is -- you met them again, swapped
    details, and the graph filed a second record. Losing it in the merge would
    lose the only reason the user merged."""
    store.upsert({"name": "Kang Ling", "contacts": {"phone": "+65 9123 4567"}})
    store.upsert({"name": "KL", "contacts": {"instagram": "kangling",
                                             "phone": "+65 8000 0000"}})
    survivor = store.merge(_id(store, "KL"), _id(store, "Kang Ling"))
    assert survivor["contacts"] == {"phone": "+65 9123 4567", "instagram": "kangling"}, \
        "the survivor's own number wins the clash; the source only fills gaps"


def test_a_record_written_before_contacts_existed_still_loads(store):
    store.upsert({"name": "Kang Ling", "notes": ["very smart"]})
    rid = _id(store, "Kang Ling")
    assert store.get(rid)["contacts"] == {}
    assert store.replace({**store.get(rid), "notes": []})["contacts"] == {}


def test_contacts_stay_out_of_candidate_retrieval(store):
    """The load-bearing one. `search` feeds dedupe, so anything added to its
    haystack moves the resolution benchmark -- and a shared handle is not
    evidence of a shared identity. Searching by handle is a UI filter
    (`shared.js::haystack`), not a resolver input."""
    store.upsert({"name": "Kang Ling", "contacts": {"instagram": "tenniskaki"}})
    assert store.search("tenniskaki") == []
    assert [r["name"] for r in store.search("Kang Ling")] == ["Kang Ling"]


def test_every_channel_the_ui_offers_is_one_the_store_accepts():
    """The page's CONTACT_FIELDS and this tuple have to agree or a field saves
    into nothing. Cheap tripwire for the day a fifth channel is added."""
    assert CHANNELS == ("phone", "instagram", "telegram", "linkedin")
