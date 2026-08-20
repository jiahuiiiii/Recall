"""Preflight. Must print OK before any Bedrock run.

Checks the four things that actually break, in the order they break:
  1. credentials exist and are not expired
  2. the region is set and is the one Bedrock will actually use
  3. the model id is one THIS account can call (per-model, per-region, off by
     default -- and cross-region "global." profiles are not on every account)
  4. a real inference call returns tokens

On failure it prints the specific fix for the credential style in use, and on a
model failure it lists the Claude ids this account CAN call so the fix is a
copy-paste rather than a console hunt.
"""

from __future__ import annotations

import sys

from recall._common import DEFAULT_REGION, HAIKU


def _credential_style() -> str:
    """Identify how creds are configured, so the fix message is the right one.

    SSO and static access keys fail identically at the call site but have
    completely different remedies, and telling a personal-account user to run
    `aws sso login` sends them somewhere that does not exist for them.
    """
    import os
    from pathlib import Path

    if os.environ.get("AWS_ACCESS_KEY_ID"):
        return "env"

    config = Path.home() / ".aws" / "config"
    creds = Path.home() / ".aws" / "credentials"

    if config.exists():
        text = config.read_text()
        if "sso_start_url" in text or "sso_session" in text:
            return "sso"
    if creds.exists() and "aws_access_key_id" in creds.read_text():
        return "keys"
    return "none"


def _credential_fix(style: str) -> str:
    profile = __import__("os").environ.get("AWS_PROFILE")
    flag = f" --profile {profile}" if profile else ""
    if style == "sso":
        return f"aws sso login{flag}      # SSO sessions expire every 8-12h"
    if style in {"keys", "env"}:
        return (
            "Your access keys are present but rejected -- they are wrong, deleted,\n"
            "  or belong to a different account. Re-check with:\n"
            f"    aws sts get-caller-identity{flag}"
        )
    return (
        "No credentials configured at all. For a personal AWS account:\n"
        "    1. IAM console -> Users -> your user -> Security credentials\n"
        "    2. Create access key -> 'Command Line Interface (CLI)'\n"
        "    3. aws configure\n"
        f"       (region: {DEFAULT_REGION}, output: json)"
    )


def _list_claude_ids(region: str) -> list[str]:
    """Every Claude id this account can actually invoke, profiles included.

    Inference profiles and foundation models are separate APIs and either one
    can be the thing that works, so both get listed.
    """
    import boto3

    bedrock = boto3.client("bedrock", region_name=region)
    ids: list[str] = []

    try:
        for p in bedrock.list_inference_profiles()["inferenceProfileSummaries"]:
            pid = p.get("inferenceProfileId", "")
            if "anthropic" in pid and p.get("status", "ACTIVE") == "ACTIVE":
                ids.append(pid)
    except Exception:  # noqa: BLE001 - not every region exposes this API
        pass

    try:
        for m in bedrock.list_foundation_models(byProvider="anthropic")["modelSummaries"]:
            mid = m.get("modelId", "")
            if "ON_DEMAND" in (m.get("inferenceTypesSupported") or []):
                ids.append(mid)
    except Exception:  # noqa: BLE001
        pass

    return sorted(set(ids))


def main() -> int:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    if "--list-models" in sys.argv:
        # Credentials first: an empty model list because nobody is logged in
        # looks identical to an empty list because nothing is enabled, and the
        # two have completely different fixes.
        try:
            boto3.client("sts", region_name=DEFAULT_REGION).get_caller_identity()
        except Exception as exc:  # noqa: BLE001
            style = _credential_style()
            print(f"Cannot list models: {type(exc).__name__}: {exc}\n")
            print(f"Fix: {_credential_fix(style)}")
            return 1

        ids = _list_claude_ids(DEFAULT_REGION)
        if not ids:
            print(f"Credentials are fine, but no Claude models are callable in {DEFAULT_REGION}.")
            print("Enable them: Bedrock console -> Model access -> Modify model access.")
            print(f"If Haiku 4.5 is not offered there, try AWS_REGION=us-east-1.")
            return 1
        print(f"Claude ids callable in {DEFAULT_REGION}:")
        for i in ids:
            print(f"  {i}")
        haiku = [i for i in ids if "haiku-4-5" in i] or [i for i in ids if "haiku" in i]
        if haiku:
            print(f"\nPut this in .env:\n  RECALL_MODEL_ID={haiku[0]}")
        return 0

    style = _credential_style()
    print(f"region:      {DEFAULT_REGION}")
    print(f"model:       {HAIKU}")
    print(f"credentials: {style}\n")

    try:
        ident = boto3.client("sts", region_name=DEFAULT_REGION).get_caller_identity()
        print(f"[ok] credentials      account={ident['Account']} arn={ident['Arn']}")
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] credentials    {type(exc).__name__}: {exc}")
        print(f"\n  Fix: {_credential_fix(style)}")
        return 1

    try:
        bedrock = boto3.client("bedrock", region_name=DEFAULT_REGION)
        models = bedrock.list_foundation_models()["modelSummaries"]
        print(f"[ok] bedrock reachable  {len(models)} models visible in {DEFAULT_REGION}")
    except (ClientError, BotoCoreError) as exc:
        print(f"[FAIL] bedrock          {type(exc).__name__}: {exc}")
        if "AccessDenied" in str(exc):
            print(
                "\n  Fix: this IAM identity lacks Bedrock permissions.\n"
                "       Attach the AWS managed policy 'AmazonBedrockFullAccess'\n"
                "       to your user (IAM -> Users -> Permissions -> Add permissions)."
            )
        else:
            print(f"\n  Fix: check Bedrock is available in {DEFAULT_REGION} for this account.")
        return 1

    try:
        from langchain_core.messages import HumanMessage

        from recall._common import LEDGER, chat_model

        llm = chat_model(label="preflight", max_tokens=64)
        reply = llm.invoke([HumanMessage(content="Reply with the single word: OK")])
        text = reply.content
        if isinstance(text, list):
            text = " ".join(b.get("text", "") for b in text if isinstance(b, dict))
        print(f"[ok] inference        model replied: {str(text).strip()[:40]!r}")

        # finish_reason == "length" means the reply was CUT, not that the model
        # failed. Truncated JSON downstream looks like a model bug but is the
        # token ceiling, so surface it here where it is unambiguous.
        if (reply.response_metadata or {}).get("stopReason") == "max_tokens":
            print("     note: stopReason=max_tokens -- reply was truncated by the ceiling")

        print(f"\n{LEDGER.report()}")
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] inference        {type(exc).__name__}: {exc}")
        _explain_model_failure(str(exc))
        return 1

    print("\nOK")
    return 0


def _explain_model_failure(err: str) -> None:
    print()
    if "AccessDenied" in err or "not authorized" in err:
        print(
            f"  Model access is per-model, per-region, and off by default.\n"
            f"  Fix: Bedrock console -> Model access -> Enable Claude Haiku 4.5\n"
            f"       in region {DEFAULT_REGION}, then wait for status 'Access granted'."
        )
    elif "ValidationException" in err or "not found" in err or "invalid" in err.lower():
        print(
            f"  The model id is not callable in {DEFAULT_REGION}. This is the usual\n"
            f"  personal-account failure: the 'global.' cross-region profile is a\n"
            f"  workshop-account default and may not exist for you."
        )
    else:
        print("  Inference failed for a reason other than access or model id.")

    ids = _list_claude_ids(DEFAULT_REGION)
    if ids:
        print(f"\n  Claude ids this account CAN call in {DEFAULT_REGION}:")
        for i in ids:
            print(f"    {i}")
        haiku = [i for i in ids if "haiku-4-5" in i] or [i for i in ids if "haiku" in i]
        if haiku:
            print(f"\n  Put this in .env:\n    RECALL_MODEL_ID={haiku[0]}")
    else:
        print(
            f"\n  No Claude models are enabled in {DEFAULT_REGION}.\n"
            f"  Enable them: Bedrock console -> Model access -> Modify model access.\n"
            f"  If Haiku 4.5 is not offered there, try region us-east-1 instead:\n"
            f"    AWS_REGION=us-east-1 in .env"
        )


if __name__ == "__main__":
    sys.exit(main())
