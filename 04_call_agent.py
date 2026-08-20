"""Hit the deployed endpoint.

    uv run 04_call_agent.py "met Wei Lin from GIC, said I'd send her the repo"
    uv run 04_call_agent.py --file data/memos/day1.txt
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from recall._common import DEFAULT_REGION

AGENT_NAME = "recall"


def main(argv: list[str]) -> int:
    if "--file" in argv:
        transcript = Path(argv[argv.index("--file") + 1]).read_text().strip()
    elif argv:
        transcript = " ".join(a for a in argv if not a.startswith("--"))
    else:
        print(__doc__)
        return 1

    try:
        from bedrock_agentcore_starter_toolkit import Runtime
    except ImportError:
        print("starter toolkit not installed. Run: uv sync --extra aws")
        return 1

    runtime = Runtime()
    runtime.configure(entrypoint="01_run_local.py", agent_name=AGENT_NAME, region=DEFAULT_REGION)
    response = runtime.invoke({"transcript": transcript})

    payload = response
    if isinstance(response, (str, bytes)):
        payload = json.loads(response)
    print(payload.get("summary") or json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
