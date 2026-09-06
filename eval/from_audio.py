"""Record a memo, get a fixture stub. Removes the typing from fixture writing.

    uv run eval/from_audio.py memo.m4a --scenario arc_conference

Transcribes the audio and appends a memo block to the scenario file with the
transcript filled in and the mentions left for you. You still label — that is
the part that must be yours — but you no longer type the transcript.

Speaking them also fixes the register: typed fixtures read like written prose,
and prose is the easy case. A real memo has filler words, self-corrections and
Whisper's own name mangling, which is where the pipeline actually breaks.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from recall.tools.transcribe import transcribe

FIXTURES = Path(__file__).parent / "fixtures"

STUB = '''  - id: {mid}
    transcript: |
      {text}
    mentions:
      # TODO label each person mentioned above. One entry per person.
      #   cluster     which human — REUSE an existing id if you have met them before
      #   as          how you referred to them THIS time (unique within this memo)
      #   substantive false if you only greeted or name-dropped them
      #   ambiguous   true only if YOU cannot tell who it is; then cluster: UNRESOLVED
      - {{ cluster: TODO, as: "TODO", substantive: true, ambiguous: false }}
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--scenario", required=True, help="fixture id, e.g. arc_conference")
    args = ap.parse_args()

    path = FIXTURES / f"{args.scenario}.yaml"
    if not path.exists():
        print(f"no such fixture: {path}")
        return 1

    text = transcribe(args.audio)
    if text.startswith("ERROR:"):
        print(text)
        return 1
    text = " ".join(text.split())

    body = path.read_text()
    used = [int(n) for n in _memo_numbers(body)]
    mid = f"m{max(used) + 1 if used else 1}"

    # A skeleton's placeholder memo is replaced, not appended to -- otherwise the
    # first real memo lands after an unwritten stub and the ids read wrong.
    if "REPLACE" in body:
        body = body[: body.index("memos:") + len("memos:")] + "\n"
        mid = "m1"

    path.write_text(body.rstrip("\n") + "\n" + STUB.format(mid=mid, text=text))
    print(f"appended {mid} to {path.name}\n")
    print(f"  {text}\n")
    print("Now open the file and fill in the mentions, then:")
    print("  uv run eval/check_fixtures.py")
    return 0


def _memo_numbers(body: str) -> list[str]:
    import re

    return re.findall(r"^\s*-\s*id:\s*m(\d+)\s*$", body, re.MULTILINE)


if __name__ == "__main__":
    sys.exit(main())
