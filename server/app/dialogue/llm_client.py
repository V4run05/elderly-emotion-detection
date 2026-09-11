"""Emotion-conditioned response generation. The LLM provider is isolated behind
_call_llm() so it can be swapped without touching the prompt-building logic."""

import os

SYSTEM_PROMPT = (
    "You are a warm, caring companion checking in on an elderly person. "
    "Keep responses short (2-3 sentences), spoken-friendly, and empathetic. "
    "Respond naturally to how they sound, without naming the emotion label itself."
)


def _build_prompt(emotion_label: str, mood_history: list = None) -> str:
    lines = [f"The person's voice currently sounds: {emotion_label}."]
    if mood_history:
        recent = ", ".join(
            f"{row['emotion_label']} ({row['timestamp']})" for row in mood_history
        )
        lines.append(f"Their recent check-in history: {recent}.")
    lines.append("Respond with a brief, empathetic spoken message for them.")
    return "\n".join(lines)


def _call_llm(system_prompt: str, user_prompt: str) -> str:
    from groq import Groq

    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    completion = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        # gpt-oss models spend a chunk of the token budget on hidden reasoning before the
        # visible reply, so max_tokens needs headroom well beyond the short reply length itself.
        max_tokens=400,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return completion.choices[0].message.content


def generate_response(emotion_label: str, mood_history: list = None) -> str:
    prompt = _build_prompt(emotion_label, mood_history)
    return _call_llm(SYSTEM_PROMPT, prompt)
