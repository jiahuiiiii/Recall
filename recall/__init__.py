"""Recall -- a relationship-capture agent."""

from dotenv import load_dotenv

# Load .env here, not in a submodule. Anything under `recall.` triggers this
# module first, so every import path gets the environment. Putting it in
# _common instead meant a module that did not happen to import _common --
# the transcription tool, for one -- silently saw no GROQ_API_KEY and reported
# it as a missing key rather than a missing import.
load_dotenv()

__version__ = "0.1.0"
