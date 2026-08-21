"""The cost ledger is only useful if it sees every call and prices it honestly."""

from __future__ import annotations

import pytest

from recall._common import UsageCallback, UsageLedger, pricing_for


class _Msg:
    def __init__(self, usage): self.usage_metadata = usage


class _Gen:
    def __init__(self, usage): self.message = _Msg(usage)


class _Result:
    """Shaped like a langchain LLMResult."""
    def __init__(self, usage): self.generations = [[_Gen(usage)]]


@pytest.fixture(autouse=True)
def fresh_ledger(monkeypatch):
    ledger = UsageLedger()
    monkeypatch.setattr("recall._common.LEDGER", ledger)
    return ledger


def test_callback_records_usage_off_a_reply(fresh_ledger):
    handler = UsageCallback("extract_people", "global.anthropic.claude-haiku-4-5-20251001-v1:0")
    handler.on_llm_end(_Result({"input_tokens": 500, "output_tokens": 40}))

    assert fresh_ledger.calls == 1
    assert fresh_ledger.input_tokens == 500
    assert fresh_ledger.output_tokens == 40


def test_cached_tokens_are_not_priced_as_fresh_input(fresh_ledger):
    """Cache reads are 10x cheaper than fresh input. Counting them as input
    would overstate the run cost by roughly an order of magnitude."""
    fresh_ledger.record(
        "step",
        {
            "input_tokens": 1200,  # langchain folds cached tokens into this
            "output_tokens": 10,
            "input_token_details": {"cache_read": 1000},
        },
        "global.anthropic.claude-haiku-4-5-20251001-v1:0",
    )

    assert fresh_ledger.input_tokens == 200
    assert fresh_ledger.cache_read_tokens == 1000
    assert fresh_ledger.cost_usd == pytest.approx((200 * 1 + 1000 * 0.10 + 10 * 5) / 1e6)


def test_pricing_prefers_the_longest_matching_key():
    """'claude-3-5-sonnet' and 'claude-3-haiku' both contain shorter fragments;
    a shortest-match lookup would price Sonnet at Haiku rates."""
    assert pricing_for("apac.anthropic.claude-3-5-sonnet-20241022-v2:0") == (3.0, 15.0, 3.75, 0.30)
    assert pricing_for("anthropic.claude-3-haiku-20240307-v1:0") == (0.25, 1.25, 0.30, 0.025)
    assert pricing_for("apac.amazon.nova-pro-v1:0") == (0.80, 3.20, 1.00, 0.08)


def test_unknown_model_reports_tokens_but_refuses_to_invent_a_cost(fresh_ledger):
    """A confidently wrong cost figure is worse than an honest blank."""
    fresh_ledger.record("enricher", {"input_tokens": 10_000, "output_tokens": 500}, "some.new.model")

    assert fresh_ledger.input_tokens == 10_000
    assert fresh_ledger.cost_usd == 0.0
    assert fresh_ledger.unpriced_models == {"some.new.model"}
    assert "excludes unpriced" in fresh_ledger.report()


def test_mixed_models_price_independently(fresh_ledger):
    """A run that falls back mid-way must not price every call at one rate."""
    fresh_ledger.record("a", {"input_tokens": 1_000_000, "output_tokens": 0}, "apac.amazon.nova-pro-v1:0")
    fresh_ledger.record("b", {"input_tokens": 1_000_000, "output_tokens": 0}, "global.anthropic.claude-haiku-4-5-20251001-v1:0")

    assert fresh_ledger.cost_usd == pytest.approx(0.80 + 1.00)
