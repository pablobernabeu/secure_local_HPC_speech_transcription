"""A missing jiwer must stop a benchmark before it loads a model (EVAL-01).

evaluation.wer imports without jiwer so that its normaliser and writers
can be tested anywhere, which moved the failure from import time to the
first score. benchmark_anonymisation then caught that failure as an
unscorable utterance and wrote a summary whose WER fields were all null,
with exit status 0, after decoding every condition on the GPU. These tests
remove jiwer and replace every loader with one that fails the test if it
is reached. No audio, model or network.
"""

from __future__ import annotations

import sys
import types

import pytest

np = pytest.importorskip("numpy")

from evaluation import benchmark_anonymisation as ba
from evaluation import benchmark_wer as bw
from evaluation import wer


def _never(*args, **kwargs):
    pytest.fail("a loader ran although the scorer is missing")


def test_require_jiwer_raises_import_error_without_jiwer(monkeypatch):
    monkeypatch.setattr(wer, "jiwer", None)
    with pytest.raises(ImportError, match="jiwer"):
        wer.require_jiwer()


def test_the_wer_benchmark_fails_before_loading_the_model(monkeypatch, tmp_path):
    monkeypatch.setattr(wer, "jiwer", None)
    monkeypatch.setattr(bw, "_apply_seed", _never)
    monkeypatch.setattr(bw, "_build_asr_pipeline", _never)
    monkeypatch.setattr(bw, "_iter_samples", _never)
    runs = bw._build_runs(["raw"], tmp_path / "wer_report.csv",
                          tmp_path / "wer_summary.json")
    with pytest.raises(ImportError, match="jiwer"):
        bw.run_benchmark("d", "c", "s", "m", None, runs)
    assert not (tmp_path / "wer_summary.json").exists()


def test_the_anonymisation_benchmark_fails_before_loading_anything(
        monkeypatch, tmp_path):
    monkeypatch.setattr(wer, "jiwer", None)
    monkeypatch.setattr(ba, "_load_utterances", _never)
    monkeypatch.setattr(ba, "_load_embedder", _never)
    out = tmp_path / "anon"
    with pytest.raises(ImportError, match="jiwer"):
        ba.run(out, limit=2, alphas=[0.8])
    assert not out.exists()


def test_a_scorer_lost_mid_run_is_not_read_as_unscorable(monkeypatch, tmp_path):
    """wer_of must re-raise ImportError, not return a missing score."""
    # The up-front check passes; the scorer then fails as a missing
    # jiwer would.
    monkeypatch.setattr(wer, "jiwer", types.SimpleNamespace())

    def lost_scorer(reference, hypothesis):
        raise ImportError("jiwer is required for WER scoring.")

    monkeypatch.setattr(wer, "compute_metrics", lost_scorer)
    utterances = [
        {"uid": f"u{i}", "speaker": f"S{i}", "meeting": "M",
         "audio": np.zeros(160, dtype=np.float32), "reference": "hello there"}
        for i in range(2)]
    monkeypatch.setattr(ba, "_load_utterances",
                        lambda limit, hf_token, per_meeting=None, skipped=None:
                        utterances)
    monkeypatch.setattr(ba, "_load_embedder",
                        lambda hf_token, failures=None: (lambda audio: np.ones(3), "stub"))
    fake = types.ModuleType("transformers")
    fake.pipeline = lambda *a, **k: (lambda audio: {"text": "hello there"})
    monkeypatch.setitem(sys.modules, "transformers", fake)
    with pytest.raises(ImportError, match="jiwer"):
        ba.run(tmp_path / "anon", limit=2, alphas=[0.8])
    assert not (tmp_path / "anon" / "anonymisation_summary.json").exists()
