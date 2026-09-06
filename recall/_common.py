"""Shared model factory, cost accounting, and prompt-cache helpers.

Everything that talks to Bedrock goes through `chat_model()`. Nothing in the
graph imports a client class directly, so swapping region/model/credentials is
a one-file change.

Metering is a callback handler, not a wrapper object. A wrapper looks simpler
until something downstream type-checks the model -- `create_react_agent`
demands a real Runnable and rejects anything else -- and then the sub-agent
dies at runtime while every unit test that stubbed the agent still passes.
A callback rides along on the real model and survives `with_structured_output`,
`bind_tools`, and the react loop untouched.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Any

# .env is loaded in recall/__init__.py, which runs before any submodule.

# Nova 2 Lite through the US cross-region profile is the code default because
# it is callable on the hackathon account and is the same model family the
# published benchmark and rehearsed demo use. Sonnet 4.6 is callable there too,
# but its extraction choices changed the demo's candidate graph. The variable
# keeps its historical name; everything reads HAIKU.
_DEFAULT_HAIKU = "us.amazon.nova-2-lite-v1:0"
_DEFAULT_SONNET = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"

HAIKU = os.environ.get("RECALL_MODEL_ID", _DEFAULT_HAIKU)
SONNET = os.environ.get("RECALL_SONNET_MODEL_ID", _DEFAULT_SONNET)

# Bedrock follows the CLI default region, not the SSO region (and on a personal
# account, whatever `aws configure` wrote into ~/.aws/config). Setting it in one
# place and defaulting loudly is what stops the "works for me, 404s for you" bug.
# us-east-1 matches the default model above: the judges' account denies every
# model in ap-southeast-1, so a fresh clone with no .env has to land somewhere
# that works.
DEFAULT_REGION = os.environ.get("AWS_REGION") or os.environ.get(
    "AWS_DEFAULT_REGION", "us-east-1"
)

# USD per million tokens: (input, output, cache_write, cache_read).
# Keyed by substring, longest match wins. Only rates worth trusting go in here:
# an unlisted model reports its token counts and declines to invent a price,
# because a confidently wrong cost figure is worse than an honest blank.
PRICING: dict[str, tuple[float, float, float, float]] = {
    "claude-haiku-4-5": (1.00, 5.00, 1.25, 0.10),
    "claude-sonnet-4-5": (3.00, 15.00, 3.75, 0.30),
    "claude-3-haiku": (0.25, 1.25, 0.30, 0.025),
    "claude-3-5-sonnet": (3.00, 15.00, 3.75, 0.30),
    "nova-micro": (0.035, 0.14, 0.0875, 0.00875),
    "nova-lite": (0.06, 0.24, 0.15, 0.015),
    "nova-pro": (0.80, 3.20, 1.00, 0.08),
}


def pricing_for(model_id: str) -> tuple[float, float, float, float] | None:
    """Rates for a model id, or None when we have no trustworthy figure."""
    match = ""
    for key in PRICING:
        if key in model_id and len(key) > len(match):
            match = key
    return PRICING[match] if match else None


@dataclass
class _Row:
    calls: int = 0
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0


@dataclass
class UsageLedger:
    """Running token/cost tally, keyed by (graph step, model).

    Cost is measured per prompt, not discovered at month-end, so every model
    call lands here and the total prints at the end of a run.
    """

    rows: dict[tuple[str, str], _Row] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, label: str, usage: dict[str, Any] | None, model: str = "") -> None:
        if not usage:
            return
        details = usage.get("input_token_details") or {}
        cache_read = int(details.get("cache_read") or 0)
        cache_write = int(details.get("cache_creation") or 0)
        # langchain folds cached tokens into input_tokens; split them out so the
        # cheap reads are not priced as fresh input (they are ~10x cheaper).
        raw_in = int(usage.get("input_tokens") or 0)
        fresh_in = max(raw_in - cache_read - cache_write, 0)
        out = int(usage.get("output_tokens") or 0)

        with self._lock:
            row = self.rows.setdefault((label, model), _Row())
            row.calls += 1
            row.input += fresh_in
            row.output += out
            row.cache_read += cache_read
            row.cache_write += cache_write

    # -- aggregate views, kept flat for convenience ------------------------
    @property
    def calls(self) -> int:
        return sum(r.calls for r in self.rows.values())

    @property
    def input_tokens(self) -> int:
        return sum(r.input for r in self.rows.values())

    @property
    def output_tokens(self) -> int:
        return sum(r.output for r in self.rows.values())

    @property
    def cache_read_tokens(self) -> int:
        return sum(r.cache_read for r in self.rows.values())

    @property
    def cache_write_tokens(self) -> int:
        return sum(r.cache_write for r in self.rows.values())

    @property
    def cost_usd(self) -> float:
        """Cost of the priced calls only. See `unpriced_models`."""
        total = 0.0
        for (_, model), row in self.rows.items():
            rates = pricing_for(model)
            if rates is None:
                continue
            p_in, p_out, p_cw, p_cr = rates
            total += (
                row.input * p_in
                + row.output * p_out
                + row.cache_write * p_cw
                + row.cache_read * p_cr
            ) / 1_000_000
        return total

    @property
    def unpriced_models(self) -> set[str]:
        return {m for (_, m) in self.rows if pricing_for(m) is None}

    def report(self) -> str:
        lines = [
            (
                f"model calls: {self.calls}   "
                f"in: {self.input_tokens}  out: {self.output_tokens}  "
                f"cache_read: {self.cache_read_tokens}  "
                f"cache_write: {self.cache_write_tokens}"
            )
        ]
        unpriced = self.unpriced_models
        if unpriced:
            lines.append(
                f"est. cost: ${self.cost_usd:.4f} (excludes unpriced: {', '.join(sorted(unpriced))})"
            )
        else:
            lines.append(f"est. cost: ${self.cost_usd:.4f}")

        for (label, model), row in sorted(self.rows.items(), key=lambda kv: -kv[1].output):
            short = model.split(".")[-1][:34] if model else "unknown"
            lines.append(
                f"  {label:<20} {row.calls}x  in={row.input:<6} out={row.output:<6} "
                f"cache_r={row.cache_read:<6} {short}"
            )
        return "\n".join(lines)


LEDGER = UsageLedger()


class UsageCallback:
    """Records token usage off every model reply.

    Implemented against langchain's callback interface but constructed lazily so
    importing this module never requires langchain -- the tests exercise the
    ledger on its own.
    """

    def __new__(cls, label: str, model: str):
        from langchain_core.callbacks import BaseCallbackHandler

        class _Handler(BaseCallbackHandler):
            def __init__(self) -> None:
                self.label = label
                self.model = model

            def on_llm_end(self, response: Any, **_: Any) -> None:
                for generation in getattr(response, "generations", []) or []:
                    for gen in generation:
                        message = getattr(gen, "message", None)
                        usage = getattr(message, "usage_metadata", None)
                        if usage:
                            LEDGER.record(self.label, usage, self.model)

        return _Handler()


def chat_model(
    *,
    label: str,
    model: str = HAIKU,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    region: str | None = None,
    **kwargs: Any,
):
    """Return a Bedrock chat model wired into the cost ledger.

    `label` names the graph step and shows up in the cost report, so a runaway
    node is obvious from the totals instead of needing a bisect.

    The return value is a real ChatBedrockConverse. Anything that accepts a
    LangChain model -- `create_react_agent`, `with_structured_output`,
    `bind_tools` -- accepts this unchanged.
    """
    from botocore.config import Config
    from langchain_aws import ChatBedrockConverse

    return ChatBedrockConverse(
        model=model,
        region_name=region or DEFAULT_REGION,
        temperature=temperature,
        max_tokens=max_tokens,
        callbacks=[UsageCallback(label, model)],
        # Retry transient Bedrock failures at the API layer.
        # `ModelErrorException: The system encountered an unexpected error`
        # arrives with no warning and killed a multi-minute eval sweep on its
        # first occurrence. Adaptive mode also backs off on throttling, which is
        # the other thing that interrupts a long run.
        config=kwargs.pop("config", None) or Config(
            retries={"max_attempts": 5, "mode": "adaptive"},
            read_timeout=90,
        ),
        **kwargs,
    )


CACHE_POINT = {"cachePoint": {"type": "default"}}


def supports_cache_point(model_id: str) -> bool:
    """Whether this model accepts Bedrock prompt-cache points.

    Cache points are an Anthropic-model feature on Bedrock; sending one to a
    model that does not support it is a hard ValidationException, not a silent
    no-op, so the system-prompt builder has to ask first.
    """
    return "anthropic" in model_id or "claude" in model_id


def cached_system(text: str) -> Any:
    """System prompt content, cache-pointed when the active model supports it.

    The system prompt is resent on every step of the loop; once the sub-agent
    instructions are in it is well over 1k tokens, which is the threshold where
    caching pays for itself immediately. On a model without cache points we
    return plain text rather than failing the call.
    """
    if not supports_cache_point(HAIKU):
        return text
    return [{"type": "text", "text": text}, CACHE_POINT]
