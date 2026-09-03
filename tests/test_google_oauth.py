"""The Google OAuth round-trip and token storage. Offline, no Google contacted.

Nothing here calls Google. What is tested is the part that is ours and that
fails silently when wrong: the `state` guard, encryption at rest, and the pages
a user actually lands on when something breaks.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

# The OAuth backend is an optional extra (`uv sync --extra deploy`). Without it
# the rest of the suite must still run offline with no credentials, so skip
# rather than fail -- a fresh clone should not see 16 errors for a feature it
# has not installed.
pytest.importorskip("cryptography", reason="needs --extra deploy")

from web import google_calendar as gc
from web.server import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _scratch_token(tmp_path, monkeypatch):
    """Never the real token file."""
    monkeypatch.setattr(gc, "TOKEN_PATH", tmp_path / "google_token.json")
    gc._STATES.clear()
    return tmp_path


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://example.test/oauth/google/callback")


# --- the state guard -------------------------------------------------------


def test_a_state_works_once_and_only_once():
    """The state is what ties a callback to a request WE started.

    Replayable, it stops being a guard: anyone who can reach the callback could
    feed us an authorization code of their choosing.
    """
    state = gc.create_state()
    assert gc.consume_state(state) is True
    assert gc.consume_state(state) is False


def test_a_forged_state_is_rejected():
    assert gc.consume_state("not-one-we-issued") is False
    assert gc.consume_state("") is False


def test_states_expire(monkeypatch):
    state = gc.create_state()
    monkeypatch.setattr(gc.time, "time", lambda: 10**10)
    assert gc.consume_state(state) is False


def test_two_states_are_not_the_same():
    assert gc.create_state() != gc.create_state()


# --- token storage ---------------------------------------------------------


def test_a_token_round_trips_encrypted(monkeypatch, _scratch_token):
    monkeypatch.setenv("RECALL_TOKEN_KEY", gc.new_key())
    gc.save_connection("1//refresh-token-value")

    on_disk = json.loads((_scratch_token / "google_token.json").read_text())
    assert on_disk["encrypted"] is True
    # The point of encryption at rest: the secret is not in the file.
    assert "1//refresh-token-value" not in json.dumps(on_disk)

    assert gc.load_connection()["refresh_token"] == "1//refresh-token-value"


def test_the_token_file_is_not_world_readable(monkeypatch, _scratch_token):
    """A standing grant to write someone's calendar."""
    monkeypatch.setenv("RECALL_TOKEN_KEY", gc.new_key())
    gc.save_connection("1//refresh")
    mode = (_scratch_token / "google_token.json").stat().st_mode & 0o777
    assert mode == 0o600


def test_a_missing_key_is_an_error_not_a_silent_plaintext_fallback(monkeypatch):
    """Losing the key must not look like losing the connection.

    Falling back to reading it as plaintext would return ciphertext as a token
    and produce an unexplainable Google error at write time instead.
    """
    monkeypatch.setenv("RECALL_TOKEN_KEY", gc.new_key())
    gc.save_connection("1//refresh")
    monkeypatch.delenv("RECALL_TOKEN_KEY")
    with pytest.raises(RuntimeError, match="RECALL_TOKEN_KEY"):
        gc.load_connection()


def test_disconnect_removes_the_token(monkeypatch):
    monkeypatch.setenv("RECALL_TOKEN_KEY", gc.new_key())
    gc.save_connection("1//refresh")
    assert gc.connected() is True
    assert gc.disconnect() is True
    assert gc.connected() is False
    assert gc.disconnect() is False       # nothing left to remove, not an error


def test_no_connection_reads_as_none():
    assert gc.load_connection() is None
    assert gc.connected() is False


# --- the routes ------------------------------------------------------------


def test_start_refuses_cleanly_when_google_is_not_configured(monkeypatch):
    for key in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI"):
        monkeypatch.delenv(key, raising=False)
    r = client.get("/oauth/google/start", follow_redirects=False)
    assert r.status_code == 503
    assert "GOOGLE_CLIENT_ID" in r.text


def test_start_redirects_to_google_with_a_state(configured):
    r = client.get("/oauth/google/start", follow_redirects=False)
    assert r.status_code == 307
    location = r.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/auth")
    # offline + consent are what make Google issue a refresh token, and issue
    # one AGAIN on a reconnect. Without the second, reconnecting an authorised
    # account returns no refresh token and the connection cannot be renewed.
    assert "access_type=offline" in location
    assert "prompt=consent" in location
    assert "state=" in location


def test_the_callback_rejects_a_state_it_never_issued(configured):
    r = client.get("/oauth/google/callback?code=abc&state=forged")
    assert r.status_code == 400
    assert "no longer valid" in r.text


def test_the_callback_needs_both_code_and_state(configured):
    assert client.get("/oauth/google/callback?code=abc").status_code == 400
    assert client.get("/oauth/google/callback?state=abc").status_code == 400


def test_a_google_error_is_shown_as_text_not_a_traceback(configured):
    r = client.get("/oauth/google/callback?error=access_denied")
    assert r.status_code == 400
    assert "access_denied" in r.text
    assert "Traceback" not in r.text


def test_an_expired_state_does_not_say_which_guess_was_close(configured):
    """Expired, reused and forged all produce the same message on purpose."""
    state = gc.create_state()
    gc.consume_state(state)
    reused = client.get(f"/oauth/google/callback?code=abc&state={state}")
    forged = client.get("/oauth/google/callback?code=abc&state=zzz")
    assert reused.text == forged.text


# --- health ----------------------------------------------------------------


def test_healthz_reports_state_without_leaking_any_of_it(monkeypatch, configured):
    monkeypatch.setenv("RECALL_TOKEN_KEY", gc.new_key())
    gc.save_connection("1//super-secret-refresh-token")

    body = client.get("/healthz").json()
    assert body["ok"] is True
    assert body["google_oauth_configured"] is True
    assert body["google_calendar_connected"] is True
    # A health check that echoes a secret is a health check that publishes one.
    raw = json.dumps(body)
    assert "super-secret" not in raw
    assert "test-secret" not in raw
