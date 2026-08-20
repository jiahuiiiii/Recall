"""extract_people -- transcript to typed Person records."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from recall._common import cached_system, chat_model
from recall.state import PeopleExtraction, RecallState

SYSTEM = """You extract people from a voice memo that someone recorded right after \
a networking event, conference, or meeting.

The speaker is talking fast and informally. Names are phonetic guesses from speech \
recognition and may be misspelled. Your job is to pull out every distinct human they \
mention meeting or talking about.

Rules:
- One entry per distinct human. If the speaker refers to the same person by name and \
then by nickname or role ("Wei Lin ... she ... the GIC woman"), that is ONE person; \
put the alternate references in `aliases`.
- Do not invent details. If the company or role was not said, leave it null. A \
guessed employer poisons the dedupe step downstream.
- `notes` should preserve what the speaker actually said about the person -- their \
interests, what they are working on, what was promised, how they seemed. Condense \
the phrasing but do not editorialise or summarise away specifics.
- Skip people who are only mentioned in passing and were not actually met or \
discussed as contacts (e.g. "my wife texted me", "like that guy from the podcast").
- Keep the speaker themselves out of the list."""


def extract_people_node(state: RecallState) -> dict:
    """Return `people`: everyone the memo is about."""
    transcript = (state.get("transcript") or "").strip()
    if not transcript:
        return {"people": []}

    # temperature=0: this is extraction, not writing. Sampling here produces
    # different people on different runs, which makes dedupe untestable.
    llm = chat_model(label="extract_people", temperature=0.0).with_structured_output(
        PeopleExtraction
    )
    result: PeopleExtraction = llm.invoke(
        [
            SystemMessage(content=cached_system(SYSTEM)),
            HumanMessage(content=f"Voice memo transcript:\n\n{transcript}"),
        ]
    )
    people = [p.model_dump() for p in result.people]
    names = ", ".join(p["name"] for p in people) or "nobody"
    return {
        "people": people,
        "messages": [AIMessage(content=f"Extracted {len(people)} people: {names}.")],
    }
