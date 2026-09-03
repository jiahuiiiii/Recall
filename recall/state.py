"""The single source of truth for a Recall run.

One TypedDict. Heavy payloads (full transcript, raw enrichment text) live here;
prompts carry references and short summaries, not the blobs.

Nodes return PARTIAL updates -- only the keys they changed. An unmatched key is
dropped silently by LangGraph, so field names here and in node returns must match
exactly. If a node's output "vanishes", suspect a typo here first.
"""

from __future__ import annotations

import json
import operator
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field, field_validator


# --------------------------------------------------------------------------
# Structured-output models. Every extraction step returns one of these via
# with_structured_output(), never "reply in JSON" prompting -- the model wraps
# JSON in a code fence eventually and json.loads dies.
# --------------------------------------------------------------------------


def as_list(value: object) -> list[str]:
    """Coerce a notes/aliases/met_at field to a list of strings.

    Guards one specific, silent corruption: `list("a string")` returns
    ['a', ' ', 's', 't', ...]. Every list field here is fed by model output, and
    a model that returns a bare string where the schema says list[str] turns one
    note into ninety single-character notes -- which then persist, get deduped,
    and get consolidated, all without raising. Normalising once at the boundary
    is cheaper than auditing every `list(...)` call downstream forever.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if v is not None and str(v).strip()]
    return [str(value)]


def decode_list(value: object) -> object:
    """Undo a model returning a JSON *string* where the schema says list.

    Structured output is not a guarantee about the wire format. Bedrock
    intermittently returns `people` as `'[{"name": "Big Boss", ...}]'` -- a
    correct JSON document, encoded once too often -- and Pydantic rejects it
    with `Input should be a valid list [input_type=str]`. That killed one memo
    in a resolution sweep and an ENTIRE run of the question benchmark, which is
    why the 30 Aug headline is n=2 rather than n=3.

    Coercion rather than a retry: the payload is already correct, so re-asking
    costs a model call to receive the same content. A string that is not JSON is
    left alone, so Pydantic still reports the real problem instead of this
    function hiding it.
    """
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return []
    if text[0] not in "[{":
        return value  # a bare string; as_list semantics apply, not JSON
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        return value
    return decoded if isinstance(decoded, list) else [decoded]


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
    notes: list[str] = Field(
        default_factory=list,
        description=(
            "One separate entry per distinct thing the speaker said about this "
            "person. ONE FACT PER ENTRY -- never join several facts into one "
            "string with semicolons or commas. Use the speaker's own words, "
            "lightly tidied, not a paraphrase. Include personal details, "
            "opinions, plans, and anything that would help recognise them later."
        ),
    )
    aliases: list[str] = Field(
        default_factory=list,
        description="Other names or nicknames used for this person in the memo.",
    )
    substantive: bool = Field(
        description=(
            "True only if the memo says something about this person BEYOND having "
            "seen, greeted, or name-dropped them. Ask: does the memo state a fact, "
            "an opinion, a plan, or a promise involving them? If the only content is "
            "that they were present or were said hello to, this is false."
        )
    )

    @field_validator("notes", "aliases", mode="before")
    @classmethod
    def _coerce_list(cls, v: object) -> object:
        return as_list(decode_list(v))


class PeopleExtraction(BaseModel):
    """All people found in a single memo."""

    people: list[Person] = Field(
        default_factory=list, description="One entry per distinct human mentioned."
    )

    @field_validator("people", mode="before")
    @classmethod
    def _coerce_people(cls, v: object) -> object:
        return decode_list(v)


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


class ConsolidatedRecord(BaseModel):
    """A person's accumulated notes and meeting places, deduplicated."""

    notes: list[str] = Field(
        description=(
            "The distinct things recorded about this person, one fact per entry, "
            "in the speaker's own words. Redundant restatements merged into one."
        )
    )
    met_at: list[str] = Field(
        description=(
            "Distinct places or events where this person was met. Different "
            "descriptions of the SAME occasion collapse to the fullest one."
        )
    )

    @field_validator("notes", "met_at", mode="before")
    @classmethod
    def _coerce_list(cls, v: object) -> object:
        # Same guard as Person: with_structured_output intermittently returns a
        # list field as a JSON *string*. Ungated it raises mid-consolidation and
        # the whole merge is lost. See decode_list and To fix #5a.
        return as_list(decode_list(v))


class Commitment(BaseModel):
    """Something the speaker said they would do, or somewhere they said they'd be.

    Two kinds in one model rather than two models, because both end up as the
    same thing -- a dated entry on a calendar -- and splitting them would mean
    two extraction calls to read one sentence. `kind` is what the calendar
    branches on; everything downstream of it stays one code path.
    """

    kind: Literal["followup", "attending"] = Field(
        default="followup",
        description=(
            "'followup' when the speaker owes someone an action. 'attending' when "
            "the speaker said they are going to a named, dated event. Default to "
            "'followup' when it reads like a promise."
        ),
    )
    person_name: str = Field(
        description=(
            "Who the commitment is owed to. For an 'attending' entry, who the "
            "speaker is going with -- empty string if they named nobody."
        )
    )
    what: str = Field(
        description=(
            "For 'followup', the action promised, as a short imperative phrase. "
            "For 'attending', the name of the event as the speaker said it."
        )
    )
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

    @field_validator("commitments", mode="before")
    @classmethod
    def _coerce_commitments(cls, v: object) -> object:
        return decode_list(v)


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

    @field_validator("drafts", mode="before")
    @classmethod
    def _coerce_drafts(cls, v: object) -> object:
        return decode_list(v)


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
    # How to reach them: {"phone": "+65 …", "instagram": "kangling", …}. Keys
    # are `contacts.CHANNELS`; a channel with nothing in it is ABSENT, never
    # "". User-entered and display-only -- `resolve.compare` does not read it,
    # so it cannot move the resolution benchmark. See `recall/contacts.py`.
    contacts: dict[str, str]
    first_seen: str
    last_seen: str
    # How many separate occasions this person has been recorded on. NOT
    # len(met_at) -- that is the set of distinct places, deduplicated, so
    # meeting the same person three times at the same hall leaves it at 1.
    times_met: int


class KnownMatch(TypedDict, total=False):
    """An extracted person resolved onto an existing stored record."""

    person: dict
    record_id: str
    confidence: float
    reasoning: str
    score: float          # raw Fellegi-Sunter-style score, before squashing
    zone: str             # which band it landed in


class Hypothesis(TypedDict):
    """One candidate identity for an ambiguous mention."""

    record_id: str        # "" means the "new person" hypothesis
    name: str
    score: float
    explain: str


class AmbiguousMention(TypedDict):
    """A mention the band could not settle. This is what a question is FOR.

    Carried in state even when the interim adjudicator resolves it, so the
    benchmark can count how many arose and EIG can later select over the same
    hypothesis set.
    """

    person: dict
    hypotheses: list[Hypothesis]
    resolved_to: str | None    # set by whatever settles it, None while open


class CalendarEvent(TypedDict, total=False):
    title: str
    date: str | None
    person_name: str
    idempotency_key: str
    # "declined" = the human was shown this event and said no. Recorded rather
    # than dropped: "nothing appeared on my calendar" must be answerable from
    # the run itself.
    status: Literal["created", "duplicate", "skipped", "declined", "error"]
    detail: str


def is_interactive(config) -> bool:
    """True when this run can stop and wait for a person.

    A pause needs somewhere to keep the half-finished run, so it needs a
    checkpointer -- and the CLI, the tests and the eval harness all compile the
    graph without one. Rather than have those paths discover that by raising
    inside `interrupt()`, the caller declares up front whether a human is
    reachable, and the nodes take a different route when nobody is.

    Set by whoever builds the run:  config={"configurable": {"interactive": True}}
    """
    if not config:
        return False
    return bool((config.get("configurable") or {}).get("interactive"))


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
    ambiguous: list[AmbiguousMention]

    enrichments: dict[str, str]

    commitments: list[dict]
    drafts: list[dict]
    calendar_events: list[CalendarEvent]

    # merge (parallel branch) and persist (after the join) both write ids here,
    # so it accumulates instead of last-write-wins -- otherwise persist silently
    # erases the ids merge just wrote.
    # At most one per memo. None when nothing was worth asking about.
    question: dict | None

    # What the human's answer settled, when there was one. Absent on a run that
    # never paused -- which is every non-interactive run, so nothing downstream
    # may treat its presence as guaranteed.
    resolution: dict | None

    persisted_ids: Annotated[list[str], operator.add]
    summary: str

    errors: Annotated[list[str], operator.add]
