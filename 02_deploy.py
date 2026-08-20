"""Configure + launch the AgentCore runtime. BILLABLE FROM HERE.

Run 01_run_local.py first. Everything that breaks in deploy also breaks locally,
and locally it is free.
"""

from __future__ import annotations

import sys

from recall._common import DEFAULT_REGION

AGENT_NAME = "recall"


def main() -> int:
    try:
        from bedrock_agentcore_starter_toolkit import Runtime
    except ImportError:
        print("starter toolkit not installed. Run: uv sync --extra aws")
        return 1

    confirm = input("This creates billable AWS resources. Type 'deploy' to continue: ")
    if confirm.strip().lower() != "deploy":
        print("aborted.")
        return 1

    runtime = Runtime()
    runtime.configure(
        entrypoint="01_run_local.py",
        agent_name=AGENT_NAME,
        region=DEFAULT_REGION,
        requirements_file="requirements.txt",
        auto_create_execution_role=True,
        auto_create_ecr=True,
    )
    result = runtime.launch()
    print(f"\nlaunched: {result}")
    print("\nWhen you are done:  uv run 03_teardown.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
