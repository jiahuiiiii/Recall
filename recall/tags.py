"""Tags for filtering the person graph.

A record has no tag field: `notes` is free text ("studies computer science at
NUS"), and real keyed attributes are the `attribute_edge` work in Future work.
Deriving tags lexically -- recurring n-grams -- produced `lives`, `studies`,
`pretty`, `together`: predicates that are true of everyone and filter nothing.
A model reads the facts instead.

**Display only.** `resolve.compare` never reads `tags`, so nothing here can move
the resolution benchmark. If that stops being true, this file needs a threshold
and a re-run, and it is not currently that kind of code.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from recall._common import cached_system, chat_model
from recall.state import as_list
from recall.text import tokens

SYSTEM = """You label people in someone's contact book with short tags, so they can \
filter to "everyone doing computer science" or "everyone from my hall".

You are given EVERY person at once. That is deliberate: the tags only work if the \
same idea gets the SAME string everywhere. "CS", "Computer Science" and "comp sci" \
as three tags for three people is a failure -- it makes three filters that each match \
one person instead of one filter that matches three.

Rules:
- Reuse a tag across people wherever it honestly applies. A tag only one person can \
ever have is close to useless; prefer the shared shape ("computer science") over the \
unique detail ("CS 1101S assignment").
- Lowercase. Two to four words at most. No punctuation.
- Tag what a person IS or DOES, not what happened once. "computer science", \
"malaysian", "lives in acacia" are tags. "offered me dessert", "was hungry", \
"quite smart" are not -- they are events and opinions, not categories.
- Only from what the notes actually say. Do not infer a nationality from a name, a \
course from a module code you are guessing at, or a hall from a building. If it is \
not stated, there is no tag.
- At most 5 tags per person. Fewer is fine. A person the notes say little about gets \
one tag or none.
- Every person in the input must appear in the output, even with an empty tag list."""


class PersonTags(BaseModel):
    id: str = Field(description="The person's id, copied exactly from the input.")
    tags: list[str] = Field(default_factory=list, description="Lowercase, 2-4 words each.")


class TagAssignment(BaseModel):
    people: list[PersonTags] = Field(default_factory=list)


def _facts(record: dict) -> str:
    bits = [
        record.get("name") or "",
        " ".join(as_list(record.get("aliases"))),
        record.get("company") or "",
        record.get("role") or "",
        " ".join(as_list(record.get("met_at"))),
        " ".join(as_list(record.get("notes"))),
    ]
    return " ".join(b for b in bits if b)


def corroborated(tag: str, record: dict) -> bool:
    """Does anything in the record support this tag?

    The guard. A model asked to categorise will happily infer "malaysian" from a
    name or "engineering" from a hall, and a tag is an assertion about a real
    person that the user did not make. Requiring a shared content word is crude
    -- it drops a fair tag whose wording differs entirely from the note -- but
    it fails toward saying less about people, which is the right direction here.
    """
    t, hay = tokens(tag), tokens(_facts(record))
    return bool(t) and bool(t & hay)


def canonicalise(assigned: dict[str, list[str]]) -> dict[str, list[str]]:
    """Collapse tags that are the same idea spelled two ways.

    Telling the model to reuse one string is necessary but not sufficient: on a
    real graph it still produced "malaysian" for three people and "malaysia" for
    a fourth, which silently costs that person their place in the filter. The
    prompt cannot be trusted with a consistency property, so enforce it in code
    -- the same reason the substantive filter is code and not an instruction.

    Rule: when one tag is a prefix of another (>= 5 chars, so "cs" cannot
    swallow "cs1231s"), both become whichever the model used for more people.
    """
    counts: dict[str, int] = {}
    for tags in assigned.values():
        for t in tags:
            counts[t] = counts.get(t, 0) + 1

    canon = {t: t for t in counts}
    for a in counts:
        for b in counts:
            if a is b or len(a) < 5 or not b.startswith(a):
                continue
            winner = max((a, b), key=lambda t: (counts[t], -len(t)))
            canon[a] = canon[b] = winner

    out: dict[str, list[str]] = {}
    for rid, tags in assigned.items():
        seen, kept = set(), []
        for t in tags:
            c = canon.get(t, t)
            if c not in seen:
                seen.add(c)
                kept.append(c)
        out[rid] = kept
    return out


def generate_tags(records: list[dict]) -> dict[str, list[str]]:
    """Tag every record in ONE call. Returns {record_id: tags}.

    One call, not one per person, because the vocabulary has to be shared to be
    filterable at all -- see SYSTEM. It also costs one request instead of N.
    """
    usable = [r for r in records if r.get("id") and _facts(r).strip()]
    if not usable:
        return {}

    listing = "\n\n".join(
        f"id: {r['id']}\nname: {r.get('name', '')}\nfacts: {_facts(r)}" for r in usable
    )
    llm = chat_model(label="tags", temperature=0.0).with_structured_output(TagAssignment)
    result: TagAssignment = llm.invoke(
        [
            {"role": "system", "content": cached_system(SYSTEM)},
            {"role": "user", "content": f"People:\n\n{listing}"},
        ]
    )

    by_id = {r["id"]: r for r in usable}
    out: dict[str, list[str]] = {}
    for entry in result.people:
        record = by_id.get(entry.id)
        if not record:
            continue  # a model-invented id belongs to nobody
        seen, kept = set(), []
        for raw in as_list(entry.tags):
            tag = " ".join(raw.lower().split())
            if tag and tag not in seen and corroborated(tag, record):
                seen.add(tag)
                kept.append(tag)
        out[entry.id] = kept[:5]
    return canonicalise(out)
