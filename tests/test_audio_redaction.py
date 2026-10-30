"""Unit tests for ``audio_redaction``.

The redaction core is pure signal processing plus a span finder driven by
an injected masking function, so these tests run with only numpy and the
standard library. They pin: span silencing and bleeping leave the rest of
the waveform untouched, overlapping spans merge, the span finder redacts
exactly the words the masker flags (and skips words without timestamps),
and the stdlib WAV round-trip preserves the signal.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from audio_redaction import (
    find_name_spans,
    read_wav,
    redact_spans,
    redacted_duration,
    word_text,
    write_wav,
    _merge_spans,
)


def test_redact_spans_silence_zeros_only_the_span():
    sr = 100
    audio = np.ones(300, dtype=np.float32)
    out = redact_spans(audio, sr, [(1.0, 2.0)], mode="silence", pad_s=0.0)
    assert np.all(out[100:200] == 0.0)
    assert np.all(out[:100] == 1.0)
    assert np.all(out[200:] == 1.0)
    # The input array is not mutated.
    assert np.all(audio == 1.0)


def test_redact_spans_bleep_writes_a_tone():
    sr = 1000
    audio = np.ones(3000, dtype=np.float32)
    out = redact_spans(audio, sr, [(1.0, 2.0)], mode="bleep", pad_s=0.0,
                       bleep_hz=100.0, bleep_amp=0.3)
    region = out[1000:2000]
    assert np.all(np.abs(region) <= 0.3 + 1e-6)
    assert not np.allclose(region, 1.0)      # it was overwritten
    assert np.abs(region.mean()) < 0.05      # a sine averages to ~0
    assert np.all(out[:1000] == 1.0) and np.all(out[2000:] == 1.0)


def test_merge_and_duration():
    assert _merge_spans([(1.0, 2.0), (1.5, 3.0)]) == [(1.0, 3.0)]
    assert _merge_spans([(4.0, 5.0), (1.0, 2.0)]) == [(1.0, 2.0), (4.0, 5.0)]
    assert redacted_duration([(1.0, 2.0), (1.5, 3.0)]) == pytest.approx(2.0)
    assert redacted_duration([(1.0, 2.0), (4.0, 5.0)]) == pytest.approx(2.0)


def test_find_name_spans_redacts_flagged_words_only():
    transcript = {
        "segments": [
            {"words": [
                {"text": "Hello", "start": 0.0, "end": 0.5},
                {"text": "Ahmed", "start": 0.5, "end": 1.0},
                {"text": "there", "start": 1.0, "end": 1.3},
                {"text": "NoTime"},                      # skipped: no times
            ]},
            {"text": "a segment with no word timestamps"},  # skipped
        ]
    }
    stub = lambda t: "[NAME]" if t == "Ahmed" else t  # noqa: E731
    spans = find_name_spans(transcript, stub)
    assert spans == [(0.5, 1.0)]


def test_find_name_spans_detects_surname_placeholder():
    """Surname redaction ([SURNAME]) is picked up, not just [NAME]."""
    transcript = {"segments": [{"words": [
        {"text": "met", "start": 0.0, "end": 0.3},
        {"text": "Bernabeu", "start": 0.3, "end": 0.9},
    ]}]}
    stub = lambda t: "[SURNAME]" if t == "Bernabeu" else t  # noqa: E731
    assert find_name_spans(transcript, stub) == [(0.3, 0.9)]


def test_find_name_spans_on_committed_example_runs():
    """The span finder consumes the shipped word-timestamped transcript."""
    example = (PROJECT_ROOT / "example_output" / "variants" / "02_timestamps"
               / "example_transcript.json")
    transcript = json.loads(example.read_text(encoding="utf-8"))
    # The pipeline stores word text under "word"; word_text reads either key.
    first_word = word_text(transcript["segments"][0]["words"][0])
    # A stub that redacts the first spoken word must yield a span at t=0.
    stub = lambda t: "[NAME]" if t == first_word else t  # noqa: E731
    spans = find_name_spans(transcript, stub)
    assert spans and spans[0][0] == pytest.approx(
        transcript["segments"][0]["words"][0]["start"])


def test_wav_roundtrip(tmp_path):
    sr = 16000
    audio = np.linspace(-0.5, 0.5, 2000, dtype=np.float32)
    path = tmp_path / "tone.wav"
    write_wav(path, audio, sr)
    back, sr_back = read_wav(path)
    assert sr_back == sr
    assert len(back) == len(audio)
    assert np.max(np.abs(back - audio)) < 1e-3   # 16-bit quantisation
