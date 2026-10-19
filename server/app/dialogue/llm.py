"""Companion replies, personalised from the profile and memory, guided by the analysis.

The system prompt is rebuilt for every reply from: the person's profile (companion/profile.py),
what the companion remembers (companion/memory.py), and the date/time. Each user message gets a
private note with the emotional guidance (masked / low / ok, or the safety override) and optional
hints (companion/plan.py) the companion may use if they fit. Conversations are open-ended.

The provider (Groq) is isolated in complete()/complete_json() so it can be swapped.

Resilience (docs/EVALUATION.md §6-7): a model that hits a long rate limit (the free daily token
budget) is put on cooldown until Groq says it's available again, and replies move down the chain
LLM_MODEL -> LLM_FAST_MODEL -> LLM_BACKUP_MODELS. If nothing answers, the companion says honestly
that it's having trouble (UNAVAILABLE_REPLY), never "I didn't catch that" (the speech was heard).
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
UNAVAILABLE_REPLY = ("Sorry, I'm having a little trouble thinking right now, my connection is struggling. "
                     "Could we try again in a few minutes?")
FALLBACK_REPLY = UNAVAILABLE_REPLY   # old name, kept for callers


class LLMUnavailable(RuntimeError):
    """No model in the chain could answer (rate-limited, failing or no key)."""


_cooldown: dict = {}          # model -> monotonic time it may be used again
_last_problem: dict = {}      # model -> (wall time, message), for /api/health
COOLDOWN_MIN_S = 20           # shorter rate-limit waits are per-minute limits: no cooldown
COOLDOWN_MAX_S = 3600


def _rate_limit_wait(exc) -> float | None:
    m = re.search(r"try again in (?:(\d+)h)?(?:(\d+)m)?([\d.]+)s", str(exc))
    if not m:
        return None
    return int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + float(m.group(3))


def available(model: str) -> bool:
    return time.monotonic() >= _cooldown.get(model, 0.0)


def chain() -> list:
    """Reply models in order of preference that aren't on cooldown."""
    out = []
    for m in [config.LLM_MODEL, config.LLM_FAST_MODEL, *config.LLM_BACKUP_MODELS]:
        if m and m not in out and available(m):
            out.append(m)
    return out


def status() -> dict:
    """For /api/health and the dashboard: is the companion running on its usual model?"""
    now = time.monotonic()
    cooling = {m: round(t - now) for m, t in _cooldown.items() if t > now}
    usable = chain()
    return {"degraded": config.LLM_MODEL in cooling or not usable,
            "unavailable": not usable,
            "using": usable[0] if usable else None, "cooling_s": cooling,
            "last_problem": {m: {"at": at, "message": msg} for m, (at, msg) in _last_problem.items()}}

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
# After a flagged message, the rest of the conversation keeps this in mind.
SAFETY_FOLLOWUP = ("Earlier in this conversation they said something that may mean they don't want to live. "
                   "Stay with them gently: listen, keep it calm and simple, and now and then check whether "
                   "they've reached {contact} or {helpline} ({number}). Don't switch to cheerful topics or "
                   "suggestions unless they do. Never promise to keep it secret.")


def _spoken_number(number: str) -> str:
    """'14416' -> '1 4 4 1 6' so the voice reads it digit by digit."""
    return " ".join(c for c in number if c.isdigit())


def safety_reply(p: dict, first: bool, ask: bool = False) -> str:
    """Fixed reply when the self-harm screen flags a message. Not generated by the LLM: in testing the
    LLM once answered "I keep thinking about joining him" by talking about a granddaughter's exam.
    ask=True: only the LLM screen flagged it (no clear words) and it's the first time in this
    conversation, so ask directly first (asking about suicide doesn't put the idea there, and grief
    alone was sometimes flagged). A "yes" is flagged again and gets the helpline reply."""
    name = profile_mod.address_as(p)
    contact = p["family_contact"]["name"] or "your family"
    helpline, number = config.HELPLINE_NAME, _spoken_number(config.HELPLINE_NUMBER)
    if ask:
        return (f"{name}, I want to be sure I understand you. When you say that, are you having thoughts of "
                f"not wanting to live, or of hurting yourself? You can tell me honestly.")
    if first:
        return (f"{name}, thank you for telling me. I'm taking what you said seriously, and you don't have to "
                f"carry this alone. Please call {contact} now, or {helpline} on {number}, they're there day "
                f"and night. {contact} will see a note from me that you need someone with you.")
    return (f"I'm still right here with you, {name}. Have you been able to reach {contact}? If not, {helpline} "
            f"is on {number}, any time, and you can tell them what you told me.")


def system_prompt(p: dict, memory_text: str, now: datetime, sensitive_open: bool = False) -> str:
    companion = profile_mod.companion_name(p)
    address = profile_mod.address_as(p)
    style = profile_mod.STYLES[p["companion"]["style"]]
    parts = [
        f"You are {companion}, a {style} friend to {address}. They talk to you whenever they like, "
        f"about anything at all. You're good company: curious, a bit playful, happy to chat about "
        f"small things, share an opinion, tell a joke or a story, or think something through with them. "
        f"You are not a therapist or an assistant. Below is what you know about them; use it only when "
        f"it's relevant to what they're talking about.",
        profile_mod.describe(p, sensitive_open),
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
        f"- You are {companion}, a voice companion app, not a person. You have no body, family, home, past or "
        "senses: never claim you ate, smelled, heard or saw something, went somewhere, live nearby, or remember "
        "your own mother or childhood. If it comes up, say lightly that you're an app. Opinions and humour are fine.\n"
        "- Only say things about their life and the people in it that are in your notes or that they told you in "
        "this conversation. Don't add details (what someone likes or cooks, when someone visits or calls, what "
        "happened last week). If you're not sure, ask instead.\n"
        "- If they seem confused or mix something up (who visited, what day or time it is, whether someone is "
        "still alive), gently give the right fact once from your notes, kindly and without making them feel "
        "corrected. If you don't know, say so.\n"
        "- If they want to move on from a joke or topic (short replies, 'it's just a bird'), drop it and follow "
        "their lead.\n"
        "- Never name a specific song or film title (you often get them wrong); you can talk about well-known "
        "artists or ask them which songs they love. Don't make up other facts you aren't sure of.\n"
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


def _note(support: dict, status: str, hints: list, safety: bool, p: dict, asked_last: bool = False,
          safety_earlier: bool = False) -> str:
    contact = p["family_contact"]["name"] or "their family"
    if safety:
        return f"[Private note: {SAFETY.format(contact=contact)}]"
    if safety_earlier:   # no hints or suggestions after a safety concern
        return "[Private note: " + SAFETY_FOLLOWUP.format(contact=contact, helpline=config.HELPLINE_NAME,
                                                         number=config.HELPLINE_NUMBER) + "]"
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


def _effort(model: str, effort: str) -> str:
    """gpt-oss takes low/medium/high. qwen3 takes none/default, and with reasoning on it spent the
    token budget thinking and cut a reply off mid-sentence, so replies (effort "low") use "none"."""
    if model.startswith("qwen/"):
        return "none" if effort == "low" else "default"
    return effort


def complete(messages: list, model: str | None = None, max_tokens: int = 400,
             effort: str = "low", response_format: dict | None = None) -> str:
    from groq import BadRequestError, Groq, RateLimitError

    model = model or config.LLM_MODEL
    if not available(model):
        raise LLMUnavailable(f"{model} is rate-limited for {_cooldown[model] - time.monotonic():.0f}s more")
    client = Groq(api_key=config.GROQ_API_KEY)
    last_error = None
    for _attempt in range(MAX_ATTEMPTS):
        try:
            kwargs = {"response_format": response_format} if response_format else {}
            completion = client.chat.completions.create(
                model=model,
                # gpt-oss spends part of max_tokens on hidden reasoning before the visible reply;
                # keep headroom (~150 truncated replies). reasoning_effort=low keeps latency down.
                max_tokens=max_tokens,
                reasoning_effort=_effort(model, effort),
                messages=messages,
                **kwargs,
            )
            content = (completion.choices[0].message.content or "").strip()
            content = re.sub(r"<think>.*?(</think>|$)", "", content, flags=re.S).strip()  # qwen-style reasoning
            if content:
                return content
            last_error = RuntimeError("empty completion")  # all budget went to reasoning; retry
        except RateLimitError as exc:
            wait = _rate_limit_wait(exc)
            _last_problem[model] = (datetime.now().astimezone().isoformat(timespec="seconds"), str(exc)[:200])
            if wait is not None and wait >= COOLDOWN_MIN_S:
                _cooldown[model] = time.monotonic() + min(wait, COOLDOWN_MAX_S)
                logger.warning("%s rate-limited for %.0fs, using the next model", model, wait)
            raise
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
    mention = (f"In a short sentence of its own, mention this naturally (as something you're looking forward "
               f"to or curious about), from what you remember: {hook}." if hook else
               "You have nothing specific to bring up today, so don't mention any events, plans or "
               "observations (don't make any up).")
    instruction = (f"[Private note: Write your opening line for today's first chat. Greet them with "
                   f"'good {part}'. {mention} End with a separate, direct question asking how they are "
                   f"feeling today (don't join it to the other sentence with 'and'). Max 3 short sentences, "
                   f"in English.]")
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
    """Returns (text, model used). Asks the primary model; if it hasn't answered after
    LLM_HEDGE_DELAY_S, also asks the next one. The primary wins if it answers within
    LLM_PRIMARY_WAIT_S, otherwise the second model's answer is used. If both fail, the remaining
    models in the chain are tried one by one. Raises LLMUnavailable if nothing answers."""
    models = chain()
    if not models:
        raise LLMUnavailable("every reply model is rate-limited")
    primary, rest = models[0], models[1:]
    t0 = time.perf_counter()
    f_primary = _hedge_pool.submit(complete, messages, primary)
    try:
        return f_primary.result(timeout=min(config.LLM_HEDGE_DELAY_S, config.LLM_PRIMARY_WAIT_S)), primary
    except FutureTimeout:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("primary model %s failed (%s)", primary, str(exc)[:120])
        return _one_by_one(messages, rest)
    if not rest:
        return f_primary.result(timeout=30), primary
    second = rest[0]
    f_second = _hedge_pool.submit(complete, messages, second)
    try:
        wait = max(0.0, config.LLM_PRIMARY_WAIT_S - (time.perf_counter() - t0))
        return f_primary.result(timeout=wait), primary
    except FutureTimeout:
        logger.info("primary model slow (>%.1fs), using %s", config.LLM_PRIMARY_WAIT_S, second)
    except Exception as exc:  # noqa: BLE001
        logger.warning("primary model %s failed (%s), using %s", primary, str(exc)[:120], second)
    try:
        return f_second.result(timeout=30), second
    except Exception as exc:  # noqa: BLE001 -- second failed too: wait a little longer for the primary
        logger.warning("model %s failed (%s)", second, str(exc)[:120])
    if not f_primary.done() or f_primary.exception() is None:
        try:
            return f_primary.result(timeout=max(1.0, 30 - (time.perf_counter() - t0))), primary
        except Exception:  # noqa: BLE001
            pass
    return _one_by_one(messages, rest[1:])


def _one_by_one(messages: list, models: list) -> tuple[str, str]:
    for m in models:
        if not available(m):
            continue
        try:
            return complete(messages, model=m), m
        except Exception as exc:  # noqa: BLE001
            logger.warning("model %s failed (%s)", m, str(exc)[:120])
    raise LLMUnavailable("no reply model answered")


def reply(p: dict, memory_text: str, history: list, user_text: str, status: str, support: dict,
          hints: list, safety: bool, now: datetime, safety_earlier: bool = False,
          sensitive_open: bool = False) -> str:
    """history: earlier messages of THIS conversation as [{role, content}] (oldest first).
    support: from companion/plan.py support(); emotional notes only when it says so.
    safety_earlier: a message earlier in this conversation was flagged by the self-harm screen.
    sensitive_open: they brought up a sensitive topic in this conversation (profile.sensitive_opened)."""
    asked_last = bool(history) and history[-1]["role"] == "assistant" and "?" in history[-1]["content"]
    note = _note(support, status, hints, safety, p, asked_last, safety_earlier)
    messages = [{"role": "system", "content": system_prompt(p, memory_text, now, sensitive_open)}, *history,
                {"role": "user", "content": f"{note}\n{user_text}"}]
    try:
        text, model = hedged(messages)
        logger.info("reply from %s", model)
        return tidy(text)
    except Exception as exc:  # noqa: BLE001 -- a reply is best-effort; never fail the conversation
        logger.warning("LLM reply failed, telling the user: %s", exc)
        return UNAVAILABLE_REPLY
