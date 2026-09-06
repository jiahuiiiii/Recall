"""Web tools -- used ONLY inside the enricher sub-agent.

Raw search results are long and noisy; keeping them behind a sub-agent boundary
is the whole point of the supervisor pattern. Nothing here should ever be bound
to the main graph's model.

Provider is whichever key is present: Tavily > Brave > Serper > DuckDuckGo HTML
(no key, best-effort). Missing keys degrade to a weaker provider rather than
failing the run.
"""

from __future__ import annotations

import os
import re

import httpx
from langchain_core.tools import tool

TIMEOUT = 15.0


@tool
def web_search(query: str) -> str:
    """Search the public web and return the top results as title/URL/snippet lines.

    Use this to confirm a person's current employer, job title, or public
    background. Search for the person together with their company or field --
    a bare common name returns the wrong human. Run at most two or three
    searches, then stop and report what you found.

    Args:
        query: The search query, e.g. "Wei Lin GIC quantitative infrastructure".

    Returns up to 8 results as plain text, or a message starting with "ERROR:".
    """
    query = (query or "").strip()
    if not query:
        return "ERROR: empty search query."
    try:
        if os.environ.get("TAVILY_API_KEY"):
            return _tavily(query)
        if os.environ.get("BRAVE_API_KEY"):
            return _brave(query)
        if os.environ.get("SERPER_API_KEY"):
            return _serper(query)
        return _duckduckgo(query)
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: web search failed ({type(exc).__name__}): {exc}"


@tool
def fetch_page(url: str) -> str:
    """Fetch one web page and return its visible text, truncated to ~6000 characters.

    Use this only when a search snippet is promising but too short to confirm a
    fact -- for example an official team page or a conference speaker bio.
    Do not fetch more than two pages per person.

    Args:
        url: Absolute http(s) URL from a previous web_search result.

    Returns page text, or a message starting with "ERROR:".
    """
    if not (url or "").startswith(("http://", "https://")):
        return f"ERROR: not an absolute http(s) URL: {url!r}"
    try:
        resp = httpx.get(
            url,
            timeout=TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; RecallAgent/0.1)"},
        )
        resp.raise_for_status()
        return _visible_text(resp.text)[:6000]
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: could not fetch {url} ({type(exc).__name__}): {exc}"


def _fmt(rows: list[tuple[str, str, str]]) -> str:
    if not rows:
        return "No results found."
    return "\n\n".join(
        f"{i}. {title}\n   {url}\n   {snippet}"
        for i, (title, url, snippet) in enumerate(rows[:8], 1)
    )


def _tavily(query: str) -> str:
    resp = httpx.post(
        "https://api.tavily.com/search",
        json={
            "api_key": os.environ["TAVILY_API_KEY"],
            "query": query,
            "max_results": 8,
            "search_depth": "basic",
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return _fmt(
        [
            (r.get("title", ""), r.get("url", ""), (r.get("content") or "")[:400])
            for r in resp.json().get("results", [])
        ]
    )


def _brave(query: str) -> str:
    resp = httpx.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": 8},
        headers={
            "X-Subscription-Token": os.environ["BRAVE_API_KEY"],
            "Accept": "application/json",
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return _fmt(
        [
            (r.get("title", ""), r.get("url", ""), _strip_tags(r.get("description", ""))[:400])
            for r in resp.json().get("web", {}).get("results", [])
        ]
    )


def _serper(query: str) -> str:
    resp = httpx.post(
        "https://google.serper.dev/search",
        json={"q": query, "num": 8},
        headers={"X-API-KEY": os.environ["SERPER_API_KEY"]},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return _fmt(
        [
            (r.get("title", ""), r.get("link", ""), (r.get("snippet") or "")[:400])
            for r in resp.json().get("organic", [])
        ]
    )


def _duckduckgo(query: str) -> str:
    """Keyless fallback. Scrapes the HTML endpoint, so it is best-effort only --
    if it returns nothing the enricher reports 'no public info' and the graph
    carries on rather than stalling."""
    resp = httpx.post(
        "https://html.duckduckgo.com/html/",
        data={"q": query},
        timeout=TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (compatible; RecallAgent/0.1)"},
    )
    resp.raise_for_status()
    rows: list[tuple[str, str, str]] = []
    blocks = re.findall(
        r'<a rel="nofollow" class="result__a" href="(.*?)".*?>(.*?)</a>(.*?)(?=<a rel="nofollow"|</div>\s*</div>\s*</div>)',
        resp.text,
        re.DOTALL,
    )
    for href, title, tail in blocks:
        snippet = _strip_tags(tail)
        rows.append((_strip_tags(title), href, snippet[:400]))
    return _fmt(rows)


def _strip_tags(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html)).strip()


def _visible_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|nav|footer|svg)[^>]*>.*?</\1>", " ", html)
    return _strip_tags(html)
