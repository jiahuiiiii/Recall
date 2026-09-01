"""Structured output is not a guarantee about the wire format.

Bedrock intermittently returns a list field as a JSON *string*. It killed one
memo in a resolution sweep and an entire run of the question benchmark, which is
why the 30 Aug headline table is n=2. These pin the coercion.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from recall.state import PeopleExtraction, Person

DOUBLE_ENCODED = json.dumps([
    {"name": "Big Boss", "company": None, "role": None, "met_at": None,
     "notes": ["gives off the same vibe as Quiet One"], "aliases": [], "substantive": True},
    {"name": "Quiet One", "company": None, "role": None, "met_at": None,
     "notes": ["very quiet"], "aliases": [], "substantive": True},
])


def test_people_arriving_as_a_json_string_is_decoded():
    """The measured failure: `Input should be a valid list [input_type=str]`."""
    got = PeopleExtraction.model_validate({"people": DOUBLE_ENCODED})
    assert [p.name for p in got.people] == ["Big Boss", "Quiet One"]


def test_a_real_list_is_untouched():
    got = PeopleExtraction.model_validate(
        {"people": [{"name": "Marvi", "notes": [], "aliases": [], "substantive": True}]}
    )
    assert [p.name for p in got.people] == ["Marvi"]


def test_empty_and_missing_are_empty_not_errors():
    assert PeopleExtraction.model_validate({"people": ""}).people == []
    assert PeopleExtraction.model_validate({}).people == []


def test_a_string_that_is_not_json_still_raises():
    """Coercion must not swallow a genuine schema violation -- otherwise the next
    real failure is invisible instead of loud."""
    with pytest.raises(ValidationError):
        PeopleExtraction.model_validate({"people": "not json at all"})


def test_list_fields_take_json_strings_without_exploding():
    """`list("a string")` yields per-character entries. A bare string must stay
    one entry; a JSON array must become its elements."""
    p = Person.model_validate(
        {"name": "X", "notes": '["a","b"]', "aliases": "CJ", "substantive": True}
    )
    assert p.notes == ["a", "b"]
    assert p.aliases == ["CJ"]

    bare = Person.model_validate(
        {"name": "X", "notes": "she is nice", "aliases": [], "substantive": True}
    )
    assert bare.notes == ["she is nice"]
