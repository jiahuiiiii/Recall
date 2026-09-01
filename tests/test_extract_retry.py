"""Extraction retries a malformed structured-output response.

Nova intermittently returns `people` as a string. When it is well-formed JSON,
`state.decode_list` coerces it. When it is MALFORMED it cannot be coerced, only
re-asked — and a single un-retried memo used to unwind an entire run of the
question benchmark, which is why two headline tables ran at n=2.
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


class _Flaky:
    """Raises like the real thing for `n_bad` calls, then succeeds."""

    def __init__(self, n_bad: int) -> None:
        self.n_bad = n_bad
        self.calls = 0

    def invoke(self, _messages, **__):
        self.calls += 1
        if self.calls <= self.n_bad:
            return PeopleExtraction.model_validate({"people": MALFORMED})
        return GOOD


def _install(monkeypatch, flaky):
    class _M:
        def with_structured_output(self, *_a, **_k):
            return flaky
    monkeypatch.setattr(extract_mod, "chat_model", lambda **_: _M())


def test_a_malformed_response_is_retried_and_succeeds(monkeypatch):
    flaky = _Flaky(n_bad=1)
    _install(monkeypatch, flaky)
    out = extract_mod.extract_people_node(
        {"transcript": "The dyed-hair OGL guy told us IVP trials start next Tuesday."}
    )
    assert [p["name"] for p in out["people"]] == ["OGL guy"]
    assert flaky.calls == 2, "should have re-asked exactly once"


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
