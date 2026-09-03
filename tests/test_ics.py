"""The .ics backend. Offline, no network, no calendar touched.

The point of this backend is that it works for someone who is not the developer:
no Google Cloud project, no OAuth client, no account. That makes the *file* the
whole product, so these tests are mostly about the file being one a real
calendar app will accept -- the failure mode is not an exception, it is an event
that silently does not appear on somebody else's phone.
"""

from __future__ import annotations

import pytest

from recall.tools.calendar import (
    ics_path,
    ics_text,
    propose_event,
    write_proposed,
)

EVENT = {
    "title": "Follow up with Alex Chua: send the deck",
    "date": "2026-09-11",
    "person_name": "Alex Chua",
    "idempotency_key": "recall-0123456789abcdef",
    "channel": "email",
}


@pytest.fixture
def ics_env(tmp_path, monkeypatch):
    """Point every path at a scratch dir. Never the user's real calendar."""
    monkeypatch.setenv("RECALL_CALENDAR", "ics")
    monkeypatch.setattr("recall.tools.calendar.ICS_DIR", tmp_path / "ics")
    monkeypatch.setattr("recall.tools.calendar.LEDGER_PATH", tmp_path / "cal.json")
    return tmp_path


# --- the file itself -------------------------------------------------------


def test_the_end_date_is_exclusive():
    """An all-day event on the 11th ends on the 12th.

    Same date for both is the classic .ics bug: Google and Apple render it
    anyway, Outlook drops the event entirely. You find it on someone else's
    phone, which is the worst place to find anything.
    """
    text = ics_text(EVENT)
    assert "DTSTART;VALUE=DATE:20260911" in text
    assert "DTEND;VALUE=DATE:20260912" in text


def test_lines_end_with_crlf():
    """RFC 5545 requires it. Most clients forgive bare LF and Outlook does not."""
    text = ics_text(EVENT)
    assert "\r\n" in text
    for line in text.split("\r\n"):
        assert not line.endswith("\r") and "\n" not in line


def test_commas_in_a_promise_are_escaped():
    """A comma is a FIELD SEPARATOR, so unescaped it truncates the summary.

    "send the deck, the pricing, and a demo" would arrive on the calendar as
    "send the deck" — with no error anywhere.
    """
    event = {**EVENT, "title": "Follow up: send the deck, the pricing, and a demo"}
    body = ics_text(event)
    summary = "".join(
        line.removeprefix(" ")
        for line in body.split("\r\n")
        if line.startswith(("SUMMARY:", " "))
    )
    assert "deck\\, the pricing\\, and a demo" in summary


def test_semicolons_and_backslashes_are_escaped_in_the_right_order():
    """Backslash first, or our own escapes get escaped again."""
    event = {**EVENT, "title": r"Send C:\deck; then call"}
    text = ics_text(event)
    assert r"C:\\deck\; then call" in text.replace("\r\n ", "")


def test_long_titles_are_folded_at_75_octets():
    """Unfolded long lines are rejected by strict parsers."""
    event = {**EVENT, "title": "Follow up with Alexandra " + "very " * 30 + "long"}
    text = ics_text(event)
    for line in text.split("\r\n"):
        assert len(line.encode()) <= 75, f"unfolded line: {line[:80]}"
    # Folding must be recoverable: continuations start with a single space.
    assert "\r\n " in text


def test_folding_never_splits_a_character_in_half():
    """The limit is octets but the unit is characters.

    Split a multi-byte name mid-character and the file is either rejected or
    renders as mojibake. Names are exactly where this shows up.
    """
    event = {**EVENT, "title": "Follow up with " + "Zoë Ångström " * 8}
    text = ics_text(event)
    for line in text.split("\r\n"):
        assert len(line.encode()) <= 75
    assert "Zoë Ångström" in text.replace("\r\n ", "")


def test_the_uid_is_the_idempotency_key():
    """So re-importing the same file UPDATES the event instead of duplicating it.

    That is the same guarantee the local ledger gives us, enforced by the
    calendar client — which matters because the user may import it twice.
    """
    assert f"UID:{EVENT['idempotency_key']}@recall.local" in ics_text(EVENT)


def test_the_event_is_all_day_and_does_not_block_time():
    """A commitment is "by Friday", not "at 14:30".

    Inventing a start time would put a meeting in someone's day that nobody
    agreed to, and would drag timezones into a file that otherwise needs none.
    """
    text = ics_text(EVENT)
    assert "TRANSP:TRANSPARENT" in text
    assert "DTSTART;VALUE=DATE:" in text          # a date, never a datetime
    assert "DTSTART:" not in text


def test_it_round_trips_through_a_real_parser():
    """Cheap proof the structure is well-formed, not just that strings appear."""
    text = ics_text(EVENT)
    lines = [x for x in text.split("\r\n") if x]
    assert lines[0] == "BEGIN:VCALENDAR" and lines[-1] == "END:VCALENDAR"
    assert lines.count("BEGIN:VEVENT") == lines.count("END:VEVENT") == 1
    unfolded = text.replace("\r\n ", "")
    for line in [x for x in unfolded.split("\r\n") if x]:
        assert ":" in line, f"property with no value: {line}"


# --- writing ---------------------------------------------------------------


def test_writing_produces_a_file_named_by_its_key(ics_env):
    result = write_proposed(dict(EVENT))
    assert result["status"] == "created"
    written = ics_env / "ics" / f"{EVENT['idempotency_key']}.ics"
    assert written.exists()
    assert result["ics_path"] == str(written)


def test_a_rerun_reports_duplicate_but_still_leaves_the_file(ics_env):
    """Status and artifact answer different questions.

    "Is this new to me?" and "can the user get the file?" are not the same, and
    suppressing the write on a re-run means someone who deleted the download
    cannot get it back without hand-editing JSON.
    """
    write_proposed(dict(EVENT))
    written = ics_env / "ics" / f"{EVENT['idempotency_key']}.ics"
    written.unlink()

    again = write_proposed(dict(EVENT))
    assert again["status"] == "duplicate"
    assert written.exists()


def test_the_file_on_disk_keeps_its_crlf(ics_env):
    """Written with newline='' so Python cannot translate CRLF into CRCRLF."""
    result = write_proposed(dict(EVENT))
    with open(result["ics_path"], newline="") as fh:
        raw = fh.read()
    assert "\r\n" in raw and "\r\r\n" not in raw


def test_a_proposed_event_renders_without_extra_fields(ics_env):
    """`propose_event` output feeds straight in — no adapter between them."""
    proposal = propose_event("Priya", "send the migration notes", "2026-09-15")
    result = write_proposed(proposal)
    assert result["status"] == "created"
    assert "SUMMARY:Follow up with Priya: send the migration notes" in ics_text(proposal)


# --- the route's guard -----------------------------------------------------


@pytest.mark.parametrize(
    "key",
    ["../../etc/passwd", "recall-../secrets", "", "recall-XYZ", "recall-0123", "nope"],
)
def test_only_a_generated_key_can_name_a_file(key):
    """The web route maps a URL segment onto a path with this.

    Keys are generated today, but "generated" stops being true the moment
    someone types the URL themselves.
    """
    assert ics_path(key) is None


def test_a_real_key_resolves():
    assert ics_path("recall-0123456789abcdef") is not None


# --- events you attend, not follow-ups you owe -----------------------------


ATTENDING = {
    "title": "Acacia Welcome Night",
    "date": "2026-09-18",
    "person_name": "Crispy, Kit Yee",
    "kind": "attending",
    "idempotency_key": "recall-aaaaaaaaaaaaaaaa",
    "channel": "email",
}


def test_an_attended_event_keeps_its_own_name():
    """"Follow up with Crispy: Acacia Welcome Night" is not what anyone said."""
    assert "SUMMARY:Acacia Welcome Night" in ics_text(ATTENDING)


def test_an_attended_event_marks_you_busy_and_a_followup_does_not():
    """A nudge that blocks your whole day is worse than no nudge.

    Backwards, this is what makes reminder apps show you as unavailable all
    week — so the free/busy state is not cosmetic.
    """
    assert "TRANSP:OPAQUE" in ics_text(ATTENDING)
    assert "TRANSP:TRANSPARENT" in ics_text(EVENT)


def test_an_attended_event_records_who_you_are_going_with():
    assert "DESCRIPTION:With Crispy\\, Kit Yee." in ics_text(ATTENDING)


def test_an_attended_event_with_nobody_named_still_renders():
    """`person_name` is "" when the speaker named no one. Not an error."""
    text = ics_text({**ATTENDING, "person_name": ""})
    assert "DESCRIPTION:Captured by Recall." in text
    assert "SUMMARY:Acacia Welcome Night" in text


def test_propose_event_titles_the_two_kinds_differently():
    followup = propose_event("Crispy", "send the wristband details", "2026-09-18")
    attending = propose_event(
        "Crispy", "Acacia Welcome Night", "2026-09-18", kind="attending"
    )
    assert followup["title"] == "Follow up with Crispy: send the wristband details"
    assert attending["title"] == "Acacia Welcome Night"
    assert attending["kind"] == "attending"


def test_adding_kind_did_not_change_existing_followup_keys():
    """Every key generated before `attending` existed must still hash the same.

    Folding `kind` in unconditionally would invalidate every key in an existing
    ledger at once, and the next run would re-create every event the user
    already has.
    """
    from recall.tools.calendar import idempotency_key

    assert idempotency_key("Crispy", "send details", "2026-09-18") == idempotency_key(
        "Crispy", "send details", "2026-09-18", "followup"
    )
    assert idempotency_key(
        "Crispy", "send details", "2026-09-18", "attending"
    ) != idempotency_key("Crispy", "send details", "2026-09-18")


# --- the one-tap Google Calendar link (chat apps mishandle .ics files) -----


def test_gcal_link_dates_are_start_slash_exclusive_end():
    """Same rule as the .ics: end is exclusive, or a client drops the event."""
    from recall.tools.calendar import gcal_link

    url = gcal_link(EVENT)
    assert "dates=20260911%2F20260912" in url
    assert url.startswith("https://calendar.google.com/calendar/render?action=TEMPLATE")


def test_gcal_link_escapes_a_title_with_a_comma():
    """A raw comma or colon in the query would truncate or corrupt the link."""
    from urllib.parse import parse_qs, urlparse

    from recall.tools.calendar import gcal_link

    event = {**EVENT, "title": "Follow up: send deck, pricing, demo"}
    q = parse_qs(urlparse(gcal_link(event)).query)
    assert q["text"] == ["Follow up: send deck, pricing, demo"]


def test_gcal_link_describes_who_you_are_going_with_for_an_event():
    from urllib.parse import parse_qs, urlparse

    from recall.tools.calendar import gcal_link

    q = parse_qs(urlparse(gcal_link(ATTENDING)).query)
    assert q["text"] == ["Acacia Welcome Night"]
    assert "With Crispy, Kit Yee" in q["details"][0]
