"""Telegram transport tests. No network, no Groq, no AWS.

Same rule as tests/test_server.py: the bot must never become a second
implementation of the pipeline, so these check translation only -- that a voice
note reaches the transcriber, that a pause becomes a keyboard, and that the
value a tap resumes with is the one EIG scored the question under.
"""

from __future__ import annotations

import pytest
from langgraph.types import Command, Interrupt

import telegram_bot as tg


class FakeBot:
    """Records what would have gone to Telegram."""

    def __init__(self, downloads: dict[str, str] | None = None) -> None:
        self.sent: list[dict] = []
        self.acks: list[str] = []
        self.downloads = downloads or {}
        self.deleted: list[str] = []

    def send(self, chat_id, text, buttons=None):
        self.sent.append({"chat_id": chat_id, "text": text, "buttons": buttons or []})
        return {"ok": True}

    def typing(self, chat_id):
        pass

    def ack(self, callback_id, text=""):
        self.acks.append(text)

    def download(self, file_id):
        return self.downloads.get(file_id, "/tmp/does-not-exist.ogg")

    # convenience
    @property
    def last(self) -> dict:
        return self.sent[-1]

    def buttons(self) -> list[dict]:
        return [b for row in self.last["buttons"] for b in row]


QUESTION = {
    "type": "question",
    "mention": "Jia En",
    "question": "What do they study at NUS?",
    "eig": 0.803,
    "prior_entropy": 1.27,
    "answers": ["computer science", "business analytics", ""],
    "outcomes": {
        "computer science": "computer science",
        "business analytics": "business analytics",
        "": "something else",
    },
    "hypotheses": [
        {"record_id": "p_1", "name": "Jia En", "prior": 0.49},
        {"record_id": "p_2", "name": "Jia Ying", "prior": 0.49},
    ],
    "rejected": [{"question": "Same school as you?", "eig": 0.0}],
}


class FakeGraph:
    """Pauses on the first stream, finishes on the second."""

    def __init__(self, paused: dict | None = None, final: dict | None = None) -> None:
        self.paused = paused
        self.final = final or {}
        self.payloads: list = []

    def stream(self, payload, config=None, stream_mode=None):
        self.payloads.append(payload)
        if self.paused is not None and not isinstance(payload, Command):
            yield {"__interrupt__": [Interrupt(value=self.paused)]}
            return
        yield {"extract": {"new_people": []}}

    def get_state(self, config):
        return type("S", (), {"values": self.final})()


@pytest.fixture(autouse=True)
def _allow_everyone(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "42")


def _message(**kw):
    return {"message": {"chat": {"id": 42}, **kw}}


def _tap(data: str):
    return {"callback_query": {"id": "cb1", "data": data, "message": {"chat": {"id": 42}}}}


def test_a_typed_memo_runs_the_graph(monkeypatch):
    graph = FakeGraph(final={"new_people": [{"name": "Kang Ling"}]})
    monkeypatch.setattr(tg, "build_graph", lambda checkpointer=None: graph)

    bot, pending = FakeBot(), {}
    tg.handle(bot, pending, _message(text="met Kang Ling at the camp"))

    assert graph.payloads[0]["transcript"] == "met Kang Ling at the camp"
    assert "Kang Ling" in bot.last["text"]


def test_a_voice_note_is_transcribed_then_run(monkeypatch, tmp_path):
    audio = tmp_path / "memo.ogg"
    audio.write_bytes(b"\x00\x01")
    graph = FakeGraph(final={})
    monkeypatch.setattr(tg, "build_graph", lambda checkpointer=None: graph)
    monkeypatch.setattr(tg, "transcribe", lambda path: "  met Jia En again  ")

    bot = FakeBot(downloads={"f1": str(audio)})
    tg.handle(bot, {}, _message(voice={"file_id": "f1", "duration": 12}))

    assert graph.payloads[0]["transcript"] == "met Jia En again"
    # Echoed back before any model work, so a mis-heard name is visible early.
    assert "met Jia En again" in bot.sent[0]["text"]
    # And the temp file does not outlive the transcription.
    assert not audio.exists()


def test_a_transcription_failure_is_a_message_not_a_crash(monkeypatch):
    monkeypatch.setattr(tg, "transcribe", lambda path: "ERROR: GROQ_API_KEY is not set")
    monkeypatch.setattr(tg, "build_graph", lambda checkpointer=None: FakeGraph())

    bot = FakeBot()
    tg.handle(bot, {}, _message(voice={"file_id": "f1"}))

    assert "GROQ_API_KEY" in bot.last["text"]


def test_a_pause_becomes_a_keyboard_carrying_the_bits_it_turned_down(monkeypatch):
    monkeypatch.setattr(tg, "build_graph", lambda checkpointer=None: FakeGraph(paused=QUESTION))

    bot, pending = FakeBot(), {}
    tg.handle(bot, pending, _message(text="saw her again"))

    text = bot.last["text"]
    assert "What do they study at NUS?" in text
    assert "0.803" in text
    # The claim is the selection, so the rejected question and its measured
    # value have to be visible, not just the one it asked.
    assert "Same school as you?" in text and "0.000" in text
    assert len(bot.buttons()) == 3
    assert pending[42].kind == "question"


def test_the_something_else_answer_survives_the_round_trip(monkeypatch):
    """The empty string is not a legal callback payload, and it is the guard.

    `questions.py` puts `outcomes[""] = "something else"` in every attribute
    probe so a stranger cannot be merged into a known contact. If the button
    carried the answer instead of its index, this option could not exist.
    """
    graph = FakeGraph(paused=QUESTION, final={})
    monkeypatch.setattr(tg, "build_graph", lambda checkpointer=None: graph)

    bot, pending = FakeBot(), {}
    tg.handle(bot, pending, _message(text="saw her again"))

    something_else = bot.buttons()[-1]
    assert something_else["text"] == "something else"
    assert something_else["callback_data"] == "a:2"

    tg.handle(bot, pending, _tap("a:2"))
    resumed = graph.payloads[-1]
    assert isinstance(resumed, Command)
    assert resumed.resume == ""          # the value EIG scored, not the label
    assert 42 not in pending


def test_every_button_payload_fits_telegrams_64_byte_cap(monkeypatch):
    monkeypatch.setattr(tg, "build_graph", lambda checkpointer=None: FakeGraph(paused=QUESTION))
    bot = FakeBot()
    tg.handle(bot, {}, _message(text="saw her again"))
    for button in bot.buttons():
        assert 1 <= len(button["callback_data"].encode()) <= 64


def test_the_calendar_gate_renders_as_a_confirmation(monkeypatch):
    paused = {
        "type": "confirm_events",
        "backend": "local",
        "events": [{"index": 0, "title": "Coffee with Kang Ling", "start": "2026-09-04T10:00"},
                   {"index": 1, "title": "Send deck", "start": "2026-09-05T09:00"}],
    }
    graph = FakeGraph(paused=paused, final={})
    monkeypatch.setattr(tg, "build_graph", lambda checkpointer=None: graph)

    bot, pending = FakeBot(), {}
    tg.handle(bot, pending, _message(text="coffee with kang ling on friday"))

    assert pending[42].kind == "confirm"
    assert "Coffee with Kang Ling" in bot.last["text"]

    # Skip all resumes with "none": an unrecognised or declining reply must
    # write nothing to a real calendar.
    tg.handle(bot, pending, _tap("a:1"))
    assert graph.payloads[-1].resume == "none"


def test_a_second_memo_cannot_start_while_a_question_is_open(monkeypatch):
    monkeypatch.setattr(tg, "build_graph", lambda checkpointer=None: FakeGraph(paused=QUESTION))
    bot, pending = FakeBot(), {}
    tg.handle(bot, pending, _message(text="first"))
    tg.handle(bot, pending, _message(text="second"))

    assert "Answer the question above first" in bot.last["text"]


def test_cancel_drops_the_pending_question(monkeypatch):
    monkeypatch.setattr(tg, "build_graph", lambda checkpointer=None: FakeGraph(paused=QUESTION))
    bot, pending = FakeBot(), {}
    tg.handle(bot, pending, _message(text="first"))
    tg.handle(bot, pending, _message(text="/cancel"))

    assert 42 not in pending


def test_a_stale_tap_after_a_restart_is_explained_not_a_crash():
    """InMemorySaver does not survive a restart, so neither does the run."""
    bot = FakeBot()
    tg.handle(bot, {}, _tap("a:0"))
    assert bot.acks == ["That question has expired."]


def test_an_unlisted_chat_is_refused_and_told_its_id(monkeypatch):
    """The store is process-global, so two users would share one person graph."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "999")
    bot = FakeBot()
    tg.handle(bot, {}, _message(text="hello"))

    assert "42" in bot.last["text"]
    assert len(bot.sent) == 1


def test_the_graph_is_run_interactively_or_it_never_pauses():
    """`configurable.interactive` is the switch, not the checkpointer."""
    config = tg._config(42)["configurable"]
    assert config["interactive"] is True
    assert config["thread_id"] == "tg-42"


def test_an_unexpected_failure_comes_back_as_a_message(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("bedrock said no")

    monkeypatch.setattr(tg, "build_graph", boom)
    bot = FakeBot()
    tg.handle(bot, {}, _message(text="hello"))

    assert "bedrock said no" in bot.last["text"]
