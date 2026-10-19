"""When the companion should go beyond plain conversation, and what it could bring up.

Default: just chat, like a friend. Emotional support is only brought in when it's actually
needed, because single-message voice/face readings are noisy (ordinary lines like "Um" or
"Oh no, I forgot" can read as "low"), and reacting to every one made replies repetitive and
forced. Support is needed when:

    distress in words   the sentiment of what they said is clearly negative
    sustained low       most of their recent spoken messages read as low / masked
    daily answer        their answer to "how are you feeling today?" reads low or masked

Like a friend, it listens first: a concrete suggestion is only offered when support is still
needed on the next message too (never on the daily answer alone), and at most once every few
messages. Other optional hints: a remembered event early on, and a due reminder once a day.
"""

import re
from datetime import timedelta

from app.companion import reminders as reminders_mod

# Words that make negative sentiment *emotional* rather than a small mishap ("I forgot my tablet").
EMOTION_WORDS = re.compile(
    r"\b(lonely|alone|miss(ing)?|sad|unhappy|depressed|down|low|cry(ing)?|tears|scared|afraid|frightened|"
    r"worried|worry|anxious|nervous|upset|hurt|hurting|grief|griev\w*|heartbroken|hopeless|empty|"
    r"tired of|fed up|nobody|no one|useless|burden|can'?t sleep|angry|frustrated)\b", re.IGNORECASE)

DISTRESS_VALENCE = -0.5      # negative words AND an emotion word (EMOTION_WORDS) = distress
SUSTAINED_WINDOW = 4         # look at the last N spoken messages (incl. this one)
SUSTAINED_MIN_LOW = 4        # ... and all of them must read low/masked (single readings are noisy)
SUGGESTION_COOLDOWN = 5      # messages between two support suggestions


def greeting_hook(recall: dict, today) -> str | None:
    """Something real and timely to mention in a greeting: an event today/yesterday/tomorrow,
    or a birthday within two days. None means: don't mention anything specific."""
    for m in recall["upcoming"]:
        if abs((m["date"] - today).days) <= 1:
            when = {-1: "yesterday", 0: "today", 1: "tomorrow"}[(m["date"] - today).days]
            return f"{m['text']} ({when})"
    for b in recall["birthdays"]:
        if b["in_days"] <= 2:
            return f"{b['name']}'s birthday is {'today' if b['in_days'] == 0 else 'in ' + str(b['in_days']) + ' days'}"
    return None


def support(turns: list, status: str, verbal_valence: float, wellbeing: bool, spoken: bool,
            text: str = "") -> dict:
    """Decide whether this reply needs emotional care. turns: earlier messages in this conversation.
    Returns {mode: None | "daily" | "distress" | "sustained", suggest: bool}."""
    recent = [t["status"] for t in turns if t.get("input", "voice") == "voice"][-(SUSTAINED_WINDOW - 1):]
    if spoken:
        recent.append(status)
    sustained = len(recent) >= SUSTAINED_WINDOW and sum(s in ("low", "masked") for s in recent) >= SUSTAINED_MIN_LOW
    mode = None
    if verbal_valence <= DISTRESS_VALENCE and EMOTION_WORDS.search(text.replace("\u2019", "'")):
        mode = "distress"
    elif wellbeing and status in ("low", "masked"):
        mode = "daily"
    elif sustained:
        mode = "sustained"
    recently_suggested = any(t["analysis"].get("support_suggested") for t in turns[-SUGGESTION_COOLDOWN:])
    still_needed = bool(turns) and turns[-1]["analysis"].get("support") in ("distress", "sustained")
    suggest = mode in ("distress", "sustained") and still_needed and not recently_suggested
    return {"mode": mode, "suggest": suggest}


def _follow_up(recall: dict) -> str | None:
    if recall["upcoming"]:
        return recall["upcoming"][0]["text"]
    if recall["birthdays"]:
        return f"{recall['birthdays'][0]['name']}'s birthday is coming up"
    return None


_FILLER = {"after", "before", "with", "today", "tomorrow", "yesterday", "coming", "going", "will", "have",
           "about", "this", "that", "their", "there", "from", "into", "over", "your"}


def _mentioned(text: str, replies: list) -> bool:
    """Rough check whether a topic was already raised: one of its first two key words appears in a
    companion line (errs on the side of not repeating)."""
    words = [w.strip(".,!?") for w in text.lower().replace("'s", "").split()]
    keys = [w for w in words if len(w) > 3 and w not in _FILLER][:2] or words[:1]
    return any(k in r.lower() for k in keys for r in replies)


def hints(p: dict, recall: dict, conversation_replies: list, replies_today: list, suggest_support: bool,
          now) -> list:
    """Optional things the companion may bring up if they fit.
    conversation_replies: companion lines so far in this conversation (incl. greeting).
    replies_today: companion lines across all of today's conversations."""
    out = []
    if len(conversation_replies) <= 2:
        hook = _follow_up(recall)
        if hook and not _mentioned(hook, replies_today):
            out.append(f"If the conversation allows, you could ask about: {hook}.")
    due = reminders_mod.to_mention(now)
    if due and not _mentioned(due["title"], replies_today):   # once a day, not every conversation
        out.append(f"A reminder is due ({reminders_mod.describe(due)}). If there's a natural moment, "
                   "check on it once, lightly.")
    if suggest_support:
        ideas = p["cheer_up"] or p["activities"] or p["interests"]
        out.append(f"If it would genuinely help, you may offer ONE small idea (for example from: "
                   f"{ideas or 'things they enjoy'}). Pick something you haven't suggested before.")
    return out
