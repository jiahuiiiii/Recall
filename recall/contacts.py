"""Contact handles -- how you actually reach a person.

A record holds who someone is; this holds how to get hold of them. Four
channels, because those are the four ways people at these events actually swap
details: a phone number, Instagram, Telegram, LinkedIn.

**Storage and display only.** `resolve.compare` never reads `contacts` and
`LocalPersonStore.search` deliberately keeps them out of its haystack, so
nothing here can move the resolution benchmark. Handles are also exactly the
wrong thing to match on -- two people sharing a phone number is a data-entry
mistake, not evidence, and a resolver that trusted one would merge them
silently. If that ever changes, this file needs a weight and a re-run, and it is
not currently that kind of code.

It is also NOT an integration. Nothing here sends, fetches, or logs in; a
handle is a string the user typed and a link the browser can open. The "no new
calendar/email/LinkedIn work" non-goal is about plumbing, and this is a text
field.

Normalisation happens at the store boundary, once, for the same reason
`as_list` does: what arrives is a pasted URL as often as a handle
(`https://www.instagram.com/kangling/?hl=en`), and a record holding four
spellings of one profile cannot be linked to or compared against itself.
"""

from __future__ import annotations

import re

# Fixed order. The stored dict is written in it, so two records with the same
# handles serialise identically and a diff of the graph shows real changes.
CHANNELS: tuple[str, ...] = ("phone", "instagram", "telegram", "linkedin")

LABELS: dict[str, str] = {
    "phone": "Phone",
    "instagram": "Instagram",
    "telegram": "Telegram",
    "linkedin": "LinkedIn",
}

PLACEHOLDERS: dict[str, str] = {
    "phone": "+65 9123 4567",
    "instagram": "@handle",
    "telegram": "@handle",
    "linkedin": "linkedin.com/in/…",
}

_SCHEME = re.compile(r"^\s*(?:https?:)?//", re.IGNORECASE)
_LINKEDIN_HOST = re.compile(r"^(?:[a-z0-9-]+\.)?linkedin\.com/", re.IGNORECASE)
# Anything a person legitimately writes in a number, and nothing else. Letters
# are dropped rather than kept: "call me on 9123 4567" is a note, not a number.
_PHONE_KEEP = re.compile(r"[^\d+()\-. ]+")


def _bare(value: str) -> str:
    """Strip scheme, query, fragment and surrounding slashes off a pasted URL."""
    v = _SCHEME.sub("", (value or "").strip())
    v = v.split("?", 1)[0].split("#", 1)[0]
    return v.strip().strip("/")


def _after_host(value: str, hosts: tuple[str, ...]) -> str:
    """The path part of a pasted profile URL, or the value if it is not one."""
    v = _bare(value)
    if v.lower().startswith("www."):
        v = v[4:]
    for host in hosts:
        low = v.lower()
        if low == host:
            return ""
        if low.startswith(host + "/"):
            return v[len(host) + 1 :].strip("/")
    return v


def _handle(value: str, hosts: tuple[str, ...]) -> str:
    """A bare handle: no URL, no leading @, no trailing path segments."""
    v = _after_host(value, hosts).lstrip("@").strip()
    return v.split("/", 1)[0].strip()


def normalise(channel: str, value: str) -> str:
    """One channel's value, cleaned. Empty string means "nothing usable here".

    Never raises on content and never rewrites a handle's characters -- a
    handle that is wrong should stay wrong and visible rather than become a
    different, plausible-looking handle. Only decoration comes off.
    """
    if channel not in LABELS:
        raise ValueError(f"unknown contact channel {channel!r}")
    raw = (value or "").strip()
    if not raw:
        return ""

    if channel == "phone":
        cleaned = " ".join(_PHONE_KEEP.sub(" ", raw).split())
        # Fewer than five digits is not a phone number in any country, so it is
        # a mis-paste. Dropping beats storing something that dials nowhere.
        return cleaned if sum(c.isdigit() for c in cleaned) >= 5 else ""
    if channel == "instagram":
        return _handle(raw, ("instagram.com", "instagr.am"))
    if channel == "telegram":
        return _handle(raw, ("t.me", "telegram.me", "telegram.dog"))

    # LinkedIn is the odd one: the path carries its own type. `in/…` is a
    # person, `company/…` is not, and a bare handle is a person by convention --
    # so store the path, not the handle, and a company page still links.
    path = _LINKEDIN_HOST.sub("", _bare(raw)).strip("/").lstrip("@").strip()
    if path and "/" not in path:
        path = f"in/{path}"
    return path


def as_contacts(value: object) -> dict[str, str]:
    """Coerce whatever arrived into a clean {channel: handle} map.

    The boundary guard, same job as `as_list`: unknown channels are dropped,
    empty values are dropped rather than stored as `""`, and the result is
    ordered by `CHANNELS`. A record therefore never holds a key the UI has no
    field for, and "absent" has exactly one spelling.
    """
    if not isinstance(value, dict):
        return {}
    out: dict[str, str] = {}
    for channel in CHANNELS:
        raw = value.get(channel)
        if raw is None:
            continue
        cleaned = normalise(channel, str(raw))
        if cleaned:
            out[channel] = cleaned
    return out


def unknown_channels(value: object) -> list[str]:
    """Keys `as_contacts` would silently drop. The API says so instead.

    Dropping is right for the store -- an old record with a retired channel
    must still load -- but a caller that typed `whatsapp` deserves to be told,
    not to watch its write vanish."""
    if not isinstance(value, dict):
        return []
    return sorted(str(k) for k in value if k not in LABELS)


def link(channel: str, value: str) -> str | None:
    """A URL the browser can open, or None when there is nothing to open.

    Built here rather than in the page so the normalisation and the link cannot
    disagree about what the stored string means -- the server hands the browser
    both, and there is one implementation of the rule.
    """
    handle = normalise(channel, value)
    if not handle:
        return None
    if channel == "phone":
        return "tel:" + re.sub(r"[^\d+]", "", handle)
    if channel == "instagram":
        return f"https://instagram.com/{handle}"
    if channel == "telegram":
        return f"https://t.me/{handle}"
    return f"https://www.linkedin.com/{handle}"


def links(contacts: object) -> dict[str, str]:
    """{channel: url} for every channel with something in it."""
    out: dict[str, str] = {}
    for channel, handle in as_contacts(contacts).items():
        url = link(channel, handle)
        if url:
            out[channel] = url
    return out
