"""Tests for the AMI meeting reconstruction.

The point of the timeline mode is that overlapping speech survives
reconstruction, so the tests assert on the reconstructed waveform and on
the reference derived from it, not merely on the code path taken. A
reconstruction that returned the right dictionaries while silently
flattening the overlap would pass a structural test and fail these.

No audio, network or model is required: decoding is injected.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.ami_meetings import (
    concat_meeting,
    group_rows_by_meeting,
    meeting_statistics,
    mix_meeting,
    overlap_duration,
)

SR = 1000  # a low rate keeps the fixtures small and the arithmetic exact


def _row(meeting, speaker, begin, end, level=1.0, clip_s=None):
    """One utterance row; ``level`` labels the speaker's audio distinctly."""
    return {
        "meeting_id": meeting,
        "speaker_id": speaker,
        "begin_time": begin,
        "end_time": end,
        "_level": level,
        "_clip_s": end - begin if clip_s is None else clip_s,
    }


def _decode(row):
    """Constant-amplitude audio, so sums are easy to reason about."""
    return (np.full(int(round(row["_clip_s"] * SR)), row["_level"],
                    dtype=np.float32), SR)


def _failing_decode(row):
    raise RuntimeError("undecodable")


# ---------------------------------------------------------------------------
# group_rows_by_meeting
# ---------------------------------------------------------------------------

class TestGrouping:
    def test_groups_contiguous_meetings_and_sorts_by_begin_time(self):
        rows = [
            _row("M1", "A", 3.0, 4.0),
            _row("M1", "B", 1.0, 2.0),
            _row("M2", "C", 0.0, 1.0),
        ]
        grouped = list(group_rows_by_meeting(rows))
        assert [mid for mid, _ in grouped] == ["M1", "M2"]
        assert [r["begin_time"] for r in grouped[0][1]] == [1.0, 3.0]

    def test_limit_stops_after_complete_meetings(self):
        rows = [_row("M1", "A", 0, 1), _row("M2", "B", 0, 1), _row("M3", "C", 0, 1)]
        grouped = list(group_rows_by_meeting(rows, limit_meetings=2))
        assert [mid for mid, _ in grouped] == ["M1", "M2"]

    def test_a_meeting_that_reappears_is_an_error_not_a_silent_split(self):
        """Splitting one meeting in two would corrupt every timeline."""
        rows = [_row("M1", "A", 0, 1), _row("M2", "B", 0, 1), _row("M1", "A", 5, 6)]
        with pytest.raises(ValueError, match="reappeared"):
            list(group_rows_by_meeting(rows))

    def test_empty_stream_yields_nothing(self):
        assert list(group_rows_by_meeting([])) == []


# ---------------------------------------------------------------------------
# overlap_duration
# ---------------------------------------------------------------------------

class TestOverlapDuration:
    def test_disjoint_turns_have_no_overlap(self):
        ref = [{"start": 0, "end": 2, "speaker": "A"},
               {"start": 3, "end": 5, "speaker": "B"}]
        assert overlap_duration(ref) == (4.0, 0.0)

    def test_partial_overlap_is_counted_once(self):
        ref = [{"start": 0, "end": 3, "speaker": "A"},
               {"start": 2, "end": 5, "speaker": "B"}]
        speech, overlap = overlap_duration(ref)
        assert speech == pytest.approx(5.0)   # union 0-5
        assert overlap == pytest.approx(1.0)  # 2-3

    def test_a_nested_turn_still_registers_as_overlap(self):
        """Pairwise intersection logic tends to miss containment."""
        ref = [{"start": 0, "end": 10, "speaker": "A"},
               {"start": 4, "end": 6, "speaker": "B"}]
        speech, overlap = overlap_duration(ref)
        assert speech == pytest.approx(10.0)
        assert overlap == pytest.approx(2.0)

    def test_three_simultaneous_speakers_are_not_double_counted(self):
        ref = [{"start": 0, "end": 4, "speaker": "A"},
               {"start": 0, "end": 4, "speaker": "B"},
               {"start": 0, "end": 4, "speaker": "C"}]
        speech, overlap = overlap_duration(ref)
        assert speech == pytest.approx(4.0)
        assert overlap == pytest.approx(4.0)

    def test_empty_reference(self):
        assert overlap_duration([]) == (0.0, 0.0)


# ---------------------------------------------------------------------------
# mix_meeting
# ---------------------------------------------------------------------------

class TestMixMeeting:
    def test_audio_lands_at_its_true_offset(self):
        rows = [_row("M", "A", 2.0, 3.0, level=0.5)]
        audio, ref, stats = mix_meeting(rows, _decode, sample_rate=SR)
        assert audio.size == 3 * SR
        assert np.allclose(audio[:2 * SR], 0.0)          # silence before
        assert np.allclose(audio[2 * SR:3 * SR], 0.5)    # speech in place
        assert ref == [{"start": 2.0, "end": 3.0, "speaker": "A"}]
        assert stats["silence_fraction"] == pytest.approx(2 / 3, abs=1e-3)

    def test_simultaneous_speakers_are_summed_not_sequenced(self):
        """The defining property: overlap must survive reconstruction."""
        rows = [_row("M", "A", 0.0, 2.0, level=0.25),
                _row("M", "B", 1.0, 3.0, level=0.25)]
        audio, ref, stats = mix_meeting(rows, _decode, sample_rate=SR,
                                        normalise=False)
        assert audio.size == 3 * SR
        assert np.allclose(audio[:1 * SR], 0.25)        # A alone
        assert np.allclose(audio[1 * SR:2 * SR], 0.50)  # A and B together
        assert np.allclose(audio[2 * SR:], 0.25)        # B alone
        assert stats["overlap_s"] == pytest.approx(1.0)
        assert stats["overlap_fraction"] == pytest.approx(1 / 3, abs=1e-4)

    def test_concatenation_would_have_destroyed_that_overlap(self):
        """Contrast case pinning down what the legacy mode gives up."""
        rows = [_row("M", "A", 0.0, 2.0, level=0.25),
                _row("M", "B", 1.0, 3.0, level=0.25)]
        _, ref, stats = concat_meeting(rows, _decode, sample_rate=SR)
        assert stats["overlap_s"] == 0.0
        assert ref[0]["end"] <= ref[1]["start"]

    def test_peak_normalisation_applies_one_global_gain(self):
        rows = [_row("M", "A", 0.0, 2.0, level=0.8),
                _row("M", "B", 0.0, 2.0, level=0.8)]
        audio, _, stats = mix_meeting(rows, _decode, sample_rate=SR)
        assert float(np.max(np.abs(audio))) == pytest.approx(1.0)
        assert stats["normalisation_gain"] == pytest.approx(1 / 1.6, abs=1e-4)

    def test_quiet_meetings_are_left_untouched(self):
        rows = [_row("M", "A", 0.0, 2.0, level=0.3)]
        audio, _, stats = mix_meeting(rows, _decode, sample_rate=SR)
        assert stats["normalisation_gain"] == 1.0
        assert np.allclose(audio[:2 * SR], 0.3)

    def test_an_overlong_clip_is_trimmed_to_its_annotation(self):
        """Otherwise the extra audio is charged to the system as false alarm."""
        rows = [_row("M", "A", 0.0, 1.0, level=1.0, clip_s=2.0)]
        audio, ref, stats = mix_meeting(rows, _decode, sample_rate=SR)
        assert ref[0]["end"] == 1.0
        assert audio.size == 1 * SR
        assert stats["clip_annotation_mismatch_s"] == pytest.approx(1.0)

    def test_a_short_clip_is_reported_rather_than_padded(self):
        rows = [_row("M", "A", 0.0, 2.0, level=1.0, clip_s=1.0)]
        audio, ref, stats = mix_meeting(rows, _decode, sample_rate=SR)
        assert ref[0]["end"] == 2.0            # the annotation still governs
        assert np.allclose(audio[SR:], 0.0)    # nothing invented
        assert stats["clip_annotation_mismatch_s"] == pytest.approx(1.0)

    def test_duration_cap_truncates_audio_and_reference_together(self):
        rows = [_row("M", "A", 0.0, 2.0), _row("M", "B", 4.0, 6.0)]
        audio, ref, stats = mix_meeting(rows, _decode, sample_rate=SR,
                                        max_duration_s=5.0)
        assert audio.size == 5 * SR
        assert [r["end"] for r in ref] == [2.0, 5.0]
        assert stats["speech_s"] == pytest.approx(3.0)

    def test_utterances_beyond_the_cap_are_dropped_entirely(self):
        rows = [_row("M", "A", 0.0, 2.0), _row("M", "B", 8.0, 9.0)]
        _, ref, _ = mix_meeting(rows, _decode, sample_rate=SR,
                                max_duration_s=5.0)
        assert [r["speaker"] for r in ref] == ["A"]

    def test_an_undecodable_clip_is_counted_not_fatal(self):
        rows = [_row("M", "A", 0.0, 1.0)]
        audio, ref, stats = mix_meeting(rows, _failing_decode, sample_rate=SR)
        assert stats["skipped_utterances"] == 1
        assert ref == []
        assert audio.size == 1 * SR

    def test_zero_length_annotations_are_dropped(self):
        rows = [_row("M", "A", 1.0, 1.0), _row("M", "B", 2.0, 3.0)]
        _, ref, _ = mix_meeting(rows, _decode, sample_rate=SR)
        assert [r["speaker"] for r in ref] == ["B"]

    def test_empty_meeting_returns_empty_audio(self):
        audio, ref, stats = mix_meeting([], _decode, sample_rate=SR)
        assert audio.size == 0 and ref == [] and stats["n_utterances"] == 0

    def test_a_differing_sample_rate_is_resampled_to_the_target(self):
        row = _row("M", "A", 0.0, 1.0, level=0.4)

        def decode_8k(r):
            return np.full(int(1.0 * 8000), 0.4, dtype=np.float32), 8000

        audio, _, _ = mix_meeting([row], decode_8k, sample_rate=SR)
        assert audio.size == SR
        assert np.allclose(audio, 0.4, atol=1e-6)


# ---------------------------------------------------------------------------
# concat_meeting and statistics
# ---------------------------------------------------------------------------

class TestConcatMeeting:
    def test_gap_is_inserted_between_utterances(self):
        rows = [_row("M", "A", 0.0, 1.0, level=1.0),
                _row("M", "B", 10.0, 11.0, level=1.0)]
        audio, ref, stats = concat_meeting(rows, _decode, sample_rate=SR,
                                           gap_s=0.5)
        assert ref[0] == {"start": 0.0, "end": 1.0, "speaker": "A"}
        assert ref[1] == {"start": 1.5, "end": 2.5, "speaker": "B"}
        assert audio.size == 3 * SR       # 1 + 0.5 + 1 + 0.5
        assert stats["mode"] == "concat"

    def test_utterance_cap_is_honoured(self):
        rows = [_row("M", "A", i, i + 1) for i in range(10)]
        _, ref, _ = concat_meeting(rows, _decode, sample_rate=SR,
                                   max_utterances=3)
        assert len(ref) == 3


class TestMeetingStatistics:
    def test_silence_fraction_measures_unannotated_time(self):
        ref = [{"start": 0, "end": 2, "speaker": "A"}]
        stats = meeting_statistics(ref, duration_s=10.0)
        assert stats["silence_fraction"] == pytest.approx(0.8)
        assert stats["n_speakers"] == 1

    def test_zero_duration_does_not_divide_by_zero(self):
        stats = meeting_statistics([], duration_s=0.0)
        assert stats["silence_fraction"] == 0.0
        assert stats["overlap_fraction"] == 0.0
