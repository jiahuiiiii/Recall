"""Offline stand-ins for Bedrock.

The graph's wiring -- the conditional edge, the fan-in, memory persistence across
sessions, calendar idempotency -- is exactly the part that must not break, and
none of it needs a real model to verify. These fakes let the whole pipeline run
in milliseconds with no credentials and no spend.
"""

from __future__ import annotations

from typing import Any

from recall.state import (
    Commitment,
    CommitmentExtraction,
    Draft,
    DraftBundle,
    PeopleExtraction,
    Person,
)


class FakeStructured:
    def __init__(self, schema: type, scripted: dict[type, Any]) -> None:
        self._schema = schema
        self._scripted = scripted

    def invoke(self, messages: Any, **_: Any) -> Any:
        value = self._scripted.get(self._schema)
        if value is None:
            raise AssertionError(f"no scripted reply for {self._schema.__name__}")
        return value(messages) if callable(value) and not isinstance(value, type) else value


class FakeModel:
    """Quacks like the metered model wrapper, returns scripted objects."""

    def __init__(self, scripted: dict[type, Any]) -> None:
        self._scripted = scripted

    def with_structured_output(self, schema: type, **_: Any) -> FakeStructured:
        return FakeStructured(schema, self._scripted)

    def bind_tools(self, *_: Any, **__: Any) -> FakeModel:
        return self

    def invoke(self, *_: Any, **__: Any) -> Any:
        raise AssertionError("unstructured invoke not scripted")


def fake_chat_model(scripted: dict[type, Any]):
    def _factory(**_: Any) -> FakeModel:
        return FakeModel(scripted)

    return _factory


class FakeEnricherAgent:
    """Stands in for the enricher sub-agent's react loop."""

    def __init__(self, replies: dict[str, str]) -> None:
        self._replies = replies

    def invoke(self, payload: dict, **_: Any) -> dict:
        from langchain_core.messages import AIMessage

        brief = payload["messages"][0].content
        for name, reply in self._replies.items():
            if name in brief:
                return {"messages": [AIMessage(content=reply)]}
        return {"messages": [AIMessage(content="NO RELIABLE PUBLIC INFORMATION FOUND.")]}


# --- canned extraction results -------------------------------------------------

WEI_LIN = Person(
    name="Wei Lin",
    company="GIC",
    role="quant infrastructure lead",
    met_at="SuperAI mixer, Marina Bay Sands",
    notes=[
        "Six years at GIC",
        "Feature store held together with cron jobs",
        "Hiring a mid-to-senior quant infra role",
    ],
    aliases=[],
    substantive=True,
)

ARJUN = Person(
    name="Arjun Menon",
    company="Sea Group",
    role="recommendations engineer",
    met_at="SuperAI mixer, Marina Bay Sands",
    notes=[
        "Gave the embedding drift talk",
        "Argues you do not need a vector DB at their scale",
    ],
    aliases=[],
    substantive=True,
)

# Seen and greeted, nothing said about him. Must never reach the person graph.
PASSING_MENTION = Person(
    name="Daniel",
    company="Stripe",
    role=None,
    met_at="SuperAI mixer, Marina Bay Sands",
    notes=["Ran into him again, nothing new, just said hi"],
    aliases=[],
    substantive=False,
)

DAY1_PEOPLE = PeopleExtraction(people=[WEI_LIN, ARJUN])

DAY1_COMMITMENTS = CommitmentExtraction(
    commitments=[
        Commitment(person_name="Wei Lin", what="send the Kestrel repo", due="2026-08-21", channel="email"),
        Commitment(person_name="Arjun Menon", what="introduce him to Marcus", due="2026-08-23", channel="email"),
    ]
)

DAY1_DRAFTS = DraftBundle(
    drafts=[
        Draft(
            person_name="Wei Lin",
            channel="email",
            subject="Kestrel repo, as promised",
            body="Good talking last night about the cron-job feature store. Here's Kestrel.",
        ),
        Draft(
            person_name="Arjun Menon",
            channel="email",
            subject="Intro to Marcus",
            body="Putting you two together - Marcus is hitting the same vector DB question at Grab.",
        ),
    ]
)
