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
- `notes` is a LIST, one entry per distinct thing said about the person. Split on \
meaning, not on sentence boundaries: "she's very smart and nice, we formed a team for \
the hackathon, and she does computer science like me" is THREE entries, not one.
- Keep the speaker's own words. Lightly tidy grammar, nothing more. Do not paraphrase, \
do not compress two facts into one entry, do not drop qualifiers -- "computer science, \
same major as me" must not become "studies computer science", because the shared-major \
detail is exactly the kind of thing that makes a contact worth remembering.
- Keep the speaker themselves out of the list.

Set `substantive` by this test, not by feel. The memo must state a FACT, an OPINION, \
a PLAN, or a PROMISE involving the person. If the only thing said is that they were \
there, that they were greeted, or that they were mentioned by name, `substantive` is \
false -- even when you know who they are and even when they were genuinely met.

  "ran into Daniel from the Stripe thing again, nothing new, just said hi"
      -> substantive: false. Presence and a greeting. No fact, plan, or promise.
  "Marcus was there too and I finally did the Arjun intro in person"
      -> Marcus substantive: false. He is the venue for someone else's event.
      -> Arjun substantive: true. A promise involving him was discharged.
  "Priya, didn't catch her last name, partner at some early stage fund"
      -> substantive: true. A fact is stated, even though the name is incomplete.

Still list a person with `substantive: false` -- do not silently drop them. The \
pipeline decides what to do with that flag."""


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
    # The model reports everyone; the filter is code. Asking a model to silently
    # omit borderline people makes the decision invisible and unstable -- the same
    # memo yielded different name lists run to run. An explicit boolean it must
    # set, filtered deterministically here, is reproducible and debuggable.
    all_people = [p.model_dump() for p in result.people]
    people = [p for p in all_people if p.get("substantive")]
    skipped = [p["name"] for p in all_people if not p.get("substantive")]

    names = ", ".join(p["name"] for p in people) or "nobody"
    note = f"Extracted {len(people)} people: {names}."
    if skipped:
        note += f" Skipped {len(skipped)} passing mention(s): {', '.join(skipped)}."
    return {"people": people, "messages": [AIMessage(content=note)]}
