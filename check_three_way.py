"""Deterministic repro of the three-way ambiguous case, end to end, offline.

Mirrors ask_node's arithmetic exactly (same prior construction, same derive,
same rank_questions) but skips transcription and extraction, which are the only
non-deterministic steps. Nothing here touches the live graph.
"""
import sys

from recall.answer import resolve_with_answer
from recall.eig import Hypothesis, normalise, rank_questions
from recall.nodes.ask import PRIOR_TEMPERATURE
from recall.questions import derive, needs_model
from recall.resolve import Zone, decide

# --- the three stored people, as the storyboard wants them -------------------
RECORDS = [
    {"id": "p_jason", "name": "Jason", "aliases": [], "company": None,
     "role": None, "met_at": [],
     "notes": ["Malaysian", "studies computer science",
               "lives in Eusoff Hall", "wears glasses"]},
    {"id": "p_john", "name": "John", "aliases": [], "company": None,
     "role": None, "met_at": [],
     "notes": ["Malaysian", "studies electrical engineering",
               "lives in Raffles Hall", "wears glasses"]},
    {"id": "p_johnson", "name": "Johnson", "aliases": [], "company": None,
     "role": None, "met_at": [],
     "notes": ["Malaysian", "studies psychology",
               "lives in Eusoff Hall", "wears glasses"]},
]

# --- the mention, as extraction would emit it --------------------------------
MENTION = {"name": "the Malaysian first-year with glasses", "aliases": [],
           "company": None, "role": None, "met_at": [],
           "notes": ["Malaysian", "year one", "wears glasses"]}

print("=" * 72)
zone, cands = decide(MENTION, RECORDS)
print(f"ZONE: {zone.value}")
for c in cands:
    print(f"  {c.name:<10} score={c.score:6.2f}   {c.agreement.explain()}")
if zone is not Zone.AMBIGUOUS:
    print("\n!! not ambiguous -- the question path never fires. Stop here.")
    sys.exit(1)

# --- priors, exactly as ask_node builds them ---------------------------------
raw = {c.record_id: c.score for c in cands}
raw[""] = 0.0                      # the "someone new" hypothesis
prior = normalise(raw, temperature=PRIOR_TEMPERATURE)
names = {c.record_id: c.name for c in cands} | {"": "someone new"}
hyps = [Hypothesis(rid, names[rid], prior[rid]) for rid in raw]

print("\nPRIORS")
for h in sorted(hyps, key=lambda h: -h.prior):
    print(f"  {h.name:<14} {h.prior:6.1%}")

# --- questions, scored ------------------------------------------------------
records = {r["id"]: r for r in RECORDS}
qs = derive(hyps, records)
print(f"\nDERIVED {len(qs)} questions | needs_model={needs_model(qs)}")

ranked = rank_questions(hyps, qs)
print("\nEIG RANKING")
for s in ranked[:8]:
    print(f"  {s.eig:5.3f} bits  {s.question.text}")
    print(f"               outcomes={s.question.outcomes}")

if not ranked:
    sys.exit("no questions derived")

# --- answer it --------------------------------------------------------------
best = ranked[0].question
ANSWER = sys.argv[1] if len(sys.argv) > 1 else "psychology"
res = resolve_with_answer(hyps, best, ANSWER)
print(f"\nASKED : {best.text}")
print(f"ANSWER: {ANSWER!r}")
print(f"WINNER: {res.name}  @ {res.confidence:.1%}" if res else "no resolution")
print("=" * 72)
