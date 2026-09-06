"""Recall -- a relationship-capture agent."""

from dotenv import load_dotenv

# Load .env here, not in a submodule. Anything under `recall.` triggers this
# module first, so every import path gets the environment. Putting it in
# _common instead meant a module that did not happen to import _common --
# the transcription tool, for one -- silently saw no GROQ_API_KEY and reported
# it as a missing key rather than a missing import.
load_dotenv()

# Record-and-replay for model calls, off unless RECALL_LLM_CACHE is set. Wired
# here for the same reason as load_dotenv: it must be in force before any
# module builds a model, and a global cache set later would miss the calls
# already made. See recall/llm_cache.py.
from recall.llm_cache import install as _install_llm_cache

LLM_CACHE_PATH = _install_llm_cache()

__version__ = "0.1.0"
