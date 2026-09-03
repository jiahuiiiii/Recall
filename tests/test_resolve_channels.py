"""The name channel and the descriptor channel must stay separate.

W_DESCRIPTOR_MAX is capped below T_MATCH so a description can never auto-resolve
on its own. These tests pin the two routes that defeated that cap by feeding a
description into the uncapped name channel instead. Both were measured on
arc_acacia, not imagined.
"""

from __future__ import annotations

from recall.resolve import Zone, compare, decide, score, zone

# Marvi as she stood after "the indian girl" merged into her on m16: a real
# name, plus a DESCRIPTION sitting in her aliases.
MARVI = {
    "id": "p_marvi", "name": "Marvi", "aliases": ["indian girl"], "met_at": [],
    "notes": ["an Indian girl live at the same region as me", "comes from India",
              "not Singaporean Indian", "studying econ"],
}
SHINY = {
    "id": "p_shiny", "name": "Shiny", "aliases": [], "met_at": [],
    "notes": ["Catholic Indian", "studies Business AI system", "met in UTC2851"],
}
CATHOLIC_INDIAN = {
    "name": "the Catholic Indian", "aliases": [],
    "notes": ["said she want to work as management officers in IT industry later"],
}


def test_a_description_in_aliases_is_not_a_name():
    """The arc_acacia wrong merge.

    "the indian girl" merged into Marvi, which stored that phrase in her
    aliases. Four memos later "the Catholic Indian" -- a different person --
    matched it at 1.00 on the shared token `indian`, took the uncapped name
    channel at full weight, and auto-resolved. Shiny became Marvi silently.
    """
    a = compare(CATHOLIC_INDIAN, MARVI)
    assert a.name == 0.0, "a descriptor alias must not be compared as a name"
    assert zone(score(a)) is not Zone.RESOLVED


def test_the_right_person_outranks_the_wrong_one():
    """Not merging is not enough -- the correct record has to come first, or the
    question that follows is chosen over the wrong hypotheses."""
    z, ranked = decide(CATHOLIC_INDIAN, [MARVI, SHINY])
    assert ranked[0].record_id == "p_shiny"
    assert z is Zone.AMBIGUOUS


def test_a_description_still_recalls_the_person_it_describes():
    """The fix must not buy precision by making descriptors useless. "the indian
    girl" is how this person was actually referred to, and must still LAND as a
    live hypothesis -- it just asks rather than auto-merges now.

    Under the To fix #2 policy (decided 3 Sep) a nameless match is capped into
    the ambiguous band: recalled, scored, and put to a question, never silently
    resolved. AMBIGUOUS is the correct landing, not RESOLVED and not NEW."""
    described = {"name": "indian girl", "aliases": [],
                 "notes": ["comes from India", "not Singaporean Indian", "studying econ"]}
    a = compare(described, MARVI)
    assert a.descriptor > 0.0
    assert zone(score(a)) is Zone.AMBIGUOUS


def test_a_record_is_not_evidence_about_itself():
    """`_descriptor_match` was passed the RECORD's own labels when the mention
    was named, comparing the record against itself and manufacturing a free
    desc=1.00 -- up to 2.0 of agreement from one side alone."""
    descriptor_only = {"id": "p", "name": "the indian girl", "aliases": [],
                       "notes": ["lives on 4th floor"]}
    a = compare({"name": "Shiny", "aliases": [], "notes": []}, descriptor_only)
    assert a.descriptor == 0.0
    assert score(a) == 0.0


def test_a_leading_article_marks_a_description():
    """"catholic" and "indian" are in neither DESCRIPTOR_WORDS nor any name
    list, so the phrase used to pass as a name. People say "the Catholic
    Indian"; nobody says "the Alex"."""
    from recall.resolve import _is_name
    assert not _is_name("the Catholic Indian")
    assert not _is_name("The 04 track OGL guy")
    assert _is_name("Marvi")
    assert _is_name("Kit Yee")
    assert _is_name("D'anna")


# --- an unrecognised name is not evidence of a different person -------------

CHUEI = {
    "id": "p_chuei", "name": "Tiu Chuei Enn", "aliases": [], "met_at": ["Acacia College"],
    "notes": ["from malaysian chinese independent school", "lives on the 4th floor",
              "studies computer science at NUS",
              "high school friend, everyone calls her Crispy"],
}
VIKTORIA = {
    "id": "p_vik", "name": "Viktoria", "aliases": [], "met_at": ["the dining hall"],
    "notes": ["from germany", "on exchange at NUS", "lives in Tembusu College"],
}


def test_a_nickname_recorded_in_notes_is_found():
    """Measured on the real graph. "Crispy" shares nothing with "Tiu Chuei Enn",
    so the name channel conflicted at -1.5 and filed a duplicate -- while her own
    record said "everyone calls her Crispy". The nickname was in the record; only
    `name` and `aliases` were being read."""
    a = compare({"name": "Crispy", "aliases": [], "notes": []}, CHUEI)
    assert not a.name_conflict
    assert a.descriptor > 0.0
    assert zone(score(a)) is Zone.AMBIGUOUS, "should buy a question, not a duplicate"


def test_an_unrelated_name_still_conflicts():
    """The guard rail. If any unrecognised name went ambiguous, every stranger
    would be a candidate for everyone and the band would stop meaning anything."""
    a = compare({"name": "Harold", "aliases": [], "notes": []}, VIKTORIA)
    assert a.name_conflict
    assert zone(score(a)) is Zone.NEW


def test_a_nickname_does_not_latch_onto_the_wrong_person():
    a = compare({"name": "Crispy", "aliases": [], "notes": []}, VIKTORIA)
    assert zone(score(a)) is Zone.NEW


def test_a_nickname_alone_cannot_auto_resolve():
    """It routes through the capped descriptor channel, so it can reach the band
    but never past T_MATCH on its own -- a nickname is a question, not proof."""
    a = compare({"name": "Crispy", "aliases": [], "notes": []}, CHUEI)
    assert score(a) < 3.0


def test_a_genuine_return_still_resolves():
    a = compare({"name": "Tiu Chuei Enn", "met_at": "Acacia College", "aliases": [],
                 "notes": []}, CHUEI)
    assert zone(score(a)) is Zone.RESOLVED
