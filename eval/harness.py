"""Run the resolution pipeline over fixture scenarios and score the clustering.

Deliberately does NOT run the whole graph. Enrichment, drafting and the calendar
are outside the scoped project and cost most of the tokens; the eval exercises
transcribe-free extraction plus resolution, which is what the benchmark measures.

Always runs against a throwaway store. The user's person graph is real data and
must never be written to by an eval sweep.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

FIXTURES = Path(__file__).parent / "fixtures"


@dataclass
class Mention:
    memo_id: str
    cluster: str          # gold cluster id; UNRESOLVED means "no single right answer"
    as_written: str
    substantive: bool
    ambiguous: bool

    @property
    def key(self) -> str:
        return f"{self.memo_id}:{self.as_written}"


@dataclass
class Memo:
    id: str
    transcript: str
    mentions: list[Mention]


@dataclass
class Scenario:
    id: str
    description: str
    memos: list[Memo]

    @property
    def gold_clusters(self) -> dict[str, str]:
        """mention key -> gold cluster, for mentions that should be recorded.

        Passing mentions are excluded: they are scored by the substantive metric,
        not the clustering one. Genuinely ambiguous mentions are excluded too --
        scoring a coin flip as right or wrong would be noise, and they are counted
        separately as the denominator for question efficiency.
        """
        return {
            m.key: m.cluster
            for memo in self.memos
            for m in memo.mentions
            if m.substantive and m.cluster != "UNRESOLVED"
        }

    @property
    def gold_substantive(self) -> dict[str, bool]:
        return {m.key: m.substantive for memo in self.memos for m in memo.mentions}

    @property
    def ambiguous_keys(self) -> set[str]:
        return {m.key for memo in self.memos for m in memo.mentions if m.ambiguous}


def load_scenarios(path: Path | None = None) -> list[Scenario]:
    out: list[Scenario] = []
    for f in sorted((path or FIXTURES).glob("*.yaml")):
        raw = yaml.safe_load(f.read_text()) or {}

        # A half-written entry -- a bare "-" with nothing under it -- parses as a
        # null list item and then blows up deep inside the loader with an
        # unhelpful TypeError. Say which file and which entry instead.
        for i, entry in enumerate(raw.get("memos") or []):
            if entry is None:
                raise ValueError(
                    f"{f.name}: memo entry #{i + 1} is empty — a stray '-' with nothing "
                    f"under it. Delete the line or finish the memo."
                )
            if not entry.get("id"):
                raise ValueError(f"{f.name}: memo entry #{i + 1} has no `id:`")
            if entry.get("transcript") is None:
                raise ValueError(f"{f.name}/{entry['id']}: no `transcript:`")
            for j, m in enumerate(entry.get("mentions") or []):
                if m is None:
                    raise ValueError(
                        f"{f.name}/{entry['id']}: mention #{j + 1} is empty"
                    )
                missing = [k for k in ("cluster", "as") if not m.get(k)]
                if missing:
                    raise ValueError(
                        f"{f.name}/{entry['id']}: mention #{j + 1} is missing {missing}"
                    )
                # A typo'd boolean -- `falso`, `ture`, `False ` -- parses as a
                # STRING, and every non-empty string is truthy. `ambiguous: falso`
                # silently means true, and `substantive: ture` silently keeps a
                # mention that should have been filtered. Both corrupt the
                # benchmark rather than failing.
                for flag in ("substantive", "ambiguous"):
                    if flag in m and not isinstance(m[flag], bool):
                        raise ValueError(
                            f"{f.name}/{entry['id']}: mention #{j + 1} has "
                            f"{flag}: {m[flag]!r} — must be true or false, "
                            f"not a string. Check the spelling."
                        )

        memos = [
            Memo(
                id=str(m["id"]).strip(),
                transcript=m["transcript"].strip(),
                mentions=[
                    Mention(
                        memo_id=str(m["id"]).strip(),
                        # Stripped on load. A trailing space in `as:` produces a
                        # mention key nothing can match, and the mention then
                        # scores as a miss for a reason invisible in the YAML.
                        cluster=str(x["cluster"]).strip(),
                        as_written=str(x["as"]).strip(),
                        substantive=bool(x.get("substantive", True)),
                        ambiguous=bool(x.get("ambiguous", False)),
                    )
                    for x in (m.get("mentions") or [])
                ],
            )
            for m in raw["memos"]
        ]
        out.append(Scenario(id=raw["id"], description=raw.get("description", ""), memos=memos))
    return out


@dataclass
class RunResult:
    scenario_id: str
    pred_clusters: dict[str, str] = field(default_factory=dict)
    pred_substantive: dict[str, bool] = field(default_factory=dict)
    n_ambiguous_flagged: int = 0
    questions_asked: int = 0
    errors: list[str] = field(default_factory=list)


def run_scenario(scenario: Scenario, store_path: Path) -> RunResult:
    """Feed each memo through extract + resolve, in order, against a fresh store."""
    os.environ["RECALL_STORE_PATH"] = str(store_path)

    # Imported late and re-imported per run so the store path env var is picked up.
    from recall.nodes.dedupe import dedupe_node
    from recall.nodes.extract import extract_people_node
    from recall.nodes.merge import merge_node
    from recall.nodes.persist import persist_node

    result = RunResult(scenario_id=scenario.id)

    for memo in scenario.memos:
        try:
            extracted = extract_people_node({"transcript": memo.transcript})
            people = extracted.get("people", [])

            # One alignment, used by BOTH metrics. Doing it once is not just
            # tidiness: scoring "was this mention kept?" by a looser rule than
            # "which person is this mention?" lets a memo report every gold
            # mention as extracted while none of them can be placed.
            alignment = align(memo.mentions, people)

            # Substantive: did each gold mention survive the filter?
            # Aliases count. The extractor canonicalises to a full name and puts
            # the spoken form in `aliases` ("Tiu Chuei Enn" / "Crispy"), which is
            # correct behaviour -- matching on `name` alone scores it as a miss.
            for m in memo.mentions:
                result.pred_substantive[m.key] = m.key in alignment

            state: dict[str, Any] = {"people": people}
            routed = dedupe_node(state)
            state.update(routed)

            # Which record id did each extracted person land on? Keyed by
            # position in `people`, because that is what `align` refers to and
            # because two people in one memo can carry equal dicts.
            record_of: dict[int, str] = {}
            for match in routed.get("known_matches", []):
                i = _index_of(people, match["person"])
                if i is not None:
                    record_of[i] = match["record_id"]
            merge_node(state)

            persisted = persist_node(state)
            new_ids = persisted.get("persisted_ids", [])
            for person, rid in zip(state.get("new_people", []), new_ids):
                i = _index_of(people, person)
                if i is not None:
                    record_of[i] = rid

            for key, i in alignment.items():
                if i in record_of:
                    result.pred_clusters[key] = record_of[i]
            # People the system named that no gold mention claims -- a spurious
            # extraction. It has to reach the metrics, or inventing contacts is
            # free.
            for i, rid in record_of.items():
                if i not in set(alignment.values()):
                    result.pred_clusters[f"{memo.id}:<{people[i].get('name')}>"] = rid

            result.n_ambiguous_flagged += len(routed.get("ambiguous", []))
        except Exception as exc:  # noqa: BLE001 - one bad memo must not kill the sweep
            result.errors.append(f"{scenario.id}/{memo.id}: {type(exc).__name__}: {exc}")

    return result


def _labels(person: dict) -> frozenset[str]:
    """Every string the system offers for this person: name plus aliases."""
    out = {str(person.get("name", "")).lower().strip()}
    out |= {str(a).lower().strip() for a in (person.get("aliases") or [])}
    return frozenset(x for x in out if x)


_DISAMBIGUATOR = re.compile(r"\s*\(\d+\)\s*$")


def _strip_disambiguator(label: str) -> str:
    """Drop a trailing "(1)"/"(2)".

    A plural reference — "the two MCIS girls" — is one phrase covering two
    people, but mention keys must be unique within a memo. The numeric suffix
    exists only to separate the keys; the speaker never said it, so it must not
    take part in matching.
    """
    return _DISAMBIGUATOR.sub("", label).strip()


# Function words carry no identity. Leaving them in means "the tennis boy with
# square glasses" and "the tennis girl with round gold glasses" share `the` and
# `with`, which under a single-shared-token rule made them the same person.
# Words that DO discriminate -- boy/girl/guy, no, colours, sports -- stay in.
_STOPWORDS = frozenset({"a", "an", "the", "this", "that", "these", "those", "and", "or",
    "but", "with", "without", "who", "whom", "whose", "which", "what", "is", "was", "are",
    "were", "be", "been", "being", "do", "does", "did", "i", "me", "my", "mine", "we",
    "our", "us", "you", "your", "he", "him", "his", "she", "her", "hers", "they", "them",
    "their", "at", "in", "on", "of", "for", "from", "to", "by", "as", "also", "just",
    "still", "then", "there", "here", "got", "kept", "keep", "very", "quite", "super",
    "really",
})

# Below this, two labels are not the same person. Kept low because the
# assignment is competitive -- argmax decides between real rivals, and the floor
# only has to keep a label with nothing in common from latching on.
MIN_ALIGN = 0.25


def _content(label: str) -> frozenset[str]:
    a = _strip_disambiguator(label).lower()
    a = re.sub(r"[^a-z0-9' ]+", " ", a)
    return frozenset(t for t in a.split() if t and t not in _STOPWORDS)


def similarity(as_written: str, label: str) -> float:
    """How much two ways of referring to a person agree, in [0, 1].

    Jaccard over content words, NOT "do they share any token". The gold label is
    how the speaker referred to someone ("the CNM girl with clear glasses") and
    the system emits its own shorthand ("CNM girl"), so exact equality would
    score correct behaviour as failure -- but any-token-overlap scores every
    descriptor in a memo as every other one, which is worse: it silently merges
    distinct gold mentions into a single key and reports the rest as misses.
    """
    ta, tb = _content(as_written), _content(label)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def best_similarity(as_written: str, labels: frozenset[str]) -> float:
    return max((similarity(as_written, x) for x in labels), default=0.0)


def align(mentions: list[Mention], people: list[dict]) -> dict[str, int]:
    """Map each gold mention key onto the index of the person it refers to.

    Greedy on the strongest pair first, and **one gold mention per person**,
    with one exception: a person may serve several gold mentions that share a
    gold cluster. That is the alias case -- "Chong Jie" and "CJ" are two keys
    for one human, and the extractor is right to emit one record with an alias.
    Because the exemption is keyed on the mentions agreeing about the cluster,
    it can never hide a wrong merge: a collapse of two DIFFERENT clusters onto
    one person still costs, which is the whole reason the assignment is
    exclusive.
    """
    scored: list[tuple[float, int, int]] = []
    for mi, m in enumerate(mentions):
        for pi, person in enumerate(people):
            s = best_similarity(m.as_written, _labels(person))
            if s >= MIN_ALIGN:
                scored.append((s, mi, pi))
    # -s first, then mention/person index, so a tie resolves the same way every
    # run. An unstable tie-break makes the benchmark irreproducible for a reason
    # nobody would think to look for.
    scored.sort(key=lambda t: (-t[0], t[1], t[2]))

    out: dict[str, int] = {}
    taken: dict[int, str] = {}          # person index -> gold cluster already on it
    for _s, mi, pi in scored:
        m = mentions[mi]
        if m.key in out:
            continue
        if pi in taken and taken[pi] != m.cluster:
            continue
        out[m.key] = pi
        taken[pi] = m.cluster
    return out


def _index_of(people: list[dict], person: dict) -> int | None:
    """Position of `person` in `people`, by identity.

    Identity, not equality: the nodes pass the same dict objects through, and
    two people in one memo can compare equal before the store fills them in.
    """
    for i, p in enumerate(people):
        if p is person:
            return i
    return None


def fresh_store_path() -> Path:
    d = tempfile.mkdtemp(prefix="recall-eval-")
    return Path(d) / "graph.json"
