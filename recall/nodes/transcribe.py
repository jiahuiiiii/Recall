"""Front of the graph: audio -> text."""

from __future__ import annotations

from langchain_core.messages import AIMessage

from recall.state import RecallState
from recall.tools.transcribe import transcribe


def transcribe_node(state: RecallState) -> dict:
    """Fill `transcript` from `audio_path`, or pass through typed notes.

    A transcript already in state wins: it lets the demo run without an audio
    file and lets tests pin exact input.
    """
    if state.get("transcript"):
        return {}

    audio_path = state.get("audio_path")
    if not audio_path:
        return {
            "transcript": "",
            "errors": ["no audio_path and no transcript supplied"],
            "messages": [AIMessage(content="Nothing to process: no audio, no transcript.")],
        }

    text = transcribe(audio_path)
    if text.startswith("ERROR:"):
        # Tool failures come back as content, never exceptions. The run continues
        # to the summary node, which reports what broke.
        return {"transcript": "", "errors": [text], "messages": [AIMessage(content=text)]}

    return {
        "transcript": text,
        "messages": [AIMessage(content=f"Transcribed {len(text)} chars from {audio_path}.")],
    }
