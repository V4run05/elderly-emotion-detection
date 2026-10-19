from app.dialogue import stt, tts


def test_hallucinations_dropped_only_on_quiet_clips():
    assert stt.clean(" you ", quiet=True) == ""
    assert stt.clean("Thank you.", quiet=True) == ""
    assert stt.clean("Thank you.", quiet=False) == "Thank you."   # a real spoken thanks is kept
    assert stt.clean("Okay.", quiet=True) == "Okay."              # short real answers are kept
    assert stt.clean("...", quiet=False) == ""


def test_tts_chunks_respect_limit_and_keep_all_words():
    text = ("It's okay to have days like that. " * 8 + "How did you sleep? "
            + "word " * 60).strip()
    chunks = tts._chunks(text, 200)
    assert all(len(c) <= 200 for c in chunks)
    assert " ".join(chunks).split() == text.split()


def test_hedged_uses_fast_model_when_primary_is_slow(monkeypatch):
    import time as _time
    from app import config
    from app.dialogue import llm
    monkeypatch.setattr(config, "LLM_PRIMARY_WAIT_S", 0.2)

    def fake(messages, model=None, **kwargs):
        if model == config.LLM_MODEL:
            _time.sleep(0.6)
            return "slow but good"
        return "fast"
    monkeypatch.setattr(llm, "complete", fake)
    assert llm.hedged([]) == ("fast", config.LLM_FAST_MODEL)
    monkeypatch.setattr(config, "LLM_PRIMARY_WAIT_S", 2.0)
    assert llm.hedged([]) == ("slow but good", config.LLM_MODEL)



def test_tidy_removes_dashes_and_markdown():
    from app.dialogue.llm import tidy
    assert tidy("That's okay\u2014sometimes it slips the mind.") == "That's okay, sometimes it slips the mind."
    assert tidy("Good afternoon \u2013 how are you?") == "Good afternoon, how are you?"
    assert tidy("I'm thinking about lemon rice; it still smells like sunshine.") == \
        "I'm thinking about lemon rice. It still smells like sunshine."
    assert tidy("A well-known song - very nice.") == "A well-known song, very nice."
    assert tidy("I **love** that\n\n*really*") == "I love that really"
    assert "\u2014" not in tidy("a\u2014b\u2014c")
    assert tidy("Did you see the roses again?I'm glad.") == "Did you see the roses again? I'm glad."
    assert tidy("One. Two. Three. Four. Five. Six.") == "One. Two. Three."
    # a closing question survives the cap, so a long answer can continue
    assert tidy("A. B. C. D. E. Shall I go on?") == "A. B. Shall I go on?"
    # list numbering is removed, not counted as sentences
    assert tidy("1. Wash the dal. 2. Chop the onions. 3. Heat the oil.") == "Wash the dal. Chop the onions. Heat the oil."


def test_note_only_mentions_feelings_when_support_is_needed():
    from app.companion import profile
    from app.dialogue import llm
    p = profile.normalize({})
    plain = llm._note({"mode": None, "suggest": False}, "low", [], False, p)
    assert "chatting naturally" in plain and "low" not in plain
    care = llm._note({"mode": "daily", "suggest": True}, "masked", [], False, p)
    assert "voice and face seem low" in care


def test_tidy_word_limit_cuts_only_between_sentences():
    from app.dialogue.llm import tidy
    long_sentence = " ".join(["word"] * 90) + "."
    assert tidy(long_sentence) == long_sentence                     # one long sentence is kept whole
    two = "A " + " ".join(["a"] * 49) + ". B " + " ".join(["b"] * 39) + ". Want the rest?"
    assert tidy(two) == "A " + " ".join(["a"] * 49) + ". Want the rest?"   # 2nd sentence would pass 75 words
