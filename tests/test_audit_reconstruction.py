"""Tests for the reconstruction audit.

The audit's job is to notice when reconstructed audio does not sit where
its reference says it does. Its own correctness is therefore checked by
building signals whose alignment is known, including a deliberately
displaced one: an audit that reported everything as fine would be worse
than no audit, because the benchmark's central premise would then look
verified when it was not.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.audit_reconstruction import (
    audit_meeting,
    energy_envelope,
    reference_mask,
)

SR = 16_000


def _tone(duration_s, amplitude=0.5):
    t = np.arange(int(duration_s * SR)) / SR
    return (amplitude * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def _build(spans, total_s, shift_s=0.0):
    """Audio carrying a tone over each span, optionally displaced."""
    audio = np.zeros(int(total_s * SR), dtype=np.float32)
    for start, end in spans:
        a = int(round((start + shift_s) * SR))
        b = int(round((end + shift_s) * SR))
        a, b = max(0, a), min(audio.size, b)
        if b > a:
            audio[a:b] = _tone((b - a) / SR)
    return audio


def _reference(spans, speaker="A"):
    return [{"start": s, "end": e, "speaker": speaker} for s, e in spans]


class TestEnergyEnvelope:
    def test_frame_count_follows_the_frame_length(self):
        rms = energy_envelope(np.zeros(SR, dtype=np.float32), SR, frame_s=0.01)
        assert rms.size == 100

    def test_silence_has_no_energy_and_a_tone_does(self):
        assert float(energy_envelope(np.zeros(SR, np.float32), SR).max()) == 0.0
        assert float(energy_envelope(_tone(1.0), SR).min()) > 0.0

    def test_audio_shorter_than_a_frame_returns_nothing(self):
        assert energy_envelope(np.zeros(5, np.float32), SR).size == 0


class TestReferenceMask:
    def test_marks_only_the_annotated_frames(self):
        mask = reference_mask(_reference([(1.0, 2.0)]), n_frames=300)
        assert not mask[:100].any()
        assert mask[100:200].all()
        assert not mask[200:].any()

    def test_spans_past_the_end_are_clipped_rather_than_raising(self):
        mask = reference_mask(_reference([(0.5, 99.0)]), n_frames=100)
        assert mask[50:].all()

    def test_overlapping_spans_merge(self):
        mask = reference_mask(
            [{"start": 0.0, "end": 1.0, "speaker": "A"},
             {"start": 0.5, "end": 1.5, "speaker": "B"}], n_frames=200)
        assert mask[:150].all()
        assert not mask[150:].any()


class TestAuditMeeting:
    def test_aligned_audio_scores_high_and_reports_no_shift(self):
        spans = [(1.0, 3.0), (5.0, 8.0)]
        audio = _build(spans, total_s=10.0)
        result = audit_meeting(audio, SR, _reference(spans))
        assert result["checked"] is True
        assert result["best_shift_ms"] == 0
        assert result["speech_coverage"] > 0.95
        assert result["silence_purity"] > 0.95

    def test_a_displaced_reconstruction_is_caught(self):
        """The failure the audit exists for."""
        spans = [(1.0, 3.0), (5.0, 8.0)]
        audio = _build(spans, total_s=10.0, shift_s=0.1)   # 100 ms late
        result = audit_meeting(audio, SR, _reference(spans))
        assert result["best_shift_ms"] == 100
        assert result["agreement_at_best_shift"] > result["agreement_at_zero_shift"]

    def test_a_displacement_in_the_other_direction_is_signed_correctly(self):
        spans = [(2.0, 4.0), (6.0, 9.0)]
        audio = _build(spans, total_s=12.0, shift_s=-0.05)
        assert audit_meeting(audio, SR, _reference(spans))["best_shift_ms"] == -50

    def test_missing_audio_shows_up_as_low_coverage(self):
        spans = [(1.0, 3.0), (5.0, 8.0)]
        audio = _build([(1.0, 3.0)], total_s=10.0)     # second span absent
        result = audit_meeting(audio, SR, _reference(spans))
        assert result["speech_coverage"] < 0.5
        assert result["silence_purity"] > 0.95

    def test_audio_outside_its_annotation_shows_up_as_low_purity(self):
        audio = _build([(1.0, 9.0)], total_s=10.0)     # far more than annotated
        result = audit_meeting(audio, SR, _reference([(1.0, 3.0)]))
        assert result["speech_coverage"] > 0.95
        assert result["silence_purity"] < 0.5

    def test_an_empty_reference_declines_rather_than_scoring(self):
        assert audit_meeting(_tone(1.0), SR, [])["checked"] is False

    def test_silent_audio_declines_rather_than_dividing_by_zero(self):
        result = audit_meeting(np.zeros(SR, np.float32), SR,
                               _reference([(0.1, 0.5)]))
        assert result["checked"] is True
        assert result["speech_coverage"] == pytest.approx(0.0)
