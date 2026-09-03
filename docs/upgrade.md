Below is the simplest complete setup for your Recall MVP:

```text
Telegram voice message
→ Recall backend
→ Google OAuth
→ Google Calendar
```

Use:

- FastAPI for the backend
- Telegram bot for input
- Google Calendar API for reminders
- Render for hosting
- SQLite for a one-user demo, PostgreSQL/Supabase for multiple users

## 1. Create the Telegram bot

Open Telegram and message `@BotFather`.

Send:

```text
/newbot
```

Follow the instructions and copy the bot token.

Add it to `.env`:

```env
TELEGRAM_BOT_TOKEN=your_token_here
```

Never commit `.env` to GitHub.

## 2. Create a Google Cloud project

Go to Google Cloud Console.

1. Create a project called `Recall`.
2. Enable **Google Calendar API**.
3. Configure the OAuth consent screen.
4. Choose `External` for testing with personal Google accounts.
5. Add your Google account as a test user.
6. Create credentials.
7. Select **OAuth client ID**.
8. Select **Web application**.

You will eventually add this redirect URI:

```text
https://YOUR-BACKEND-DOMAIN/oauth/google/callback
```

For local testing:

```text
https://YOUR-NGROK-DOMAIN.ngrok.app/oauth/google/callback
```

Use this permission scope:

```text
https://www.googleapis.com/auth/calendar.events
```

This allows Recall to create and edit calendar events. [Google Calendar authorization scopes](https://developers.google.com/workspace/calendar/api/auth)

Add the credentials to `.env`:

```env
GOOGLE_CLIENT_ID=your_client_id
GOOGLE_CLIENT_SECRET=your_client_secret
GOOGLE_REDIRECT_URI=https://YOUR-BACKEND-DOMAIN/oauth/google/callback
```

## 3. Install dependencies

From the Recall repository:

```bash
uv add google-api-python-client google-auth-httplib2 google-auth-oauthlib
uv add python-telegram-bot
```

Your current Recall project already has a FastAPI server under:

```text
web/server.py
```

You can add the Google Calendar and Telegram code there, or create separate modules:

```text
web/
  server.py
  google_calendar.py
  telegram_bot.py
```

## 4. Understand the user connection flow

Each Telegram user connects their own Google Calendar.

```text
Telegram user ID
→ Google account
→ encrypted refresh token
```

The flow is:

1. User sends `/connect_calendar`.
2. Recall generates a one-time OAuth state linked to that Telegram user.
3. Recall sends a “Connect Google Calendar” button.
4. User authorizes Google.
5. Google redirects to your backend.
6. Backend exchanges the authorization code for tokens.
7. Backend stores the refresh token for that Telegram user.
8. Recall can later create calendar events for that user.

Do not pass the Telegram ID directly through an unprotected URL and trust it. Store it server-side using a temporary OAuth `state`.

## 5. Add the database tables

You need at least these records:

```text
calendar_connections
--------------------
telegram_user_id
provider
encrypted_refresh_token
calendar_id
created_at
updated_at
```

And temporary OAuth states:

```text
oauth_states
------------
state
telegram_user_id
expires_at
```

For your first demo, SQLite is acceptable. For a hosted multi-user version, use Supabase or Neon PostgreSQL because Render’s local files should not be treated as permanent storage.

## 6. Implement Google OAuth

Create `web/google_calendar.py`:

```python
import os
import secrets

from google_auth_oauthlib.flow import Flow

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events"
]


def create_state() -> str:
    return secrets.token_urlsafe(32)


def get_authorization_url(state: str) -> str:
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": os.environ["GOOGLE_CLIENT_ID"],
                "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [
                    os.environ["GOOGLE_REDIRECT_URI"]
                ],
            }
        },
        scopes=SCOPES,
    )

    flow.redirect_uri = os.environ["GOOGLE_REDIRECT_URI"]

    url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        state=state,
    )

    return url


def exchange_code(code: str, state: str):
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": os.environ["GOOGLE_CLIENT_ID"],
                "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [
                    os.environ["GOOGLE_REDIRECT_URI"]
                ],
            }
        },
        scopes=SCOPES,
        state=state,
    )

    flow.redirect_uri = os.environ["GOOGLE_REDIRECT_URI"]
    flow.fetch_token(code=code)

    return flow.credentials
```

## 7. Add OAuth routes to FastAPI

In `web/server.py`:

```python
from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

from web.google_calendar import (
    create_state,
    exchange_code,
    get_authorization_url,
)


@app.get("/oauth/google/start")
async def start_google_oauth(telegram_user_id: int):
    state = create_state()

    # Save this relationship in your database.
    await save_oauth_state(
        state=state,
        telegram_user_id=telegram_user_id,
    )

    url = get_authorization_url(state)
    return RedirectResponse(url)


@app.get("/oauth/google/callback")
async def google_callback(request: Request):
    code = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code or not state:
        return HTMLResponse(
            "Missing authorization information.",
            status_code=400,
        )

    telegram_user_id = await consume_oauth_state(state)

    if telegram_user_id is None:
        return HTMLResponse(
            "Invalid or expired authorization state.",
            status_code=400,
        )

    credentials = exchange_code(code, state)

    await save_calendar_connection(
        telegram_user_id=telegram_user_id,
        refresh_token=credentials.refresh_token,
        calendar_id="primary",
    )

    return HTMLResponse(
        """
        <h2>Google Calendar connected.</h2>
        <p>You can now return to Telegram.</p>
        """
    )
```

For a real version, the Telegram bot should call a backend function to generate the authorization link instead of allowing anyone to manually supply another user’s ID.

## 8. Implement the Telegram bot

Create `web/telegram_bot.py`:

```python
import os

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)


async def connect_calendar(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    telegram_user_id = update.effective_user.id

    backend_url = os.environ["PUBLIC_BACKEND_URL"]

    url = (
        f"{backend_url}/oauth/google/start"
        f"?telegram_user_id={telegram_user_id}"
    )

    keyboard = [[
        InlineKeyboardButton(
            "Connect Google Calendar",
            url=url,
        )
    ]]

    await update.message.reply_text(
        "Connect your Google Calendar so Recall can create reminders.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


def build_bot():
    application = (
        Application.builder()
        .token(os.environ["TELEGRAM_BOT_TOKEN"])
        .build()
    )

    application.add_handler(
        CommandHandler("connect_calendar", connect_calendar)
    )

    return application


if __name__ == "__main__":
    build_bot().run_polling()
```

Add:

```env
PUBLIC_BACKEND_URL=https://YOUR-BACKEND-DOMAIN
```

For the hackathon, Telegram polling is easier than Telegram webhooks.

## 9. Create Google Calendar events

Add this function:

```python
import os

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


def create_calendar_event(
    refresh_token: str,
    event: dict,
) -> str:
    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        scopes=[
            "https://www.googleapis.com/auth/calendar.events"
        ],
    )

    service = build(
        "calendar",
        "v3",
        credentials=credentials,
    )

    created_event = (
        service.events()
        .insert(
            calendarId="primary",
            body=event,
        )
        .execute()
    )

    return created_event["htmlLink"]
```

Example event:

```python
event = {
    "summary": "Send product deck to Sarah",
    "description": (
        "Follow up after meeting Sarah from GIC. "
        "Created by Recall from a voice memo."
    ),
    "start": {
        "dateTime": "2026-09-08T09:00:00+08:00",
        "timeZone": "Asia/Singapore",
    },
    "end": {
        "dateTime": "2026-09-08T09:15:00+08:00",
        "timeZone": "Asia/Singapore",
    },
    "reminders": {
        "useDefault": True,
    },
}
```

## 10. Connect this to Recall

After Recall transcribes a voice message, extract a commitment object:

```json
{
  "person": "Sarah",
  "company": "GIC",
  "action": "send product deck",
  "due_date": "2026-09-08",
  "confidence": 0.96,
  "source_text": "I promised to send her the product deck next Tuesday"
}
```

Only create a reminder proposal if:

- The action is specific.
- The person is known.
- The date is known.
- The statement was an actual promise.
- The confidence is sufficiently high.

Then send this through Telegram:

```text
I detected a promise to send Sarah the product deck next Tuesday.

Create a calendar reminder?
```

Add buttons:

```text
[Create reminder] [Edit] [Cancel]
```

The event should be created only when the user presses `Create reminder`.

## 11. Handle Telegram button clicks

Store the proposed event in your database:

```text
calendar_proposals
------------------
id
telegram_user_id
event_json
status
google_event_id
created_at
```

The callback should:

1. Verify the Telegram user owns the proposal.
2. Load their calendar connection.
3. Decrypt the refresh token.
4. Create the Google Calendar event.
5. Save the Google event ID.
6. Mark the proposal as completed.
7. Return the calendar link.

Make it idempotent. If the user presses the button twice, Recall should not create two reminders.

## 12. Test locally with ngrok

Start your FastAPI backend:

```bash
uv run uvicorn web.server:app --host 0.0.0.0 --port 8000
```

In another terminal:

```bash
ngrok http 8000
```

Suppose ngrok gives you:

```text
https://abc123.ngrok.app
```

Set:

```env
PUBLIC_BACKEND_URL=https://abc123.ngrok.app
GOOGLE_REDIRECT_URI=https://abc123.ngrok.app/oauth/google/callback
```

Add the same callback URL in Google Cloud Console.

Then start the Telegram bot:

```bash
uv run python -m web.telegram_bot
```

Test in this order:

1. Send `/connect_calendar`.
2. Click `Connect Google Calendar`.
3. Authorize Google.
4. Return to Telegram.
5. Send a voice message with a clear promise.
6. Check the extracted commitment.
7. Tap `Create reminder`.
8. Open Google Calendar.
9. Check that the event exists.
10. Tap the button again and ensure a duplicate is not created.

## 13. Deploy to Render

Use two Render services if the backend and Telegram bot are separate processes.

### Web Service

Purpose:

```text
FastAPI + Google OAuth callback
```

Start command:

```bash
uv run uvicorn web.server:app --host 0.0.0.0 --port $PORT
```

### Background Worker

Purpose:

```text
Telegram polling bot
```

Start command:

```bash
uv run python -m web.telegram_bot
```

Set these environment variables in Render:

```env
TELEGRAM_BOT_TOKEN=...
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=https://recall-api.onrender.com/oauth/google/callback
PUBLIC_BACKEND_URL=https://recall-api.onrender.com
DATABASE_URL=...
AWS_REGION=...
RECALL_MODEL_ID=...
```

After deploying:

1. Copy the Render backend URL.
2. Update `GOOGLE_REDIRECT_URI`.
3. Add the final callback URL to Google Cloud Console.
4. Restart the Render service.
5. Test `/connect_calendar` again.

The frontend does not need to be hosted for the Telegram demo.

## 14. Security requirements

Before allowing real users to connect:

- Use HTTPS.
- Encrypt refresh tokens.
- Validate OAuth `state`.
- Use Telegram numeric user IDs.
- Require confirmation before creating events.
- Never log access tokens.
- Provide `/disconnect_calendar`.
- Delete tokens when disconnected.
- Request only `calendar.events` permission.
- Allow users to delete or export their Recall data.
- Do not automatically submit sales messages or calendar events without user approval.

## Recommended hackathon scope

Build only:

1. Telegram voice messages.
2. Google Calendar connection.
3. Contact extraction.
4. Duplicate/contact resolution.
5. One clarification question.
6. Promise detection.
7. Telegram confirmation.
8. Google Calendar reminder creation.
9. Follow-up message draft.

Your final demo story should be:

> A salesperson sends one voice message to Telegram after meeting a prospect. Recall remembers the relationship, resolves uncertainty, detects the promised follow-up, asks for confirmation, and puts the task on the salesperson’s calendar—without requiring them to open a CRM.
