"""Record-and-replay cache for model calls, so a demo cannot be lost to the API.

Off unless RECALL_LLM_CACHE names a file. Prime it once against a working
account; every later run with the same memo text replays from disk, offline and
byte-identical. This does NOT make the pipeline deterministic in general -- it
makes one rehearsed input deterministic, which is the only thing a demo needs.

A cache, not a stub: every entry was produced by a real model call. Say so if
anyone asks whether the demo is live -- extraction is replayed, resolution and
question selection run for real, and those are the parts that are the claim.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import warnings
from pathlib import Path
from typing import Any

from langchain_core.caches import BaseCache
from langchain_core.load import dumpd, load


class FileCache(BaseCache):
    """Prompt -> generations, as one JSON object on disk.

    Whole file rewritten per write. A demo cache holds tens of entries, so the
    simple thing is correct here; do not reach for SQLite until it hurts.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {}
        if self.path.exists():
            self._data = json.loads(self.path.read_text() or "{}")

    @staticmethod
    def _key(prompt: str, llm_string: str) -> str:
        return hashlib.sha256(f"{prompt}\x00{llm_string}".encode()).hexdigest()

    def lookup(self, prompt: str, llm_string: str) -> list | None:
        hit = self._data.get(self._key(prompt, llm_string))
        if not hit:
            return None
        # `load` rebuilds the AIMessage including tool_calls, which is what
        # `with_structured_output` reads. A plain json round-trip loses them.
        # Warnings suppressed because the input is this process's own cache
        # file, not untrusted data -- and a beta warning per model call buries
        # the demo output.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return [load(g) for g in hit]

    def update(self, prompt: str, llm_string: str, return_val: list) -> None:
        with self._lock:
            self._data[self._key(prompt, llm_string)] = [dumpd(g) for g in return_val]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=1))
            tmp.replace(self.path)

    def clear(self, **kwargs: Any) -> None:
        with self._lock:
            self._data = {}
            self.path.unlink(missing_ok=True)

    async def alookup(self, prompt: str, llm_string: str) -> list | None:
        return self.lookup(prompt, llm_string)

    async def aupdate(self, prompt: str, llm_string: str, return_val: list) -> None:
        self.update(prompt, llm_string, return_val)

    async def aclear(self, **kwargs: Any) -> None:
        self.clear(**kwargs)


def install() -> str | None:
    """Wire the cache in if RECALL_LLM_CACHE is set. Returns the path, or None."""
    path = os.environ.get("RECALL_LLM_CACHE")
    if not path:
        return None
    from langchain_core.globals import set_llm_cache

    set_llm_cache(FileCache(path))
    return path
