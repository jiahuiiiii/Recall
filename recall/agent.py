"""AgentCore entrypoint.

The same graph serves the CLI and the deployed runtime -- there is exactly one
implementation of the pipeline, and this module only translates payloads.
"""

from __future__ import annotations

from typing import Any

from recall.graph import run


def handle(payload: dict[str, Any]) -> dict[str, Any]:
    """Process one memo.

    Payload accepts either:
        {"transcript": "..."}   already-typed notes
        {"audio_path": "..."}   a file readable by the runtime
        {"prompt": "..."}       alias for transcript (AgentCore's default field)
    """
    transcript = payload.get("transcript") or payload.get("prompt") or ""
    audio_path = payload.get("audio_path")

    if not transcript and not audio_path:
        return {"error": "supply either `transcript` or `audio_path`"}

    state = run(transcript=transcript, audio_path=audio_path, verbose=False)

    # Return the structured result, not just the printable summary -- a caller
    # that wants to render its own UI should not have to parse our text output.
    return {
        "summary": state.get("summary", ""),
        "new_people": state.get("new_people", []),
        "known_matches": state.get("known_matches", []),
        "enrichments": state.get("enrichments", {}),
        "commitments": state.get("commitments", []),
        "drafts": state.get("drafts", []),
        "calendar_events": state.get("calendar_events", []),
        "errors": state.get("errors", []),
    }
