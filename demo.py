"""Prepare and launch the rehearsed interactive Recall demo.

    uv run demo.py

The web app starts from a throwaway copy of the committed synthetic seed. The
first memo proves cross-session recognition by finding Wei Lin. The second says
only "the partner from Canopy" and pauses on a three-person ambiguity.

All three partners share company, role, event, and the desire to see the deck.
Their investment focus is the one useful difference, so EIG has a unique best
question: "What do they cover in Singapore?"
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SEED = ROOT / "data/demo_seed.json"
MEMOS = (
    ("1. Recognise someone from an earlier memo", ROOT / "data/memos/demo_recognise.txt"),
    ("2. Pause on a three-person ambiguity", ROOT / "data/memos/demo_ask.txt"),
)


def main() -> int:
    scratch = Path(tempfile.mkdtemp(prefix="recall-demo-"))
    graph = scratch / "graph.json"
    shutil.copyfile(SEED, graph)
    env = os.environ.copy()
    env.update(
        {
            "RECALL_STORE_PATH": str(graph),
            "RECALL_CALENDAR_PATH": str(scratch / "calendar.json"),
            "RECALL_RELATIONS_PATH": str(scratch / "relations.json"),
            "RECALL_ICS_DIR": str(scratch / "ics"),
            "RECALL_CALENDAR": "ics",
            "RECALL_SKIP_ENRICHMENT": "1",
        }
    )

    print("Recall demo ready — using a throwaway copy of the synthetic seed.")
    print("Open http://localhost:8000 and paste these memos in order:\n")
    for label, path in MEMOS:
        print(f"{label}: {path.relative_to(ROOT)}")
    print(
        "\nFor the second memo, show the chosen question and rejected alternatives.\n"
        "Choose 'seed-stage companies' to resolve the mention to Rachel Tan.\n"
        "The shared company/role/deck questions buy little; investment focus is\n"
        "the unique highest-information question."
    )
    print(f"\nScratch data: {scratch}\n")

    try:
        return subprocess.run(
            [sys.executable, "web/server.py"], cwd=ROOT, env=env, check=False
        ).returncode
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
