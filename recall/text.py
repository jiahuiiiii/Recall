"""Token matching shared by candidate retrieval and entity resolution.

Both need the same notion of "do these two strings refer to the same thing",
and it must behave identically in each: a token pair that retrieves a candidate
should also count as agreement when that candidate is scored. Keeping one
implementation is what guarantees that.

Pure functions. No I/O, no model calls.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

STOPWORDS = {
    "the", "a", "an", "and", "at", "of", "in", "on", "for", "to", "with",
    "from", "she", "he", "they", "her", "his", "their", "is", "was", "said",
    "met", "who", "that", "it", "i",
}

# Weights for how a query token can match a stored one. Exact is worth most;
# the softer forms exist because two specific things happen constantly:
#   - the speaker describes rather than names ("the german girl" vs "Germany")
#   - Whisper spells a name phonetically ("Viktorya" vs "Viktoria")
# Both return nothing under exact matching, and an empty candidate list makes
# dedupe skip the model entirely -- so the person is silently filed as new.
EXACT = 1.0
CONTAINED = 0.75
SIMILAR = 0.6

MIN_FUZZY_LEN = 4        # below this, substrings match far too much ("hui", "ing")
SIMILARITY_FLOOR = 0.85


def tokens(text: str) -> set[str]:
    return {
        t for t in re.findall(r"[a-z0-9]+", (text or "").lower())
        if t not in STOPWORDS and len(t) > 1
    }


def token_match(a: str, b: str) -> float:
    """How well one token matches another, 0.0 if not at all."""
    if a == b:
        return EXACT
    if len(a) < MIN_FUZZY_LEN or len(b) < MIN_FUZZY_LEN:
        return 0.0
    # "german" in "germany"; "ling" in "huiling" when a name is split.
    if a in b or b in a:
        return CONTAINED
    # A transposition or one wrong letter, which is what phonetic
    # transcription produces.
    if SequenceMatcher(None, a, b).ratio() >= SIMILARITY_FLOOR:
        return SIMILAR
    return 0.0


def match_strength(query: set[str], stored: set[str]) -> float:
    """Total match, each query token scored by its best stored counterpart."""
    if not query or not stored:
        return 0.0
    return sum(max((token_match(q, h) for h in stored), default=0.0) for q in query)


def best_match(a: str, b: str) -> float:
    """How completely two short strings (names, companies) agree, 0..1.

    Compares token to token rather than string to string so "Wei Lin" and
    "Lin, Wei" agree, and a middle name does not sink an otherwise exact match.

    Every token of the SHORTER string must find a counterpart, and the result is
    how well they did on average. Extra tokens on the longer side are silence --
    a family name the speaker dropped, a suffix -- not disagreement, which is
    why "Kit" still matches "Kit Yee" at 1.0.

    Scoring the single best pair instead (`max`) meant one shared token carried
    the whole name: "Hui Ning" matched "Hui Wen" at 1.00 on `hui`, cleared
    T_MATCH, and merged two different people with no question asked. The
    disagreeing halves have to count, or a shared syllable is indistinguishable
    from the same name. Measured on arc_godwin, not hypothetical.
    """
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    scores = [max((token_match(x, y) for y in long_), default=0.0) for x in short]
    return sum(scores) / len(scores)


def overlap_ratio(a: set[str], b: set[str]) -> float:
    """Fraction of the smaller token set matched in the larger, 0..1."""
    if not a or not b:
        return 0.0
    return match_strength(a, b) / min(len(a), len(b))
