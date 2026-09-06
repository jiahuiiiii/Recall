"""Dry-run the three demo memos: zone, candidates, EIG, resolution.

Offline and deterministic -- the same arithmetic ask_node runs, minus the
extraction step. Records here must mirror seed_three_way.py.
"""
from recall.answer import resolve_with_answer
from recall.eig import Hypothesis, normalise, rank_questions
from recall.nodes.ask import PRIOR_TEMPERATURE
from recall.questions import derive, needs_model
from recall.resolve import Zone, decide

RECORDS = [
 {"id":"p_jason","name":"Jason","aliases":[],"company":None,"role":None,"met_at":["orientation"],
  "notes":["Malaysian","studies computer science",
           "lives in Eusoff Hall","plays for the Eusoff basketball team","wears glasses"]},
 {"id":"p_john","name":"John","aliases":[],"company":None,"role":None,"met_at":["orientation"],
  "notes":["Malaysian","studies electrical engineering",
           "lives in Raffles Hall","wears glasses"]},
 {"id":"p_johnson","name":"Johnson","aliases":[],"company":None,"role":None,"met_at":["orientation"],
  "notes":["Malaysian","studies psychology",
           "lives in Eusoff Hall","plays for the Eusoff basketball team","wears glasses"]},
]
records = {r["id"]: r for r in RECORDS}

SCENES = [
 ("1 SoC",       {"name":"the Malaysian guy from SoC","notes":["Malaysian","from School of Computing"]}, "computer science"),
 ("2 CDE",       {"name":"the Malaysian guy from CDE","notes":["Malaysian","from CDE"]}, "raffles"),
 ("3 basketball",{"name":"the Malaysian guy from the Eusoff basketball team",
                  "notes":["Malaysian","plays for the Eusoff basketball team"]}, "psychology"),
]

for title, mention, answer in SCENES:
    m = {"aliases":[],"company":None,"role":None,"met_at":[], **mention}
    zone, cands = decide(m, RECORDS)
    print("="*70); print(f"SCENE {title}   ZONE={zone.value}")
    for c in cands: print(f"   {c.name:<9} {c.score:5.2f}  {c.agreement.explain()}")
    if zone is not Zone.AMBIGUOUS:
        print("   !! no question fires"); continue
    raw = {c.record_id: c.score for c in cands}; raw[""] = 0.0
    prior = normalise(raw, temperature=PRIOR_TEMPERATURE)
    names = {c.record_id: c.name for c in cands} | {"": "someone new"}
    hyps = [Hypothesis(r, names[r], prior[r]) for r in raw]
    qs = derive(hyps, records)
    ranked = rank_questions(hyps, qs)
    print(f"   needs_model={needs_model(qs)}  candidates={len(cands)}")
    for s in ranked[:4]:
        print(f"   {s.eig:5.3f}  {s.question.text}")
    if ranked:
        res = resolve_with_answer(hyps, ranked[0].question, answer)
        print(f"   -> ANSWER {answer!r} => {res.name} @ {res.confidence:.0%}" if res else "   -> none")
