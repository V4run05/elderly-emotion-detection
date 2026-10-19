from app.analysis import masking, safety


def test_reassurance_phrases_found():
    assert masking.find_reassurance("I'm fine, nothing to worry about.") == [
        "I'm fine", "nothing to worry about"]
    assert masking.find_reassurance("Can't complain. Don’t worry about me.")  # curly apostrophe
    assert masking.find_reassurance("I'm not fine at all") == []


def test_says_fine_seems_low_is_masked():
    # fixed line until the personal baseline is ready: -0.55 (config.LOW_NONVERBAL_THRESHOLD)
    assert masking.classify(0.7, -0.6, reassurance=True) == "masked"
    assert masking.classify(0.4, -0.6, reassurance=False) == "masked"
    assert masking.classify(0.6, -0.34, reassurance=True) == "ok"   # the voice model's usual neutral


def test_reassurance_counts_as_saying_ok_even_with_neutral_words():
    assert masking.classify(0.0, -0.6, reassurance=True) == "masked"
    assert masking.classify(0.0, -0.6, reassurance=False) == "low"


def test_openly_low_is_low_not_masked():
    assert masking.classify(-0.8, -0.5, reassurance=False) == "low"
    assert masking.classify(-0.5, 0.1, reassurance=False) == "low"


def test_congruent_positive_is_ok():
    assert masking.classify(0.8, 0.4, reassurance=True) == "ok"
    assert masking.classify(0.3, -0.4, reassurance=False) == "ok"  # not low enough


def test_small_gap_is_not_masked():
    # says mildly OK (0.15) and seems low on a personal scale (-0.2, line -0.15): gap 0.35 < 0.5
    assert masking.classify(0.15, -0.2, reassurance=False, low_threshold=-0.15) == "low"


def test_masking_score_range_and_gating():
    assert masking.masking_score(1.0, -1.0, True) == 1.0
    assert masking.masking_score(-0.5, -0.9, False) == 0.0  # not presenting as OK
    assert 0.0 < masking.masking_score(0.6, -0.4, False) < 1.0


def test_safety_screen():
    assert safety.is_safety_concern("Sometimes I just want to die")
    assert safety.is_safety_concern("they'd be better off without me")
    assert not safety.is_safety_concern("I'm dying to see my grandchildren")
    assert not safety.is_safety_concern("I'm fine, just tired")
