"""extract_people -- transcript to typed Person records."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import ValidationError

from recall._common import cached_system, chat_model
from recall.state import PeopleExtraction, RecallState, salvage_object_list

# Structured output is not a guarantee about the wire format. Nova intermittently
# returns `people` as a STRING rather than a list -- sometimes a correctly encoded
# JSON document (handled by `state.decode_list`), sometimes malformed:
#
#   '[{"name": "OGL guy", ...}]}, "met_at": "MPSH"}]'   <- met_at after the close
#
# Malformed output is RE-ASKED first. `temperature=0` is not determinism on
# Bedrock, so a retry genuinely resamples, and a resample recovers the whole memo
# where a salvage recovers only its head. Two spare attempts, because the cost of
# losing the memo is an entire benchmark run: one bad extraction used to take out
# ~34 scorable cases in run_questions.
#
# Only once every attempt has come back corrupt does `state.salvage_object_list`
# keep the complete people that appear before the break -- and the node says so
# in its summary, because a partial extraction that reads like a clean one is
# indistinguishable from a memo the model genuinely found nobody in.
EXTRACT_ATTEMPTS = 3

REPAIR_REQUEST = (
    "Your previous structured response was malformed. Return the complete "
    "`people` list again with valid JSON: every person must be a complete "
    "object and every list field must be an array."
)


def _rejected_people_payload(exc: ValidationError) -> str | None:
    """The raw `people` string Pydantic rejected, when that is what failed.

    Anything else -- a genuine schema violation inside a decoded object, say --
    returns None, so salvage never fires on a failure it does not understand.
    """
    for err in exc.errors():
        if err.get("loc") == ("people",) and isinstance(err.get("input"), str):
            return err["input"]
    return None

SYSTEM = """You extract people from a voice memo that someone recorded right after \
a networking event, conference, or meeting.

The speaker is talking fast and informally. Names are phonetic guesses from speech \
recognition and may be misspelled. Your job is to pull out every distinct human they \
mention meeting or talking about.

Rules:
- One entry per distinct human. If the speaker refers to the same person by name and \
then by nickname or role ("Wei Lin ... she ... the GIC woman"), that is ONE person; \
put the alternate references in `aliases`.
- Keep every definite role or descriptive reference as an alias. "The Stripe engineer \
called" is a person, even when their name appears elsewhere in the memo: extract \
`name: "Alex Morgan", aliases: ["the Stripe engineer"]` when a later line says "Alex can \
do Thursday", and likewise keep "the Canva manager" or "the Wise product guy". Do not \
omit someone because the reference is a role rather than a conventional name; set \
`substantive` from the fact, plan, or promise about them as usual.
- A nickname stated as a FACT is still an alias. "Tiu Chuei Enn, everyone calls her \
Crispy" means `name: "Tiu Chuei Enn"` and `aliases: ["Crispy"]` -- put it in `aliases`, \
not only in `notes`. Recording it as a note alone means the next memo that says just \
"Crispy" cannot find her and files a duplicate person.
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
    messages = [
        SystemMessage(content=cached_system(SYSTEM)),
        HumanMessage(content=f"Voice memo transcript:\n\n{transcript}"),
    ]
    salvage_note = ""
    for attempt in range(EXTRACT_ATTEMPTS):
        try:
            result: PeopleExtraction = llm.invoke(messages)
            break
        except ValidationError as exc:
            if attempt < EXTRACT_ATTEMPTS - 1:
                messages.append(HumanMessage(content=REPAIR_REQUEST))
                continue
            # Every resample came back corrupt. Keep the complete people the
            # model did produce -- but a salvage is a PARTIAL extraction, so it
            # has to be visible downstream. Raise rather than return an empty
            # list when there is nothing to keep: a memo that silently yields
            # nobody is a missed recognition the eval cannot distinguish from a
            # correct empty extraction.
            salvaged, abandoned = salvage_object_list(_rejected_people_payload(exc))
            if not salvaged:
                raise
            try:
                result = PeopleExtraction.model_validate({"people": salvaged})
            except ValidationError:
                raise exc from None  # the head is not a valid Person either
            salvage_note = (
                f" Salvaged {len(salvaged)} person(s) from malformed model output "
                f"after {EXTRACT_ATTEMPTS} attempts"
            )
            salvage_note += (
                f"; abandoned {len(abandoned)} unparseable characters, which may "
                f"have held people this memo mentions."
                if abandoned
                else "."
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
    note += salvage_note
    return {"people": people, "messages": [AIMessage(content=note)]}
