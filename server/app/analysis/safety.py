"""Minimal safety net: flag messages that mention self-harm or wanting to die, so the family
dashboard raises an urgent alert immediately instead of waiting for a multi-day trend.

This is a keyword screen, not a clinical tool -- it will miss indirect phrasing. It exists so
the system never silently stores a disclosure like this. See docs/PROJECT_SPEC.md (Ethics).
"""

import re

SAFETY_PATTERNS = [
    r"\b(kill|hurt|harm)(ing)? myself\b",
    r"\b(want|wish|wanted|going) to die\b",
    r"\bend (it all|my life)\b",
    r"\bsuicid",
    r"\bno (reason|point) (to|in) (live|living|go on|going on)\b",
    r"\bbetter off (dead|without me)\b",
    r"\bdon'?t want to (live|be here|wake up)\b",
]
_COMPILED = [re.compile(p, re.IGNORECASE) for p in SAFETY_PATTERNS]


def is_safety_concern(text: str) -> bool:
    text = text.replace("’", "'")
    return any(rx.search(text) for rx in _COMPILED)
