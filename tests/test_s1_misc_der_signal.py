"""EDER-06: every DER scoring path hands the pipeline the same signal.

The cache stores each reconstruction as a 16-bit PCM WAV. A run that
built the cache used to score the unquantised float mix it had just
written, and a run without ``--cache-dir`` never quantised at all, so the
same command gave different audio on its first and second invocation.
These tests drive the real ``build_corpus`` with a synthetic stream.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

pytest.importorskip("soundfile")

from evaluation import ami_meetings as am  # noqa: E402
from evaluation import benchmark_der as bd  # noqa: E402

SR = am.SAMPLE_RATE


def _rows():
    rng = np.random.default_rng(0)
    rows = []
    for m in range(2):
        for u in range(2):
            begin = float(u)
            rows.append({
                "meeting_id": f"M{m}", "speaker_id": f"S{u}",
                "begin_time": begin, "end_time": begin + 0.5,
                # Values no 16-bit sample can hold exactly.
                "audio": {"array": rng.uniform(-0.3, 0.3, SR // 2).astype(np.float32),
                          "sampling_rate": SR},
            })
    return rows


@pytest.fixture
def stream(monkeypatch):
    monkeypatch.setattr(bd, "_stream_ami", lambda split, hf_token: iter(_rows()))


def _audio(**kwargs):
    return {mid: audio for mid, audio, _, _ in bd.build_corpus(split="test", **kwargs)}


def test_first_and_second_run_into_a_cache_score_the_same_audio(tmp_path, stream):
    first = _audio(cache_dir=tmp_path)       # builds the cache
    second = _audio(cache_dir=tmp_path)      # reads it back
    assert first.keys() == second.keys() == {"M0", "M1"}
    for mid in first:
        assert first[mid].dtype == np.float32
        np.testing.assert_array_equal(first[mid], second[mid])


def test_a_run_without_a_cache_scores_the_cached_signal(tmp_path, stream):
    cached = _audio(cache_dir=tmp_path)
    uncached = _audio(cache_dir=None)
    for mid in cached:
        np.testing.assert_array_equal(cached[mid], uncached[mid])


def test_the_signal_is_quantised_not_the_raw_mix(stream):
    rows = [r for r in _rows() if r["meeting_id"] == "M0"]
    raw, _, _ = am.mix_meeting(rows, lambda r: am.decode_audio_bytes(r["audio"]),
                               sample_rate=SR)
    scored = _audio(cache_dir=None)["M0"]
    assert scored.shape == raw.shape
    assert not np.array_equal(scored, raw)
    # 16-bit quantisation moves no sample by more than one step.
    assert np.max(np.abs(scored - raw)) <= 1.0 / 32767


def test_as_cached_leaves_an_empty_signal_alone():
    empty = np.zeros(0, dtype=np.float32)
    assert bd._as_cached(empty).size == 0
