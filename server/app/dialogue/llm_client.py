"""Emotion-aware, multi-turn conversational response generation. The LLM provider is
isolated behind _call_llm() so it can be swapped without touching the prompt-building logic."""

import os

SYSTEM_PROMPT = (
    "You are a warm, caring companion having an ongoing spoken conversation with an elderly "
    "person checking in on how they're doing. Keep replies short (1-3 sentences), natural, and "
    "spoken-friendly -- this is a voice conversation, not a chat message. Respond to what they "
    "actually said, referencing earlier parts of the conversation when relevant, the way a "
    "real ongoing conversation would. You're quietly told how their voice sounds emotionally "
    "each turn -- let it shape your tone, but never name the emotion label itself or say "
    "things like 'I can hear you are sad'. Ask a gentle follow-up question sometimes instead of "
    "just consoling, the way a real conversation partner would."
)

MODEL_ID = "openai/gpt-oss-20b"
MAX_ATTEMPTS = 3
FALLBACK_RESPONSE = "Sorry, I got a bit distracted there -- could you tell me that again?"


def _call_llm(conversation_history: list, user_text: str, emotion_label: str) -> str:
    from groq import Groq, BadRequestError

    client = Groq(api_key=os.environ["GROQ_API_KEY"])

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in conversation_history:
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append(
        {
            "role": "user",
            "content": f"[Their voice currently sounds: {emotion_label}]\n{user_text}",
        }
    )

    last_error = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            completion = client.chat.completions.create(
                model=MODEL_ID,
                # gpt-oss models spend a chunk of the token budget on hidden reasoning before
                # the visible reply, so max_tokens needs headroom well beyond the short reply
                # length itself.
                max_tokens=400,
                messages=messages,
            )
            return completion.choices[0].message.content
        except BadRequestError as exc:
            # Known intermittent Groq/gpt-oss bug: the model occasionally emits a spurious
            # tool-call-formatted response even though no `tools` were passed in this request
            # at all. It's not caused by anything in our prompt and isn't consistently
            # reproducible, so the documented workaround is just to retry.
            body = getattr(exc, "body", None) or {}
            code = (body.get("error") or {}).get("code") if isinstance(body, dict) else None
            if code == "tool_use_failed" and attempt < MAX_ATTEMPTS - 1:
                last_error = exc
                continue
            raise

    raise last_error


def generate_response(
    user_text: str, emotion_label: str, conversation_history: list = None
) -> str:
    try:
        return _call_llm(conversation_history or [], user_text, emotion_label)
    except Exception:
        # A conversational reply is best-effort -- if the LLM provider is having a bad moment,
        # degrade to a generic prompt-to-repeat rather than 500ing the whole check-in (the user
        # still gets emotion detection + a spoken response, just not a contextual one this turn).
        return FALLBACK_RESPONSE
