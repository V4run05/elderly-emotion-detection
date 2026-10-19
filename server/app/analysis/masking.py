"""The core idea of the project: detect when what someone SAYS ("I'm fine") doesn't match how
they SEEM (voice tone + face).

One rule is applied at every level -- a single answer (turn), a whole check-in (session),
and a day -- so results stay consistent and explainable:

    says_ok  = verbal_valence >= SAYS_OK_THRESHOLD  or  a reassurance phrase was used
    seems_low = nonverbal_valence <= LOW_NONVERBAL_THRESHOLD

    "masked" : says_ok and seems_low and (verbal - nonverbal) >= MASKING_GAP_THRESHOLD
    "low"    : seems_low, or verbal_valence <= NEGATIVE_VERBAL_THRESHOLD (openly not OK)
    "ok"     : everything else

masking_score (0..1) is a continuous version for charts: the verbal-minus-nonverbal gap,
scaled to 0..1, and only counted when the person is presenting as OK.
"""

import re

from app import config

# Classic minimizing / reassurance phrases. Matching one counts as "says OK" even when the
# sentiment model reads the sentence as neutral (e.g. "Can't complain. Don't worry about me.").
REASSURANCE_PATTERNS = [
    r"\b(i'?m|i am|i'm doing|doing)\s+(fine|okay|ok|alright|all right|good|well)\b",
    r"\bnothing to worry about\b",
    r"\bdon'?t (you )?worry( about me)?\b",
    r"\bcan'?t complain\b",
    r"\bnot (too )?bad\b",
    r"\bsame as (always|usual|ever)\b",
    r"\bno complaints\b",
    r"\b(it'?s|that'?s) nothing\b",
    r"\bjust (a bit |a little )?tired\b",
]
_COMPILED = [re.compile(p, re.IGNORECASE) for p in REASSURANCE_PATTERNS]


def find_reassurance(text: str) -> list:
    """Returns the reassurance phrases found in the text (as written)."""
    text = text.replace("’", "'")
    return [m.group(0) for rx in _COMPILED for m in [rx.search(text)] if m]


def classify(verbal_valence: float, nonverbal_valence: float, reassurance: bool,
             low_threshold: float | None = None) -> str:
    """low_threshold: the person's own low line (analysis/baseline.py); fixed default if None."""
    says_ok = verbal_valence >= config.SAYS_OK_THRESHOLD or reassurance
    low = config.LOW_NONVERBAL_THRESHOLD if low_threshold is None else low_threshold
    seems_low = nonverbal_valence <= low
    gap = verbal_valence - nonverbal_valence
    if says_ok and seems_low and gap >= config.MASKING_GAP_THRESHOLD:
        return "masked"
    if seems_low or verbal_valence <= config.NEGATIVE_VERBAL_THRESHOLD:
        return "low"
    return "ok"


def masking_score(verbal_valence: float, nonverbal_valence: float, reassurance: bool) -> float:
    says_ok = verbal_valence >= config.SAYS_OK_THRESHOLD or reassurance
    if not says_ok:
        return 0.0
    # Reassurance with neutral-sounding words still counts as presenting OK, so floor verbal at 0.
    gap = max(verbal_valence, 0.0) - nonverbal_valence
    return float(min(1.0, max(0.0, gap / 2.0)))


def analyse(verbal_valence: float, nonverbal_valence: float, reassurance_phrases: list,
            low_threshold: float | None = None) -> dict:
    reassurance = bool(reassurance_phrases)
    return {
        "status": classify(verbal_valence, nonverbal_valence, reassurance, low_threshold),
        "masking_score": masking_score(verbal_valence, nonverbal_valence, reassurance),
    }
