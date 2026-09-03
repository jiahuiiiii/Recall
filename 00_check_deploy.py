"""Preflight for a hosted deployment. Reads config, writes nothing, spends nothing.

    uv run 00_check_deploy.py            # is this environment deployable?
    uv run 00_check_deploy.py --new-key  # generate RECALL_TOKEN_KEY

Same shape as 00_check_bedrock.py and 00_check_calendar.py: it checks things
that are individually cheap to get wrong and collectively fatal, and it says
which one is missing rather than failing at the first request in production.

Run it locally before deploying, and again against the deployed service by
reading /healthz -- that endpoint reports the same facts from inside the
container, which is where they actually matter.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import recall  # noqa: F401  - loads .env before anything reads os.environ

OK, BAD, WARN, SKIP = "  OK  ", " FAIL ", " WARN ", "  --  "


def say(mark: str, text: str, detail: str = "") -> None:
    print(f"[{mark}] {text}")
    if detail:
        for line in detail.strip().split("\n"):
            print(f"         {line}")


def main() -> int:
    if "--new-key" in sys.argv:
        from web.google_calendar import new_key

        print(new_key())
        print("\nSet this as RECALL_TOKEN_KEY. Lose it and the stored Google token")
        print("cannot be read -- delete the token file and reconnect.")
        return 0

    env = os.environ.get
    failures = 0
    warnings = 0

    print("\n--- model ------------------------------------------------------")
    model = env("RECALL_MODEL_ID")
    if not model:
        say(BAD, "RECALL_MODEL_ID is unset.",
            "The code default is a marketplace-gated Anthropic id that a personal\n"
            "account cannot call. Every run would fail with\n"
            "'ValidationException: invalid model identifier', which reads like a typo.")
        failures += 1
    else:
        say(OK, f"RECALL_MODEL_ID={model}")

    if env("AWS_ACCESS_KEY_ID") and env("AWS_SECRET_ACCESS_KEY"):
        say(OK, f"AWS keys present, region {env('AWS_REGION', '(unset)')}")
        if not env("AWS_REGION"):
            say(WARN, "AWS_REGION is unset; boto3 will not guess it in a container.")
            warnings += 1
    elif env("AWS_SESSION_TOKEN"):
        say(WARN, "Using temporary SSO credentials.",
            "These expire in about an hour. A deployed service needs long-lived\n"
            "IAM keys or it stops working mid-demo with no warning.")
        warnings += 1
    else:
        say(WARN, "No AWS keys in the environment (fine locally, fatal in a container).")
        warnings += 1

    print("\n--- storage ----------------------------------------------------")
    paths = {
        "RECALL_STORE_PATH": "data/person_graph.json",
        "RECALL_RELATIONS_PATH": "data/relations.json",
        "RECALL_CALENDAR_PATH": "data/calendar.json",
        "RECALL_GOOGLE_TOKEN_PATH": "data/google_token.json",
    }
    ephemeral = [k for k, default in paths.items() if not env(k, "").startswith("/")]
    if ephemeral and env("RENDER"):
        say(BAD, "Storage paths are relative, so they are NOT on the mounted disk.",
            "Everything under them is wiped on every deploy and every spin-down:\n"
            "the person graph (everyone becomes a stranger) and the Google token\n"
            "(you re-do consent, on stage). Point these at the disk:\n"
            + "\n".join(f"  {k}=/var/data/{Path(v).name}" for k, v in paths.items()))
        failures += 1
    elif ephemeral:
        say(SKIP, "Relative storage paths — correct locally, wrong in a container.")
    else:
        say(OK, "All storage paths are absolute.")

    print("\n--- telegram ---------------------------------------------------")
    if not env("TELEGRAM_BOT_TOKEN"):
        say(WARN, "TELEGRAM_BOT_TOKEN unset — the bot will not start.")
        warnings += 1
    else:
        say(OK, "TELEGRAM_BOT_TOKEN set")

    allowed = [x for x in (env("TELEGRAM_ALLOWED_CHAT_IDS", "")).split(",") if x.strip()]
    if not allowed:
        say(BAD, "TELEGRAM_ALLOWED_CHAT_IDS is empty.",
            "This is the ONLY thing keeping the deployment single-tenant.\n"
            "get_store() is process-global on one RECALL_STORE_PATH and takes no\n"
            "user argument, so a stranger who finds the bot would resolve their\n"
            "contacts against yours -- and two people named Alex would merge.\n"
            "Message the bot once; it prints the chat id to paste here.")
        failures += 1
    else:
        say(OK, f"{len(allowed)} chat id(s) allowed — deployment is single-tenant")

    print("\n--- calendar ---------------------------------------------------")
    backend = env("RECALL_CALENDAR", "local").lower()
    say(OK if backend in ("ics", "google") else WARN, f"RECALL_CALENDAR={backend}")
    if backend == "local":
        say(WARN, "The local backend writes a JSON file nobody looks at.",
            "Use 'ics' (no setup, works for anyone) or 'google' (OAuth).")
        warnings += 1

    if backend == "google":
        from web import google_calendar

        if not google_calendar.configured():
            missing = [k for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
                                   "GOOGLE_REDIRECT_URI") if not env(k)]
            say(BAD, f"RECALL_CALENDAR=google but missing: {', '.join(missing)}")
            failures += 1
        else:
            say(OK, "Google OAuth client configured")

        public = (env("PUBLIC_BACKEND_URL") or "").rstrip("/")
        redirect = env("GOOGLE_REDIRECT_URI") or ""
        if not public:
            say(BAD, "PUBLIC_BACKEND_URL is unset — /connect_calendar cannot build a link.")
            failures += 1
        elif redirect and not redirect.startswith(public):
            say(BAD, "PUBLIC_BACKEND_URL and GOOGLE_REDIRECT_URI disagree.",
                f"start:    {public}/oauth/google/start\n"
                f"redirect: {redirect}\n"
                "Google rejects a redirect_uri that is not registered on the OAuth\n"
                "client, and the error appears in the browser, not in your logs.")
            failures += 1
        elif public:
            say(OK, f"callback {public}/oauth/google/callback")
            if urlparse(public).scheme != "https":
                say(BAD, "PUBLIC_BACKEND_URL is not https. Google requires it.")
                failures += 1

        if not env("RECALL_TOKEN_KEY"):
            say(WARN, "RECALL_TOKEN_KEY unset — the refresh token is stored in plaintext.",
                "Generate one:  uv run 00_check_deploy.py --new-key")
            warnings += 1
        else:
            say(OK, "Refresh token will be encrypted at rest")

    print("\n--- transcription ----------------------------------------------")
    if env("GROQ_API_KEY"):
        say(OK, "GROQ_API_KEY set")
    else:
        say(BAD, "GROQ_API_KEY unset — voice notes cannot be transcribed.",
            "Typed memos still work, which makes this easy to miss until someone\n"
            "sends the bot a voice message.")
        failures += 1

    print("\n" + "-" * 64)
    if failures:
        print(f"{failures} blocking problem(s), {warnings} warning(s). Fix before deploying.")
        return 1
    print(f"Ready to deploy. {warnings} warning(s).")
    print("\nAfter the first deploy: copy the Render URL into PUBLIC_BACKEND_URL and")
    print("GOOGLE_REDIRECT_URI, add the callback to the Google OAuth client, restart,")
    print("then check /healthz and send /connect_calendar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
