"""Validate fixtures before spending model calls on them.

    uv run eval/check_fixtures.py

Catches the mistakes that make a fixture score meaninglessly rather than wrongly:
a cluster only ever mentioned once (nothing to link), an ambiguous mention with a
definite label, a scenario too short to exercise memory at all. Costs nothing --
it never calls a model.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.harness import load_all_scenarios  # noqa: E402

TARGET_MEMOS = 20
TARGET_AMBIGUOUS = 8
PLACEHOLDER = "REPLACE"


def is_placeholder(memo) -> bool:
    """Skeleton memos must not count toward the targets.

    A progress bar that fills up with unwritten stubs is worse than no progress
    bar: it says the benchmark is nearly ready when nothing has been written.
    """
    if PLACEHOLDER in memo.transcript:
        return True
    return any(PLACEHOLDER in m.as_written or PLACEHOLDER in m.cluster for m in memo.mentions)


def main() -> int:
    scenarios = load_all_scenarios()
    if not scenarios:
        print("no fixtures found in eval/fixtures/")
        return 1

    errors: list[str] = []
    warnings: list[str] = []
    total_memos = total_mentions = total_ambig = total_passing = 0
    linked_clusters = skeleton_memos = 0
    skeletons: list[str] = []

    print(f"{'scenario':<24} {'memos':>6} {'ments':>6} {'people':>7} {'recurs':>7} {'ambig':>6} {'passing':>8}")
    print("-" * 72)

    for s in scenarios:
        stubs = [m.id for m in s.memos if is_placeholder(m)]
        if stubs:
            skeleton_memos += len(stubs)
            if len(stubs) == len(s.memos):
                skeletons.append(s.id)
                print(f"{s.id:<24} {'—':>6} {'—':>6} {'—':>7} {'—':>7} {'—':>6} {'—':>8}   (skeleton, not written yet)")
                continue
            warnings.append(f"{s.id}: {len(stubs)} unwritten memo(s) {stubs} — not counted")

        memo_ids = [m.id for m in s.memos]
        dupes = [k for k, v in Counter(memo_ids).items() if v > 1]
        if dupes:
            errors.append(f"{s.id}: duplicate memo id(s) {dupes} — later ones overwrite earlier scoring keys")

        # Mentions are keyed memo_id:as, so two people referred to identically in
        # ONE memo collide and the second silently replaces the first. Realistic
        # ("met two Alexes") and invisible without this check.
        for m in s.memos:
            labels = Counter(x.as_written for x in m.mentions)
            for label, count in labels.items():
                if count > 1:
                    errors.append(
                        f"{s.id}/{m.id}: {count} mentions both written as {label!r}. "
                        f"They collide into one scoring key — distinguish them "
                        f"(e.g. \"Alex (robotics)\" / \"Alex (fintech)\")."
                    )

        cluster_memos: dict[str, set[str]] = {}
        ambig = passing = 0
        written = [m for m in s.memos if not is_placeholder(m)]
        for m in written:
            for x in m.mentions:
                if x.ambiguous:
                    ambig += 1
                    if x.cluster != "UNRESOLVED":
                        warnings.append(
                            f"{s.id}/{m.id}: '{x.as_written}' is ambiguous but has a definite "
                            f"cluster '{x.cluster}'. If you can label it, it isn't ambiguous."
                        )
                elif x.cluster == "UNRESOLVED":
                    errors.append(
                        f"{s.id}/{m.id}: '{x.as_written}' is UNRESOLVED but not marked ambiguous"
                    )
                if not x.substantive:
                    passing += 1
                    if x.ambiguous:
                        warnings.append(
                            f"{s.id}/{m.id}: '{x.as_written}' is both non-substantive and "
                            f"ambiguous. Non-substantive mentions are filtered before "
                            f"resolution runs, so `ambiguous` is never acted on. Pick one."
                        )
                if x.substantive and not x.ambiguous and x.cluster != "UNRESOLVED":
                    cluster_memos.setdefault(x.cluster, set()).add(m.id)

        # Distinct memos, so a duplicated memo id cannot fake a recurrence.
        multi = sum(1 for memos in cluster_memos.values() if len(memos) > 1)
        linked_clusters += multi
        scored = len(s.gold_clusters)

        if scored < 2:
            warnings.append(
                f"{s.id}: only {scored} scored mention(s) — B-cubed is trivially 1.000. "
                f"Add memos so there is something to get wrong."
            )
        if multi == 0 and len(s.memos) > 1:
            warnings.append(
                f"{s.id}: nobody appears in more than one memo, so this file tests nothing "
                f"about recognition. Bring an existing person back in a later memo."
            )
        if len(s.memos) < 3:
            warnings.append(f"{s.id}: {len(s.memos)} memos. Longer scenarios are harder and more realistic.")

        print(f"{s.id:<24} {len(written):>6} {sum(len(m.mentions) for m in written):>6} "
              f"{len(cluster_memos):>7} {multi:>7} {ambig:>6} {passing:>8}")

        total_memos += len(written)
        total_mentions += sum(len(m.mentions) for m in written)
        total_ambig += ambig
        total_passing += passing

    print("-" * 72)
    print(f"{'TOTAL':<24} {total_memos:>6} {total_mentions:>6} {'':>7} {linked_clusters:>7} "
          f"{total_ambig:>6} {total_passing:>8}")

    print("\nprogress toward a reportable benchmark:")
    print(f"  memos            {total_memos:>3} / {TARGET_MEMOS}   {_bar(total_memos, TARGET_MEMOS)}")
    print(f"  ambiguous        {total_ambig:>3} / {TARGET_AMBIGUOUS}   {_bar(total_ambig, TARGET_AMBIGUOUS)}"
          "   <- the denominator for the EIG headline")
    print(f"  recurring people {linked_clusters:>3} / 12  {_bar(linked_clusters, 12)}"
          "   <- people in 2+ memos; each one is a recognition test")
    print(f"  passing mentions {total_passing:>3}       (should NOT be recorded)")

    if skeletons:
        print(f"\n  {len(skeletons)} skeleton file(s) awaiting content: {', '.join(skeletons)}")

    for w in warnings:
        print(f"\n  warn: {w}")
    for e in errors:
        print(f"\n  ERROR: {e}")

    if errors:
        print(f"\n{len(errors)} error(s) — fix before running the benchmark.")
        return 1
    print("\nfixtures are well-formed.")
    return 0


def _bar(n: int, target: int, width: int = 24) -> str:
    filled = min(width, round(width * n / target)) if target else width
    return "[" + "#" * filled + "." * (width - filled) + "]"


if __name__ == "__main__":
    sys.exit(main())
