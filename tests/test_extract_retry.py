"""Extraction retries a malformed structured-output response.

Nova intermittently returns `people` as a string. When it is well-formed JSON,
`state.decode_list` coerces it. When it is malformed the node RE-ASKS -- a
resample recovers the whole memo, where a salvage recovers only its head -- and
only once every attempt has failed does it keep the complete people ahead of the
break, saying so in its summary. A single un-retried memo used to unwind an
entire run of the question benchmark, which is why two headline tables ran at n=2.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

import recall.nodes.extract as extract_mod
from recall.state import PeopleExtraction, Person

GOOD = PeopleExtraction(people=[
    Person(name="OGL guy", notes=["told us IVP trials start next Tuesday"],
           aliases=[], substantive=True)
])

# The shape actually observed: `met_at` after its object was already closed.
MALFORMED = '[{"name": "OGL guy", "substantive": true}]}, "met_at": "MPSH"}]'
UNSALVAGEABLE = '[{"name":'


# A break in the MIDDLE: the model closed one person, corrupted the next, and
# the third is complete but unreachable behind the break. Salvage keeps the head
# and must not pretend the rest never existed.
BROKEN_MIDDLE = (
    '[{"name": "OGL guy", "substantive": true}, {"name": , }, '
    '{"name": "Wei Lin", "substantive": true}]'
)


class _Flaky:
    """Raises like the real thing for `n_bad` calls, then succeeds."""

    def __init__(self, n_bad: int, payload: str = UNSALVAGEABLE) -> None:
        self.n_bad = n_bad
        self.payload = payload
        self.calls = 0

    def invoke(self, _messages, **__):
        self.calls += 1
        if self.calls <= self.n_bad:
            return PeopleExtraction.model_validate({"people": self.payload})
        return GOOD


def _install(monkeypatch, flaky):
    class _M:
        def with_structured_output(self, *_a, **_k):
            return flaky
    monkeypatch.setattr(extract_mod, "chat_model", lambda **_: _M())


def test_a_resample_is_preferred_to_a_salvage(monkeypatch):
    """The head of a malformed list is a PARTIAL memo; a resample is a whole one.

    Salvaging on the first failure would quietly trade recall for one saved
    model call, in exactly the case the retry was built for.
    """
    flaky = _Flaky(n_bad=1, payload=MALFORMED)
    _install(monkeypatch, flaky)
    out = extract_mod.extract_people_node({"transcript": "anything"})
    assert flaky.calls == 2, "a salvageable response must still be re-asked"
    assert "Salvaged" not in out["messages"][0].content


def test_a_complete_person_before_a_malformed_tail_survives_a_lost_memo(monkeypatch):
    flaky = _Flaky(n_bad=99, payload=MALFORMED)
    _install(monkeypatch, flaky)
    out = extract_mod.extract_people_node({"transcript": "anything"})
    assert [p["name"] for p in out["people"]] == ["OGL guy"]
    assert flaky.calls == extract_mod.EXTRACT_ATTEMPTS


def test_a_salvage_says_it_salvaged(monkeypatch):
    """A partial extraction that reads like a clean one is the whole failure.

    `Extracted 1 people: OGL guy.` is indistinguishable from a memo that
    genuinely mentions one person, and the eval scores the loss as a missed
    recognition with nothing to explain it.
    """
    flaky = _Flaky(n_bad=99, payload=BROKEN_MIDDLE)
    _install(monkeypatch, flaky)
    out = extract_mod.extract_people_node({"transcript": "anything"})

    assert [p["name"] for p in out["people"]] == ["OGL guy"]
    note = out["messages"][0].content
    assert "Salvaged 1 person(s)" in note
    # Wei Lin is complete but sits behind the break, and resyncing past a broken
    # object can invent a person nobody mentioned -- so she is lost on purpose,
    # and the note has to admit it.
    assert "abandoned" in note
    assert "Wei Lin" not in note


def test_salvage_keeps_the_head_and_reports_the_tail_it_could_not_read():
    from recall.state import salvage_object_list

    kept, abandoned = salvage_object_list(MALFORMED)
    assert [p["name"] for p in kept] == ["OGL guy"]
    assert abandoned == "", "the array closed cleanly; the trailing noise cost nobody"

    kept, abandoned = salvage_object_list(BROKEN_MIDDLE)
    assert [p["name"] for p in kept] == ["OGL guy"]
    assert "Wei Lin" in abandoned, "a person was lost; the caller must be able to see it"

    assert salvage_object_list(UNSALVAGEABLE)[0] == []


def test_a_wholly_malformed_response_is_retried_and_succeeds(monkeypatch):
    flaky = _Flaky(n_bad=1)
    _install(monkeypatch, flaky)
    out = extract_mod.extract_people_node(
        {"transcript": "The dyed-hair OGL guy told us IVP trials start next Tuesday."}
    )
    assert [p["name"] for p in out["people"]] == ["OGL guy"]
    assert flaky.calls == 2, "should have re-asked exactly once"


def test_retry_explains_the_required_repair_to_the_model(monkeypatch):
    class _InspectingFlaky(_Flaky):
        def __init__(self) -> None:
            super().__init__(n_bad=1)
            self.message_sets = []

        def invoke(self, messages, **kwargs):
            self.message_sets.append(messages)
            return super().invoke(messages, **kwargs)

    flaky = _InspectingFlaky()
    _install(monkeypatch, flaky)
    extract_mod.extract_people_node({"transcript": "anything"})
    assert "previous structured response was malformed" in flaky.message_sets[1][-1].content


def test_it_gives_up_rather_than_returning_nobody(monkeypatch):
    """Raising is the honest failure. Returning an empty list would look
    identical to a memo that genuinely mentions no one, and the eval would score
    it as a missed recognition with no error to explain it."""
    flaky = _Flaky(n_bad=99)
    _install(monkeypatch, flaky)
    with pytest.raises(ValidationError):
        extract_mod.extract_people_node({"transcript": "anything"})
    assert flaky.calls == extract_mod.EXTRACT_ATTEMPTS


def test_a_clean_response_costs_one_call(monkeypatch):
    flaky = _Flaky(n_bad=0)
    _install(monkeypatch, flaky)
    extract_mod.extract_people_node({"transcript": "anything"})
    assert flaky.calls == 1, "retry must not cost a call on the happy path"
