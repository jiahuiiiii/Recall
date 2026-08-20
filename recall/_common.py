"""Shared model factory, cost accounting, and prompt-cache helpers.

Everything that talks to Bedrock goes through `chat_model()`. Nothing in the
graph imports a client class directly, so swapping region/model/credentials is
a one-file change.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv

load_dotenv()

# Haiku 4.5 is the default for every step. Sonnet only if Haiku is measurably
# wrong on a step -- and the reason gets written down at the call site.
# The "global." prefix is a cross-region inference profile. It is the workshop
# account's default, but a personal AWS account frequently does not have it and
# needs a regional profile instead ("apac.", "us.", "eu.") or the bare model id.
# RECALL_MODEL_ID overrides without touching code; 00_check_bedrock.py prints the
# exact value this account can actually call.
_DEFAULT_HAIKU = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
_DEFAULT_SONNET = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"

HAIKU = os.environ.get("RECALL_MODEL_ID", _DEFAULT_HAIKU)
SONNET = os.environ.get("RECALL_SONNET_MODEL_ID", _DEFAULT_SONNET)

# Bedrock follows the CLI default region, not the SSO region (and on a personal
# account, whatever `aws configure` wrote into ~/.aws/config). Setting it in one
# place and defaulting loudly is what stops the "works for me, 404s for you" bug.
DEFAULT_REGION = os.environ.get("AWS_REGION") or os.environ.get(
    "AWS_DEFAULT_REGION", "ap-southeast-1"
)

# Haiku 4.5 list price, USD per million tokens.
PRICE_IN_PER_MTOK = 1.00
PRICE_OUT_PER_MTOK = 5.00
PRICE_CACHE_WRITE_PER_MTOK = 1.25
PRICE_CACHE_READ_PER_MTOK = 0.10


@dataclass
class UsageLedger:
    """Running token/cost tally. Cost is measured per prompt, not discovered
    at month-end, so every model call lands here and the total is printed at
    the end of a run."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    by_label: dict[str, dict[str, int]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, label: str, usage: dict[str, Any] | None) -> None:
        if not usage:
            return
        details = usage.get("input_token_details") or {}
        cache_read = int(details.get("cache_read") or 0)
        cache_write = int(details.get("cache_creation") or 0)
        # langchain reports cached tokens inside input_tokens; split them out so
        # the cheap reads are not priced as fresh input.
        raw_in = int(usage.get("input_tokens") or 0)
        fresh_in = max(raw_in - cache_read - cache_write, 0)
        out = int(usage.get("output_tokens") or 0)

        with self._lock:
            self.calls += 1
            self.input_tokens += fresh_in
            self.output_tokens += out
            self.cache_read_tokens += cache_read
            self.cache_write_tokens += cache_write
            slot = self.by_label.setdefault(
                label, {"calls": 0, "in": 0, "out": 0, "cache_read": 0, "cache_write": 0}
            )
            slot["calls"] += 1
            slot["in"] += fresh_in
            slot["out"] += out
            slot["cache_read"] += cache_read
            slot["cache_write"] += cache_write

    @property
    def cost_usd(self) -> float:
        return (
            self.input_tokens * PRICE_IN_PER_MTOK
            + self.output_tokens * PRICE_OUT_PER_MTOK
            + self.cache_read_tokens * PRICE_CACHE_READ_PER_MTOK
            + self.cache_write_tokens * PRICE_CACHE_WRITE_PER_MTOK
        ) / 1_000_000

    def report(self) -> str:
        lines = [
            f"model calls: {self.calls}   "
            f"in: {self.input_tokens}  out: {self.output_tokens}  "
            f"cache_read: {self.cache_read_tokens}  cache_write: {self.cache_write_tokens}",
            f"est. cost: ${self.cost_usd:.4f}",
        ]
        for label, s in sorted(self.by_label.items(), key=lambda kv: -kv[1]["out"]):
            lines.append(
                f"  {label:<22} {s['calls']}x  in={s['in']:<6} out={s['out']:<6} "
                f"cache_r={s['cache_read']}"
            )
        return "\n".join(lines)


LEDGER = UsageLedger()


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
    """
    from langchain_aws import ChatBedrockConverse

    llm = ChatBedrockConverse(
        model=model,
        region_name=region or DEFAULT_REGION,
        temperature=temperature,
        max_tokens=max_tokens,
        **kwargs,
    )
    return _MeteredModel(llm, label)


class _MeteredModel:
    """Thin passthrough that records `usage_metadata` on every reply.

    Wrapping rather than subclassing keeps `with_structured_output` and `bind_tools`
    working unchanged -- they return new runnables, which we re-wrap.
    """

    def __init__(self, inner: Any, label: str) -> None:
        self._inner = inner
        self._label = label

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._inner, name)
        if name in {"bind_tools", "bind", "with_retry"}:

            def _wrapped(*a: Any, **kw: Any) -> Any:
                return _MeteredModel(attr(*a, **kw), self._label)

            return _wrapped
        return attr

    def with_structured_output(self, schema: Any, **kwargs: Any) -> "_StructuredMeteredModel":
        """Structured output, still metered.

        A plain `with_structured_output(...).invoke()` returns a bare Pydantic
        object with no usage attached, which would make most of the graph
        invisible to the cost ledger -- and most of the graph is structured
        calls. Forcing include_raw keeps the token counts, and unwrapping here
        means node code still gets the typed object it expects.
        """
        kwargs.pop("include_raw", None)
        return _StructuredMeteredModel(
            self._inner.with_structured_output(schema, include_raw=True, **kwargs),
            self._label,
            schema,
        )

    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        result = self._inner.invoke(*args, **kwargs)
        LEDGER.record(self._label, getattr(result, "usage_metadata", None))
        return result


class _StructuredMeteredModel:
    """Unwraps include_raw output: meters the raw reply, returns the parsed object."""

    def __init__(self, inner: Any, label: str, schema: Any) -> None:
        self._inner = inner
        self._label = label
        self._schema = schema

    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        result = self._inner.invoke(*args, **kwargs)
        LEDGER.record(self._label, getattr(result.get("raw"), "usage_metadata", None))

        if result.get("parsing_error"):
            raise ValueError(
                f"{self._label}: model output did not match {self._schema.__name__}: "
                f"{result['parsing_error']}"
            )
        return result["parsed"]


CACHE_POINT = {"cachePoint": {"type": "default"}}


def cached_system(text: str) -> list[dict[str, Any]]:
    """System prompt content blocks ending in a Bedrock cache point.

    The system prompt is resent on every step of the loop; once the sub-agent
    instructions are in it is well over 1k tokens, which is the threshold where
    caching pays for itself immediately.
    """
    return [{"type": "text", "text": text}, CACHE_POINT]
