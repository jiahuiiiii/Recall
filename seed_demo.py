"""Seed the person graph with people who are hard to tell apart.

    uv run seed_demo.py                  # scratch graph, prints how to use it
    uv run seed_demo.py --write          # writes data/person_graph.json
    uv run seed_demo.py --store PATH     # somewhere else

**A clarifying question is impossible on an empty graph.** "Ambiguous" means
"which of the people I already know is this?", so with nobody known every
mention is trivially new: `store.search` returns no candidates, the three-zone
band never runs, `ambiguous` stays empty and `ask_node` has nothing to select
over. You need at least two people the resolver can confuse.

These records are built to be confusable on purpose -- same school, same hall,
same course family -- because that is what makes a loose reference like "the
malaysian girl" land in the ambiguous band instead of resolving cleanly.

Free and offline: no model calls, no Bedrock, no spend.

`--write` is required to touch the real graph. Seeded people are indistinguishable
from ones the user actually recorded, and a demo record that later looks like a
fact the agent invented is the expensive kind of confusion.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

LIVE = Path("data/person_graph.json")
SCRATCH = Path(".recall-demo-graph.json")

# Two Malaysian Chinese independent school girls in the same hall, differing in
# floor and course. A mention that names neither ("the malaysian girl") scores
# identically against both -- which is the tie EIG exists to break.
PEOPLE = [
    {"name": "Kit Yee",
     "met_at": ["Acacia orientation camp"],
     "notes": ["from malaysian chinese independent school",
               "lives at the 18th floor",
               "studies geospatial intelligence at NUS",
               "in group 2 at orientation"]},
    {"name": "Tiu Chuei Enn",
     "met_at": ["Acacia College"],
     "notes": ["from malaysian chinese independent school",
               "lives on the 4th floor",
               "studies computer science at NUS",
               "high school friend, everyone calls her Crispy"]},
    {"name": "Viktoria",
     "met_at": ["the dining hall"],
     "notes": ["from germany",
               "on exchange at NUS",
               "lives in Tembusu College"]},
    {"name": "Kang Ling",
     "met_at": ["the SimplifyNext hackathon"],
     "notes": ["studies computer science at NUS",
               "on my hackathon team"]},
]

SUGGESTED = "I bumped into the malaysian girl again at dinner, the one from the independent school."


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help=f"write {LIVE} — the graph the web UI actually reads")
    ap.add_argument("--store", default=None, help="write somewhere else entirely")
    args = ap.parse_args(argv)

    target = Path(args.store) if args.store else (LIVE if args.write else SCRATCH)
    target.parent.mkdir(parents=True, exist_ok=True)

    # Point the store at the target BEFORE importing it: get_store() reads the
    # environment at call time, and LocalPersonStore loads the file on
    # construction, so a store built against the default path never sees this.
    os.environ["RECALL_STORE_PATH"] = str(target)
    from recall.memory import get_store

    store = get_store()
    existing = {r.get("name") for r in store.all()}
    added = [p["name"] for p in PEOPLE if p["name"] not in existing]
    for person in PEOPLE:
        if person["name"] not in existing:
            store.upsert(person)

    print(f"graph: {target}")
    print(f"added: {', '.join(added) if added else '(nothing — all four already there)'}")
    print(f"total: {len(get_store().all())} people\n")

    if target != LIVE:
        print("This is NOT the graph the web UI reads. To use it:\n")
        print(f"  RECALL_STORE_PATH={target} uv run web/server.py\n")
        print(f"Or seed the real one with:  uv run {Path(__file__).name} --write\n")

    print("Then run a memo that names neither of them, e.g.\n")
    print(f"  {SUGGESTED}\n")
    print("Kit Yee and Tiu Chuei Enn score identically on it, so it lands in the")
    print("ambiguous band and the agent picks one question to tell them apart.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
