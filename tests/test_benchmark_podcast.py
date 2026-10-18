"""Unit tests for ``evaluation.benchmark_podcast``.

The scorer is reference-free and pure, so these tests pin each metric on a
small hand-built transcript and then smoke-test the whole analysis on the
committed word-timestamped, diarised example transcript.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.benchmark_podcast import (  # noqa: E402
    analyse,
    diarisation_metrics,
    masking_metrics,
    repetition_metrics,
    timestamp_metrics,
)


def _seg(start, end, text, speaker=None, words=None):
    seg = {"start": start, "end": end, "text": text}
    if speaker:
        seg["speaker"] = speaker
    if words is not None:
        seg["words"] = words
    return seg


def test_timestamp_metrics_flags_backward_jump():
    good = {"segments": [_seg(0.0, 1.0, "a b", words=[
        {"text": "a", "start": 0.0, "end": 0.4},
        {"text": "b", "start": 0.5, "end": 0.9},
    ])]}
    assert timestamp_metrics(good)["monotonicity_violations"] == 0

    bad = {"segments": [_seg(0.0, 1.0, "a b", words=[
        {"text": "a", "start": 0.5, "end": 0.9},
        {"text": "b", "start": 0.1, "end": 0.3},  # starts before previous word
    ])]}
    assert timestamp_metrics(bad)["monotonicity_violations"] >= 1


def test_timestamp_coverage_and_gaps():
    """speech_s is the union of the words; segment_span_s that of the
    segments, which include the pauses inside them (EPRIV-32)."""
    t = {"segments": [
        _seg(0.0, 4.0, "x x", words=[{"text": "x", "start": 0.0, "end": 1.0},
                                     {"text": "x", "start": 2.0, "end": 4.0}]),
        _seg(5.0, 9.0, "y", words=[{"text": "y", "start": 5.0, "end": 8.0}]),
    ]}
    m = timestamp_metrics(t, audio_duration_s=10.0)
    assert m["speech_s"] == pytest.approx(6.0)          # pause 1.0-2.0 excluded
    assert m["segment_span_s"] == pytest.approx(8.0)
    assert m["coverage_ratio"] == pytest.approx(0.6)
    assert m["segment_coverage_ratio"] == pytest.approx(0.8)
    assert m["max_gap_s"] == pytest.approx(1.0)   # gap between 4.0 and 5.0
    assert m["n_overlaps"] == 0
    assert m["end_drift_s"] == pytest.approx(1.0)  # 10.0 - 9.0


def test_diarisation_counts_speakers_and_turns():
    t = {"segments": [
        _seg(0.0, 1.0, "a", speaker="SPEAKER_00"),
        _seg(1.0, 2.0, "b", speaker="SPEAKER_01"),
        _seg(2.0, 3.0, "c", speaker="SPEAKER_00"),
    ]}
    m = diarisation_metrics(t, expected_speakers=2)
    assert m["has_speakers"] is True
    assert m["n_speakers"] == 2
    assert m["speaker_count_error"] == 0
    assert m["n_turns"] == 3
    assert m["talk_time_s"] == {"SPEAKER_00": 2.0, "SPEAKER_01": 1.0}


def test_diarisation_absent_labels():
    assert diarisation_metrics({"segments": [_seg(0.0, 1.0, "a")]}) == \
        {"has_speakers": False}


def test_masking_rate_uses_injected_masker():
    t = {"text": "I met Ahmed and Ahmed left"}
    stub = lambda s: s.replace("Ahmed", "[NAME]")  # noqa: E731
    m = masking_metrics(t, stub)
    assert m["n_tokens"] == 6
    assert m["n_redacted"] == 2
    assert m["redaction_rate"] == pytest.approx(2 / 6, abs=1e-4)


def test_repetition_detects_run():
    assert repetition_metrics({"text": "the the the end"})["max_immediate_repeat"] == 3
    assert repetition_metrics({"text": "no repeats here"})["max_immediate_repeat"] == 1


def test_analyse_on_committed_example():
    example = (PROJECT_ROOT / "example_output" / "variants"
               / "04_diarisation_and_timestamps" / "example_transcript.json")
    transcript = json.loads(example.read_text(encoding="utf-8"))
    rec = analyse(transcript, mask_fn=lambda s: s, audio_duration_s=None)
    assert rec["timestamps"]["n_words"] > 0
    assert rec["timestamps"]["monotonicity_violations"] == 0   # a clean example
    assert rec["diarisation"]["has_speakers"] is True
    assert rec["diarisation"]["n_speakers"] == 2
    assert rec["masking"]["n_tokens"] > 0
    assert rec["repetition"]["max_immediate_repeat"] >= 1
