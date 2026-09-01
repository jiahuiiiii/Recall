"""Run the benchmark and print the table.

    uv run eval/run_eval.py                # 3 repeats, all scenarios
    uv run eval/run_eval.py --repeats 5
    uv run eval/run_eval.py --scenario known_return

Bedrock is not deterministic even at temperature 0, so this repeats each scenario
and reports mean and spread. A single run is an anecdote, and a benchmark table
built from one is the kind of thing a judge disproves by re-running it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.harness import fresh_store_path, load_scenarios, run_scenario  # noqa: E402
from eval.metrics import b_cubed, binary, pairwise, summarise  # noqa: E402


def _with_misses(gold: dict[str, str], pred: dict[str, str]) -> dict[str, str]:
    """Score gold mentions the system never produced.

    The metrics only compare keys present in both, so a mention the pipeline
    failed to extract would otherwise vanish from the denominator -- a system
    that found three of four people would score a clean 1.000. Each miss becomes
    its own singleton cluster, which is what actually happened: it was not linked
    to anyone.
    """
    out = dict(pred)
    for key in gold:
        out.setdefault(key, f"__missed__{key}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--scenario", default=None, help="run only this scenario id")
    args = ap.parse_args()

    scenarios = load_scenarios()
    if args.scenario:
        scenarios = [s for s in scenarios if s.id == args.scenario]
    if not scenarios:
        print("no scenarios found in eval/fixtures/")
        return 1

    from recall._common import HAIKU, LEDGER

    n_memos = sum(len(s.memos) for s in scenarios)
    print(f"model    : {HAIKU}")
    print(f"scenarios: {len(scenarios)}  memos: {n_memos}  repeats: {args.repeats}\n")

    if n_memos < 20:
        print(f"!! {n_memos} memos. Below ~20 these numbers are anecdotes, not results.")
        print("!! Add fixtures before quoting anything from this table.\n")

    rows: dict[str, dict[str, list[float]]] = {}
    all_errors: list[str] = []
    total_ambiguous = 0
    total_flagged = 0

    for s in scenarios:
        acc = {"b3_f1": [], "b3_p": [], "b3_r": [], "pw_f1": [], "sub_f1": []}
        covered: list[float] = []
        for _ in range(args.repeats):
            r = run_scenario(s, fresh_store_path())
            all_errors += r.errors
            total_flagged += r.n_ambiguous_flagged
            pred = _with_misses(s.gold_clusters, r.pred_clusters)
            covered.append(
                len(s.gold_clusters.keys() & r.pred_clusters.keys()) / max(len(s.gold_clusters), 1)
            )
            b3 = b_cubed(s.gold_clusters, pred)
            pw = pairwise(s.gold_clusters, pred)
            sub = binary(s.gold_substantive, r.pred_substantive)
            acc["b3_f1"].append(b3.f1)
            acc["b3_p"].append(b3.precision)
            acc["b3_r"].append(b3.recall)
            acc["pw_f1"].append(pw.f1)
            acc["sub_f1"].append(sub.f1)
        acc["coverage"] = covered
        rows[s.id] = acc
        total_ambiguous += len(s.ambiguous_keys)

    w = max(len(k) for k in rows) + 2
    def cell(vals): return f"{sum(vals)/len(vals):.3f}" if vals else "n/a"
    print(f"{'scenario':<{w}} {'B3 F1':>7} {'B3 P':>7} {'B3 R':>7} {'pair F1':>8} {'subst':>7} {'covrg':>7}")
    print("-" * (w + 48))
    for sid, acc in rows.items():
        print(f"{sid:<{w}} {cell(acc['b3_f1']):>7} {cell(acc['b3_p']):>7} {cell(acc['b3_r']):>7} "
              f"{cell(acc['pw_f1']):>8} {cell(acc['sub_f1']):>7} {cell(acc['coverage']):>7}")

    print("\nspread across repeats (a single run is an anecdote):")
    for sid, acc in rows.items():
        print(f"  {sid:<{w}} B3 F1 {summarise(acc['b3_f1'])}")

    overall = [v for acc in rows.values() for v in acc["b3_f1"]]
    print(f"\nB-cubed F1 across all scenarios: {summarise(overall)}")

    # This script measures RESOLUTION only. It used to close with a hardcoded
    # "no question node yet / NOT IMPLEMENTED", which stayed there long after
    # `ask_node` shipped and read as a status report -- it was a string
    # literal. A stale literal that looks like a measurement is worse than no
    # line at all, so point at the script that actually measures the headline.
    print("\n--- ambiguous band (the denominator run_questions.py measures over) ---")
    print(f"  gold ambiguous mentions      : {total_ambiguous}")
    print(f"  flagged ambiguous at runtime : {total_flagged}")
    print("  questions per resolution     : run `uv run eval/run_questions.py`")

    if all_errors:
        print(f"\n--- errors ({len(all_errors)}) ---")
        for e in all_errors[:10]:
            print("  !", e)

    print(f"\n{LEDGER.report()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
