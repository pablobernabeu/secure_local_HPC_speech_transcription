"""Tests for the fine-tuning data preparation.

The fine-tuning script trains a segmentation model on AMI and the
benchmark scores one on AMI, so the two must build their audio the same
way. They did not: the benchmark was rebuilt to place each utterance at
its true onset and sum the headset channels, while data preparation here
still concatenated utterances with silent gaps. A model trained that way
would never see two people talking at once and would then be scored on
audio where 15% of the speech is overlapped.

These tests pin the join between the shared reconstruction and the RTTM
annotation written beside it. They need no GPU, no network and no
pyannote.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation import finetune_pyannote_segmentation as ft
from evaluation.ami_meetings import mix_meeting

SR = 1000


def _row(speaker, begin, end, level=0.4):
    return {"meeting_id": "M", "speaker_id": speaker,
            "begin_time": begin, "end_time": end, "_level": level}


def _decode(row):
    n = int(round((row["end_time"] - row["begin_time"]) * SR))
    return np.full(n, row["_level"], dtype=np.float32), SR


def _parse_rttm(path):
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        f = line.split()
        rows.append({"uri": f[1], "start": float(f[3]),
                     "duration": float(f[4]), "speaker": f[7]})
    return rows


class TestDataPreparationUsesTheSharedReconstruction:
    def test_the_module_imports_the_benchmark_reconstruction(self):
        """A local reimplementation is how the two drifted apart before."""
        assert ft.mix_meeting is mix_meeting

    def test_the_concatenation_constants_are_gone(self):
        """Their presence would mean the old path is still reachable."""
        assert not hasattr(ft, "_SILENCE_GAP_S")
        assert not hasattr(ft, "_DEFAULT_UTT_PER_MEETING")


class TestRttmMatchesTheReconstruction:
    def _prepare(self, tmp_path, rows, max_duration_s=None):
        audio, reference, stats = mix_meeting(
            rows, _decode, sample_rate=SR, max_duration_s=max_duration_s)
        path = tmp_path / "M.rttm"
        ft._write_rttm(reference, "M", path)
        return audio, reference, stats, _parse_rttm(path)

    def test_every_reference_turn_reaches_the_rttm(self, tmp_path):
        rows = [_row("A", 0.0, 2.0), _row("B", 1.0, 3.0), _row("A", 5.0, 6.0)]
        _, reference, _, rttm = self._prepare(tmp_path, rows)
        assert len(rttm) == len(reference) == 3
        for written, ref in zip(rttm, reference, strict=True):
            assert written["speaker"] == ref["speaker"]
            assert written["start"] == pytest.approx(ref["start"], abs=1e-6)
            assert written["duration"] == pytest.approx(
                ref["end"] - ref["start"], abs=1e-6)

    def test_overlapping_turns_survive_into_the_annotation(self, tmp_path):
        """The property the old concatenation destroyed."""
        rows = [_row("A", 0.0, 2.0), _row("B", 1.0, 3.0)]
        audio, _, stats, rttm = self._prepare(tmp_path, rows)
        assert stats["overlap_s"] == pytest.approx(1.0)
        # Two speakers are annotated as active across the same second...
        a = next(r for r in rttm if r["speaker"] == "A")
        b = next(r for r in rttm if r["speaker"] == "B")
        assert a["start"] < b["start"] < a["start"] + a["duration"]
        # ...and the audio there is the sum of both, not one after the other.
        assert float(audio[int(1.5 * SR)]) > float(audio[int(0.5 * SR)])

    def test_turn_onsets_are_absolute_not_cumulative(self, tmp_path):
        """Concatenation wrote a running cursor; the timeline writes onsets."""
        rows = [_row("A", 0.0, 1.0), _row("B", 10.0, 11.0)]
        _, _, _, rttm = self._prepare(tmp_path, rows)
        assert rttm[1]["start"] == pytest.approx(10.0)

    def test_a_duration_cap_truncates_annotation_and_audio_together(self, tmp_path):
        rows = [_row("A", 0.0, 2.0), _row("B", 4.0, 8.0)]
        audio, _, _, rttm = self._prepare(tmp_path, rows, max_duration_s=5.0)
        assert audio.size == 5 * SR
        assert rttm[-1]["start"] + rttm[-1]["duration"] == pytest.approx(5.0)

    def test_the_uri_is_written_on_every_line(self, tmp_path):
        rows = [_row("A", 0.0, 1.0), _row("B", 2.0, 3.0)]
        _, _, _, rttm = self._prepare(tmp_path, rows)
        assert {r["uri"] for r in rttm} == {"M"}

    def test_an_empty_meeting_writes_an_empty_annotation(self, tmp_path):
        path = tmp_path / "M.rttm"
        ft._write_rttm([], "M", path)
        assert path.read_text(encoding="utf-8") == ""
