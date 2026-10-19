"""Companion replies, personalised from the profile and memory, guided by the analysis.

The system prompt is rebuilt for every reply from: the person's profile (companion/profile.py),
what the companion remembers (companion/memory.py), and the date/time. Each user message gets a
private note with the emotional guidance (masked / low / ok, or the safety override) and optional
hints (companion/plan.py) the companion may use if they fit. Conversations are open-ended.

The provider (Groq) is isolated in complete()/complete_json() so it can be swapped.
"""

import json
import logging
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import datetime

from app import config
from app.companion import profile as profile_mod

logger = logging.getLogger("uvicorn.error")

MAX_ATTEMPTS = 3
_hedge_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="llm")
FALLBACK_REPLY = "Sorry, I didn't quite catch that. Could you tell me again?"

# Emotional notes are only added when support is actually needed (companion/plan.py support()).
# Otherwise the companion just chats.
MOOD_NOTES = {
    "daily_masked": "This answers today's 'how are you feeling?'. Their words say fine, but their voice and "
                    "face seem low. Don't point it out; respond warmly and leave a little room for them to "
                    "say more if they want to.",
    "daily_low": "This answers today's 'how are you feeling?' and they don't seem great. Respond with care.",
    "distress": "What they said sounds upset. Respond with warmth and let them talk about it; ask or "
                "listen rather than fix. Don't rush to suggest things.",
    "sustained": "Over the last several messages they have seemed a bit low. Be a little gentler and "
                 "warmer, but keep the conversation going naturally.",
}
CHAT = "Just keep chatting naturally, like a friend."
SAFETY = ("They may have mentioned harming themselves or not wanting to live. Take it seriously and "
          "gently: say you're glad they told you, that they're not alone, that you're letting "
          "{contact} know so someone can be with them, and encourage them to call someone or a "
          "helpline right now. Ignore all other aims.")


def system_prompt(p: dict, memory_text: str, now: datetime) -> str:
    companion = profile_mod.companion_name(p)
    address = profile_mod.address_as(p)
    style = profile_mod.STYLES[p["companion"]["style"]]
    parts = [
        f"You are {companion}, a {style} friend to {address}. They talk to you whenever they like, "
        f"about anything at all. You're good company: curious, a bit playful, happy to chat about "
        f"small things, share an opinion, tell a joke or a story, or think something through with them. "
        f"You are not a therapist or an assistant. Below is what you know about them; use it only when "
        f"it's relevant to what they're talking about.",
        profile_mod.describe(p),
    ]
    if memory_text:
        parts.append(memory_text)
    part = "morning" if now.hour < 12 else "afternoon" if now.hour < 17 else "evening"
    parts.append(f"Right now it is {now:%A %d %B, %I:%M %p} ({part}).")
    parts.append(
        "How to talk:\n"
        "- Respond to exactly what they just said. If they ask a question, answer it directly first. If they "
        "ask you to do something (sing, tell a joke or story, guess, help think something through, play a "
        "word game), actually do it. If you didn't understand, say so and ask.\n"
        "- Keep it a normal, flowing conversation. Don't steer back to their family, garden, songs or health "
        "on your own. Never repeat a suggestion, question or topic you've already raised in this "
        "conversation unless they bring it up again.\n"
        "- Don't comfort, reassure or suggest activities unless the private note says support is needed or "
        "they clearly ask for it. No 'I'm here for you', no 'that sounds lovely' on every turn.\n"
        f"- It's spoken aloud: usually 1-2 short sentences in plain words, never more than 3. For anything long "
        "(a recipe, a story, instructions), give only the first small part in 2-3 sentences, then ask if they'd "
        "like the next part; continue from where you stopped when they say yes. No numbered lists. Use their "
        f"name ({address}) only now and then.\n"
        "- Punctuation: write like people talk. Never use em dashes, en dashes or semicolons, use commas or "
        "full stops instead. No lists, markdown, asterisks or emojis.\n"
        "- Don't interview them. Ask a question in at most every other reply; the rest of the time just "
        "react, agree, add your own small thought, a bit of humour or a little fact, the way friends talk. "
        "When they give short answers, offer something of your own instead of another question.\n"
        "- Don't keep pulling the conversation back to things from your notes (visits, plans, the garden, "
        "songs). Mention something from your notes at most once per conversation, and only if it connects "
        "to what they're saying.\n"
        "- Always reply in English (speech recognition and the voice are English-only). A familiar word or "
        "form of address from their language is fine.\n"
        "- Each message has a private note. Follow it but never mention it. Never name their emotions "
        "('you sound sad'), never diagnose, never give medical advice (suggest their doctor or family).\n"
        "- Don't invent facts about their life, and be careful about who did what. Never name a specific song "
        "or film title (you often get them wrong); you can talk about well-known artists or ask them which "
        "songs they love. Don't make up other facts you aren't sure of.\n"
        "- If they bring up adult or intimate topics, respond calmly and respectfully, like a mature friend, "
        "without lecturing or abruptly changing the subject.\n"
        "- If they just say something short like 'okay', 'yes' or 'hmm', reply briefly and naturally, or move "
        "on with something light. Don't pad the reply.\n"
        "- If they ask you to sing: you can't really sing, so say so playfully and offer something else, like "
        "talking about a song they love or saying a few words of a very famous one you're sure of.\n"
        "- Don't assume things happened today (a walk, a visit, a meal) unless they said so.\n"
        "- Never sound like an assistant: no 'how can I help you?' or 'let me know if you need anything'. "
        "Don't ask 'how are you feeling?' again if they've already answered it.")
    return "\n\n".join(parts)


def mood_note(support: dict, status: str) -> str | None:
    mode = support.get("mode")
    if mode == "daily":
        return MOOD_NOTES["daily_masked" if status == "masked" else "daily_low"]
    return MOOD_NOTES.get(mode) if mode else None


def _note(support: dict, status: str, hints: list, safety: bool, p: dict, asked_last: bool = False) -> str:
    if safety:
        contact = p["family_contact"]["name"] or "their family"
        return f"[Private note: {SAFETY.format(contact=contact)}]"
    text = mood_note(support, status) or CHAT
    if asked_last:
        text += (" Your last reply asked a question, so don't end this one with a question: answer or react, "
                 "and add a thought of your own.")
    if hints:
        text += " Optional, only if it fits naturally right now (otherwise ignore): " + " ".join(hints)
    return f"[Private note: {text}]"


MAX_SENTENCES = 3
MAX_WORDS = 75          # spoken replies stay short; longer answers continue in the next turn
_EMPHASIS = re.compile(r"(\*\*|\*|__|_)(?=\S)(.+?)(?<=\S)\1")


def tidy(text: str) -> str:
    """Make a reply speakable: no em/en dashes or semicolons, no markdown emphasis, no line breaks, bullets or
    list numbers, and at most MAX_SENTENCES sentences. If it's cut, a closing question ("Shall I go
    on?") is kept so a long answer can continue in the next turn."""
    text = _EMPHASIS.sub(r"\2", text)
    text = re.sub(r"\s*[\u2014\u2013]\s*", ", ", text)          # em / en dash -> comma
    text = re.sub(r"\s+-{2,}\s+|\s+-\s+", ", ", text)            # " - " / " -- " used as a dash
    text = re.sub(r"^[\s>*\-\u2022]+", "", text, flags=re.M)     # bullets / quote markers
    text = re.sub(r"\s*\n+\s*", " ", text)
    text = re.sub(r"\s*;\s*(\w)", lambda m: ". " + m.group(1).upper(), text)   # semicolon -> new sentence
    text = text.replace(";", ".")
    text = re.sub(r",\s*([,.!?])", r"\1", text)                  # ", ." -> "."
    text = re.sub(r"([.!?])([A-Z])", r"\1 \2", text)            # "again?I'm" -> "again? I'm"
    text = re.sub(r"(?:^|(?<=[.!?] ))\d{1,2}[.)] +", "", text)  # list numbering "2. " / "3) "
    text = re.sub(r"\s{2,}", " ", text).strip()
    sentences = re.split(r"(?<=[.!?])\s+(?=[\"\u201c'(A-Z0-9])", text)
    closing = sentences[-1] if len(sentences) > 1 and sentences[-1].rstrip().endswith("?") else None
    body = sentences[:-1] if closing else sentences
    room_s = MAX_SENTENCES - (1 if closing else 0)
    room_w = MAX_WORDS - (len(closing.split()) if closing else 0)
    keep, words = [], 0
    for s in body:   # whole sentences only, never cut mid-sentence
        n = len(s.split())
        if keep and (len(keep) >= room_s or words + n > room_w):
            break
        keep.append(s)
        words += n
    if len(keep) < len(body) or closing:
        text = " ".join(keep + ([closing] if closing else []))
    return text


def complete(messages: list, model: str | None = None, max_tokens: int = 400,
             effort: str = "low", response_format: dict | None = None) -> str:
    from groq import BadRequestError, Groq

    client = Groq(api_key=config.GROQ_API_KEY)
    last_error = None
    for _attempt in range(MAX_ATTEMPTS):
        try:
            kwargs = {"response_format": response_format} if response_format else {}
            completion = client.chat.completions.create(
                model=model or config.LLM_MODEL,
                # gpt-oss spends part of max_tokens on hidden reasoning before the visible reply;
                # keep headroom (~150 truncated replies). reasoning_effort=low keeps latency down.
                max_tokens=max_tokens,
                reasoning_effort=effort,
                messages=messages,
                **kwargs,
            )
            content = (completion.choices[0].message.content or "").strip()
            if content:
                return content
            last_error = RuntimeError("empty completion")  # all budget went to reasoning; retry
        except BadRequestError as exc:
            # Known intermittent Groq/gpt-oss bug: "tool_use_failed" even though no tools are
            # passed. Not caused by our prompt; retrying is the documented workaround.
            body = getattr(exc, "body", None) or {}
            code = (body.get("error") or {}).get("code") if isinstance(body, dict) else None
            if code != "tool_use_failed":
                raise
            last_error = exc
    raise last_error


def complete_json(messages: list, schema: dict, model: str | None = None, effort: str = "medium") -> dict:
    """Strict JSON-schema output (Groq structured outputs).

    If Groq rejects the output on a schema technicality (code json_validate_failed, e.g. null
    where a list was expected), the generated JSON is in the error body: use it rather than
    losing the whole answer. Callers must tolerate nulls."""
    from groq import BadRequestError

    try:
        raw = complete(messages, model=model, max_tokens=2500, effort=effort,
                       response_format={"type": "json_schema",
                                        "json_schema": {"name": "result", "schema": schema, "strict": True}})
    except BadRequestError as exc:
        body = getattr(exc, "body", None) or {}
        err = (body.get("error") or {}) if isinstance(body, dict) else {}
        if err.get("code") == "json_validate_failed" and err.get("failed_generation"):
            logger.info("using JSON from a schema-rejected generation: %s", err.get("message", "")[:120])
            return json.loads(err["failed_generation"])
        raise
    return json.loads(raw)


def _fallback_greeting(p: dict, now: datetime) -> str:
    part = "morning" if now.hour < 12 else "afternoon" if now.hour < 17 else "evening"
    name, companion = profile_mod.address_as(p), profile_mod.companion_name(p)
    return random.choice([
        f"Good {part}, {name}! It's {companion}. How are you feeling today?",
        f"Hello {name}, good {part}. How have you been today?",
    ])


def greeting(p: dict, memory_text: str, hook: str | None, now: datetime) -> str:
    """A personal opening line: greets them, may mention one remembered thing (`hook`, chosen
    by the server from real memories so nothing is invented), then asks how they are feeling
    (that answer is the one the masking check cares most about)."""
    if not config.GROQ_API_KEY:
        return _fallback_greeting(p, now)
    part = "morning" if now.hour < 12 else "afternoon" if now.hour < 17 else "evening"
    mention = (f"Briefly mention this, from what you remember: {hook}." if hook else
               "You have nothing specific to bring up today, so don't mention any events, plans or "
               "observations (don't make any up).")
    instruction = (f"[Private note: Write your opening line for today's first chat. Greet them with "
                   f"'good {part}'. {mention} You MUST end with a direct question asking how they are "
                   f"feeling today. Max 2 short sentences, in English.]")
    try:
        return tidy(hedged([{"role": "system", "content": system_prompt(p, memory_text, now)},
                            {"role": "user", "content": instruction}])[0])
    except Exception as exc:  # noqa: BLE001
        logger.warning("greeting LLM failed, using template: %s", exc)
        return _fallback_greeting(p, now)


def casual_greeting(p: dict, memory_text: str, hook: str | None, now: datetime) -> str:
    """Greeting for a later conversation the same day (the daily question was already answered).
    `hook` is ignored on purpose: it was usually already mentioned in the first greeting."""
    name = profile_mod.address_as(p)
    if not config.GROQ_API_KEY:
        return f"Hello again, {name}! What's on your mind?"
    instruction = ("[Private note: You already talked earlier today. Greet them warmly again in one short "
                   "sentence, like a friend popping back in, and invite them to chat (for example, ask "
                   "what they've been up to or what's on their mind). Don't mention specific events, don't "
                   "ask how they're feeling again, never offer 'help'. English.]")
    try:
        return tidy(hedged([{"role": "system", "content": system_prompt(p, memory_text, now)},
                            {"role": "user", "content": instruction}])[0])
    except Exception as exc:  # noqa: BLE001
        logger.warning("casual greeting failed: %s", exc)
        return f"Hello again, {name}! What's on your mind?"


def farewell(p: dict, now: datetime) -> str:
    name = profile_mod.address_as(p)
    later = "Have a lovely evening" if now.hour >= 17 else "Have a lovely day"
    return random.choice([f"Bye for now, {name}. {later}!", f"Talk to you soon, {name}. {later}!"])


def hedged(messages: list) -> tuple[str, str]:
    """Ask the primary (better) and fast models at the same time. Returns (text, model used).
    Primary wins if it answers within LLM_PRIMARY_WAIT_S; otherwise the fast model's answer."""
    primary, fast = config.LLM_MODEL, config.LLM_FAST_MODEL
    if not fast or fast == primary:
        return complete(messages, model=primary), primary
    t0 = time.perf_counter()
    f_primary = _hedge_pool.submit(complete, messages, primary)
    f_fast = _hedge_pool.submit(complete, messages, fast)
    try:
        return f_primary.result(timeout=config.LLM_PRIMARY_WAIT_S), primary
    except FutureTimeout:
        logger.info("primary model slow (>%.1fs), using %s", config.LLM_PRIMARY_WAIT_S, fast)
    except Exception as exc:  # noqa: BLE001
        logger.warning("primary model failed (%s), using %s", exc, fast)
    try:
        return f_fast.result(timeout=30), fast
    except Exception:  # noqa: BLE001 -- fast failed too: wait a little longer for the primary
        remaining = max(1.0, 30 - (time.perf_counter() - t0))
        return f_primary.result(timeout=remaining), primary


def reply(p: dict, memory_text: str, history: list, user_text: str, status: str, support: dict,
          hints: list, safety: bool, now: datetime) -> str:
    """history: earlier messages of THIS conversation as [{role, content}] (oldest first).
    support: from companion/plan.py support(); emotional notes only when it says so."""
    asked_last = bool(history) and history[-1]["role"] == "assistant" and "?" in history[-1]["content"]
    messages = [{"role": "system", "content": system_prompt(p, memory_text, now)}, *history,
                {"role": "user", "content": f"{_note(support, status, hints, safety, p, asked_last)}\n{user_text}"}]
    try:
        text, model = hedged(messages)
        logger.info("reply from %s", model)
        return tidy(text)
    except Exception as exc:  # noqa: BLE001 -- a reply is best-effort; never fail the conversation
        logger.warning("LLM reply failed, using fallback: %s", exc)
        return FALLBACK_REPLY
