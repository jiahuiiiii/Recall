"""Seed the three-way demo case into whatever RECALL_STORE_PATH points at.

Deterministic: no model call, so the three records are byte-identical every run.
Note phrasing is load-bearing -- "studies X" / "lives in Y" is what makes the
derived question read as a sentence. See repro.py.
"""
import os
import sys

from recall.memory import get_store

if "RECALL_STORE_PATH" not in os.environ:
    sys.exit("refusing to run without RECALL_STORE_PATH -- do not seed the live graph")

# Faculty is deliberately NOT stored. It is perfectly correlated with subject
# here, so storing both makes two questions worth identical bits and which one
# gets asked is an arbitrary tie-break -- on one run the demo asks about the
# faculty Ben just named, which looks broken. Subject alone splits all three.
PEOPLE = [
    ("Jason",   "computer science",       "Eusoff",  True),
    ("John",    "electrical engineering", "Raffles", False),
    ("Johnson", "psychology",             "Eusoff",  True),
]
store = get_store()
for name, subject, hall, basketball in PEOPLE:
    notes = ["Malaysian", f"studies {subject}", f"lives in {hall} Hall", "wears glasses"]
    if basketball:
        notes.append("plays for the Eusoff basketball team")
    store.upsert({
        "id": f"p_{name.lower()}", "name": name, "aliases": [],
        "company": None, "role": None, "met_at": ["orientation week"],
        "notes": notes,
    })
    print(f"seeded {name:<8} {subject}, {hall} Hall"
          + (", basketball" if basketball else ""))
print(f"\n-> {os.environ['RECALL_STORE_PATH']}  ({len(store.all())} people)")
