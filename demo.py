"""Prepare and launch the three-beat interactive Recall demo.

    uv run demo.py

The web app starts with a fresh, throwaway person graph. Paste the three memo files in
the order printed here: day 1 creates contacts, day 2 recognises Wei Lin while adding two
partners at Jungle, and the final memo says only "the partner from Jungle".

That last reference is deliberately a THREE-way ambiguity -- Priya from day 1 ("Antler
maybe? Or Jungle"), plus Rachel Sim and Nadia Osman from day 2. With only two candidates
every discriminating question is worth identical bits and EIG, uncertainty sampling and
random all pick the same one by construction; the argmax has nothing to choose. Three
candidates is the smallest case where the selection is visibly doing work.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MEMOS = (
    ("1. Create memory", ROOT / "data/memos/day1.txt"),
    ("2. Recognise Wei Lin; add two Jungle partners", ROOT / "data/memos/demo_day2.txt"),
    ("3. Pause on a 3-way ambiguity for EIG", ROOT / "data/memos/demo_ask.txt"),
)


def main() -> int:
    scratch = Path(tempfile.mkdtemp(prefix="recall-demo-"))
    env = os.environ.copy()
    env.update(
        {
            "RECALL_STORE_PATH": str(scratch / "graph.json"),
            "RECALL_CALENDAR_PATH": str(scratch / "calendar.json"),
            "RECALL_RELATIONS_PATH": str(scratch / "relations.json"),
            "RECALL_CALENDAR": "local",
        }
    )

    print("Recall demo ready — using a fresh throwaway graph.")
    print("Open http://localhost:8000 and paste these memos in order:\n")
    for label, path in MEMOS:
        print(f"{label}: {path.relative_to(ROOT)}")
    print(
        "\nFor the final memo, show the selected question, its information gain, and the\n"
        "rejected alternatives before answering it. All three candidates want the deck,\n"
        "so that question buys ~0 bits and is visibly rejected; what separates them is\n"
        "seed vs enterprise focus."
    )
    print(f"\nScratch data: {scratch}\n")

    return subprocess.run(
        [sys.executable, "web/server.py"], cwd=ROOT, env=env, check=False
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
