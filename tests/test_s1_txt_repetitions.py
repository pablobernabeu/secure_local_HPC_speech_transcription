"""Stage-1 fix to detect_and_fix_repetitions (audit finding T1-05).

The phrase count was twice the copies plus one, so every loop the
pattern saw was cut at five copies, and it was case-sensitive, so a
loop with a capitalised first copy was never cut. Phrases are now cut
above PHRASE_REPETITION_LENIENCY x max_repetitions copies, counted
without regard to case.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# T1-05: detect_and_fix_repetitions
# ---------------------------------------------------------------------------

def test_phrase_repeated_five_times_is_kept(transcription_module):
    text = "thank you " * 5 + "so much"
    assert transcription_module.detect_and_fix_repetitions(text) == text.strip()


def test_phrase_repeated_ten_times_is_kept(transcription_module):
    text = "thank you " * 10 + "so much"
    assert transcription_module.detect_and_fix_repetitions(text) == text.strip()


def test_phrase_repeated_eleven_times_is_cut(transcription_module):
    out = transcription_module.detect_and_fix_repetitions(
        "thank you " * 11 + "so much")
    assert out == "thank you [...] so much"


def test_capitalised_first_copy_is_counted(transcription_module):
    out = transcription_module.detect_and_fix_repetitions(
        "Okay so " + "okay so " * 11 + "end")
    assert out == "Okay so [...] end"


def test_threshold_scales_with_max_repetitions(transcription_module):
    m = transcription_module
    text = "you know " * 7 + "right"
    assert m.detect_and_fix_repetitions(text, max_repetitions=3) == \
        "you know [...] right"
    assert m.PHRASE_REPETITION_LENIENCY * 3 < 7


def test_sentence_loop_thresholds_are_named(transcription_module):
    m = transcription_module
    assert m.detect_and_fix_repetitions("Yes. " * 6 + "No.") == "Yes. No."
    assert m.detect_and_fix_repetitions("Yes. " * 11 + "No.") == "Yes. [...] No."
    assert m.SENTENCE_LOOP_MARKER_ABOVE == 10


def test_twelve_fold_loop_is_still_cut(transcription_module):
    text = ("the quick brown fox " * 12).strip()
    assert transcription_module.detect_and_fix_repetitions(text) == \
        "the quick brown fox [...]"
