"""Self-harm screen: flags messages that may mean the person is thinking about harming themselves
or not wanting to live, so the reply follows a fixed safe script and the family dashboard raises an
urgent alert immediately.

Two layers (docs/EVALUATION.md §5):
1. keyword_flag(): instant regex screen. Catches the common direct phrasings; misses most
   indirect ones ("I don't see the point anymore"), so it is only the backup.
2. llm_flag(): an LLM screen (SAFETY_SCREEN_MODEL, Groq's gpt-oss-safeguard-20b) that also sees
   the previous messages, so "I keep thinking about joining him" after talking about a late husband
   is understood. Measured 100% of direct and 92% of indirect statements, no false alarms on idioms
   like "this heat is killing me". If it fails or is rate-limited, SAFETY_SCREEN_FALLBACKS are tried;
   if they all fail, only the keyword result is used.
A message is flagged if either layer flags it. This is a screen, not a clinical tool.
"""

import json
import logging
import re

from app import config

logger = logging.getLogger("uvicorn.error")

SAFETY_PATTERNS = [
    r"\b(kill|hurt|harm|cut)(ing)? myself\b",
    r"\b(want|wish|wanted|going|ready) to die\b",
    r"\bwish (i|I) (was|were) dead\b",
    r"\bend(ing)? (it all|my life|everything)\b",
    r"\bsuicid",
    r"\bno (reason|point) (to|in) (live|living|go on|going on|being here)\b",
    r"\bbetter off (dead|without me)\b",
    r"\bdon'?t want to (live|be alive|be here|wake up|go on)\b",
    r"\b(sleep|go to sleep) and (not|never) wake up\b",
    r"\btired of (living|life|being alive)\b",
    r"\bcan'?t go on (like this|anymore|any more)\b",
    r"\b(take|took) all (my|the) (tablets|pills)\b",
]
_COMPILED = [re.compile(p, re.IGNORECASE) for p in SAFETY_PATTERNS]

SCREEN_PROMPT = (
    "You screen messages that an older person says to their companion app. Decide whether their LAST "
    "message expresses, directly or indirectly, thoughts of suicide, self-harm, wanting to die, not "
    "wanting to live, or preparing to die (giving things away, saying goodbye for good). Indirect "
    "examples that count: 'I don't see the point anymore', 'everyone would be better off without me', "
    "'I keep thinking about joining my late husband', 'God should just take me'. Idioms ('dying to see "
    "them', 'this heat is killing me'), grief or loneliness alone, and tiredness alone do not count. "
    "The earlier messages and background are only there to understand what the last message means.\n"
    'Answer only JSON: {"risk": true|false}')


def keyword_flag(text: str) -> bool:
    text = text.replace("’", "'")
    return any(rx.search(text) for rx in _COMPILED)


def is_safety_concern(text: str) -> bool:
    """Keyword layer only (kept for callers and tests that need an offline answer)."""
    return keyword_flag(text)


def _ask(model: str, text: str, earlier: list, background: str) -> bool:
    from app.dialogue import llm

    parts = []
    if background:
        parts.append(f"Background: {background}")
    if earlier:
        parts.append("Earlier messages from them:\n" + "\n".join(f"- {m}" for m in earlier[-3:]))
    parts.append(f"LAST message: {text}")
    raw = llm.complete([{"role": "system", "content": SCREEN_PROMPT}, {"role": "user", "content": "\n\n".join(parts)}],
                       model=model, max_tokens=700, effort="medium" if model.startswith("qwen/") else "low",
                       response_format={"type": "json_object"})
    return bool(json.loads(raw[raw.find("{"): raw.rfind("}") + 1]).get("risk"))


def llm_flag(text: str, earlier: list | None = None, background: str = "") -> tuple[bool | None, str | None]:
    """(flagged, model used). (None, None) if no screen model answered."""
    from app.dialogue import llm
    if not config.GROQ_API_KEY or not config.SAFETY_SCREEN_ENABLED:
        return None, None
    for model in (config.SAFETY_SCREEN_MODEL, *config.SAFETY_SCREEN_FALLBACKS):
        if not model or not llm.available(model):
            continue
        try:
            return _ask(model, text, earlier or [], background), model
        except Exception as exc:  # noqa: BLE001 -- the keyword layer still applies
            logger.warning("safety screen %s failed: %s", model, str(exc)[:160])
    return None, None


def screen(text: str, earlier: list | None = None, background: str = "") -> dict:
    """Both layers. Returns {flag, keyword, llm, model}."""
    kw = keyword_flag(text)
    llm_result, model = (None, None) if kw else llm_flag(text, earlier, background)
    return {"flag": bool(kw or llm_result), "keyword": kw, "llm": llm_result, "model": model}
