"""Relationships between people -- the edges of the person graph.

A `PersonRecord` is an island: it holds who someone is and says nothing about
how they stand to anyone else. This file holds the edges. "A and B are business
partners", "C is A's close friend but B's competitor" -- the things a memo
actually says about how people relate, kept as typed edges rather than buried in
one person's prose.

**Storage and display only.** `resolve.compare` reads six fields off a record
(name/aliases, company, role, met_at, notes) and `LocalPersonStore.search`
builds its haystack from the same six. An edge is not one of them, and edges
live in their OWN file rather than on the record, so there is no path by which
anything here reaches the resolver. That is why this can ship without re-running
the B3 or question-efficiency tables -- the guarantee is structural, not
measured. If a relation is ever fed to `compare()`, this file needs a weight, a
threshold and a re-run, and it is not currently that kind of code.

Edges are deliberately kept OUT of candidate retrieval for a second reason
beyond the benchmark: a shared relationship is evidence two records are
DIFFERENT people. "Wei Han and Marcus are co-founders" names both; putting that
note in Marcus's haystack makes Wei Han a candidate for Marcus, which is exactly
backwards. Same argument as `contacts`, one step stronger.

The guard, and the reason this is not just a prompt
---------------------------------------------------
A model asked "who relates to whom" over a hall full of students will return an
edge for every pair, because everyone shares a course, a floor and an event.
That is the `tags.py` failure mode -- predicates true of everyone, which
categorise nothing -- and here it is worse, because an edge is an assertion
about TWO real people that the user never made.

So the model supplies only the INTERPRETATION (what kind of relationship, and
what they did together) and code supplies the PROOF: an edge survives only if
some note on one of the two records literally names the other person. No note
naming them, no edge. A relationship the memos never mentioned cannot be
invented by a fluent paragraph, the same way `enrich._verify` will not accept a
biography that does not cite the memo.

Name matching here is deliberately STRICTER than the resolver's. `best_match`
scores partial token agreement, which is right when deciding whether a spoken
name is a stored person; it is wrong here, because four `Jia*` people in one OG
would each "name" the others on a shared syllable and the graph would fill with
edges nobody said. A whole name, on word boundaries, or nothing.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import TypedDict

from pydantic import BaseModel, Field

from recall._common import cached_system, chat_model
from recall.state import as_list
from recall.text import tokens

# A CLOSED vocabulary, for the reason `tags.canonicalise` exists: an open one
# gives you "partner", "collaborator" and "works with" as three colours in the
# legend and three filters that each match one pair. The list covers what these
# memos actually contain -- students and people met at events -- and anything
# outside it lands on `knows`, which claims only that the memo put them
# together.
KINDS: tuple[str, ...] = (
    "partner",     # built or ran something together
    "colleague",   # same employer or team
    "classmate",   # same course, school or OG
    "friend",
    "family",
    "mentor",      # DIRECTED: a mentors b
    "competitor",
    "knows",       # the memo links them, nature unstated
)

LABELS: dict[str, str] = {
    "partner": "Partners",
    "colleague": "Colleagues",
    "classmate": "Classmates",
    "friend": "Friends",
    "family": "Family",
    "mentor": "Mentors",
    "competitor": "Competitors",
    "knows": "Knows",
}

# Most relationships are mutual and storing them twice, once each way, gives two
# rows that can disagree after an edit. These are symmetric, so the pair is
# canonically ordered and `a`/`b` carry no meaning beyond identity. `mentor` is
# the exception and reads a -> b.
DIRECTED: frozenset[str] = frozenset({"mentor"})

# How much of the model's `what` phrase has to be supported by the evidence note.
# Same job as `tags.corroborated`, one notch stricter: a tag is one categorical
# word and a `what` is a clause, so requiring a single shared token would accept
# almost anything.
MIN_SUPPORT = 0.5


class Relation(TypedDict, total=False):
    """One edge. Lives in `data/relations.json`, never on a PersonRecord."""

    id: str
    a: str           # person id
    b: str           # person id
    kind: str        # one of KINDS
    what: str        # short phrase: "run a supper club together"
    evidence: str    # the stored note that grounds it, verbatim
    source: str      # "derived" (a model call) or "user" (typed in the UI)


SYSTEM = """You read someone's contact notes and say how the people in them relate \
to each other.

You are given every person at once, each with an id and the notes recorded about \
them. Return one entry per relationship you can see IN THE NOTES.

The hard rule: a relationship must be something the notes SAY, not something they \
imply. Two people studying computer science are not classmates unless a note says \
they take a class together. Two people at the same hall are not friends unless a \
note says so. If you would have to reason to get there, it is not there.

You will be checked: an edge is discarded unless one of the two people's notes \
names the other person outright. Proposing a pair whose notes never mention each \
other wastes the entry.

kind must be exactly one of: partner, colleague, classmate, friend, family, \
mentor, competitor, knows.
- partner   - they built, ran or organised something together
- colleague - same employer or team
- classmate - same course, class, project group or orientation group
- friend    - the notes call them close
- family    - related
- mentor    - a mentors, teaches or advises b. THIS ONE HAS A DIRECTION: put the \
mentor in `a`.
- competitor- rivals, competing for the same thing
- knows     - the notes put them together but do not say how. Use this rather \
than guessing a warmer one.

what: a short phrase in the speaker's own words for what the notes say they did \
or are - "run a supper club together", "competing for the same grant". Six words \
at most. It must reuse the wording of the note, not paraphrase it away."""


class ProposedRelation(BaseModel):
    a: str = Field(description="Person id, copied exactly from the input.")
    b: str = Field(description="Person id, copied exactly from the input.")
    kind: str = Field(description="One of the eight listed kinds.")
    what: str = Field(default="", description="Six words at most, in the note's wording.")


class RelationProposal(BaseModel):
    relations: list[ProposedRelation] = Field(default_factory=list)


# --------------------------------------------------------------------------
# The guard
# --------------------------------------------------------------------------


def _labels(record: dict) -> list[str]:
    """Every string this person is called: name plus aliases."""
    out = [record.get("name") or "", *as_list(record.get("aliases"))]
    return [s.strip() for s in out if s and s.strip()]


def names_in(text: str, record: dict) -> bool:
    """Does `text` name this person outright?

    Whole label, on word boundaries. Not `best_match`, which scores partial
    agreement and is right for the resolver and wrong here: with `Jia En`,
    `Jia Ying`, `Jia Qi` and `Jia Yaw` in one orientation group, partial
    matching makes every note about one of them "name" the other three, and the
    graph fills with edges nobody said. A missed edge costs one line in a
    picture; an invented one is a claim about two real people.
    """
    hay = (text or "").lower()
    for label in _labels(record):
        pattern = r"\b" + r"\s+".join(re.escape(w) for w in label.lower().split()) + r"\b"
        if re.search(pattern, hay):
            return True
    return False


def evidence_for(rec_a: dict, rec_b: dict) -> str | None:
    """The note that grounds an edge between these two, or None.

    Looks on BOTH records, because the memo could have introduced either one
    first: "went to the hackathon with Marcus" may sit on Wei Han's record, on
    Marcus's, or on both. The first note naming the other person wins; ties do
    not matter because any one of them is a true citation.
    """
    for owner, other in ((rec_a, rec_b), (rec_b, rec_a)):
        for note in as_list(owner.get("notes")):
            if names_in(note, other):
                return note
    return None


def supported(what: str, evidence: str) -> bool:
    """Is the model's phrasing actually drawn from the note it cites?

    `evidence` is found in code, so it cannot be fabricated -- but `what` is
    free text and will drift into a nicer story than the note tells ("run a
    startup together" from a note that says they queued for supper). Requiring
    real overlap keeps the label answerable against the evidence shown beside
    it. An empty `what` is fine: the edge still has a kind and a citation.
    """
    if not what.strip():
        return True
    w, e = tokens(what), tokens(evidence)
    if not w:
        return True
    return len(w & e) / len(w) >= MIN_SUPPORT


def canonical(rel: Relation) -> Relation:
    """Order the pair, so one relationship is one row.

    Symmetric kinds get their ids sorted: without this the model returning
    (A,B,friend) on one refresh and (B,A,friend) on the next leaves two rows
    that render as two edges and disagree the moment one is deleted. Directed
    kinds are left alone -- swapping a mentor and their mentee is not a
    normalisation, it is a different claim.
    """
    if rel.get("kind") in DIRECTED:
        return rel
    a, b = rel.get("a", ""), rel.get("b", "")
    return {**rel, "a": min(a, b), "b": max(a, b)}


def key(rel: Relation) -> tuple[str, str, str]:
    r = canonical(rel)
    return (r.get("a", ""), r.get("b", ""), r.get("kind", ""))


# --------------------------------------------------------------------------
# Derivation
# --------------------------------------------------------------------------


def _facts(record: dict) -> str:
    bits = [
        record.get("company") or "",
        record.get("role") or "",
        " ".join(as_list(record.get("met_at"))),
        " ".join(as_list(record.get("notes"))),
    ]
    return " ".join(b for b in bits if b)


def generate_relations(records: list[dict]) -> list[Relation]:
    """Derive edges for the whole graph in ONE call.

    One call rather than one per pair, for the same two reasons as `tags`: a
    pairwise sweep is O(n^2) requests over a graph that is mostly unrelated
    people, and the model can only say "these two, not those two" if it sees
    everyone at once.

    A separate call from extraction, deliberately. Adding a `relationships`
    field to `state.Person` would change the schema of the call that also emits
    `name`, `notes` and `company` -- fields `resolve.compare` DOES read -- and
    `temperature=0` is not determinism here, so the resolution baseline would
    have to be re-measured. Reading the stored notes afterwards costs one extra
    call and cannot touch a score.
    """
    usable = [r for r in records if r.get("id") and as_list(r.get("notes"))]
    if len(usable) < 2:
        return []  # nothing to relate

    listing = "\n\n".join(
        "id: {id}\nname: {name}\nnotes:\n{notes}".format(
            id=r["id"],
            name=r.get("name", ""),
            notes="\n".join(f"  - {n}" for n in as_list(r.get("notes"))) or "  -",
        )
        for r in usable
    )
    llm = chat_model(label="relations", temperature=0.0).with_structured_output(
        RelationProposal
    )
    result: RelationProposal = llm.invoke(
        [
            {"role": "system", "content": cached_system(SYSTEM)},
            {"role": "user", "content": f"People:\n\n{listing}"},
        ]
    )
    return ground(result.relations, usable)


def ground(proposals: Iterable[object], records: list[dict]) -> list[Relation]:
    """Keep only the proposed edges the stored notes actually support.

    Split out from `generate_relations` so the guard is testable without a model
    call -- the same reason `tags.corroborated` is its own function. This is
    where most of a model's output is expected to die, and that is the design
    working, not a bug.
    """
    by_id = {r["id"]: r for r in records if r.get("id")}
    kept: dict[tuple[str, str, str], Relation] = {}

    for p in proposals:
        a, b = getattr(p, "a", ""), getattr(p, "b", "")
        kind = (getattr(p, "kind", "") or "").strip().lower()
        what = " ".join((getattr(p, "what", "") or "").split())

        if a == b or a not in by_id or b not in by_id:
            continue  # a model-invented id belongs to nobody
        if kind not in KINDS:
            continue  # outside the closed vocabulary; `knows` was available
        evidence = evidence_for(by_id[a], by_id[b])
        if evidence is None:
            continue  # THE guard: no note names the other person
        if not supported(what, evidence):
            what = ""  # keep the edge and its citation, drop the embroidery

        rel = canonical({"a": a, "b": b, "kind": kind, "what": what,
                         "evidence": evidence, "source": "derived"})
        # A pair can hold two different kinds honestly ("partner" and
        # "competitor" are the interesting case the user asked for), so the key
        # includes the kind. The same kind proposed twice collapses.
        kept.setdefault(key(rel), {**rel, "id": f"r_{uuid.uuid4().hex[:8]}"})

    return list(kept.values())


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------


class RelationStore:
    """Edges on disk, in their own file.

    Separate from `person_graph.json` rather than a field on the record,
    because an edge belongs to a PAIR. Stored on both records it is two copies
    that drift; stored on one it is invisible from the other. A separate file
    also means `LocalPersonStore` needs no change at all, so nothing that feeds
    the resolver was touched to add this.
    """

    def __init__(self, path: str | os.PathLike[str] = "data/relations.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._rels: list[Relation] = []
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            raw = json.loads(self.path.read_text() or "{}")
            self._rels = [r for r in raw.get("relations", []) if r.get("a") and r.get("b")]

    def _flush(self) -> None:
        self.path.write_text(
            json.dumps({"relations": self._rels}, indent=2)
        )

    def all(self) -> list[Relation]:
        return list(self._rels)

    def add(self, rel: Relation) -> Relation:
        """Add one edge, or return the existing one for that pair and kind."""
        rel = canonical(rel)
        k = key(rel)
        for existing in self._rels:
            if key(existing) == k:
                return existing
        stored: Relation = {**rel, "id": rel.get("id") or f"r_{uuid.uuid4().hex[:8]}"}
        self._rels.append(stored)
        self._flush()
        return stored

    def remove(self, rel_id: str) -> bool:
        before = len(self._rels)
        self._rels = [r for r in self._rels if r.get("id") != rel_id]
        if len(self._rels) == before:
            return False
        self._flush()
        return True

    def replace_derived(self, rels: list[Relation]) -> list[Relation]:
        """Swap in a fresh derivation, keeping every hand-made edge.

        A refresh re-reads the notes, so a derived edge the notes no longer
        support should disappear. An edge the USER drew is not the model's to
        withdraw -- same principle as the person panel, where the graph will get
        people wrong and a contact book you cannot correct is one you stop
        trusting.
        """
        user_made = [r for r in self._rels if r.get("source") == "user"]
        taken = {key(r) for r in user_made}
        self._rels = user_made + [r for r in rels if key(r) not in taken]
        self._flush()
        return self.all()

    def repoint(self, source_id: str, target_id: str) -> int:
        """Follow a person merge. Returns how many edges moved.

        `PersonStore.merge` deletes the source record, so every edge touching it
        would otherwise point at a person who no longer exists and vanish from
        the graph silently. Self-edges created by the move are dropped -- after
        a merge, "A partners with B" where A and B turned out to be one human is
        not a relationship, it is the duplicate that was just fixed.
        """
        moved, out, seen = 0, [], set()
        for rel in self._rels:
            r = dict(rel)
            if r.get("a") == source_id:
                r["a"], moved = target_id, moved + 1
            if r.get("b") == source_id:
                r["b"], moved = target_id, moved + 1
            if r["a"] == r["b"]:
                continue
            r = canonical(r)
            if key(r) in seen:
                continue  # the merge collapsed two edges into one
            seen.add(key(r))
            out.append(r)
        self._rels = out
        self._flush()
        return moved

    def drop_person(self, person_id: str) -> int:
        """Forget every edge touching a deleted person. Returns how many went."""
        before = len(self._rels)
        self._rels = [
            r for r in self._rels if person_id not in (r.get("a"), r.get("b"))
        ]
        gone = before - len(self._rels)
        if gone:
            self._flush()
        return gone


def get_relation_store() -> RelationStore:
    """The edge store. `RECALL_RELATIONS_PATH` redirects it.

    Parallel to `RECALL_STORE_PATH`: a throwaway run must be able to point BOTH
    somewhere scratch, or an exploratory memo writes edges into the real graph
    and later looks like the agent inventing relationships nobody described.
    """
    return RelationStore(os.environ.get("RECALL_RELATIONS_PATH", "data/relations.json"))
