"""Stage-1 fix to the review flags in confidence.py (audit finding CORE-09).

The speech-rate flags counted a run of letters as one word, so Chinese and
Japanese, written without spaces, looked like near-silence. Han characters
and kana now count one unit each, scripts with no validated unit are not
rate-flagged (and counted), and text in scripts that use spaces, English
among them, is flagged exactly as before.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import confidence  # noqa: E402

_OLD_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def _old_flags(segments):
    """The flags as the pre-fix implementation computed them."""
    out = []
    previous = None
    for index, seg in enumerate(segments):
        tokens = [t.lower() for t in _OLD_WORD_RE.findall(seg.get("text") or "")]
        norm = " ".join(tokens)
        flags = []
        if not tokens:
            flags.append("empty")
        if norm and norm == previous:
            flags.append("duplicate_of_previous")
        if (confidence._max_immediate_repeat(tokens) >= 3
                or confidence._max_phrase_repeat(tokens) >= 3):
            flags.append("internal_repetition")
        start, end = seg.get("start"), seg.get("end")
        rate = None
        if start is not None and end is not None:
            duration = float(end) - float(start)
            if duration > 0:
                rate = len(tokens) / duration
                if duration >= 2.5 and rate < 0.5:
                    flags.append("low_speech_rate")
                elif rate > 7.0:
                    flags.append("high_speech_rate")
        previous = norm or previous
        if flags:
            out.append((index, len(tokens),
                        round(rate, 2) if rate is not None else None, flags))
    return out


def _new_flags(segments):
    return [(r["index"], r["words"], r["speech_rate"], r["flags"])
            for r in confidence.flag_segments(segments)]


# ---------------------------------------------------------------------------
# The reported false positives
# ---------------------------------------------------------------------------

def test_ordinary_mandarin_and_japanese_are_not_low_rate():
    segments = [
        {"start": 0, "end": 5, "text": "我们今天讨论这个问题，然后我们看看结果。"},
        {"start": 5, "end": 9, "text": "私たちは今日この問題について話し合います"},
    ]
    assert confidence.flag_segments(segments) == []


def test_near_silent_chinese_segment_is_still_low_rate():
    segments = [{"start": 0, "end": 6, "text": "嗯"}]
    [record] = confidence.flag_segments(segments)
    assert record["flags"] == ["low_speech_rate"]


def test_implausibly_fast_chinese_is_high_rate():
    segments = [{"start": 0, "end": 1, "text": "我们今天讨论这个问题然后我们看看结果"}]
    [record] = confidence.flag_segments(segments)
    assert record["flags"] == ["high_speech_rate"]


def test_mixed_script_segment_uses_both_bounds():
    # 3 words at 7/s need 0.43 s and 7 characters at 14/s need 0.5 s,
    # 0.93 s in all: within 1 s, too much for 0.8 s.
    text = "the AI model 我们今天讨论这"
    assert confidence.flag_segments([{"start": 0, "end": 1.0, "text": text}]) == []
    [record] = confidence.flag_segments([{"start": 0, "end": 0.8, "text": text}])
    assert record["flags"] == ["high_speech_rate"]


def test_devanagari_words_are_not_split_at_vowel_signs():
    assert confidence._tokens("नमस्ते दुनिया") == ["नमस्ते", "दुनिया"]


def test_thai_is_not_rate_flagged_and_the_skip_is_counted():
    segments = [{"start": 0, "end": 6, "text": "สวัสดีครับ"},
                {"start": 6, "end": 7, "text": "hello there"}]
    assert confidence.flag_segments(segments) == []
    report = confidence.review_transcript({"segments": segments})
    assert report["summary"]["rate_flags_skipped"] == 1


# ---------------------------------------------------------------------------
# English and other spaced scripts are unchanged
# ---------------------------------------------------------------------------

def _example_segments():
    segments = []
    for path in sorted((PROJECT_ROOT / "example_output" / "variants").glob(
            "*/example_transcript.json")):
        segments.extend(json.loads(path.read_text(encoding="utf-8"))
                        .get("segments") or [])
    return segments


def test_example_transcripts_flag_exactly_as_before():
    segments = _example_segments()
    if not segments:
        pytest.skip("no example transcripts with segments")
    assert _new_flags(segments) == _old_flags(segments)


def test_case_study_tokens_and_rates_are_unchanged():
    """Every flag is a function of a segment's tokens, its rate units and
    its timing. On the case-study text the tokens are the old tokens and
    the units are the tokens, so every segment's flags are unchanged."""
    text = (PROJECT_ROOT / "output" / "case_study" / "ep05_raw_text.txt"
            ).read_text(encoding="utf-8")
    old = [t.lower() for t in _OLD_WORD_RE.findall(text)]
    new = confidence._tokens(text)
    assert new == old
    assert confidence._rate_units(new) == (len(new), 0, False)


def test_case_study_flagged_segments_are_reproduced():
    review = json.loads((PROJECT_ROOT / "output" / "case_study"
                         / "codex_mentis_ep05_review.json"
                         ).read_text(encoding="utf-8"))
    # Flagged alone, a cue cannot meet its repeated passage's partner, so
    # that flag is left to tests/test_case_study_results.py; the other
    # flags come back with the zero-duration setting the review recorded.
    zero = review["optional_checks"]["flag_zero_duration"]
    for record in review["flagged"]:
        expected = [f for f in record["flags"] if f != "repeated_passage"]
        records = confidence.flag_segments([record], flag_zero_duration=zero)
        assert [r["flags"] for r in records] == ([expected] if expected else [])
        for again in records:
            assert again["speech_rate"] == record["speech_rate"]
            assert again["words"] == record["words"]


@pytest.mark.parametrize("text", [
    "Ceci est une phrase française ordinaire.",
    "Это обычное русское предложение.",
    "이것은 평범한 한국어 문장입니다.",
])
def test_spaced_scripts_count_words(text):
    tokens = confidence._tokens(text)
    assert confidence._rate_units(tokens) == (len(tokens), 0, False)
    assert tokens == [t.lower() for t in _OLD_WORD_RE.findall(text)]


def test_token_rule_matches_the_old_regex_for_every_letter():
    """Outside combining marks, _tokens agrees with [^\\W\\d_]+."""
    sample = "".join(chr(c) for c in range(0x20, 0x3000)
                     if not chr(c).isspace())
    import unicodedata
    no_marks = "".join(ch for ch in sample
                       if unicodedata.category(ch)[0] != "M")
    assert confidence._tokens(no_marks) == \
        [t.lower() for t in _OLD_WORD_RE.findall(no_marks)]
