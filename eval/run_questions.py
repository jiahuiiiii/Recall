"""The headline table: EIG vs random vs uncertainty sampling.

    uv run eval/run_questions.py [--repeats 5] [--scenario arc_acacia]

Walks each scenario, and whenever the band flags a mention as ambiguous AND the
fixture holds the right answer, plays all three strategies against the same
candidate questions with a simulated user answering from the gold record.

Reports questions-per-resolution and the share resolved inside a 1-question
budget, which is the budget the product actually has.
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.harness import fresh_store_path, load_scenarios
from eval.metrics import summarise
from eval.strategies import MAX_QUESTIONS, build_hypotheses, play
from recall.text import overlap_ratio, tokens

STRATEGIES = ["eig", "uncertainty", "random"]

# Memos lost to a bad extraction. Reported at the end rather than swallowed: a
# smaller case set is a real caveat on the number, not a detail.
COLLECT_ERRORS: list[str] = []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=3,
                    help="full pipeline runs; extraction is not deterministic, so "
                         "the case set itself varies between runs")
    ap.add_argument("--scenario", default=None)
    ap.add_argument(
        "--fixture",
        type=Path,
        default=None,
        help="run one YAML fixture or bundle instead of the default sweep; "
             "combine with --scenario to run a single arc out of a bundle",
    )
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    fixture_path = args.fixture
    if fixture_path and not fixture_path.is_absolute():
        fixture_path = Path.cwd() / fixture_path
    scenarios = load_scenarios(fixture_path) if fixture_path else load_scenarios()
    if args.scenario:
        scenarios = [s for s in scenarios if s.id == args.scenario]
    if not scenarios:
        where = str(fixture_path) if fixture_path else "eval/fixtures/"
        print(f"no scenarios found in {where}")
        return 1

    from recall._common import HAIKU

    print(f"model    : {HAIKU}")
    print(f"repeats  : {args.repeats}\n")

    # Re-collect the cases on every repeat. Bedrock returns different
    # extractions for the same memo at temperature 0, so the SET of ambiguous
    # mentions changes run to run -- collecting once and replaying the
    # strategies over it hides the dominant source of variance and reports a
    # single sample as if it were a result.
    rng = random.Random(args.seed)
    per_run: dict[str, list[float]] = defaultdict(list)
    per_run_budget: dict[str, list[float]] = defaultdict(list)
    case_counts: list[int] = []
    example_cases: list[dict] = []

    failed_runs = 0
    for run in range(args.repeats):
        cases = []
        try:
            for sc in scenarios:
                cases += collect_cases(sc)
        except Exception as exc:  # noqa: BLE001
            # One bad call must not throw away the whole sweep. Report how many
            # runs were lost rather than silently averaging over fewer.
            failed_runs += 1
            print(f"  run {run + 1} failed: {type(exc).__name__}: {exc}"[:160])
            continue
        case_counts.append(len(cases))
        if not example_cases:
            example_cases = cases
        if not cases:
            continue

        for strategy in STRATEGIES:
            trials = [play(strategy, c["hypotheses"], c["records"], c["gold_id"], rng)
                      for c in cases]
            resolved = [t for t in trials if t.resolved]
            if resolved:
                per_run[strategy].append(
                    statistics.mean(t.questions_asked for t in resolved))
            per_run_budget[strategy].append(
                sum(1 for t in trials if t.resolved and t.questions_asked <= 1) / len(trials))

    if not example_cases:
        print("No scorable cases: the band flagged nothing with a known answer.")
        print("Write loose references that carry a definite cluster — see")
        print("eval/fixtures/README.md, 'The most valuable case to write'.")
        return 1

    if failed_runs:
        print(f"!! {failed_runs} of {args.repeats} runs failed and are excluded.\n")
    if COLLECT_ERRORS:
        print(f"!! {len(COLLECT_ERRORS)} memo(s) dropped mid-run (cases lost, run kept):")
        for e in COLLECT_ERRORS[:5]:
            print("   !", e[:150])
        print()
    print(f"scorable ambiguous mentions per run: {case_counts}")
    for c in example_cases:
        print(f"  {c['scenario']}/{c['memo']}  {c['mention']!r} -> {c['gold_name']}"
              f"   ({len(c['hypotheses'])} hypotheses)")

    print(f"\n{'strategy':<14} {'questions/resolution':>30} {'<=1 question':>14}")
    print("-" * 62)
    for strategy in STRATEGIES:
        runs = per_run[strategy]
        budget = per_run_budget[strategy]
        print(f"{strategy:<14} {summarise(runs):>30} "
              f"{statistics.mean(budget) if budget else 0:>13.0%}")

    print(f"\nbudget cap {MAX_QUESTIONS} questions; unresolved excluded from the mean.")
    print(f"{args.repeats} full pipeline runs. The case set is re-collected each time,")
    print("because extraction is not deterministic and the ambiguous set moves with it.")
    print("EIG and uncertainty sampling are themselves deterministic given a case set.")

    _shape_report(example_cases)
    _verdict(per_run)
    return 0


def _shape_report(cases: list[dict]) -> None:
    """How often the chosen question was multi-valued rather than yes/no.

    Reported because a lever nobody pulls is not a lever. If attribute probes
    are derivable but EIG keeps preferring a binary, that is worth knowing --
    it means the records rarely disagree about a value, not that the arithmetic
    is wrong.
    """
    from recall.eig import rank_questions
    from recall.questions import derive

    shapes = {"multi": 0, "binary": 0}
    for case in cases:
        ranked = rank_questions(case["hypotheses"], derive(case["hypotheses"], case["records"]))
        if not ranked:
            continue
        shapes["multi" if len(ranked[0].question.answer_space) > 2 else "binary"] += 1

    total = sum(shapes.values())
    if total:
        print(f"\nchosen question shape: {shapes['multi']}/{total} multi-valued, "
              f"{shapes['binary']}/{total} yes/no")


def _verdict(results) -> None:
    def mean_q(s):
        return statistics.mean(results[s]) if results[s] else float("inf")

    eig, unc, rnd = mean_q("eig"), mean_q("uncertainty"), mean_q("random")
    spread = max((max(v) - min(v)) for v in results.values() if len(v) > 1) if any(
        len(v) > 1 for v in results.values()) else 0.0
    if spread >= abs(eig - min(unc, rnd)):
        print(f"\nRun-to-run spread ({spread:.2f}) is as large as the gap between")
        print("strategies. Report this as inconclusive, not as a win.")
    print()
    if eig < min(unc, rnd) - 1e-9:
        print(f"EIG asks fewer questions: {eig:.2f} vs uncertainty {unc:.2f}, random {rnd:.2f}.")
    elif abs(eig - unc) < 1e-9 and eig < rnd:
        print(f"EIG ties uncertainty sampling ({eig:.2f}) and both beat random ({rnd:.2f}).")
        print("A tie is a real result: on these cases the strategies pick equally well.")
    else:
        print(f"EIG {eig:.2f}, uncertainty {unc:.2f}, random {rnd:.2f}.")
        print("Report as measured. Do not tune until it wins.")


def collect_cases(scenario) -> list[dict]:
    """Run the pipeline and keep ambiguous mentions whose answer we know."""
    import os

    os.environ["RECALL_STORE_PATH"] = str(fresh_store_path())
    from recall.memory import LocalPersonStore
    from recall.nodes.dedupe import dedupe_node
    from recall.nodes.extract import extract_people_node
    from recall.nodes.merge import merge_node
    from recall.nodes.persist import persist_node

    # Re-read the store at each point of use. LocalPersonStore loads the file
    # into memory on construction, so a single long-lived instance never sees
    # records written by later nodes -- and silently returns None for them.
    def store() -> LocalPersonStore:
        return LocalPersonStore(os.environ["RECALL_STORE_PATH"])

    gold_to_record: dict[str, str] = {}
    cases: list[dict] = []

    for memo in scenario.memos:
        # Per-memo, exactly as `harness.run_scenario` does. Without this a single
        # malformed extraction unwinds all five scenarios and `main` discards the
        # ENTIRE run -- ~34 scorable cases -- which is why the 30 and 31 Aug
        # headline tables are n=2 off a 3-repeat sweep. Losing one memo's cases
        # is a smaller lie than losing a third of the measurement.
        try:
            people = extract_people_node({"transcript": memo.transcript}).get("people", [])
            state = {"people": people}
            out = dedupe_node(state)
            state.update(out)
        except Exception as exc:  # noqa: BLE001
            COLLECT_ERRORS.append(f"{scenario.id}/{memo.id}: {type(exc).__name__}: {exc}")
            continue

        for entry in out.get("ambiguous", []):
            gold = _gold_for(memo, entry["person"].get("name", ""))
            # Only scorable when the fixture names a real person: an UNRESOLVED
            # mention has no answer to converge on.
            if gold is None or gold not in gold_to_record:
                continue
            hyps = build_hypotheses(entry)
            live = store()
            records = {h.record_id: r for h in hyps
                       if h.record_id and (r := live.get(h.record_id))}
            if gold_to_record[gold] not in records:
                continue
            cases.append({
                "scenario": scenario.id, "memo": memo.id,
                "mention": entry["person"].get("name", ""),
                "gold_id": gold_to_record[gold],
                "gold_name": records[gold_to_record[gold]].get("name", gold),
                "hypotheses": hyps, "records": records,
            })

        merge_node(state)
        ids = persist_node(state).get("persisted_ids", [])
        for person, rid in zip(state.get("new_people", []), ids):
            g = _gold_for(memo, person.get("name", ""))
            if g:
                gold_to_record.setdefault(g, rid)
        for match in out.get("known_matches", []):
            g = _gold_for(memo, match["person"].get("name", ""))
            if g:
                gold_to_record.setdefault(g, match["record_id"])

    return cases


def _gold_for(memo, name: str) -> str | None:
    """Which gold cluster this extracted name corresponds to, if any."""
    best, score = None, 0.0
    for mention in memo.mentions:
        if mention.cluster == "UNRESOLVED":
            continue
        s = overlap_ratio(tokens(name), tokens(mention.as_written))
        if s > score:
            best, score = mention.cluster, s
    return best if score >= 0.5 else None


if __name__ == "__main__":
    sys.exit(main())
