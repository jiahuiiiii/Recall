"""The cost ledger is only useful if it sees every call.

Structured output is the easy one to get wrong: the parsed object carries no
usage, so an unwrapped implementation reports ~zero cost for a graph that is
almost entirely structured calls.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from recall._common import UsageLedger, _MeteredModel


class Thing(BaseModel):
    value: str


class _Reply:
    def __init__(self, usage: dict) -> None:
        self.usage_metadata = usage
        self.content = "hi"


class _FakeInner:
    def __init__(self, usage: dict, parsed: Any = None, error: Any = None) -> None:
        self._usage = usage
        self._parsed = parsed
        self._error = error
        self.structured_kwargs: dict = {}

    def invoke(self, *_: Any, **__: Any) -> Any:
        return _Reply(self._usage)

    def with_structured_output(self, schema: Any, **kwargs: Any) -> "_FakeInner":
        self.structured_kwargs = kwargs
        inner = _FakeInner(self._usage, self._parsed, self._error)
        inner.invoke = lambda *a, **k: {  # type: ignore[method-assign]
            "raw": _Reply(self._usage),
            "parsed": self._parsed,
            "parsing_error": self._error,
        }
        return inner


@pytest.fixture(autouse=True)
def fresh_ledger(monkeypatch):
    ledger = UsageLedger()
    monkeypatch.setattr("recall._common.LEDGER", ledger)
    return ledger


def test_plain_invoke_is_metered(fresh_ledger):
    model = _MeteredModel(_FakeInner({"input_tokens": 100, "output_tokens": 20}), "step")
    model.invoke([])
    assert fresh_ledger.calls == 1
    assert fresh_ledger.input_tokens == 100
    assert fresh_ledger.output_tokens == 20


def test_structured_output_is_metered_and_returns_the_parsed_object(fresh_ledger):
    inner = _FakeInner({"input_tokens": 500, "output_tokens": 40}, parsed=Thing(value="ok"))
    structured = _MeteredModel(inner, "extract").with_structured_output(Thing)

    result = structured.invoke([])

    # Node code gets the typed object, not the include_raw envelope.
    assert isinstance(result, Thing)
    assert result.value == "ok"
    # ...and the tokens were still counted.
    assert fresh_ledger.calls == 1
    assert fresh_ledger.by_label["extract"]["in"] == 500


def test_cached_tokens_are_not_priced_as_fresh_input(fresh_ledger):
    """Cache reads are 10x cheaper than fresh input. Counting them as input
    would overstate the run cost by roughly an order of magnitude."""
    model = _MeteredModel(
        _FakeInner(
            {
                "input_tokens": 1200,  # langchain folds cached tokens into this
                "output_tokens": 10,
                "input_token_details": {"cache_read": 1000},
            }
        ),
        "step",
    )
    model.invoke([])

    assert fresh_ledger.input_tokens == 200
    assert fresh_ledger.cache_read_tokens == 1000
    # 200 fresh @ $1/M + 1000 cached @ $0.10/M + 10 out @ $5/M
    assert fresh_ledger.cost_usd == pytest.approx((200 * 1 + 1000 * 0.10 + 10 * 5) / 1e6)


def test_parsing_failure_names_the_step_and_the_schema(fresh_ledger):
    inner = _FakeInner({"input_tokens": 10, "output_tokens": 1}, parsed=None, error="bad json")
    structured = _MeteredModel(inner, "dedupe").with_structured_output(Thing)

    with pytest.raises(ValueError, match="dedupe: model output did not match Thing"):
        structured.invoke([])
