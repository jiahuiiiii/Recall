"""Run one memo through the graph from the command line. Free except for Bedrock tokens.

    uv run run_demo.py                          # built-in demo memo
    uv run run_demo.py data/memos/day2.txt      # a transcript file
    uv run run_demo.py data/audio/memo.m4a      # a voice memo (needs GROQ_API_KEY)
    uv run run_demo.py --reset                  # wipe the person graph first
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from recall.graph import run

AUDIO_SUFFIXES = {".m4a", ".mp3", ".wav", ".ogg", ".webm", ".flac"}
DEFAULT_MEMO = Path("data/memos/day1.txt")


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]

    if "--reset" in argv:
        paths = (
            Path(os.environ.get("RECALL_STORE_PATH", "data/person_graph.json")),
            Path(os.environ.get("RECALL_CALENDAR_PATH", "data/calendar.json")),
            Path(os.environ.get("RECALL_RELATIONS_PATH", "data/relations.json")),
        )
        for path in paths:
            if path.exists():
                path.unlink()
                print(f"removed {path}")

    target = Path(args[0]) if args else DEFAULT_MEMO
    if not target.exists():
        print(f"no such file: {target}")
        return 1

    try:
        if target.suffix.lower() in AUDIO_SUFFIXES:
            print(f"memo: {target} (audio)\n")
            run(audio_path=str(target))
        else:
            transcript = target.read_text().strip()
            print(f"memo: {target} ({len(transcript)} chars)\n")
            run(transcript=transcript)
    except Exception as exc:  # noqa: BLE001
        # A stack trace on stage is worse than useless. Bedrock has exactly three
        # ways of not working and each has a one-line fix; print that instead.
        return _explain(exc)
    return 0


def _explain(exc: Exception) -> int:
    name = type(exc).__name__
    text = str(exc)
    print(f"\nRun failed: {name}: {text}\n")

    if "NoCredentials" in name or "ExpiredToken" in text or "InvalidClientTokenId" in text:
        print("  AWS credentials are missing or expired.")
        print("  Fix: run `uv run 00_check_bedrock.py` -- it detects whether you are")
        print("       on SSO or static access keys and prints the right command.")
    elif "AccessDenied" in text or "not authorized" in text:
        print("  Either the IAM identity lacks Bedrock permissions, or model access")
        print("  is not enabled (it is per-model, per-region, and off by default).")
        print("  Fix: uv run 00_check_bedrock.py")
    elif "ValidationException" in name or "ResourceNotFound" in name or "could not be found" in text:
        print("  The model id is not callable in this region. On a personal AWS")
        print("  account the 'global.' cross-region profile often does not exist.")
        print("  Fix: uv run 00_check_bedrock.py --list-models   then set RECALL_MODEL_ID")
    elif "Throttling" in text or "TooManyRequests" in text:
        print("  Rate limited. Wait a few seconds and re-run.")
    else:
        print("  Run `uv run 00_check_bedrock.py` to isolate which layer is broken.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
