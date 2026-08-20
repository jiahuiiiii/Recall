"""Speech-to-text at the head of the graph.

Bedrock/Claude cannot take audio, so transcription is a discrete tool rather
than a model capability. Groq's whisper-large-v3 is free-tier and fast enough
that a 90-second memo comes back in a couple of seconds on stage.
"""

from __future__ import annotations

import os
from pathlib import Path

from langchain_core.tools import tool

MODEL = "whisper-large-v3"


@tool
def transcribe_audio(audio_path: str) -> str:
    """Transcribe a voice memo file to text.

    Use this as the first step whenever the user supplies an audio file rather
    than typed notes. Accepts m4a, mp3, wav, ogg, webm, flac.

    Args:
        audio_path: Path on disk to the audio file.

    Returns the transcript as plain text, or a message starting with "ERROR:"
    if the file is missing or the transcription service is unavailable.
    """
    return transcribe(audio_path)


def transcribe(audio_path: str) -> str:
    """Direct-call form used by the graph node (no tool envelope)."""
    path = Path(audio_path)
    if not path.exists():
        return f"ERROR: no audio file at {audio_path}"

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return (
            "ERROR: GROQ_API_KEY is not set, so the memo cannot be transcribed. "
            "Set it in .env, or pass a transcript directly instead of audio."
        )

    try:
        from groq import Groq
    except ImportError:
        return "ERROR: groq package not installed. Run: uv sync --extra audio"

    try:
        client = Groq(api_key=api_key)
        with path.open("rb") as fh:
            result = client.audio.transcriptions.create(
                file=(path.name, fh.read()),
                model=MODEL,
                response_format="text",
            )
        return result if isinstance(result, str) else getattr(result, "text", str(result))
    except Exception as exc:  # noqa: BLE001 - surfaced to the model, never raised
        return f"ERROR: transcription failed ({type(exc).__name__}): {exc}"
