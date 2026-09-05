"""Preflight. Must print OK before any Bedrock run.

Checks the four things that actually break, in the order they break:
  1. credentials exist and are not expired
  2. the region is set and is the one Bedrock will actually use
  3. the model id is one THIS account can call (per-model, per-region, off by
     default -- and cross-region "global." profiles are not on every account)
  4. a real inference call returns tokens

On failure it prints the specific fix for the credential style in use, and on a
model failure `--list-models` probes the Claude and Nova ids this account CAN
call -- in this region, then the US regions if an organisation policy denies
everything here -- so the fix is a copy-paste rather than a console hunt.
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
        # Temporary keys pasted from the SSO access portal carry a session
        # token and expire in hours; long-lived IAM keys do not. The fix for an
        # expired one is "paste a fresh set", not "your keys are wrong".
        return "session" if os.environ.get("AWS_SESSION_TOKEN") else "env"

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
    if style == "session":
        return (
            "These are temporary keys (AWS_SESSION_TOKEN is set) and they expire\n"
            "  after a few hours. Sign in to the AWS access portal, open 'Command\n"
            "  line or programmatic access', and paste a fresh AWS_ACCESS_KEY_ID /\n"
            "  AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN into .env."
        )
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


# The two model families the pipeline is known to run on. Nova is listed
# alongside Claude because on a personal account it is usually the ONLY thing
# callable, and a probe that never tries it reports "nothing works" to a user
# whose account is fine.
_FAMILIES = ("anthropic", "nova")


def _list_model_ids(region: str) -> list[str]:
    """Claude and Nova ids this account can SEE. Not the same as ids it can call.

    Inference profiles and foundation models are separate APIs and either one
    can be the thing that works, so both get listed.
    """
    import boto3

    bedrock = boto3.client("bedrock", region_name=region)
    ids: list[str] = []

    try:
        for p in bedrock.list_inference_profiles()["inferenceProfileSummaries"]:
            pid = p.get("inferenceProfileId", "")
            if any(f in pid for f in _FAMILIES) and p.get("status", "ACTIVE") == "ACTIVE":
                ids.append(pid)
    except Exception:  # noqa: BLE001 - not every region exposes this API
        pass

    try:
        for m in bedrock.list_foundation_models()["modelSummaries"]:
            mid = m.get("modelId", "")
            if not any(f in mid for f in _FAMILIES):
                continue
            if "TEXT" not in (m.get("outputModalities") or []):
                continue  # speech models (nova-sonic) fail converse() for a different reason
            if "ON_DEMAND" in (m.get("inferenceTypesSupported") or []):
                ids.append(mid)
    except Exception:  # noqa: BLE001
        pass

    return sorted(set(ids))


# Error classes that matter, in the order they should be believed.
GATE_USE_CASE = "use_case_form"
GATE_UNAVAILABLE = "not_available"
GATE_LEGACY = "legacy"
GATE_THROTTLED = "throttled"
GATE_DENIED = "access_denied"
GATE_SCP = "scp_deny"
GATE_OTHER = "other"

# Where to look when the configured region denies everything. An organisation
# SCP is usually scoped by region, and the hackathon account's allows only the
# US regions -- measured 5 Sep: all 28 ids in ap-southeast-1 denied, us-east-1
# and us-west-2 fine.
_FALLBACK_REGIONS = ("us-east-1", "us-west-2")


def _classify(message: str) -> str:
    if "service control policy" in message:
        return GATE_SCP
    if "use case details have not been submitted" in message:
        return GATE_USE_CASE
    if "marked by provider as Legacy" in message:
        return GATE_LEGACY
    if "is not available for this account" in message:
        return GATE_UNAVAILABLE
    if "Throttl" in message or "Too many requests" in message:
        return GATE_THROTTLED
    if "AccessDenied" in message or "not authorized" in message:
        return GATE_DENIED
    return GATE_OTHER


def _probe(region: str, model_id: str, attempts: int = 2) -> tuple[bool, str, str]:
    """Call the model for real, twice, and require both to succeed.

    Listing is not proof of callability: an id can be ACTIVE and visible and
    still fail on a use-case-form gate. Worse, Bedrock's answer is not always
    stable -- the same id can pass one probe and fail the next while an
    account-level gate is unresolved. A single sample therefore recommends ids
    that then die mid-demo, so callable means "passed every attempt".

    Returns (callable, gate_class, message).
    """
    import boto3
    from botocore.exceptions import ClientError

    client = boto3.client("bedrock-runtime", region_name=region)
    last_msg = ""
    for _ in range(attempts):
        try:
            client.converse(
                modelId=model_id,
                messages=[{"role": "user", "content": [{"text": "hi"}]}],
                inferenceConfig={"maxTokens": 1},
            )
        except ClientError as exc:
            last_msg = exc.response["Error"]["Message"]
            return False, _classify(last_msg), last_msg
        except Exception as exc:  # noqa: BLE001
            last_msg = f"{type(exc).__name__}: {exc}"
            return False, GATE_OTHER, last_msg
    return True, "", "callable"


# The code default first, then fallbacks in descending order of suitability
# for structured extraction and tool use. Nova 2 Lite sits high because it is
# the model the benchmark tables were measured on and the usual answer on a
# personal account.
_PREFERENCE = [
    "sonnet-4-6",
    "haiku-4-5",
    "sonnet-4-5",
    "nova-2-lite",
    "opus-4-6",
    "nova-lite",
    "claude-3-5-sonnet",
    "nova-pro",
]


def _probe_region(region: str, ids: list[str]) -> tuple[list[str], list[tuple[str, str, str]]]:
    """Probe every id in one region; print as it goes so a slow sweep is visibly alive."""
    print(f"Probing {len(ids)} model ids in {region}, 2 calls each...\n")
    callable_ids: list[str] = []
    blocked: list[tuple[str, str, str]] = []
    for mid in ids:
        ok, gate, detail = _probe(region, mid)
        if ok:
            callable_ids.append(mid)
            print(f"  [ok]      {mid}")
        else:
            blocked.append((mid, gate, detail))
            print(f"  [blocked] {mid}  ({gate})")
    return callable_ids, blocked


def _recommend(callable_ids: list[str]) -> tuple[str | None, int]:
    """Best callable id and its rank in `_PREFERENCE` (len(_PREFERENCE) = unlisted).

    The rank is returned so two regions can be compared: a region whose only
    callable model is one this project has never run on should lose to a
    region that offers the default, even if the first one was probed first.
    """
    for rank, want in enumerate(_PREFERENCE):
        matches = [i for i in callable_ids if want in i]
        if matches:
            # Prefer a regional profile over a bare model id -- bare ids have
            # tighter per-region throughput.
            profiles = [i for i in matches if "." in i.split("anthropic")[0]]
            return (profiles or matches)[0], rank
    return (callable_ids[0] if callable_ids else None), len(_PREFERENCE)


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

        ids = _list_model_ids(DEFAULT_REGION)
        if not ids:
            print(f"Credentials are fine, but no Claude or Nova models are visible in {DEFAULT_REGION}.")
            print("Enable them: Bedrock console -> Model access -> Modify model access.")
            print(f"If nothing is offered there, try AWS_REGION={_FALLBACK_REGIONS[0]}.")
            return 1

        # Probe rather than trust the listing. Each probe is a 1-token call --
        # the whole sweep costs a fraction of a cent and is the only thing that
        # actually answers "which id can I use".
        region = DEFAULT_REGION
        callable_ids, blocked = _probe_region(region, ids)
        best, rank = _recommend(callable_ids)

        # An SCP that denies most things is almost always scoped by region, so a
        # region that is mostly denied -- or that offers nothing this project has
        # run on -- is not the end of the search. Bedrock's per-id answers are
        # also not stable (a legacy id passed two probes here and failed the
        # same two twenty minutes earlier), so one stray [ok] must not stop the
        # fallback either. Try the US regions and keep whichever ranks best.
        scp_count = sum(1 for _, g, _ in blocked if g == GATE_SCP)
        if scp_count >= max(1, len(ids) // 2) or rank >= len(_PREFERENCE):
            print(f"\n{scp_count} of {len(ids)} ids in {DEFAULT_REGION} are denied by an "
                  "organisation policy; checking the US regions as well.")
            for alt in _FALLBACK_REGIONS:
                if alt == DEFAULT_REGION:
                    continue
                alt_ids = _list_model_ids(alt)
                if not alt_ids:
                    continue
                print()
                alt_ok, alt_blocked = _probe_region(alt, alt_ids)
                alt_best, alt_rank = _recommend(alt_ok)
                if alt_best and alt_rank < rank:
                    region, callable_ids, blocked = alt, alt_ok, alt_blocked
                    best, rank = alt_best, alt_rank
                    if rank == 0:
                        break

        if blocked and "--verbose" in sys.argv:
            print("\nWhy the blocked ones are blocked:")
            for mid, gate, detail in blocked:
                print(f"  {mid}\n    [{gate}] {detail[:150]}")

        # One account-level gate can block nearly everything. Reporting that once
        # is far more useful than a per-model list that all says the same thing.
        gates = [g for _, g, _ in blocked]
        if gates.count(GATE_USE_CASE) >= max(2, len(ids) // 3):
            print(
                f"\n{gates.count(GATE_USE_CASE)} of {len(ids)} ids are blocked by ONE "
                "account-level gate:\n"
                "  the Anthropic use case details form has not been submitted.\n\n"
                "  Fix: Bedrock console -> Model access -> Modify model access.\n"
                "       Fill in the Anthropic use case details (company, website,\n"
                "       industry, what you are building), submit, then enable\n"
                "       the Claude model you want. Approval is usually quick.\n\n"
                "  This is the whole problem. Do not work around it by picking a\n"
                "  different model -- while the form is outstanding, Bedrock's answer\n"
                "  is inconsistent and an id that probes fine can fail mid-run."
            )
            return 1

        if not callable_ids:
            print("\nNothing is callable. See the reasons with --verbose.")
            return 1

        print(f"\n{len(callable_ids)} callable in {region}.")
        if best:
            print("\nPut this in .env:")
            if region != DEFAULT_REGION:
                print(f"  AWS_REGION={region}")
            print(f"  RECALL_MODEL_ID={best}")
        if HAIKU not in callable_ids:
            print(
                f"\nNote: the configured default ({HAIKU}) is not callable here.\n"
                "The id above works meanwhile."
            )
        if not any("nova-2-lite" in i for i in callable_ids):
            print(
                "\nNote: Nova 2 Lite is not callable here. The published benchmark tables\n"
                "were measured on it, so they cannot be reproduced exactly from this account."
            )
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
    if "service control policy" in err:
        # Not something the user can enable in a console: an organisation-level
        # policy. On the hackathon account it is scoped two ways -- by region
        # (only the US regions) and by profile prefix (`global.` denied even
        # there, `us.` allowed) -- and the two need different fixes.
        if DEFAULT_REGION in _FALLBACK_REGIONS:
            print(
                f"  An organisation policy (SCP) denies this model id in {DEFAULT_REGION}.\n"
                "  The region is fine; the id is not -- `global.` cross-region profiles\n"
                "  are denied on this account while `us.` ones are allowed. Fix, in .env:\n"
                "    RECALL_MODEL_ID=us.anthropic.claude-sonnet-4-6    # or us.amazon.nova-2-lite-v1:0\n"
                "  Then re-run this check."
            )
        else:
            print(
                f"  An organisation policy (SCP) forbids Bedrock model calls in {DEFAULT_REGION}.\n"
                "  Nothing in the console can change that; the region can. The hackathon\n"
                "  account allows only the US regions. Fix, in .env:\n"
                f"    AWS_REGION={_FALLBACK_REGIONS[0]}\n"
                "    RECALL_MODEL_ID=us.anthropic.claude-sonnet-4-6    # or us.amazon.nova-2-lite-v1:0\n"
                "  Then re-run this check."
            )
        return
    if "AccessDenied" in err or "not authorized" in err:
        print(
            f"  Model access is per-model, per-region, and off by default.\n"
            f"  Fix: Bedrock console -> Model access -> enable {HAIKU}\n"
            f"       in region {DEFAULT_REGION}, then wait for status 'Access granted'."
        )
    elif "use case details have not been submitted" in err:
        print(
            "  This account has not submitted the Anthropic use case form, which\n"
            "  gates some Claude models on personal accounts. It is per-model, so\n"
            "  other Claude models may work while this one does not.\n"
            "  Fix: Bedrock console -> Model access -> fill in the Anthropic use\n"
            "       case details, then enable this model. Approval is usually quick."
        )
    elif "marked by provider as Legacy" in err:
        print(
            "  This model is retired and closed to accounts that were not already\n"
            "  using it. Pick a current model instead."
        )
    elif "ValidationException" in err or "not found" in err or "invalid" in err.lower():
        print(
            f"  The model id is not callable in {DEFAULT_REGION}. Either the id is\n"
            f"  wrong for this account, or access to it is gated."
        )
    else:
        print("  Inference failed for a reason other than access or model id.")

    ids = _list_model_ids(DEFAULT_REGION)
    if ids:
        print("\n  Run this to find an id that actually works:")
        print("    uv run 00_check_bedrock.py --list-models")
    else:
        print(
            f"\n  No Claude or Nova models are enabled in {DEFAULT_REGION}.\n"
            f"  Enable them: Bedrock console -> Model access -> Modify model access.\n"
            f"  If nothing is offered there, try region {_FALLBACK_REGIONS[0]} instead:\n"
            f"    AWS_REGION={_FALLBACK_REGIONS[0]} in .env"
        )


if __name__ == "__main__":
    sys.exit(main())
