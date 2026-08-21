"""Run the resolution pipeline over fixture scenarios and score the clustering.

Deliberately does NOT run the whole graph. Enrichment, drafting and the calendar
are outside the scoped project and cost most of the tokens; the eval exercises
transcribe-free extraction plus resolution, which is what the benchmark measures.

Always runs against a throwaway store. The user's person graph is real data and
must never be written to by an eval sweep.
"""

from __future__ import annotations

import os
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
        raw = yaml.safe_load(f.read_text())
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
                    for x in m.get("mentions", [])
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
    from recall.memory import LocalPersonStore
    from recall.nodes.dedupe import dedupe_node
    from recall.nodes.extract import extract_people_node
    from recall.nodes.merge import merge_node
    from recall.nodes.persist import persist_node

    result = RunResult(scenario_id=scenario.id)
    store = LocalPersonStore(store_path)

    for memo in scenario.memos:
        gold_by_name = {m.as_written.lower(): m for m in memo.mentions}
        try:
            extracted = extract_people_node({"transcript": memo.transcript})
            people = extracted.get("people", [])

            # Substantive: did each gold mention survive the filter?
            # Aliases count. The extractor canonicalises to a full name and puts
            # the spoken form in `aliases` ("Tiu Chuei Enn" / "Crispy"), which is
            # correct behaviour -- matching on `name` alone scores it as a miss.
            kept = {_labels(p) for p in people}
            for m in memo.mentions:
                result.pred_substantive[m.key] = any(
                    _matched(m.as_written, labels) for labels in kept
                )

            state: dict[str, Any] = {"people": people}
            routed = dedupe_node(state)
            state.update(routed)

            # Which record id did each extracted person land on?
            for match in routed.get("known_matches", []):
                _assign(result, memo, gold_by_name, match["person"], match["record_id"])
            merge_node(state)

            persisted = persist_node(state)
            new_ids = persisted.get("persisted_ids", [])
            for person, rid in zip(state.get("new_people", []), new_ids):
                _assign(result, memo, gold_by_name, person, rid)

            result.n_ambiguous_flagged += len(routed.get("ambiguous", []))
        except Exception as exc:  # noqa: BLE001 - one bad memo must not kill the sweep
            result.errors.append(f"{scenario.id}/{memo.id}: {type(exc).__name__}: {exc}")

    store  # keep the reference alive for the duration of the scenario
    return result


def _labels(person: dict) -> frozenset[str]:
    """Every string the system offers for this person: name plus aliases."""
    out = {str(person.get("name", "")).lower().strip()}
    out |= {str(a).lower().strip() for a in (person.get("aliases") or [])}
    return frozenset(x for x in out if x)


def _matched(as_written: str, labels: frozenset[str]) -> bool:
    """Did the system extract someone recognisable as this gold mention?

    Loose on purpose: the gold label is how the speaker referred to them
    ("the GIC one"), while the system emits its best guess at a canonical name.
    Exact string equality would score correct behaviour as failure.
    """
    a = as_written.lower().strip()
    return any(a in k or k in a or _overlap(a, k) for k in labels)


def _overlap(a: str, b: str) -> bool:
    ta, tb = set(a.split()), set(b.split())
    return bool(ta & tb)


def _assign(result: RunResult, memo: Memo, gold_by_name: dict, person: dict, record_id: str) -> None:
    """Map a system output back onto the gold mention it corresponds to."""
    labels = _labels(person)
    for gold_name, mention in gold_by_name.items():
        if _matched(gold_name, labels):
            result.pred_clusters[mention.key] = record_id
            return
    # System named someone the fixture did not list -- a spurious extraction.
    result.pred_clusters[f"{memo.id}:<{person.get('name')}>"] = record_id


def fresh_store_path() -> Path:
    d = tempfile.mkdtemp(prefix="recall-eval-")
    return Path(d) / "graph.json"
