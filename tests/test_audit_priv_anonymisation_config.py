"""Audit fixes EPRIV-17, EPRIV-28 and EPRIV-31 in benchmark_anonymisation.

The CLI defaults did not reproduce the published run, the requested
configuration was not recorded, a field named for the original arm held
the control's value, and rows skipped while sampling were not counted.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation import benchmark_anonymisation as ba  # noqa: E402


def test_cli_defaults_are_the_published_configuration(monkeypatch):
    seen = {}

    def fake_run(output_dir, limit, alphas, hf_token, model, per_meeting=None):
        seen.update(limit=limit, alphas=alphas, per_meeting=per_meeting)
        return {}

    monkeypatch.setattr(ba, "run", fake_run)
    bd = pytest.importorskip("evaluation.benchmark_der")
    monkeypatch.setattr(bd, "_load_hf_token", lambda: None)
    assert ba.main([]) == 0
    assert seen == {"limit": 200, "alphas": [0.5, 0.7, 0.8, 0.9],
                    "per_meeting": None}


def _pair(errors, words):
    return SimpleNamespace(substitutions=errors, deletions=0, insertions=0,
                           reference_words=words, hypothesis_words=words)


def test_guarded_baseline_is_named_for_its_arm():
    before = [_pair(1, 10)] * 3
    control = [_pair(2, 10)] * 3
    after = [_pair(3, 10)] * 3
    s = ba.summarise([0.5] * 3, before, after, {}, results_control=control)
    assert s["wer_cost_baseline"] == "resynthesis control"
    assert s["wer_baseline_name"] == "resynthesis control"
    assert s["wer_baseline_guarded"] == pytest.approx(0.2)
    # The legacy field keeps its value, so old and new summaries compare.
    assert s["wer_original_guarded"] == s["wer_baseline_guarded"]
    # The raw original's rate stays under its own, unguarded, key.
    assert s["wer_original"] == pytest.approx(0.1)


def test_without_a_control_the_baseline_is_named_raw():
    s = ba.summarise([0.5], [_pair(1, 10)], [_pair(3, 10)], {})
    assert s["wer_baseline_name"] == "raw original"
    assert s["wer_baseline_guarded"] == pytest.approx(0.1)


def test_skipped_rows_are_counted(monkeypatch):
    bd = pytest.importorskip("evaluation.benchmark_der")
    rows = [{"audio_id": f"u{i}", "speaker_id": "s", "meeting_id": "m1",
             "text": "hi", "audio": i, "begin_time": float(i),
             "end_time": float(i) + 1.0} for i in range(4)]

    def decode(i):
        if i == 0:
            raise ValueError("bad")
        if i == 1:
            return np.zeros(ba.SAMPLE_RATE * 2, dtype=np.float32), 8000
        if i == 2:
            return np.zeros(100, dtype=np.float32), ba.SAMPLE_RATE
        return np.zeros(ba.SAMPLE_RATE * 2, dtype=np.float32), ba.SAMPLE_RATE

    monkeypatch.setattr(bd, "_stream_ami", lambda split, token: iter(rows))
    monkeypatch.setattr(bd, "_decode_audio_bytes", decode)
    skipped = {}
    got = ba._load_utterances(5, None, skipped=skipped)
    assert [u["uid"] for u in got] == ["u3"]
    assert skipped == {"undecodable": 1, "wrong_sample_rate": 1,
                       "too_short": 1}


def test_sample_rate_comes_from_the_loader_module():
    from evaluation import ami_meetings
    assert ba.SAMPLE_RATE == ami_meetings.SAMPLE_RATE
