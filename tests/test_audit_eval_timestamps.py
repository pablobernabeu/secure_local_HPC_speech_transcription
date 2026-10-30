"""Audit fixes for evaluation.benchmark_timestamps.

The VAD end-boundary refinement behind output/evaluation_vad_refine had no
unit test; a switch back from max() to min() would have passed every test
until the next GPU run. These tests use stub VAD and ASR callables, so no
model, corpus or network is needed. torch is required only for the tensor
the refinement builds.
"""

from __future__ import annotations

import subprocess
import sys
import warnings
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("torch")

from evaluation import benchmark_timestamps as bt

_AUDIO = np.zeros(16_000, dtype=np.float32)


def _vad_returning(segments):
    def get_speech_timestamps(waveform, model, sampling_rate, return_seconds):
        assert sampling_rate == 16_000 and return_seconds is True
        return segments
    return get_speech_timestamps


def _vad_raising(*args, **kwargs):
    raise RuntimeError("silero API changed")


class TestRefineEnd:
    def test_no_speech_keeps_whisper_end(self):
        stats = {}
        assert bt._refine_end_with_vad(_AUDIO, 0.8, None, _vad_returning([]),
                                       stats=stats) == 0.8
        assert stats == {"n_vad_no_speech": 1}

    def test_a_later_vad_end_extends_the_boundary(self):
        vad = _vad_returning([{"start": 0.0, "end": 0.4},
                              {"start": 0.5, "end": 0.95}])
        assert bt._refine_end_with_vad(_AUDIO, 0.8, None, vad) == 0.95

    def test_an_earlier_vad_end_never_pulls_the_boundary_in(self):
        vad = _vad_returning([{"start": 0.0, "end": 0.6}])
        assert bt._refine_end_with_vad(_AUDIO, 0.8, None, vad) == 0.8

    def test_a_raising_vad_keeps_whisper_end_and_is_counted(self):
        stats = {}
        assert bt._refine_end_with_vad(_AUDIO, 0.8, None, _vad_raising,
                                       stats=stats) == 0.8
        assert stats == {"n_vad_exception": 1}


class TestPredictBoundaries:
    def test_chunks_without_timestamps_give_none(self):
        pipe = lambda audio: {"chunks": [{"timestamp": (None, None)}]}  # noqa: E731
        assert bt._predict_boundaries(pipe, _AUDIO) is None

    def test_no_chunks_give_none(self):
        assert bt._predict_boundaries(lambda a: {"text": "x"}, _AUDIO) is None

    def test_first_start_and_last_end_are_used(self):
        pipe = lambda audio: {"chunks": [  # noqa: E731
            {"timestamp": (0.1, 0.5)}, {"timestamp": (None, 0.7)},
            {"timestamp": (0.5, 0.9)}]}
        assert bt._predict_boundaries(pipe, _AUDIO) == (0.1, 0.9)

    def test_vad_refinement_applies_to_the_end_only(self):
        pipe = lambda audio: {"chunks": [{"timestamp": (0.1, 0.5)}]}  # noqa: E731
        stats = {}
        out = bt._predict_boundaries(
            pipe, _AUDIO, vad_model=object(),
            get_speech_timestamps=_vad_returning([{"start": 0, "end": 0.7}]),
            vad_stats=stats)
        assert out == (0.1, 0.7)
        assert stats == {}


class TestTransformersFloor:
    @pytest.mark.parametrize("version,ok", [
        ("4.56.2", True), ("4.56.0.dev0", True), ("5.0.0", True),
        ("4.55.4", False), ("4.45.0", False)])
    def test_version_floor(self, version, ok):
        assert bt._transformers_version_ok(version) is ok


def test_importing_the_module_leaves_warning_filters_alone():
    """The module once silenced every warning of any process importing it."""
    code = (
        "import warnings\n"
        "before = list(warnings.filters)\n"
        "import evaluation.benchmark_timestamps\n"
        "assert list(warnings.filters) == before\n"
    )
    result = subprocess.run([sys.executable, "-c", code],
                            capture_output=True, text=True,
                            cwd=Path(__file__).resolve().parents[1])
    assert result.returncode == 0, result.stderr


def test_run_benchmark_scopes_its_warning_filter(monkeypatch):
    seen = {}

    def fake_run(*args):
        seen["filters"] = list(warnings.filters)

    monkeypatch.setattr(bt, "_run_benchmark", fake_run)
    before = list(warnings.filters)
    bt.run_benchmark(output_dir=None, model_id="m", limit=1)
    assert seen["filters"][0][0] == "ignore"
    assert list(warnings.filters) == before
