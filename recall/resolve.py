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
# Capped below T_MATCH on purpose, exactly like W_DESCRIPTOR_MAX. At 3.0 this
# equalled T_MATCH, so an exact name match ALONE auto-resolved with zero
# corroboration and _adjudicate() -- which only runs on AMBIGUOUS -- never saw
# it. Two people called Alex merged into one record, silently. A name is the
# most distinctive single field, so it still dominates; it just is not proof of
# identity by itself. One corroborating signal (same event 1.25, same company
# 2.0, real notes overlap) carries a genuine return past T_MATCH; a bare shared
# name lands in the ambiguous band and buys a question, which is the whole
# point of the system. Measured on same_first_name, not hypothetical.
W_NAME_EXACT = 2.5
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

# A mention with NO name -- only a description, or an unrecognised label that
# turned up elsewhere in the record -- can be strong evidence of a TYPE of
# person but is never proof of WHICH person. So when the name channel
# contributes nothing at all, cap the whole total below T_MATCH: the mention can
# land anywhere in the ambiguous band and buy a question, but can never
# auto-resolve. Same shape as W_DESCRIPTOR_MAX caps the descriptor channel --
# this caps the SUM, because W_DESCRIPTOR_MAX (2.0) plus notes overlap (1.5)
# reached 3.5 with no name involved at all and silently merged "indian girl"
# into Marvi. Measured on the real pipeline, To fix #2. Below T_MATCH by a clear
# margin so a genuinely named, corroborated match always outranks a nameless one.
NAMELESS_CEILING = 2.5


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

    # Split each side, ENTRY BY ENTRY. Asking "does this side have any name?"
    # and then comparing every entry was the bug: a record with one real name
    # licensed its descriptor aliases to be compared as names. Merging "the
    # indian girl" into Marvi stored that phrase in her aliases; four memos
    # later "the Catholic Indian" matched it at 1.00 on `indian`, took the
    # uncapped name channel, and merged a second stranger in. A description
    # laundered through the alias field must not come back as a name --
    # W_DESCRIPTOR_MAX exists precisely so a description cannot auto-resolve.
    named_a = [n for n in names_a if _is_name(n)]
    named_b = [n for n in names_b if _is_name(n)]
    described_a = [n for n in names_a if not _is_name(n)]

    if named_a and named_b:
        # Compare names only against names, and only on distinctive tokens.
        name = max(
            (best_match(_name_only(a), _name_only(b)) for a in named_a for b in named_b),
            default=0.0,
        )
        name_conflict = name == 0.0
        descriptor = 0.0

        # A name we do not recognise is not automatically a DIFFERENT person.
        # "Crispy" shares nothing with "Tiu Chuei Enn", so the name channel
        # conflicted at -1.5 and filed a duplicate -- even though her record
        # said "everyone calls her Crispy" in its notes. The nickname was
        # already there; only `name` and `aliases` were being read.
        #
        # So before calling it a conflict, ask whether this label appears
        # ANYWHERE in the record. If it does, it is an unrecognised label with
        # corroboration, not a contradiction: route it through the descriptor
        # channel, which is capped below T_MATCH and therefore buys a question
        # instead of a silent merge.
        #
        # A label found nowhere in the record still conflicts, which is what
        # keeps "Harold" from going ambiguous against "Viktoria".
        if name_conflict:
            found = _descriptor_match(named_a, record)
            if found > 0.0:
                name_conflict = False
                descriptor = found
    else:
        # At least one side is a description. There is no name to agree or
        # conflict with, so the name channel stays silent and the description is
        # matched against everything known about the record instead.
        #
        # Only the MENTION's descriptions count. Passing the record's own
        # labels here compared the record against itself, so any named mention
        # scored a free desc=1.00 against any record we only ever knew by
        # description -- evidence manufactured from one side.
        name = 0.0
        name_conflict = False
        descriptor = _descriptor_match(described_a, record) if described_a else 0.0

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

    # Did the name channel say anything -- agree, partially agree, or conflict?
    # A conflict counts: the names were compared and disagreed, which is real
    # evidence (and negative), so it is not a nameless match. Only when the
    # channel is fully silent (name 0.0, no conflict) does the ceiling apply.
    name_spoke = a.name > 0.0 or a.name_conflict

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

    # No name involved: cap into the ambiguous band so it asks, never merges.
    if not name_spoke:
        total = min(total, NAMELESS_CEILING)
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


# A phrase opening with an article is a description of someone, not what they
# are called: people say "the Catholic Indian", never "the Alex". Without this,
# a description whose words happen to miss DESCRIPTOR_WORDS ("catholic",
# "indian" are in neither) takes the name channel, and then either conflicts
# with every stored name or matches the wrong one outright.
DETERMINERS = {"the", "a", "an", "this", "that", "some", "another"}


def _is_name(value: str) -> bool:
    """A real name, not a description.

    "the german girl" is not a name. Treating it as one makes every descriptive
    reference look like a name conflict, and — worse — lets two unrelated
    descriptions match each other on a shared word like `girl`.
    """
    first = value.strip().lower().split()
    if first and first[0].strip(".,'\"") in DETERMINERS:
        return False
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
