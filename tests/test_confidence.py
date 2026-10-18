"""Tests for the transcript review flags.

Each flag is paired with the failure it targets and with a negative case,
because a flag that fires on ordinary speech is worse than no flag at all:
it trains the reader to ignore it. The fixtures are therefore built to
include plausible normal segments alongside the pathological ones.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from confidence import (  # noqa: E402
    _max_immediate_repeat,
    _tokens,
    flag_segments,
    review_transcript,
    summarise,
)


def _seg(start, end, text):
    return {"start": start, "end": end, "text": text}


def _flags_for(segments):
    return {r["index"]: set(r["flags"]) for r in flag_segments(segments)}


def test_ordinary_speech_is_not_flagged():
    """The negative case: normal segments must stay silent."""
    segments = [
        _seg(0.0, 3.0, "Thank you for joining us today."),
        _seg(3.0, 7.0, "Could you describe the main privacy considerations?"),
        _seg(7.0, 10.0, "Certainly, the fundamental concern is disclosure."),
    ]
    assert flag_segments(segments) == []


def test_duplicate_segment_is_flagged():
    segments = [
        _seg(0.0, 2.0, "The study was approved."),
        _seg(2.0, 4.0, "The study was approved."),      # verbatim repeat
    ]
    assert "duplicate_of_previous" in _flags_for(segments)[1]


def test_duplicate_detection_ignores_punctuation_and_case():
    segments = [
        _seg(0.0, 2.0, "The study was approved."),
        _seg(2.0, 4.0, "the study was approved"),
    ]
    assert "duplicate_of_previous" in _flags_for(segments)[1]


def test_internal_repetition_is_flagged_for_single_tokens():
    looped = [_seg(0.0, 4.0, "the the the the cat sat")]
    assert "internal_repetition" in _flags_for(looped)[0]


def test_internal_repetition_is_flagged_for_repeated_phrases():
    """The commoner loop repeats a phrase, not a single word."""
    segments = [_seg(0.0, 5.0, "and then and then and then it stopped")]
    assert "internal_repetition" in _flags_for(segments)[0]
    longer = [_seg(0.0, 6.0, "thanks for watching thanks for watching thanks for watching")]
    assert "internal_repetition" in _flags_for(longer)[0]


def test_a_phrase_said_twice_is_not_a_loop():
    """Ordinary emphasis repeats a phrase once; a loop repeats it on."""
    segments = [_seg(0.0, 4.0, "very good very good indeed")]
    assert flag_segments(segments) == []


def test_two_adjacent_words_are_not_a_loop():
    """A doubled word is ordinary speech; three or more is a loop."""
    segments = [_seg(0.0, 3.0, "it was was quite good")]
    assert flag_segments(segments) == []


def test_long_near_wordless_segment_is_flagged():
    """The signature of decoding over silence or music."""
    segments = [_seg(0.0, 12.0, "Thank you.")]
    assert "low_speech_rate" in _flags_for(segments)[0]


def test_short_segment_with_few_words_is_not_flagged():
    """A brief interjection is normal and must not trip the rate flag."""
    segments = [_seg(0.0, 0.8, "Yes.")]
    assert flag_segments(segments) == []


def test_implausibly_fast_segment_is_flagged():
    segments = [_seg(0.0, 1.0, "one two three four five six seven eight nine ten")]
    assert "high_speech_rate" in _flags_for(segments)[0]


def test_empty_segment_is_flagged():
    assert "empty" in _flags_for([_seg(0.0, 2.0, "   ...  ")])[0]


def test_segments_without_timings_skip_rate_flags_only():
    """Missing timings must not crash, and must not fabricate a rate."""
    segments = [{"text": "the the the cat"}]
    records = flag_segments(segments)
    assert records and records[0]["speech_rate"] is None
    assert "internal_repetition" in records[0]["flags"]
    assert "low_speech_rate" not in records[0]["flags"]


def test_summary_counts_and_rate():
    segments = [
        _seg(0.0, 3.0, "A perfectly ordinary sentence here."),
        _seg(3.0, 15.0, "Thank you."),                    # low_speech_rate
        _seg(15.0, 17.0, "the the the the"),              # internal_repetition
    ]
    flagged = flag_segments(segments)
    s = summarise(segments, flagged)
    assert s["segments"] == 3
    assert s["flagged"] == 2
    assert s["flag_rate"] == round(2 / 3, 4)
    assert s["counts_by_flag"]["low_speech_rate"] == 1
    assert s["counts_by_flag"]["internal_repetition"] == 1
    # The summary states plainly that this is not model confidence.
    assert "heuristic" in s["signal"]


def test_review_transcript_end_to_end():
    transcript = {"segments": [
        _seg(0.0, 3.0, "An ordinary opening sentence."),
        _seg(3.0, 20.0, "Thank you."),
    ]}
    report = review_transcript(transcript)
    assert report["summary"]["flagged"] == 1
    assert report["flagged"][0]["index"] == 1
    assert report["flagged"][0]["words"] == 2


def test_review_handles_a_transcript_with_no_segments():
    report = review_transcript({"text": "no segments here"})
    assert report["summary"]["segments"] == 0
    assert report["summary"]["flag_rate"] == 0.0
    assert report["flagged"] == []


class TestTruncationCheck:
    """Early truncation is the dominant boundary failure the timestamp
    benchmark found on AMI, and no per-segment flag can see it: each
    surviving segment looks fine, and the transcript simply stops. The
    check is therefore against the recording's duration.
    """

    def _segments(self, last_end):
        return [_seg(0.0, 5.0, "opening words here"),
                _seg(5.0, last_end, "and the closing words")]

    def test_complete_transcript_is_not_flagged(self):
        from confidence import truncation_check
        result = truncation_check(self._segments(60.0), audio_duration_s=61.0)
        assert result["checked"] is True
        assert result["truncated"] is False

    def test_transcript_stopping_early_is_flagged(self):
        from confidence import truncation_check
        result = truncation_check(self._segments(20.0), audio_duration_s=60.0)
        assert result["truncated"] is True
        assert result["shortfall_s"] == pytest.approx(40.0)
        assert result["shortfall_fraction"] == pytest.approx(40.0 / 60.0, abs=1e-3)

    def test_trailing_silence_is_tolerated(self):
        """A recording ending on a pause must not be called truncated."""
        from confidence import truncation_check
        result = truncation_check(self._segments(59.0), audio_duration_s=60.0)
        assert result["truncated"] is False

    def test_unknown_duration_declines_rather_than_guesses(self):
        from confidence import truncation_check
        assert truncation_check(self._segments(20.0))["checked"] is False
        assert truncation_check(self._segments(20.0), 0)["checked"] is False

    def test_no_segments_declines(self):
        from confidence import truncation_check
        assert truncation_check([], audio_duration_s=60.0)["checked"] is False

    def test_review_transcript_carries_the_check(self):
        transcript = {"segments": self._segments(20.0)}
        report = review_transcript(transcript, audio_duration_s=60.0)
        assert report["truncation"]["truncated"] is True
        # And stays well-formed when the duration is unknown.
        assert review_transcript(transcript)["truncation"]["checked"] is False


def test_token_and_repeat_helpers():
    assert _tokens("Hello, world! 42 times") == ["hello", "world", "times"]
    assert _max_immediate_repeat(["a", "a", "a"]) == 3
    assert _max_immediate_repeat(["a", "b", "a"]) == 1
    assert _max_immediate_repeat([]) == 0


def test_thresholds_are_adjustable():
    segments = [_seg(0.0, 4.0, "the the cat")]
    assert flag_segments(segments) == []                       # default run of 3
    assert "internal_repetition" in _flags_for_with(segments, repeat_run=2)[0]


def _flags_for_with(segments, **kwargs):
    return {r["index"]: set(r["flags"]) for r in flag_segments(segments, **kwargs)}
