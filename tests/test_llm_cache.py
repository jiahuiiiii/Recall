"""The demo cache: off unless asked for, and lossless when on."""
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration

from recall.llm_cache import FileCache, install


def test_cache_is_off_unless_the_env_var_is_set(monkeypatch):
    monkeypatch.delenv("RECALL_LLM_CACHE", raising=False)
    assert install() is None


def test_tool_calls_survive_a_round_trip_through_disk(tmp_path):
    """`with_structured_output` reads tool_calls, so a plain json dump is not
    enough -- it keeps the text and silently drops the parsed arguments."""
    path = tmp_path / "c.json"
    msg = AIMessage(content="", tool_calls=[
        {"name": "Person", "args": {"name": "Jason"}, "id": "t1"}])
    FileCache(path).update("p", "llm", [ChatGeneration(message=msg)])

    got = FileCache(path).lookup("p", "llm")   # fresh instance: reads the file
    assert got is not None
    assert got[0].message.tool_calls[0]["args"] == {"name": "Jason"}


def test_a_different_prompt_is_a_miss(tmp_path):
    """The demo replays one rehearsed memo; an unrehearsed one must still go to
    the model rather than quietly returning the rehearsed answer."""
    path = tmp_path / "c.json"
    cache = FileCache(path)
    cache.update("p", "llm", [ChatGeneration(message=AIMessage(content="x"))])
    assert cache.lookup("other", "llm") is None
    assert cache.lookup("p", "different-model") is None
