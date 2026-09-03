"""Telegram front-end for Recall. Send a voice note, answer one question, done.

    uv run telegram_bot.py

Transport only, exactly like `web/server.py`. The graph in `recall/` is imported
and used unchanged -- there is one implementation of the pipeline and this file
must never grow a second one. Everything here is payload translation: Telegram's
update shape in, `graph.stream` in, Telegram messages out.

**Why a chat client at all.** Not to record memos -- the web UI already does that
better. A chat is the natural shape for `interrupt()`: the graph pauses on one
clarifying question, Telegram shows it as a keyboard, the tap resumes the run.
The HTTP UI has to fake that with a streamed body and a second endpoint.

Long polling rather than a webhook: `getUpdates` needs no public HTTPS URL, no
tunnel and no certificate, which is what you want running from a laptop on
stage. Webhooks buy nothing at one user.

Setup:
    1. Talk to @BotFather, /newbot, copy the token.
    2. TELEGRAM_BOT_TOKEN=... in .env  (loaded by recall/__init__.py)
    3. uv run telegram_bot.py, message the bot, paste the chat id it prints into
       TELEGRAM_ALLOWED_CHAT_IDS, restart.

**Single-tenant, and the allowlist is what enforces it.** `get_store()` is
process-global and reads one `RECALL_STORE_PATH`, so two Telegram users would
share one person graph and resolve against each other's contacts. Per-user
stores is a real change to `recall/memory.py`, not a flag; until then the bot
answers the chats you list and nobody else.
"""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

import recall  # noqa: F401  - loads .env; must happen before os.environ reads
from recall.graph import build_graph
from recall.tools.transcribe import transcribe

API_ROOT = "https://api.telegram.org"

# Telegram voice notes are always OGG/Opus; `audio` and `document` carry whatever
# the sender had. Groq accepts all of these, so the suffix is taken from the
# file_path Telegram reports rather than assumed -- the same reasoning as
# MIME_TO_SUFFIX in web/server.py, one layer down.
AUDIO_SUFFIXES = {".ogg", ".oga", ".opus", ".mp3", ".m4a", ".wav", ".webm", ".flac", ".mp4"}

# A run that paused has to survive between two updates -- the one that hit the
# question and the tap that answers it. In memory, deliberately, for the reasons
# spelled out in web/server.py: a paused run is worth nothing once the demo is
# over. **It does not survive a restart** -- restart with a question outstanding
# and the run is gone. Tap the stale button and you get told, not a stack trace.
CHECKPOINTER = InMemorySaver()

MAX_MESSAGE = 4000  # Telegram's limit is 4096; leave room for the HTML wrapper.


# ---------------------------------------------------------------------------
# pending pauses
# ---------------------------------------------------------------------------


@dataclass
class Pending:
    """One paused run, and how to turn a button press back into a resume value.

    `resumes` is indexed, not embedded in the callback data, for two reasons.
    `callback_data` is capped at 64 bytes, which a multi-valued answer
    ("computer science at NUS") can exceed. And one answer in every attribute
    probe is the **empty string** -- `questions.py` sets `outcomes[""] =
    "something else"`, the guard that stops a stranger being merged into a real
    contact -- which is not a legal callback payload at all. An index survives
    both, and the value resumed is the one EIG scored the question under.
    """

    kind: str  # "question" | "confirm"
    resumes: list[Any] = field(default_factory=list)


class Bot:
    """Everything that talks to Telegram. Injected in tests, never subclassed."""

    def __init__(self, token: str, client: httpx.Client | None = None) -> None:
        self._token = token
        self._http = client or httpx.Client(timeout=40)

    def call(self, method: str, **params: Any) -> dict:
        r = self._http.post(f"{API_ROOT}/bot{self._token}/{method}", json=params)
        return r.json()

    def download(self, file_id: str) -> str:
        """Telegram file id -> a path on local disk. Caller deletes it.

        Two hops: getFile hands back a path valid for an hour, then the file
        comes from a different host. Files up to 20MB, which a 90-second Opus
        memo is nowhere near.
        """
        info = self.call("getFile", file_id=file_id)
        if not info.get("ok"):
            raise RuntimeError(f"getFile failed: {info.get('description', info)}")
        remote = info["result"]["file_path"]
        suffix = Path(remote).suffix.lower()
        if suffix not in AUDIO_SUFFIXES:
            suffix = ".ogg"
        blob = self._http.get(f"{API_ROOT}/file/bot{self._token}/{remote}").content
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(blob)
            return tmp.name

    def send(self, chat_id: int, text: str, buttons: list[list[dict]] | None = None) -> dict:
        params: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text[:MAX_MESSAGE],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if buttons:
            params["reply_markup"] = {"inline_keyboard": buttons}
        return self.call("sendMessage", **params)

    def document(self, chat_id: int, path: str, caption: str = "") -> dict:
        """Send a file. Used for .ics, which is the whole point of that backend.

        Multipart rather than JSON, so this goes around `call()`. Tapping the
        attachment opens the phone's own calendar app with the event filled in
        -- no Google project, no OAuth, no account, and the user still decides
        whether to keep it. That is the same bargain as the drafts.
        """
        with open(path, "rb") as fh:
            r = self._http.post(
                f"{API_ROOT}/bot{self._token}/sendDocument",
                data={"chat_id": chat_id, "caption": caption[:1000]},
                files={"document": (Path(path).name, fh.read(), "text/calendar")},
            )
        return r.json()

    def typing(self, chat_id: int) -> None:
        """Transcription plus a graph run is several seconds of silence."""
        self.call("sendChatAction", chat_id=chat_id, action="typing")

    def ack(self, callback_id: str, text: str = "") -> None:
        """Stops the button spinner. Telegram nags if you never answer one."""
        self.call("answerCallbackQuery", callback_query_id=callback_id, text=text)

    def updates(self, offset: int | None) -> list[dict]:
        r = self._http.get(
            f"{API_ROOT}/bot{self._token}/getUpdates",
            params={
                "offset": offset,
                "timeout": 30,
                # Anything else is noise we would enumerate and drop. Asking for
                # only these two also means Telegram stops queueing the rest.
                "allowed_updates": '["message","callback_query"]',
            },
        )
        payload = r.json()
        return payload.get("result", []) if payload.get("ok") else []


# ---------------------------------------------------------------------------
# driving the graph
# ---------------------------------------------------------------------------


def _config(chat_id: int) -> dict[str, Any]:
    """`interactive` is the switch, not the presence of a checkpointer.

    Without it `dedupe_node` settles ambiguity with the adjudicator and
    `ask_node` never pauses -- which is exactly what the CLI and the eval
    harness rely on. The thread id is the chat, so one chat is one conversation
    the graph can be resumed into.
    """
    return {"configurable": {"thread_id": f"tg-{chat_id}", "interactive": True}}


def drive(bot: Bot, pending: dict[int, Pending], chat_id: int, payload: Any) -> None:
    """Run or resume until the graph finishes or pauses, then report.

    Both pausing nodes land here: `ask` with the clarifying question, and
    `calendar` with the events it wants to write. They resume through the same
    mechanism, so the payload's own `type` decides which card gets rendered
    rather than this function guessing from which keys are present -- the same
    rule web/server.py follows.
    """
    graph = build_graph(checkpointer=CHECKPOINTER)
    config = _config(chat_id)

    for chunk in graph.stream(payload, config=config, stream_mode="updates"):
        if "__interrupt__" in chunk:
            interrupts = chunk["__interrupt__"]
            paused = (interrupts[0].value if interrupts else {}) or {}
            if paused.get("type") == "confirm_events":
                send_confirm(bot, pending, chat_id, paused)
            else:
                send_question(bot, pending, chat_id, paused)
            return  # the run is alive in the checkpointer, waiting for a tap

    pending.pop(chat_id, None)
    send_summary(bot, chat_id, _final_state(graph, config))


def _final_state(graph, config) -> dict[str, Any]:
    """The checkpointer's view, which is the only complete one.

    A resumed leg only replays nodes from the pause onward, so accumulating the
    streamed updates would lose everything the first leg produced -- including
    the people the memo was about.
    """
    try:
        return dict(graph.get_state(config).values)
    except Exception:  # noqa: BLE001 - a partial report beats no report
        return {}


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def send_question(bot: Bot, pending: dict[int, Pending], chat_id: int, q: dict) -> None:
    """The money shot, as a chat message.

    The bits it bought and **the questions it turned down with their measured
    value** are in the text, not just the question. A bot that shows only what
    it asked demonstrates nothing a prompt could not have produced; the contrast
    between 0.803 bits and 0.000 bits is the whole claim.
    """
    outcomes = q.get("outcomes") or {}
    answers = list(q.get("answers") or [])
    prior = float(q.get("prior_entropy") or 0.0)
    eig = float(q.get("eig") or 0.0)

    lines = [
        f"❓ <b>{escape(str(q.get('question', '')))}</b>",
        "",
        f"about <i>{escape(str(q.get('mention', '')))}</i>",
        f"worth <b>{eig:.3f} bits</b>"
        + (f" of the {prior:.3f} outstanding" if prior else ""),
    ]

    hypotheses = q.get("hypotheses") or []
    if hypotheses:
        lines.append("")
        lines.append("who it might be:")
        for h in hypotheses:
            lines.append(f"  {escape(str(h.get('name', '?')))} — {float(h.get('prior', 0)):.0%}")

    rejected = q.get("rejected") or []
    if rejected:
        lines.append("")
        lines.append("questions it did <i>not</i> ask:")
        for r in rejected:
            lines.append(f"  {float(r.get('eig', 0)):.3f} — {escape(str(r.get('question', '')))}")

    # Index the answers; see Pending's docstring for why the value cannot live
    # in the callback payload.
    pending[chat_id] = Pending(kind="question", resumes=answers)
    buttons = [
        [{"text": str(outcomes.get(a) or a or "something else"), "callback_data": f"a:{i}"}]
        for i, a in enumerate(answers)
    ]
    bot.send(chat_id, "\n".join(lines), buttons)


def send_confirm(bot: Bot, pending: dict[int, Pending], chat_id: int, payload: dict) -> None:
    """The calendar gate. Nothing is written until a button is pressed.

    One resume ends the pause, so this cannot be a multi-select -- it is add
    everything, add exactly one, or add nothing. An unrecognised reply approves
    nothing (`calendar.approved_indices`), which is the right way for a gate
    over someone's real calendar to fail.
    """
    events = payload.get("events") or []
    if not events:
        return

    lines = [f"📅 <b>{len(events)} event(s)</b> ready for {escape(str(payload.get('backend', '')))}"]
    for e in events:
        when = e.get("start") or e.get("when") or ""
        lines.append(f"  • {escape(str(e.get('title', '')))}{f' — {escape(str(when))}' if when else ''}")

    resumes: list[Any] = ["all", "none"] + [[e.get("index", i)] for i, e in enumerate(events)]
    buttons = [
        [{"text": "Add all", "callback_data": "a:0"},
         {"text": "Skip all", "callback_data": "a:1"}],
    ]
    if len(events) > 1:
        buttons += [
            [{"text": f"Only: {str(e.get('title', ''))[:40]}", "callback_data": f"a:{i + 2}"}]
            for i, e in enumerate(events)
        ]

    pending[chat_id] = Pending(kind="confirm", resumes=resumes)
    bot.send(chat_id, "\n".join(lines), buttons)


def send_summary(bot: Bot, chat_id: int, state: dict) -> None:
    """A compact report, built here rather than forwarding `state["summary"]`.

    `summarize_node` formats for a 68-column terminal and appends the cost
    ledger. Reflowed into a chat bubble that reads as noise, and the ledger is a
    developer's concern, not the user's.
    """
    lines: list[str] = []

    resolution = state.get("resolution") or {}
    if resolution:
        name = escape(str(resolution.get("name") or "unresolved"))
        confidence = float(resolution.get("confidence") or 0.0)
        # Reported even when low. One answer does not always settle a three-way
        # tie, and asserting an identity at 46% belief is exactly what the
        # three-zone band exists to prevent.
        settled = "✅" if resolution.get("confident") else "🤔"
        lines.append(f"{settled} <i>{escape(str(resolution.get('mention', '')))}</i> "
                     f"→ <b>{name}</b> ({confidence:.0%})")

    known = state.get("known_matches") or []
    if known:
        names = ", ".join(escape(str((m.get("person") or {}).get("name", "?"))) for m in known)
        lines.append(f"🔁 recognised: {names}")

    new_people = state.get("new_people") or []
    if new_people:
        names = ", ".join(escape(str(p.get("name", "?"))) for p in new_people)
        lines.append(f"🆕 new: {names}")

    events = state.get("calendar_events") or []
    written = [e for e in events if e.get("status") in ("created", "duplicate")]
    if written:
        # Promise only what actually follows. The `ics` backend sends a file, the
        # `google` backend a link, and `local` neither -- saying "file(s) below"
        # for all three left the user waiting for an attachment that, on the
        # local backend, never comes.
        has_file = any(e.get("ics_path") for e in written)
        has_link = any(e.get("link") for e in written)
        tail = (" — calendar file(s) below" if has_file
                else " — link(s) below" if has_link else "")
        lines.append(f"📅 {len(written)} follow-up(s){tail}")
    declined = [e for e in events if e.get("status") == "declined"]
    if declined:
        lines.append(f"🚫 {len(declined)} declined")

    errors = state.get("errors") or []
    for err in errors[:3]:
        lines.append(f"⚠️ {escape(str(err))}")

    bot.send(chat_id, "\n".join(lines) or "Nothing to record from that one.")

    # After the summary, not inside it: an attachment that arrives before the
    # text it belongs to reads as the bot sending you a mystery file.
    for event in written:
        # The Google backend already wrote the event; its own link is the
        # receipt. For every other backend, offer a one-tap "add" link, because
        # a chat app opening a .ics is unreliable -- it often previews the file
        # instead of handing it to the calendar. The .ics still follows for
        # Apple/Outlook users, who import the file rather than tap a link.
        if link := event.get("link"):
            bot.send(chat_id, f"📅 {escape(event.get('title', 'Event'))}",
                     [[{"text": "Open in Google Calendar", "url": link}]])
            continue

        from recall.tools.calendar import gcal_link

        bot.send(chat_id, f"📅 {escape(event.get('title', 'Event'))}",
                 [[{"text": "Add to Google Calendar", "url": gcal_link(event)}]])
        path = event.get("ics_path")
        if path and Path(path).exists():
            # For Apple Calendar / Outlook: import the file instead of the link.
            bot.document(chat_id, path, caption="…or import this into Apple/Outlook")


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

HELP = (
    "🎙 <b>Recall</b>\n\n"
    "Send a <b>voice note</b> after an event — a messy 90 seconds is fine. "
    "Or type the memo out.\n\n"
    "If two people you know could be the one you meant, I'll ask "
    "<b>one</b> question, chosen by how much it tells me.\n\n"
    "/connect_calendar — let me add follow-ups to your Google Calendar\n"
    "/disconnect_calendar — revoke that\n"
    "/cancel — drop a pending question"
)


def _connect_calendar(bot: Bot, chat_id: int) -> None:
    """Send the consent button.

    The link goes to OUR backend, not to Google. The backend mints a one-time
    `state` and redirects, which is what ties the callback to a request we
    started -- a button pointing straight at Google would hand the callback an
    authorization code nobody asked for.
    """
    base = (os.environ.get("PUBLIC_BACKEND_URL") or "").rstrip("/")
    if not base:
        bot.send(chat_id, "⚠️ PUBLIC_BACKEND_URL is not set on the server, "
                          "so I cannot build the consent link.")
        return
    bot.send(
        chat_id,
        "Connect your Google Calendar and I'll add the follow-ups you promise.\n\n"
        "<i>I ask for permission to create events, and nothing else. "
        "You confirm every event before it is written.</i>",
        [[{"text": "Connect Google Calendar", "url": f"{base}/oauth/google/start"}]],
    )


def _disconnect_calendar(bot: Bot, chat_id: int) -> None:
    """Forget the stored token. We hold no access token, so this ends access."""
    try:
        from web.google_calendar import disconnect
    except ImportError:
        bot.send(chat_id, "Calendar integration is not installed on this server.")
        return
    bot.send(chat_id, "Disconnected. I can't write to your calendar any more."
             if disconnect() else "There was no calendar connected.")


def allowed(chat_id: int) -> bool:
    ids = {
        part.strip()
        for part in (os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS") or "").split(",")
        if part.strip()
    }
    return str(chat_id) in ids


def audio_file_id(message: dict) -> str | None:
    """The voice note, or an audio file, or an audio document. In that order."""
    for key in ("voice", "audio", "video_note"):
        if isinstance(message.get(key), dict):
            return message[key].get("file_id")
    doc = message.get("document")
    if isinstance(doc, dict) and Path(doc.get("file_name") or "").suffix.lower() in AUDIO_SUFFIXES:
        return doc.get("file_id")
    return None


def handle(bot: Bot, pending: dict[int, Pending], update: dict) -> None:
    """One update in, zero or more messages out. Never raises.

    Same discipline as the tools: a failure comes back as text the user can read
    and act on. An exception here would kill the poll loop, and a bot that has
    silently stopped answering is indistinguishable from a bot that is thinking.
    """
    try:
        if "callback_query" in update:
            _on_callback(bot, pending, update["callback_query"])
        elif "message" in update:
            _on_message(bot, pending, update["message"])
    except Exception as exc:  # noqa: BLE001 - a stack trace mid-demo helps nobody
        chat = _chat_id(update)
        if chat is not None:
            bot.send(chat, f"⚠️ {escape(f'{type(exc).__name__}: {exc}')}")


def _chat_id(update: dict) -> int | None:
    message = update.get("message") or (update.get("callback_query") or {}).get("message") or {}
    chat = message.get("chat") or {}
    return chat.get("id")


def _on_message(bot: Bot, pending: dict[int, Pending], message: dict) -> None:
    chat_id = (message.get("chat") or {}).get("id")
    if chat_id is None:
        return

    if not allowed(chat_id):
        # Printed, not just refused. This is the setup step: you message the bot
        # once, copy the id out of the console, and put it in .env.
        print(f"[recall] refused chat {chat_id} — add it to TELEGRAM_ALLOWED_CHAT_IDS")
        bot.send(chat_id, f"This bot is private. Chat id: <code>{chat_id}</code>")
        return

    text = (message.get("text") or "").strip()
    if text.startswith(("/start", "/help")):
        bot.send(chat_id, HELP)
        return
    if text.startswith("/connect_calendar"):
        _connect_calendar(bot, chat_id)
        return
    if text.startswith("/disconnect_calendar"):
        _disconnect_calendar(bot, chat_id)
        return
    if text.startswith("/cancel"):
        dropped = pending.pop(chat_id, None)
        bot.send(chat_id, "Dropped." if dropped else "Nothing pending.")
        return

    if chat_id in pending:
        # One pause per chat, because the thread id is the chat. Starting a
        # second run here would resume into the same thread and confuse a live
        # question with a new memo.
        bot.send(chat_id, "Answer the question above first, or /cancel it.")
        return

    file_id = audio_file_id(message)
    if file_id:
        bot.typing(chat_id)
        path = bot.download(file_id)
        try:
            transcript = transcribe(path)
        finally:
            Path(path).unlink(missing_ok=True)
        if transcript.startswith("ERROR:"):
            bot.send(chat_id, f"⚠️ {escape(transcript)}")
            return
        transcript = transcript.strip()
        # Echoed back before any model work starts, for the reason web/server.py
        # splits transcription from the run: transcription is the step most
        # likely to get a name wrong, and a wrong name is worth seeing early.
        bot.send(chat_id, f"📝 <i>{escape(transcript)}</i>")
    elif text:
        transcript = text
    else:
        bot.send(chat_id, "Send a voice note or type the memo.")
        return

    bot.typing(chat_id)
    drive(bot, pending, chat_id, {"transcript": transcript, "messages": []})


def _on_callback(bot: Bot, pending: dict[int, Pending], callback: dict) -> None:
    chat_id = ((callback.get("message") or {}).get("chat") or {}).get("id")
    callback_id = callback.get("id", "")
    if chat_id is None or not allowed(chat_id):
        bot.ack(callback_id)
        return

    waiting = pending.get(chat_id)
    if waiting is None:
        # The usual cause is a restart: InMemorySaver is gone and so is the run.
        bot.ack(callback_id, "That question has expired.")
        return

    data = callback.get("data") or ""
    index = int(data.split(":", 1)[1]) if data.startswith("a:") and data[2:].isdigit() else -1
    if not 0 <= index < len(waiting.resumes):
        bot.ack(callback_id, "Unknown answer.")
        return

    answer = waiting.resumes[index]
    pending.pop(chat_id, None)
    bot.ack(callback_id)
    bot.typing(chat_id)
    drive(bot, pending, chat_id, Command(resume=answer))


# ---------------------------------------------------------------------------
# the loop
# ---------------------------------------------------------------------------


def poll(bot: Bot, pending: dict[int, Pending] | None = None,
         updates: Iterable[dict] | None = None) -> None:
    """Long-poll forever, or drain a supplied iterable once (tests)."""
    pending = {} if pending is None else pending

    if updates is not None:
        for update in updates:
            handle(bot, pending, update)
        return

    offset: int | None = None
    print("[recall] telegram bot polling — ctrl-c to stop")
    while True:
        for update in bot.updates(offset):
            offset = update["update_id"] + 1
            handle(bot, pending, update)


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("TELEGRAM_BOT_TOKEN is not set. Get one from @BotFather and put it in .env")
        return 1
    if not (os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS") or "").strip():
        # Not fatal: the first message prints the id you need. Refusing to start
        # would make that impossible to discover.
        print("[recall] TELEGRAM_ALLOWED_CHAT_IDS is empty — message the bot to learn your id")
    try:
        poll(Bot(token))
    except KeyboardInterrupt:
        print("\n[recall] stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
