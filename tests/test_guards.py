"""The two guards that keep wrong data out of the person graph.

Both exist because a model told to be careful is still sometimes not careful,
and both failures are invisible in the output: a person who should not be a
contact, and a fluent biography belonging to a stranger.
"""

from __future__ import annotations

import pytest

from recall.nodes.enrich import _verify
from recall.state import PeopleExtraction, Person
from tests.fakes import PASSING_MENTION, WEI_LIN, fake_chat_model


def test_passing_mentions_are_filtered_out(monkeypatch):
    """Daniel was seen and greeted. He is not a contact record."""
    from recall.nodes import extract

    monkeypatch.setattr(
        extract,
        "chat_model",
        fake_chat_model({PeopleExtraction: PeopleExtraction(people=[WEI_LIN, PASSING_MENTION])}),
    )
    out = extract.extract_people_node({"transcript": "a memo"})

    assert [p["name"] for p in out["people"]] == ["Wei Lin"]
    assert "Skipped 1 passing mention(s): Daniel" in out["messages"][0].content


def test_substantive_role_aliases_reach_dedupe(monkeypatch):
    """A callback by role is a recognition input, not disposable prose.

    The recruiting arc uses references such as "the Stripe engineer" after
    Alex Morgan was first recorded. Keeping that exact phrase as an alias is
    what lets alignment and retrieval give the resolver a chance to recognise
    him; dropping it makes the mention invisible before resolution begins.
    """
    from recall.nodes import extract

    extracted = PeopleExtraction(people=[
        Person(
            name="Alex Morgan",
            aliases=["the Stripe engineer"],
            notes=["Can do Thursday after six thirty"],
            substantive=True,
        ),
        Person(
            name="Gabriel Wong",
            aliases=["the client HR lead"],
            notes=["Backend can be remote two days a week"],
            substantive=True,
        ),
    ])
    monkeypatch.setattr(extract, "chat_model", fake_chat_model({PeopleExtraction: extracted}))

    out = extract.extract_people_node({"transcript": "a recruiting callback"})

    assert [p["name"] for p in out["people"]] == ["Alex Morgan", "Gabriel Wong"]
    assert out["people"][0]["aliases"] == ["the Stripe engineer"]
    assert out["people"][1]["aliases"] == ["the client HR lead"]


def test_extraction_instructions_make_role_aliases_mandatory():
    """Keep the role-reference requirement visible as the extraction prompt evolves."""
    from recall.nodes.extract import SYSTEM

    assert "role or descriptive reference as an alias" in SYSTEM
    assert "Stripe engineer" in SYSTEM


def test_enricher_skips_people_with_nothing_to_disambiguate_on(monkeypatch):
    """A bare first name matches thousands of people; searching is worse than not."""
    import langgraph.prebuilt

    from recall.nodes import enrich
    from tests.fakes import FakeEnricherAgent

    called = []
    agent = FakeEnricherAgent({})
    original = agent.invoke
    agent.invoke = lambda payload, **kw: (called.append(1), original(payload, **kw))[1]
    monkeypatch.setattr(langgraph.prebuilt, "create_react_agent", lambda *a, **k: agent)
    monkeypatch.setattr(enrich, "chat_model", lambda **kw: object())

    bare = {"name": "Marcus", "company": None, "role": None, "met_at": None, "notes": ["was there"]}
    out = enrich.enrich_node({"new_people": [bare]})

    assert out["enrichments"]["Marcus"].startswith("NO RELIABLE")
    assert called == [], "the sub-agent should not have been invoked at all"


def test_demo_can_skip_public_enrichment_for_synthetic_people(monkeypatch):
    """A fictional name must not be matched to a real biography during a demo."""
    import langgraph.prebuilt

    from recall.nodes.enrich import enrich_node

    monkeypatch.setenv("RECALL_SKIP_ENRICHMENT", "1")
    monkeypatch.setattr(
        langgraph.prebuilt,
        "create_react_agent",
        lambda *args, **kwargs: pytest.fail("public enrichment should not start"),
    )
    out = enrich_node({
        "new_people": [{"name": "Rachel Tan", "company": "Canopy Ventures"}]
    })

    assert out["enrichments"]["Rachel Tan"].startswith("NO RELIABLE")
    assert "skipped" in out["messages"][0].content.lower()


PERSON = {"name": "Wei Lin", "company": "GIC", "role": "quant infrastructure lead", "met_at": "SuperAI mixer"}


def test_verify_keeps_enrichment_corroborated_by_the_memo():
    answer = "- Leads quant infrastructure at GIC.\n- Spoke at QuantCon 2025.\nCONFIRMED BY: employer GIC and the quant infrastructure role"
    assert _verify(PERSON, answer) == "- Leads quant infrastructure at GIC.\n- Spoke at QuantCon 2025."


@pytest.mark.parametrize(
    "answer, why",
    [
        ("- Product lead at Stripe.\nCONFIRMED BY: his first name is Daniel", "name-only is not corroboration"),
        ("- Product lead at Stripe.", "no CONFIRMED BY line at all"),
        ("CONFIRMED BY: employer GIC", "evidence but no facts"),
        ("NO RELIABLE PUBLIC INFORMATION FOUND.", "honest miss stays a miss"),
        ("", "empty answer"),
    ],
)
def test_verify_discards_uncorroborated_enrichment(answer, why):
    assert _verify(PERSON, answer).startswith("NO RELIABLE"), why


def test_verify_rejects_a_confident_biography_for_the_wrong_human():
    """The exact failure seen in a real run: a fluent, specific, wrong bio."""
    daniel = {"name": "Daniel", "company": "Stripe", "role": None, "met_at": "SuperAI mixer"}
    answer = (
        "- Product lead at Stripe, building Stripe Treasury for Europe\n"
        "- Education: Universidad de Monterrey\n"
        "CONFIRMED BY: he is named Daniel and works in tech"
    )
    assert _verify(daniel, answer).startswith("NO RELIABLE")


def test_three_letter_employers_can_corroborate():
    """GIC, DBS, AWS, IBM. A length-4 floor would reject every one of them, and
    the failure would look like the enricher simply never finding anything."""
    answer = "- Leads quant infrastructure at GIC.\nCONFIRMED BY: employer GIC"
    assert _verify(PERSON, answer) == "- Leads quant infrastructure at GIC."


def test_filler_words_do_not_create_a_bogus_match():
    """'the' appearing in both the memo and the evidence line is not corroboration."""
    person = {"name": "Alex", "company": "The Group", "role": None, "met_at": None}
    answer = "- Runs a hedge fund.\nCONFIRMED BY: the same person"
    assert _verify(person, answer).startswith("NO RELIABLE")


# --------------------------------------------------------------------------
# Consolidation: merge uses a model to deduplicate a record, and this guard is
# what makes that safe. The original notes are gone once it writes, so a bad
# consolidation is permanent and silent.
# --------------------------------------------------------------------------

from recall.nodes.merge import _safe_consolidation
from recall.state import ConsolidatedRecord

NOTES = [
    "Very smart and very nice",
    "We formed a team for the SimplifyNext hackathon",
    "Studies computer science",
    "Computer science, same major as me",
    "Finished the eval harness for our hackathon project",
    "I said I would review her PR tonight",
]
PLACES = ["orientation camp hosted by Malaysian Chinese Independent School Association", "orientation camp"]


def test_genuine_deduplication_is_accepted():
    result = ConsolidatedRecord(
        notes=[
            "Very smart and very nice",
            "We formed a team for the SimplifyNext hackathon",
            "Computer science, same major as me",
            "Finished the eval harness for our hackathon project",
            "I said I would review her PR tonight",
        ],
        met_at=["orientation camp hosted by Malaysian Chinese Independent School Association"],
    )
    out = _safe_consolidation(NOTES, PLACES, result)

    assert out is not None
    # One duplicate pair collapsed; every entry still holds exactly one fact.
    assert len(out["notes"]) == 5
    assert all(";" not in n for n in out["notes"])
    assert len(out["met_at"]) == 1


def test_summarising_instead_of_deduplicating_is_rejected():
    """'Classmate, hackathon teammate' loses the promises. Keeping a repetitive
    record beats silently destroying what the user actually said."""
    result = ConsolidatedRecord(notes=["Classmate and hackathon teammate."], met_at=["camp"])
    assert _safe_consolidation(NOTES, PLACES, result) is None


def test_emptying_the_notes_is_rejected():
    assert _safe_consolidation(NOTES, PLACES, ConsolidatedRecord(notes=[], met_at=[])) is None


def test_inventing_extra_entries_is_rejected():
    """More entries out than in means it fabricated, not deduplicated."""
    result = ConsolidatedRecord(notes=NOTES + ["also plays the piano"], met_at=PLACES)
    assert _safe_consolidation(NOTES, PLACES, result) is None


def test_places_fall_back_to_the_original_when_the_model_drops_them_all():
    result = ConsolidatedRecord(notes=NOTES[:2] + NOTES[2:], met_at=[])
    out = _safe_consolidation(NOTES, PLACES, result)
    assert out is not None
    assert out["met_at"] == PLACES


def test_short_records_are_left_alone_without_a_model_call(monkeypatch):
    """Two notes is not worth a Bedrock call."""
    from recall.nodes import merge

    monkeypatch.setattr(
        merge, "chat_model", lambda **kw: pytest.fail("should not call the model")
    )
    assert merge._consolidate({"name": "X", "notes": ["a", "b"], "met_at": ["camp"]}) is None


# --------------------------------------------------------------------------
# as_list: the boundary normaliser.
# --------------------------------------------------------------------------

from recall.state import as_list


def test_a_bare_string_becomes_one_entry_not_one_per_character():
    """`list("masters")` is ['m','a','s','t','e','r','s'].

    Observed once in a real run: a note came back as ~90 single-character
    entries, which then persisted, deduped and consolidated without raising.
    Model output shape is not guaranteed even at temperature 0, so the field is
    normalised at the boundary instead of trusted."""
    assert as_list("doing his masters in robotics") == ["doing his masters in robotics"]
    assert len(as_list("masters")) == 1


def test_as_list_passes_lists_through_and_drops_blanks():
    assert as_list(["a", "b"]) == ["a", "b"]
    assert as_list(["a", "  ", None, "b"]) == ["a", "b"]


def test_as_list_handles_none_and_empty():
    assert as_list(None) == []
    assert as_list("") == []
    assert as_list("   ") == []
    assert as_list([]) == []


def test_store_survives_a_string_where_a_list_was_expected(tmp_path):
    """End to end: a malformed record must not explode into character notes."""
    from recall.memory import LocalPersonStore

    store = LocalPersonStore(tmp_path / "graph.json")
    rec = store.upsert({"name": "Daniel Ong", "notes": "doing his masters in robotics",
                        "met_at": "NUS AI meetup"})

    assert rec["notes"] == ["doing his masters in robotics"]
    assert rec["met_at"] == ["NUS AI meetup"]
