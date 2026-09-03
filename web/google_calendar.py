"""Google Calendar over OAuth, for the hosted deployment.

    RECALL_CALENDAR=google

The third backend, and the only one that writes to a real calendar without a
developer credential on the machine. `local` is a JSON ledger, `ics` hands the
user a file, `mcp` needs a Google Cloud project per laptop -- this one asks the
user once, in a browser, and then writes on their behalf.

**Single-tenant on purpose.** One connected Google account, stored in one file,
guarded by the Telegram allowlist. `get_store()` is process-global on one
`RECALL_STORE_PATH` and takes no user argument, so a second person using the
hosted bot would resolve their contacts against the first person's graph -- a
far worse outcome than not hosting. Per-user calendars without per-user memory
would be a lock on the door of a house with no walls. See README.

Everything here fails soft: no credentials, no connection, an expired refresh
token -- all come back as an ERROR string that `calendar.py` records and the run
continues past. A dead calendar must never take down a memo.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"

# The connected account's refresh token, encrypted. Under RECALL_DATA_DIR so it
# lands on Render's persistent disk rather than the ephemeral container
# filesystem -- a token written to the container is gone on the next deploy and
# the user has to re-consent, mid-demo, in front of an audience.
TOKEN_PATH = Path(os.environ.get("RECALL_GOOGLE_TOKEN_PATH", "data/google_token.json"))

# OAuth `state` values we issued, and when they expire. In memory, and correct
# there: both ends of the exchange (`/oauth/google/start` and the callback) run
# in the same web process. A state that does not survive a restart is a state
# the user retries by pressing the button again.
_STATES: dict[str, float] = {}
STATE_TTL_SECONDS = 600


class NotConfigured(RuntimeError):
    """Raised when the Google env vars are absent. Callers turn this into text."""


def configured() -> bool:
    return all(
        os.environ.get(k)
        for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI")
    )


def _client_config() -> dict[str, Any]:
    if not configured():
        raise NotConfigured(
            "GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and GOOGLE_REDIRECT_URI must all be set."
        )
    return {
        "web": {
            "client_id": os.environ["GOOGLE_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            "auth_uri": AUTH_URI,
            "token_uri": TOKEN_URI,
            "redirect_uris": [os.environ["GOOGLE_REDIRECT_URI"]],
        }
    }


# ---------------------------------------------------------------------------
# the consent round-trip
# ---------------------------------------------------------------------------


def create_state() -> str:
    """Issue a one-time state and remember it.

    The state is what ties the callback back to a request WE started. Without
    it, anyone who can reach the callback URL can feed us an authorization code
    of their choosing -- which is the whole reason OAuth has this parameter and
    the reason `upgrade.md` says not to pass a user id through the URL and trust
    it.
    """
    _expire()
    state = secrets.token_urlsafe(32)
    _STATES[state] = time.time() + STATE_TTL_SECONDS
    return state


def consume_state(state: str) -> bool:
    """Validate and burn a state. False means expired, forged, or already used."""
    _expire()
    return _STATES.pop(state or "", None) is not None


def _expire() -> None:
    now = time.time()
    for key in [k for k, deadline in _STATES.items() if deadline < now]:
        _STATES.pop(key, None)


def authorization_url(state: str) -> str:
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(_client_config(), scopes=SCOPES)
    flow.redirect_uri = os.environ["GOOGLE_REDIRECT_URI"]
    url, _ = flow.authorization_url(
        # `offline` is what makes Google issue a refresh token at all, and
        # `consent` is what makes it issue one AGAIN on a re-connect. Without
        # the second, reconnecting an already-authorised account returns no
        # refresh token and the connection silently cannot be renewed.
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
        state=state,
    )
    return url


def exchange_code(code: str, state: str) -> str:
    """Swap the authorization code for a refresh token. Returns the token."""
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, state=state)
    flow.redirect_uri = os.environ["GOOGLE_REDIRECT_URI"]
    flow.fetch_token(code=code)
    token = flow.credentials.refresh_token
    if not token:
        raise RuntimeError(
            "Google returned no refresh token. This happens when the account was "
            "already authorised; revoke access at myaccount.google.com and retry."
        )
    return token


# ---------------------------------------------------------------------------
# token storage
# ---------------------------------------------------------------------------


def _fernet():
    """The encryption key, or None if none is set.

    Encryption is on by default and refuses to silently downgrade: a missing
    key with a stored ciphertext is an error, not a fallback to plaintext.
    """
    key = os.environ.get("RECALL_TOKEN_KEY")
    if not key:
        return None
    from cryptography.fernet import Fernet

    return Fernet(key.encode())


def new_key() -> str:
    """Generate a key for RECALL_TOKEN_KEY. Printed by the deploy check."""
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


def save_connection(refresh_token: str, calendar_id: str = "primary") -> None:
    fernet = _fernet()
    payload = {
        "provider": "google",
        "calendar_id": calendar_id,
        "encrypted": fernet is not None,
        "refresh_token": (
            fernet.encrypt(refresh_token.encode()).decode() if fernet else refresh_token
        ),
    }
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(payload, indent=2))
    # 0600. The token is a standing grant to write someone's calendar; on a
    # shared host, mode is the difference between "stored" and "published".
    TOKEN_PATH.chmod(0o600)


def load_connection() -> dict | None:
    """The stored connection, decrypted, or None if there isn't one."""
    if not TOKEN_PATH.exists():
        return None
    payload = json.loads(TOKEN_PATH.read_text() or "{}")
    token = payload.get("refresh_token")
    if not token:
        return None
    if payload.get("encrypted"):
        fernet = _fernet()
        if fernet is None:
            raise RuntimeError(
                "The stored Google token is encrypted but RECALL_TOKEN_KEY is not set. "
                "Restore the key, or delete the token file and reconnect."
            )
        token = fernet.decrypt(token.encode()).decode()
    return {"refresh_token": token, "calendar_id": payload.get("calendar_id", "primary")}


def connected() -> bool:
    try:
        return load_connection() is not None
    except RuntimeError:
        return False


def disconnect() -> bool:
    """Forget the connection. True if there was one.

    Deleting the token is the whole of `/disconnect_calendar`: we hold no access
    token of our own, so dropping the refresh token ends our access completely.
    """
    if TOKEN_PATH.exists():
        TOKEN_PATH.unlink()
        return True
    return False


# ---------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------


def create_event(event: dict) -> str:
    """Create one event on the connected calendar. Returns its link.

    `event` is the dict `propose_event` built -- the same object the user was
    shown and approved, never a rebuild of it.
    """
    from datetime import date, timedelta

    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    connection = load_connection()
    if connection is None:
        raise RuntimeError("No Google Calendar connected. Send /connect_calendar first.")

    credentials = Credentials(
        token=None,
        refresh_token=connection["refresh_token"],
        token_uri=TOKEN_URI,
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        scopes=SCOPES,
    )
    service = build("calendar", "v3", credentials=credentials, cache_discovery=False)

    start = date.fromisoformat(event["date"])
    attending = event.get("kind") == "attending"
    with_whom = (event.get("person_name") or "").strip()
    body = {
        "summary": event["title"],
        "description": (
            (f"With {with_whom}. " if with_whom else "") + "Captured by Recall."
            if attending
            else f"Follow up owed to {with_whom}. Captured by Recall."
        ),
        # All-day, and the end date is EXCLUSIVE -- same rule as the .ics path.
        # A commitment is "by Friday", not "at 14:30", and inventing a time puts
        # a meeting in someone's day that they never agreed to.
        "start": {"date": start.isoformat()},
        "end": {"date": (start + timedelta(days=1)).isoformat()},
        "transparency": "opaque" if attending else "transparent",
        "reminders": {"useDefault": True},
        # Google's own idempotency handle. Re-inserting the same id returns a
        # 409 rather than a second event, so a double-tap cannot duplicate.
        # Must be base32hex-ish and 5-1024 chars, so the hex digest works and
        # the "recall-" prefix does not.
        "id": event["idempotency_key"].replace("recall-", "recall"),
    }
    created = service.events().insert(calendarId=connection["calendar_id"], body=body).execute()
    return created.get("htmlLink", "")
