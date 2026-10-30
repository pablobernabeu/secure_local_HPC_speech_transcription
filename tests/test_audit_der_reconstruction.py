"""Loud checks on reconstruction inputs the committed runs never produced.

Multi-channel clips used to be flattened into interleaved noise, empty
meetings returned a different set of statistics keys from non-empty ones,
and a clip at another sample rate was resampled without a word. None of
these can move a committed number (the IHM clips are mono and 16 kHz);
the checks make the first two fail loudly and the third audible.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation.ami_meetings import (
    _as_mono,
    concat_meeting,
    meeting_statistics,
    mix_meeting,
)

SR = 1000


def _row(speaker, begin, end):
    return {"meeting_id": "M", "speaker_id": speaker,
            "begin_time": begin, "end_time": end}


def _mono(row):
    n = int(round((row["end_time"] - row["begin_time"]) * SR))
    return np.full(n, 0.25, dtype=np.float32), SR


def _stereo(row):
    audio, sr = _mono(row)
    return np.stack([audio, -audio], axis=1), sr


class TestMultiChannelClipsAreRefused:
    @pytest.mark.parametrize("build", [mix_meeting, concat_meeting])
    def test_a_stereo_clip_stops_the_reconstruction(self, build):
        with pytest.raises(ValueError, match="expected mono"):
            build([_row("A", 0.0, 1.0)], _stereo, sample_rate=SR)

    def test_a_single_column_clip_is_mono_and_unchanged(self):
        column, _ = _mono(_row("A", 0.0, 1.0))
        flat = _as_mono(column)
        assert np.array_equal(_as_mono(column[:, None]), flat)
        assert np.array_equal(_as_mono(column[None, :]), flat)

    def test_mono_reconstruction_is_unchanged(self):
        rows = [_row("A", 0.0, 1.0), _row("B", 0.5, 1.5)]
        audio, _, _ = mix_meeting(rows, _mono, sample_rate=SR)
        assert audio.size == int(1.5 * SR)
        assert audio[int(0.75 * SR)] == pytest.approx(0.5)


class TestEmptyMeetingsCarryTheFullStatistics:
    def _nonempty_keys(self, build):
        _, _, stats = build([_row("A", 0.0, 1.0)], _mono, sample_rate=SR)
        return set(stats)

    def test_an_empty_timeline_meeting(self):
        _, ref, stats = mix_meeting([], _mono, sample_rate=SR)
        assert ref == []
        assert set(stats) == self._nonempty_keys(mix_meeting)
        assert stats["n_speakers"] == 0 and stats["skipped_utterances"] == 0

    def test_a_concatenation_whose_every_clip_failed(self):
        def broken(row):
            raise OSError("undecodable")

        _, ref, stats = concat_meeting([_row("A", 0.0, 1.0)], broken,
                                       sample_rate=SR)
        assert ref == []
        assert set(stats) == self._nonempty_keys(concat_meeting)
        assert stats["skipped_utterances"] == 1

    def test_the_empty_statistics_are_the_zero_description(self):
        _, _, stats = mix_meeting([], _mono, sample_rate=SR)
        for key, value in meeting_statistics([], 0.0).items():
            assert stats[key] == value


class TestResamplingIsAnnounced:
    def test_a_clip_at_another_rate_warns(self):
        def at_8k(row):
            return np.zeros(8000, dtype=np.float32), 8000

        with pytest.warns(RuntimeWarning, match="linear interpolation"):
            mix_meeting([_row("A", 0.0, 1.0)], at_8k, sample_rate=SR)

    def test_a_clip_at_the_target_rate_is_silent(self, recwarn):
        mix_meeting([_row("A", 0.0, 1.0)], _mono, sample_rate=SR)
        assert not [w for w in recwarn if issubclass(w.category, RuntimeWarning)]
