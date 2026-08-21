"""The supervisor graph.

    transcribe -> extract_people -> dedupe --+-- new  --> enrich --+
                                             |                     |
                                             +-- known --> merge --+
                                                                   |
                          commitments -> drafts -> calendar -> persist -> summary

The branch after `dedupe` and the two sub-agents (`enrich`, `drafts`) are the
agentic surface being scored. Collapsing any of them into a single prompt makes
this a transcription-plus-database toy.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from recall.nodes import (
    calendar_node,
    commitments_node,
    dedupe_node,
    drafter_node,
    enrich_node,
    extract_people_node,
    merge_node,
    persist_node,
    route_after_dedupe,
    summarize_node,
    transcribe_node,
)
from recall.state import RecallState


def build_graph(checkpointer=None):
    """Compile the Recall graph. Pass a checkpointer to keep run history."""
    g = StateGraph(RecallState)

    g.add_node("transcribe", transcribe_node)
    g.add_node("extract", extract_people_node)
    g.add_node("dedupe", dedupe_node)
    g.add_node("enrich", enrich_node)
    g.add_node("merge", merge_node)
    g.add_node("commitments", commitments_node)
    g.add_node("drafts", drafter_node)
    g.add_node("calendar", calendar_node)
    g.add_node("persist", persist_node)
    g.add_node("summary", summarize_node)

    g.add_edge(START, "transcribe")
    g.add_edge("transcribe", "extract")
    g.add_edge("extract", "dedupe")

    # The conditional edge. Returns a LIST of targets, so a memo containing both
    # a stranger and an old contact fans out to both branches in one pass.
    g.add_conditional_edges(
        "dedupe",
        route_after_dedupe,
        ["enrich", "merge", "commitments"],
    )

    # Fan-in. LangGraph waits for every branch that actually ran before firing
    # `commitments`, so the drafter always sees enrichment results if there were any.
    g.add_edge("enrich", "commitments")
    g.add_edge("merge", "commitments")

    g.add_edge("commitments", "drafts")
    g.add_edge("drafts", "calendar")
    g.add_edge("calendar", "persist")
    g.add_edge("persist", "summary")
    g.add_edge("summary", END)

    return g.compile(checkpointer=checkpointer)


def run(
    *, transcript: str | None = None, audio_path: str | None = None, verbose: bool = True
) -> RecallState:
    """Run one memo end to end and return the final state."""
    graph = build_graph()
    initial: RecallState = {
        "transcript": transcript or "",
        "audio_path": audio_path,
        "messages": [],
    }

    if not verbose:
        return graph.invoke(initial)

    final: RecallState = {}
    seen = 0
    for chunk in graph.stream(initial, stream_mode="values"):
        final = chunk
        messages = chunk.get("messages") or []
        # stream_mode="values" replays the whole state every superstep, so a node
        # that returns no message leaves the previous one at the tail and it gets
        # printed again. Print only what is genuinely new.
        for message in messages[seen:]:
            content = message.content
            if isinstance(content, str) and not content.startswith("="):
                print(f"  . {content}")
        seen = len(messages)
    print("\n" + (final.get("summary") or "(no summary)"))
    return final
