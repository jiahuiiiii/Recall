"""Seed the person graph with people who are hard to tell apart.

    uv run seed_demo.py                          # scratch graph, prints how to use it
    uv run seed_demo.py --scenario sales         # the professional cast instead
    uv run seed_demo.py --write                  # writes data/person_graph.json
    uv run seed_demo.py --store PATH             # somewhere else

**A clarifying question is impossible on an empty graph.** "Ambiguous" means
"which of the people I already know is this?", so with nobody known every
mention is trivially new: `store.search` returns no candidates, the three-zone
band never runs, `ambiguous` stays empty and `ask_node` has nothing to select
over. You need at least two people the resolver can confuse.

These records are built to be confusable on purpose -- same school, same firm,
same course or sector -- because that is what makes a loose reference like "the
malaysian girl" or "the partner from Jungle" land in the ambiguous band instead
of resolving cleanly.

Two scenarios, because the setting decides which channels `resolve.compare` can
even use. In `hall` nobody has an employer, so `company` and `role` sit silent
and the tie is carried by `notes`. In `sales` both are populated, so they can
agree AND conflict -- which is the setting `business.md` pitches and the one the
eval was thinnest on before `arc_sales.yaml`.

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
HALL = [
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

# The cast of data/memos/day1.txt and day2.txt, as if those two memos had already
# been recorded, plus ONE person who was not in them: Rachel.
#
# Rachel is the whole point. day1 records Priya as a partner at "some early stage
# fund, Antler maybe? Or Jungle" -- the speaker genuinely did not know. Seeding a
# second partner who really is at Jungle makes "the partner from Jungle" a
# question the graph cannot answer from what it was told, which is the honest
# version of business.md's second Alex: the ambiguity is in the record because it
# was in the conversation, not because the fixture was rigged.
SALES = [
    {"name": "Wei Lin",
     "company": "GIC",
     "role": "quant infrastructure lead",
     "met_at": ["the SuperAI mixer at Marina Bay Sands", "the AI Engineer meetup at Funan"],
     "notes": ["about six years at GIC",
               "their feature store is held together with cron jobs",
               "hiring for a mid to senior quant infra role",
               "asked how we handle backfills in Kestrel",
               "wants two or three candidate names by Friday"]},
    {"name": "Arjun Menon",
     "company": "Sea Group",
     "role": "recommendations engineer",
     "met_at": ["the SuperAI mixer at Marina Bay Sands"],
     "notes": ["about three years in",
               "gave the talk on embedding drift",
               "argues you do not need a vector DB at their scale",
               "introduced to Marcus, who has the same problem at Grab"]},
    {"name": "Priya",
     "role": "partner at an early stage fund",
     "met_at": ["the SuperAI mixer at Marina Bay Sands"],
     "notes": ["did not catch her last name",
               "at Antler or Jungle, I was not sure which",
               "asked if we were raising",
               "wants the deck next week once it is cleaned up",
               "based in Singapore but travels to Jakarta a lot"]},
    {"name": "Rachel Sim",
     "company": "Jungle Ventures",
     "role": "partner",
     "met_at": ["the founders dinner at Tanjong Pagar"],
     "notes": ["leads their seed practice",
               "asked if we were raising",
               "wants to see the deck when it is ready",
               "does not invest outside Southeast Asia"]},
    {"name": "Chen Yu Xin",
     "company": "Tessellate",
     "role": "founding engineer",
     "met_at": ["the AI Engineer meetup at Funan"],
     "notes": ["seed stage, document extraction for logistics",
               "ex-Shopee",
               "threw out their LLM-as-judge setup because it rewarded verbosity",
               "wants the eval paper we were reading"]},
    {"name": "Marcus",
     "company": "Grab",
     "met_at": ["the AI Engineer meetup at Funan"],
     "notes": ["dealing with the same recommendations problem as Arjun"]},
]

SCENARIOS = {
    "hall": (
        HALL,
        ("I bumped into the malaysian girl again at dinner, the one from the "
         "independent school."),
        ("Kit Yee and Tiu Chuei Enn score identically on it, so it lands in the\n"
         "ambiguous band and the agent picks one question to tell them apart."),
    ),
    "sales": (
        SALES,
        ("Ran into the partner from Jungle again at the founders thing. She asked "
         "how the raise is going and wants the updated deck by end of month."),
        ("Priya was recorded as being at Antler OR Jungle, and Rachel Sim really is\n"
         "at Jungle, so the mention fits both. Merging it into either one silently is\n"
         "how a duplicate lead gets made -- the agent asks instead."),
    ),
}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", choices=sorted(SCENARIOS), default="hall",
                    help="hall (students, no employers) or sales (company and role populated)")
    ap.add_argument("--write", action="store_true",
                    help=f"write {LIVE} — the graph the web UI actually reads")
    ap.add_argument("--store", default=None, help="write somewhere else entirely")
    args = ap.parse_args(argv)

    people, suggested, why = SCENARIOS[args.scenario]
    target = Path(args.store) if args.store else (LIVE if args.write else SCRATCH)
    target.parent.mkdir(parents=True, exist_ok=True)

    # Point the store at the target BEFORE importing it: get_store() reads the
    # environment at call time, and LocalPersonStore loads the file on
    # construction, so a store built against the default path never sees this.
    os.environ["RECALL_STORE_PATH"] = str(target)
    from recall.memory import get_store

    store = get_store()
    existing = {r.get("name") for r in store.all()}
    added = [p["name"] for p in people if p["name"] not in existing]
    for person in people:
        if person["name"] not in existing:
            store.upsert(person)

    print(f"scenario: {args.scenario}")
    print(f"graph: {target}")
    print(f"added: {', '.join(added) if added else '(nothing — all of them already there)'}")
    print(f"total: {len(get_store().all())} people\n")

    if target != LIVE:
        print("This is NOT the graph the web UI reads. To use it:\n")
        print(f"  RECALL_STORE_PATH={target} uv run web/server.py\n")
        print(f"Or seed the real one with:  uv run {Path(__file__).name} "
              f"--scenario {args.scenario} --write\n")

    print("Then run a memo that names neither of them, e.g.\n")
    print(f"  {suggested}\n")
    print(why)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
