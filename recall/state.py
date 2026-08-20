"""The single source of truth for a Recall run.

One TypedDict. Heavy payloads (full transcript, raw enrichment text) live here;
prompts carry references and short summaries, not the blobs.

Nodes return PARTIAL updates -- only the keys they changed. An unmatched key is
dropped silently by LangGraph, so field names here and in node returns must match
exactly. If a node's output "vanishes", suspect a typo here first.
"""

from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# Structured-output models. Every extraction step returns one of these via
# with_structured_output(), never "reply in JSON" prompting -- the model wraps
# JSON in a code fence eventually and json.loads dies.
# --------------------------------------------------------------------------


class Person(BaseModel):
    """One human mentioned in the memo."""

    name: str = Field(description="Full name as spoken. Best guess on spelling.")
    company: str | None = Field(
        default=None, description="Employer or organisation, if mentioned."
    )
    role: str | None = Field(
        default=None, description="Job title or function, if mentioned."
    )
    met_at: str | None = Field(
        default=None,
        description="Event, place, or context where they were met, e.g. 'SuperAI 2026 afterparty'.",
    )
    notes: str = Field(
        description=(
            "Everything else said about this person, in the speaker's own words, "
            "condensed but not interpreted. Include personal details, interests, "
            "and anything that would help recognise them later."
        )
    )
    aliases: list[str] = Field(
        default_factory=list,
        description="Other names or nicknames used for this person in the memo.",
    )


class PeopleExtraction(BaseModel):
    """All people found in a single memo."""

    people: list[Person] = Field(
        default_factory=list, description="One entry per distinct human mentioned."
    )


class MatchDecision(BaseModel):
    """Whether an extracted person is someone already in the person graph."""

    is_match: bool = Field(
        description="True only if this is the SAME human as the candidate record."
    )
    candidate_id: str | None = Field(
        default=None,
        description="ID of the matched stored record. Null when is_match is false.",
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="0-1 confidence in the match decision."
    )
    reasoning: str = Field(
        description="One sentence. What settled it -- shared employer, same event, same nickname."
    )


class Commitment(BaseModel):
    """Something the speaker said they would do."""

    person_name: str = Field(description="Who the commitment is owed to.")
    what: str = Field(description="The action promised, as a short imperative phrase.")
    due: str | None = Field(
        default=None,
        description=(
            "Absolute ISO date (YYYY-MM-DD) if one can be resolved from the memo, "
            "else null. Never emit relative language like 'next week'."
        ),
    )
    channel: Literal["email", "linkedin", "whatsapp", "call", "other"] = Field(
        default="email", description="How the speaker said they would follow up."
    )


class CommitmentExtraction(BaseModel):
    commitments: list[Commitment] = Field(default_factory=list)


class Draft(BaseModel):
    """A follow-up message ready for the speaker to send."""

    person_name: str
    channel: Literal["email", "linkedin", "whatsapp", "call", "other"] = "email"
    subject: str | None = Field(
        default=None, description="Email subject line. Null for non-email channels."
    )
    body: str = Field(description="The message itself, in the speaker's voice.")


class DraftBundle(BaseModel):
    drafts: list[Draft] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Graph state
# --------------------------------------------------------------------------


class PersonRecord(TypedDict, total=False):
    """A person as stored in long-term memory (the person graph)."""

    id: str
    name: str
    company: str | None
    role: str | None
    aliases: list[str]
    met_at: list[str]
    notes: list[str]
    enrichment: str | None
    first_seen: str
    last_seen: str


class KnownMatch(TypedDict):
    """An extracted person resolved onto an existing stored record."""

    person: dict
    record_id: str
    confidence: float
    reasoning: str


class CalendarEvent(TypedDict, total=False):
    title: str
    date: str | None
    person_name: str
    idempotency_key: str
    status: Literal["created", "duplicate", "skipped", "error"]
    detail: str


class RecallState(TypedDict, total=False):
    """State for one memo through the graph.

    `messages` is the only accumulating channel -- everything else is
    last-write-wins, because each node owns its keys outright.
    """

    messages: Annotated[list[AnyMessage], add_messages]

    audio_path: str | None
    transcript: str

    people: list[dict]
    new_people: list[dict]
    known_matches: list[KnownMatch]

    enrichments: dict[str, str]

    commitments: list[dict]
    drafts: list[dict]
    calendar_events: list[CalendarEvent]

    # merge (parallel branch) and persist (after the join) both write ids here,
    # so it accumulates instead of last-write-wins -- otherwise persist silently
    # erases the ids merge just wrote.
    persisted_ids: Annotated[list[str], operator.add]
    summary: str

    errors: Annotated[list[str], operator.add]
