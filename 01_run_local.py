"""Serve the agent on localhost:8080. FREE -- always test here before deploying.

    uv run 01_run_local.py
    curl -X POST localhost:8080/invocations \
         -H 'content-type: application/json' \
         -d '{"transcript": "met Wei Lin from GIC, said I would send her the repo"}'
"""

from __future__ import annotations

import sys


def main() -> int:
    try:
        from bedrock_agentcore.runtime import BedrockAgentCoreApp
    except ImportError:
        print("bedrock-agentcore not installed. Run: uv sync --extra aws")
        return 1

    from recall.agent import handle

    app = BedrockAgentCoreApp()

    @app.entrypoint
    def invoke(payload):
        return handle(payload)

    print("Recall on http://localhost:8080  (POST /invocations)  -- free, no AWS spend")
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
