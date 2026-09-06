"""Deriving candidate questions from what the graph already knows.

Questions are built **mechanically** from the stored records behind each
hypothesis, not proposed by a model. Three reasons:

1. A derived question is guaranteed answerable — it asks about something we
   actually recorded, so the answer maps straight back onto a hypothesis.
2. It is pure, so the whole path from "ambiguous mention" to "chosen question"
   is arithmetic that can be unit-tested.
3. It is free. The enricher already dominates spend; adding a model call per
   ambiguous mention to produce something derivable is hard to justify.

The model keeps a fallback role for the case attributes cannot separate
(`needs_model`), where every derived question scores zero information.

Two shapes of question come out of this:

**Yes/no probes.** Each fact a record holds becomes "does this describe them?".
A hypothesis whose record holds a matching fact answers yes, one that does not
answers no. Always derivable, because it needs nothing of a note but its text.

**Multi-valued attribute probes.** When two records hold facts that are the same
statement with a different value in the middle — "lives at the 18th floor" vs
"lives on the 4th floor" — that is one attribute with rival answers, and asking
for the value directly is worth ~1.2-1.6x the bits of asking a yes/no about one
of them:

    "Do they live on the 4th floor?"    binary     0.301 bits
    "Which floor do they live at?"      3-valued   0.475 bits
    "Do they study computer science?"   binary     0.671 bits
    "What do they study at NUS?"        3-valued   0.803 bits

(Measured on the Kit Yee / Crispy pair with a 0.06 prior on "someone new". An
earlier estimate said "roughly double" and was wrong: the ceiling is H(prior),
so with three hypotheses no question can be worth more than 1.27 bits and none
of these is close to twice another. The doubling estimate assumed noiseless
answers. The lift is real, but 1.2-1.6x is the number to quote.)

The reason is capacity: a binary answer cannot carry more than one bit however
well chosen, and half of what it does carry is spent confirming rather than
discriminating. An n-way answer can point at one hypothesis in a single step.

Both shapes are emitted. The binary probe is not redundant once the attribute
probe exists — it is the cheaper-sounding question worth measurably less, and
the contrast between them is the demonstration that the choice is arithmetic.
"""

from __future__ import annotations

import re

from recall.eig import Hypothesis, Question
from recall.text import overlap_ratio, tokens

# Two facts count as the same fact above this much token overlap, so "lives at
# the 18th floor" and "lives on the 18th floor" do not become rival probes.
SAME_FACT = 0.8

# How dependable an answer about each kind of attribute is. These are the noise
# rates EIG divides out, and they are the whole reason it can beat "ask whatever
# is least predictable": an unreliable attribute produces surprising answers that
# mean nothing.
#
# Hand-set from what actually changes about a person, not fitted:
RELIABLE = 0.05     # course, school, employer, where you met — rarely changes
MUTABLE = 0.18      # floor, room, hall — changes every semester
SUBJECTIVE = 0.35   # "quiet", "friendly" — one person's impression on one day

_MUTABLE_WORDS = {"floor", "room", "hall", "block", "level", "unit", "apartment",
                  "lives", "live", "living", "staying", "stays"}
_SUBJECTIVE_WORDS = {"quiet", "friendly", "nice", "chatty", "outgoing", "shy",
                     "smart", "funny", "humor", "humour", "kind", "intense",
                     "hardworking", "lazy", "seems", "seemed", "quite", "very"}


def reliability(fact: str) -> float:
    """Noise rate for a question about this fact.

    Impressions first: "she is a quiet person but friendly" is subjective even
    though it mentions no mutable attribute.
    """
    t = tokens(fact)
    if t & _SUBJECTIVE_WORDS:
        return SUBJECTIVE
    if t & _MUTABLE_WORDS:
        return MUTABLE
    return RELIABLE


# Verb openings that turn a recorded fact into a natural question.
_VERB_START = re.compile(
    r"^(lives?|works?|studies|studied|is|was|has|had|likes?|plays?|speaks?|"
    r"went|goes|joined|runs?|leads?|teaches|does|wants?|covers?)\b",
    re.IGNORECASE,
)


def facts_for(record: dict) -> list[str]:
    """Everything we could ask about for one stored person."""
    out: list[str] = []
    if record.get("company"):
        out.append(f"works at {record['company']}")
    if record.get("role"):
        out.append(f"is a {record['role']}")
    for place in record.get("met_at") or []:
        out.append(f"was met at {place}")
    out.extend(n for n in (record.get("notes") or []) if n and n.strip())
    return [f.strip() for f in out if f.strip()]


def phrase(fact: str) -> str:
    """Turn a recorded fact into a question a person can answer out loud.

    Uses they/them: the graph records what someone said about a person, not that
    person's pronouns, and guessing from a name gets it wrong.
    """
    fact = fact.strip().rstrip(".")
    lowered = fact[0].lower() + fact[1:] if fact else fact
    if _VERB_START.match(lowered):
        stem = _VERB_START.match(lowered).group(0).lower()
        rest = lowered[len(stem):].strip()
        if stem in {"is", "was"}:
            return f"Are they {rest}?" if stem == "is" else f"Were they {rest}?"
        if stem in {"has", "had"}:
            return f"Do they have {rest}?" if stem == "has" else f"Did they have {rest}?"
        base = _BASE_VERB.get(stem, stem)
        return f"Do they {base} {rest}?".replace("  ", " ")
    return f"Does this sound right — {lowered}?"


# --------------------------------------------------------------------------
# Multi-valued attribute probes.
#
# A yes/no question cannot carry more than one bit no matter how well chosen.
# When two records disagree about the *value* of the same attribute, asking for
# the value directly turns one bit into log2(n) and resolves in one step what a
# chain of yes/no questions needs several to do.
#
# Finding those attributes is done by alignment, not by parsing: two facts are
# the same attribute when they share a word-level prefix and suffix and differ
# only in the middle. That is strict on purpose. A looser rule (token overlap
# above some floor) pairs "from malaysian chinese independent school" with
# "studies computer science at NUS" on the strength of school/science, and a
# nonsense question is worse than no question -- the user cannot answer it, so
# the bits it was scored at are imaginary.
# --------------------------------------------------------------------------

# Words that carry no value and are stripped from the ends of a candidate value:
# "at the 18th" is the value "18th".
_FUNCTION = {"a", "an", "the", "at", "in", "on", "of", "for", "to", "with",
             "from", "and", "is", "was", "as", "by", "her", "his", "their"}
_PREPOSITIONS = {"at", "in", "on", "of", "for", "to", "with", "from", "by"}

# Copulas and auxiliaries: they conjugate irregularly and anchor no wh-question.
_COPULAS = {"is": "are", "was": "were", "has": "have", "had": "had"}

_BASE_VERB = {"lives": "live", "works": "work", "studies": "study", "studied": "study",
              "likes": "like", "plays": "play", "speaks": "speak", "goes": "go",
              "went": "go", "joined": "join", "runs": "run", "leads": "lead",
              "teaches": "teach", "does": "do", "wants": "want", "covers": "cover"}

# The answer that argues for "someone new": the user names a value no candidate
# on record holds. Without it the answer space is closed and the question can
# only ever choose between people we already know, which is exactly the mistake
# that makes a resolver merge a stranger into an acquaintance.
SOMETHING_ELSE = "something else"

# More options than this and the question stops being answerable out loud.
MAX_VALUES = 4


def _norm(word: str) -> str:
    return word.strip(".,;:!?()'\"").lower()


def _align(a: str, b: str) -> tuple[list[str], list[str], list[str], list[str]] | None:
    """Split two facts into (prefix, middle_a, middle_b, suffix).

    None when they are not the same statement with a different middle -- which
    is most pairs, and should be.
    """
    wa, wb = a.split(), b.split()
    if not wa or not wb:
        return None

    i = 0
    while i < min(len(wa), len(wb)) and _norm(wa[i]) == _norm(wb[i]):
        i += 1
    j = 0
    while (j < min(len(wa), len(wb)) - i
           and _norm(wa[len(wa) - 1 - j]) == _norm(wb[len(wb) - 1 - j])):
        j += 1

    prefix, suffix = wa[:i], (wa[len(wa) - j:] if j else [])
    mid_a, mid_b = wa[i:len(wa) - j], wb[i:len(wb) - j]

    # Both sides must actually assert a value. An empty middle means one fact is
    # the other plus detail ("lives at the 18th floor" / "... in Acacia"), which
    # is elaboration, not disagreement.
    if not _value(mid_a) or not _value(mid_b):
        return None
    # And the shared part must say what the attribute IS. Two facts sharing only
    # "the" are not the same attribute. Three things count as saying it:
    #   - a content word anywhere in the shared part ("... floor", "was met ...")
    #   - a leading preposition: "from Penang" / "from Ipoh" is one question
    #     about origin, and `from` is all the two have in common
    #   - two or more shared words, even function words: "is a quant lead" /
    #     "is a research intern" share only "is a", but that is the role field
    #     and they are genuinely rival values. One shared function word is not
    #     enough -- "is a quant lead" / "is friendly" share just "is", and those
    #     are not alternatives at all.
    if not (_content(prefix) or _content(suffix)
            or _lead_preposition(prefix) or len(prefix) >= 2):
        return None
    return prefix, mid_a, mid_b, suffix


def _content(words: list[str]) -> list[str]:
    return [w for w in words if _norm(w) not in _FUNCTION and _norm(w)]


def _value(words: list[str]) -> str:
    """The answer a middle carries: 'at the 18th' -> '18th'."""
    out = list(words)
    while out and _norm(out[0]) in _FUNCTION:
        out.pop(0)
    while out and _norm(out[-1]) in _FUNCTION:
        out.pop()
    return " ".join(out).strip(".,;: ").lower()


def _lead_preposition(words: list[str]) -> str:
    return _norm(words[0]) if words and _norm(words[0]) in _PREPOSITIONS else ""


def _statement(fact: str) -> str:
    """A recorded fact as something said about 'they', for the listing form."""
    lowered = fact.strip().rstrip(".")
    match = _VERB_START.match(lowered)
    if not match:
        return f"they are {lowered}" if lowered else lowered
    stem = match.group(0).lower()
    rest = lowered[len(stem):].strip()
    if stem in _COPULAS:
        return f"they {_COPULAS[stem]} {rest}".strip()
    return f"they {_BASE_VERB.get(stem, stem)} {rest}".strip()


def attribute_text(prefix: list[str], suffix: list[str], prepositions: list[str],
                   facts: list[str]) -> str:
    """Phrase the attribute probe as a wh-question where the shape allows it.

    Three shapes, tried in order, each fully mechanical:

    - suffix is a prepositional phrase ("studies ___ at NUS")
      -> "What do they study at NUS?"
    - suffix is a noun the value modifies ("lives at the ___ floor")
      -> "Which floor do they live at?"
    - neither -> list the rival facts. Not elegant, but always grammatical and
      always answerable, which matters more than elegance for a fallback.
    """
    verb = _norm(prefix[0]) if prefix else ""
    base = _BASE_VERB.get(verb, verb)
    head = _content(suffix)

    # Copulas carry no action to ask "what do they ___" about: "was met at
    # Acacia camp" / "was met at Acacia College" share the verb `was`, and the
    # template produces "What do they was?". A question the user cannot parse is
    # worse than a clumsy one -- it still gets scored in bits and still gets
    # asked -- so copulas go to the listing form.
    if base and verb not in _COPULAS and _VERB_START.match(verb or ""):
        if suffix and _norm(suffix[0]) in _PREPOSITIONS:
            return f"What do they {base} {' '.join(suffix)}?".replace("  ", " ")
        if head:
            # The preposition differs between the rival facts ("at the 18th"
            # vs "on the 4th"); take the commonest, breaking ties in sorted
            # order so the question is the same on every run.
            preps = [p for p in prepositions if p]
            tail = ""
            if preps:
                tail = " " + max(sorted(set(preps)), key=preps.count)
            return f"Which {' '.join(head)} do they {base}{tail}?"

    joined = ", or ".join(_statement(f) for f in facts)
    return f"Which is right — {joined}?"


def attribute_questions(fact_sets: dict[str, list[str]]) -> list[Question]:
    """One multi-valued probe per attribute the records disagree about.

    `fact_sets` maps record_id -> that record's facts.
    """
    groups: dict[tuple, dict] = {}

    ids = list(fact_sets)
    for x, rid_a in enumerate(ids):
        for rid_b in ids[x + 1:]:
            for fact_a in fact_sets[rid_a]:
                for fact_b in fact_sets[rid_b]:
                    aligned = _align(fact_a, fact_b)
                    if aligned is None:
                        continue
                    prefix, mid_a, mid_b, suffix = aligned
                    va, vb = _value(mid_a), _value(mid_b)
                    if va == vb:
                        continue
                    key = (tuple(_norm(w) for w in prefix),
                           tuple(_norm(w) for w in suffix))
                    group = groups.setdefault(key, {
                        "prefix": prefix, "suffix": suffix,
                        "values": {}, "facts": {}, "prepositions": [],
                    })
                    for rid, mid, value, fact in ((rid_a, mid_a, va, fact_a),
                                                  (rid_b, mid_b, vb, fact_b)):
                        group["values"].setdefault(rid, value)
                        group["facts"].setdefault(rid, fact)
                        group["prepositions"].append(_lead_preposition(mid))

    questions: list[Question] = []
    for key, group in sorted(groups.items()):
        values = group["values"]
        distinct = sorted(set(values.values()))
        if len(distinct) < 2 or len(distinct) > MAX_VALUES:
            continue
        facts = [group["facts"][rid] for rid in sorted(group["facts"])]
        questions.append(
            Question(
                key="attr:" + "-".join(w for part in key for w in part)[:48],
                text=attribute_text(group["prefix"], group["suffix"],
                                    group["prepositions"], facts),
                # "someone new" is the one hypothesis that genuinely predicts
                # SOMETHING_ELSE. If this is a person we hold no record of, the
                # value they name is by definition not one of the values we have
                # on record for the candidates -- so leaving them out (uniform
                # over answers, "consistent with anything") understates it badly.
                #
                # Without this the user can answer "none of these" and still be
                # told it is Kit Yee: the known candidates carry ~49% priors and
                # only lose the noise factor, while the new-person hypothesis
                # gains nothing, so it finishes third having been proved right.
                # That is the merge-a-stranger failure the band exists to stop.
                #
                # Binary probes keep the old treatment on purpose. A person we
                # have never met might or might not live on the 4th floor, and
                # uniform is the honest model there.
                outcomes={**values, "": SOMETHING_ELSE},
                answer_space=tuple(distinct) + (SOMETHING_ELSE,),
                # Pessimistic: the probe is only as dependable as its least
                # dependable member. Overstating reliability is the dangerous
                # direction -- it makes EIG trust an answer it should not.
                noise=max(reliability(f) for f in facts),
            )
        )
    return questions


def derive(hypotheses: list[Hypothesis], records: dict[str, dict]) -> list[Question]:
    """Candidate questions for a set of hypotheses.

    `records` maps record_id -> stored record. The "someone new" hypothesis has
    no record and therefore predicts no answer: it stays consistent with
    whatever is said, which is the honest model of a person we have never met.

    Questions every candidate answers alike are KEPT, not filtered. They score
    near zero by construction, and showing them is the point: "same school as
    you?" is a plausible-sounding question worth exactly nothing, and the
    contrast between it and the chosen question is what demonstrates that the
    selection is arithmetic rather than taste.

    Both shapes are returned in one pool -- the yes/no probe for every fact, and
    a multi-valued probe for every attribute the records disagree about. They
    compete on the same scale, so nothing has to decide up front which shape is
    better; the arithmetic does.
    """
    known = [h for h in hypotheses if h.record_id and h.record_id in records]
    if len(known) < 2:
        # Nothing to compare against another record: probe the single candidate,
        # which still separates it from "someone new".
        known = [h for h in hypotheses if h.record_id and h.record_id in records]

    raw_facts = {h.record_id: facts_for(records[h.record_id]) for h in known}
    fact_sets = {rid: [(f, tokens(f)) for f in facts] for rid, facts in raw_facts.items()}

    questions: list[Question] = list(attribute_questions(raw_facts))
    seen: list[set[str]] = []

    for holder, facts in fact_sets.items():
        for fact, fact_tokens in facts:
            if not fact_tokens or any(overlap_ratio(fact_tokens, s) >= SAME_FACT for s in seen):
                continue
            seen.append(fact_tokens)

            outcomes = {
                rid: ("yes" if any(overlap_ratio(fact_tokens, other) >= SAME_FACT
                                   for _, other in other_facts) else "no")
                for rid, other_facts in fact_sets.items()
            }
            questions.append(
                Question(
                    key=f"{holder}:{_slug(fact)}",
                    text=phrase(fact),
                    outcomes=outcomes,
                    source=fact,
                    # Yes/no probes: the user can always say no, whatever the
                    # candidates on record would say.
                    answer_space=("no", "yes"),
                    noise=reliability(fact),
                )
            )

    return questions


def needs_model(questions: list[Question]) -> bool:
    """True when the stored attributes cannot separate the hypotheses.

    The signal to fall back on a model-proposed question — the records are too
    thin or too similar, so something outside them has to be asked about.
    """
    return not questions


def _slug(fact: str) -> str:
    return "-".join(sorted(tokens(fact)))[:48]
