"""Three-zone entity resolution, Fellegi-Sunter style.

For each (mention, stored record) pair we score agreement and disagreement
across a handful of fields, sum the weights, and land in one of three zones:

    score >= T_MATCH        -> RESOLVED   auto-link, no question
    T_NONMATCH .. T_MATCH   -> AMBIGUOUS  this is where we ask
    score <  T_NONMATCH     -> NEW        a person we have not met

**The middle zone existing at all is the design.** Collapsing it back to one
threshold removes the only place a clarifying question can be asked, which
removes the project's contribution. Do not "simplify" it away.

Everything here is pure: no model calls, no I/O, no clock. The LLM's job is to
extract attributes and later to propose questions; deciding *which zone a pair
falls in* is arithmetic, so it can be unit-tested and so the thresholds can be
reported honestly in the benchmark.

Caveat worth stating in the writeup: true Fellegi-Sunter estimates its weights
from labelled pairs (log m/u ratios, usually via EM). We have too few labelled
pairs for that, so these weights are hand-set. They are a principled shape --
agreement adds, disagreement subtracts, distinctive fields count for more --
not fitted parameters.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from recall.text import best_match, overlap_ratio, tokens

# --- weights ----------------------------------------------------------------
# A name is the single most distinctive field, so it dominates. Company and the
# event where you met are next: two people can share a floor, far fewer share an
# employer AND a name. Disagreement on a field both records have is evidence
# AGAINST, which is what stops "same common first name" from resolving.
W_NAME_EXACT = 3.0
W_NAME_SIMILAR = 1.5
W_NAME_CONFLICT = -1.5

W_COMPANY_AGREE = 2.0
W_COMPANY_CONFLICT = -2.5

W_ROLE_AGREE = 1.0
W_ROLE_CONFLICT = -0.75

W_EVENT_AGREE = 1.25
W_NOTES_MAX = 1.5

# A descriptive reference ("the german girl") is real evidence but never
# conclusive, so it is capped below T_MATCH: it can carry a mention into the
# ambiguous band on its own, never past it. That is the correct destination —
# a description is exactly the kind of uncertainty a question resolves.
W_DESCRIPTOR_MAX = 2.0

# Words that make a phrase a description rather than a name. Without this,
# "the german girl" and "the indian girl" share the token `girl`, score as an
# exact name match, and merge two strangers — measured, not hypothetical.
DESCRIPTOR_WORDS = {
    "girl", "guy", "man", "woman", "boy", "lady", "person", "people", "friend",
    "one", "student", "colleague", "classmate", "roommate", "senior", "junior",
    "girls", "guys", "friends", "kid", "dude",
}

# --- thresholds -------------------------------------------------------------
# Tunable, and they MUST be quoted in the benchmark alongside any result.
T_MATCH = 3.0
T_NONMATCH = 1.0

# A high score is not enough on its own. If the runner-up is nearly as good, the
# evidence identifies a *type* of person rather than a person -- "one of the
# 18th floor girls" fits three records equally. That is a near-tie, and a
# near-tie is ambiguous no matter how high the top score is. This margin is what
# separates "clearly her" from "could be any of them".
MIN_MARGIN = 1.0


class Zone(str, Enum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    NEW = "new"


@dataclass(frozen=True)
class Agreement:
    """Field-by-field comparison of one mention against one stored record."""

    name: float = 0.0            # 0..1 best token match between the names
    name_conflict: bool = False  # both named, nothing in common
    company: float | None = None  # None = at least one side did not say
    role: float | None = None
    descriptor: float = 0.0      # a described reference matched against the record
    event: float = 0.0
    notes: float = 0.0

    def explain(self) -> str:
        bits = [f"name={self.name:.2f}"]
        if self.name_conflict:
            bits.append("name_conflict")
        for label, v in (("company", self.company), ("role", self.role)):
            bits.append(f"{label}={'-' if v is None else format(v, '.2f')}")
        bits.append(f"desc={self.descriptor:.2f} event={self.event:.2f} notes={self.notes:.2f}")
        return " ".join(bits)


def compare(person: dict, record: dict) -> Agreement:
    """Field agreement between an extracted person and a stored record."""
    names_a = [n for n in [person.get("name") or "", *(person.get("aliases") or [])] if n]
    names_b = [n for n in [record.get("name") or "", *(record.get("aliases") or [])] if n]

    a_named = any(_is_name(n) for n in names_a)
    b_named = any(_is_name(n) for n in names_b)

    if a_named and b_named:
        # Compare names only against names, and only on distinctive tokens.
        name = max(
            (best_match(_name_only(a), _name_only(b)) for a in names_a for b in names_b),
            default=0.0,
        )
        name_conflict = name == 0.0
        descriptor = 0.0
    else:
        # At least one side is a description. There is no name to agree or
        # conflict with, so the name channel stays silent and the description is
        # matched against everything known about the record instead.
        name = 0.0
        name_conflict = False
        descriptor = _descriptor_match(names_a if not a_named else names_b, record)

    return Agreement(
        name=name,
        name_conflict=name_conflict,
        descriptor=descriptor,
        company=_field(person.get("company"), record.get("company")),
        role=_field(person.get("role"), record.get("role")),
        event=overlap_ratio(
            tokens(person.get("met_at") or ""),
            tokens(" ".join(record.get("met_at") or [])),
        ),
        notes=overlap_ratio(
            tokens(" ".join(person.get("notes") or [])),
            tokens(" ".join(record.get("notes") or [])),
        ),
    )


def score(a: Agreement) -> float:
    """Weighted sum of the agreement. Higher means more likely the same human."""
    total = 0.0

    if a.name >= 1.0:
        total += W_NAME_EXACT
    elif a.name > 0.0:
        total += W_NAME_SIMILAR * a.name
    elif a.name_conflict:
        total += W_NAME_CONFLICT

    for value, agree_w, conflict_w in (
        (a.company, W_COMPANY_AGREE, W_COMPANY_CONFLICT),
        (a.role, W_ROLE_AGREE, W_ROLE_CONFLICT),
    ):
        if value is None:
            continue  # not stated on one side: no evidence either way
        total += agree_w * value if value > 0 else conflict_w

    total += W_DESCRIPTOR_MAX * a.descriptor
    total += W_EVENT_AGREE * a.event
    total += min(W_NOTES_MAX, W_NOTES_MAX * a.notes)
    return total


def zone(value: float, t_match: float = T_MATCH, t_nonmatch: float = T_NONMATCH) -> Zone:
    if value >= t_match:
        return Zone.RESOLVED
    if value >= t_nonmatch:
        return Zone.AMBIGUOUS
    return Zone.NEW


@dataclass(frozen=True)
class Candidate:
    record_id: str
    name: str
    score: float
    agreement: Agreement


def rank(person: dict, records: list[dict]) -> list[Candidate]:
    """Every candidate scored, best first."""
    out = []
    for r in records:
        agreement = compare(person, r)
        out.append(
            Candidate(
                record_id=r.get("id", ""),
                name=r.get("name", ""),
                score=score(agreement),
                agreement=agreement,
            )
        )
    return sorted(out, key=lambda c: -c.score)


def decide(
    person: dict,
    records: list[dict],
    *,
    t_match: float = T_MATCH,
    t_nonmatch: float = T_NONMATCH,
    margin: float = MIN_MARGIN,
) -> tuple[Zone, list[Candidate]]:
    """Zone for this mention, plus the ranked candidates behind it.

    AMBIGUOUS returns every candidate at or above `t_nonmatch`, because those
    are the hypotheses a clarifying question has to distinguish between. The
    caller decides what to do with them; this function never asks anything.
    """
    ranked = rank(person, records)
    if not ranked:
        return Zone.NEW, []

    top = ranked[0]
    runner_up = ranked[1].score if len(ranked) > 1 else float("-inf")
    z = zone(top.score, t_match, t_nonmatch)

    if z is Zone.NEW:
        return z, []

    live = [c for c in ranked if c.score >= t_nonmatch]

    if z is Zone.RESOLVED and top.score - runner_up >= margin:
        return Zone.RESOLVED, [top]

    # Either the score is in the band, or it is high but not clearly ahead of
    # the next candidate. Both are questions.
    return Zone.AMBIGUOUS, live


def _field(a: str | None, b: str | None) -> float | None:
    """Agreement on an optional field. None when either side is silent --
    absence of evidence must not read as evidence of difference."""
    if not a or not b:
        return None
    return best_match(a, b)


def _is_name(value: str) -> bool:
    """A real name, not a description.

    "the german girl" is not a name. Treating it as one makes every descriptive
    reference look like a name conflict, and — worse — lets two unrelated
    descriptions match each other on a shared word like `girl`.
    """
    t = tokens(value)
    return bool(t) and not (t & DESCRIPTOR_WORDS)


def _name_only(value: str) -> str:
    """Drop descriptor words so names are compared on distinctive tokens."""
    return " ".join(t for t in tokens(value) if t not in DESCRIPTOR_WORDS)


def _descriptor_match(descriptions: list[str], record: dict) -> float:
    """How well a description fits everything known about a record.

    "the german girl" carries `german`, which belongs against the record's
    notes, not against its name. Matched here so the evidence is used, and
    capped by its weight so it can never auto-resolve on its own.
    """
    described = set()
    for d in descriptions:
        described |= {t for t in tokens(d) if t not in DESCRIPTOR_WORDS}
    if not described:
        return 0.0

    haystack = tokens(" ".join(filter(None, [
        record.get("name") or "",
        record.get("company") or "",
        record.get("role") or "",
        " ".join(record.get("met_at") or []),
        " ".join(record.get("notes") or []),
        " ".join(record.get("aliases") or []),
    ])))
    return overlap_ratio(described, haystack)


def confidence_from(value: float, t_match: float = T_MATCH, t_nonmatch: float = T_NONMATCH) -> float:
    """Squash a raw score to 0..1 for display.

    A monotone transform of the score centred between the thresholds — NOT a
    calibrated probability. Calibration was cut from scope precisely because
    there are too few labelled pairs to assert it honestly, so this number is
    for reading, never for claiming.
    """
    import math

    centre = (t_match + t_nonmatch) / 2
    return round(1 / (1 + math.exp(-(value - centre))), 3)
