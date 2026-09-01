"""Give records written before `times_met` existed a starting count.

    uv run backfill_times_met.py            # dry run, prints what it would set
    uv run backfill_times_met.py --write    # writes, after a timestamped backup
    uv run backfill_times_met.py --store PATH

**The true count is not recoverable from the file, and this does not pretend
otherwise.** The graph keeps no per-memo history: `met_at` is a deduplicated set
of places, and `note_log` stamps each note with the DAY it first appeared, so
three memos about one person on one afternoon leave one date behind. The best
available signal is the number of distinct days the person's notes were first
recorded on, which is a FLOOR -- never more than the truth, often less.

So this restores "at least this many", not "exactly this many". Counts are exact
only from here forward, where the store increments on each occasion.

Records that already carry `times_met` are left alone.

Free and offline: no model calls, no spend. `--write` is required to touch the
real graph.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

LIVE = Path("data/person_graph.json")


def floor_count(record: dict) -> int:
    """Fewest occasions consistent with what the record still remembers."""
    days = {e.get("at") for e in record.get("note_log") or [] if isinstance(e, dict) and e.get("at")}
    places = len(record.get("met_at") or [])
    return max(len(days), places, 1)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="actually write the graph")
    ap.add_argument("--store", type=Path, default=LIVE, help="graph file to backfill")
    args = ap.parse_args(argv)

    path: Path = args.store
    if not path.exists():
        print(f"no graph at {path}")
        return 1

    data = json.loads(path.read_text() or "{}")
    people = data.get("people", [])

    planned, skipped = [], 0
    for record in people:
        if record.get("times_met") is not None:
            skipped += 1
            continue
        planned.append((record, floor_count(record)))

    print(f"graph: {path}  ({len(people)} people, {skipped} already counted)\n")
    for record, n in planned:
        days = len({e.get("at") for e in record.get("note_log") or []
                    if isinstance(e, dict) and e.get("at")})
        print(f"  {record.get('name', '?'):18} -> {n:2}  "
              f"({days} note day(s), {len(record.get('met_at') or [])} place(s))")
    if not planned:
        print("  nothing to do")
        return 0

    if not args.write:
        print(f"\nDry run. {len(planned)} record(s) would change. Re-run with --write.")
        print("These are floors, not true counts -- see this file's docstring.")
        return 0

    backup = path.with_name(f"{path.stem}.backup-{datetime.now(UTC).astimezone():%Y%m%d-%H%M%S}-times-met{path.suffix}")
    shutil.copy2(path, backup)
    for record, n in planned:
        record["times_met"] = n
    path.write_text(json.dumps(data, indent=2))
    print(f"\nbacked up to {backup}")
    print(f"wrote {len(planned)} record(s) to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
