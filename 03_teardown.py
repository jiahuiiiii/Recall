"""Tear down the AgentCore runtime. Run this at the end of every session.

Teardown is incomplete by design: `destroy` leaves the S3 bucket, the ECR
repository, and the CloudWatch log groups behind. Those keep costing money, so
this script prints exactly what to check rather than pretending it is finished.
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

    runtime = Runtime()
    try:
        runtime.configure(entrypoint="01_run_local.py", agent_name=AGENT_NAME, region=DEFAULT_REGION)
        runtime.destroy()
        print("runtime destroyed.")
    except Exception as exc:  # noqa: BLE001
        print(f"destroy reported: {type(exc).__name__}: {exc}")

    print(
        "\nDestroy does NOT remove these. Check them manually:\n"
        f"  aws ecr describe-repositories --region {DEFAULT_REGION}\n"
        f"  aws s3 ls | grep -i {AGENT_NAME}\n"
        f"  aws logs describe-log-groups --region {DEFAULT_REGION} "
        f"--log-group-name-prefix /aws/bedrock-agentcore\n"
        "\nDo not assume billing stopped until those are empty."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
