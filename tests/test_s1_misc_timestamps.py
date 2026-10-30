"""Stage-1 tests for evaluation.benchmark_timestamps.

ESTATS-02: a final chunk without an end timestamp was dropped and the
previous chunk's end taken instead, which scored the utterance as a
truncation. ESTATS-12: the summary did not say what it sampled or how it
decoded. ESTATS-14: a run that scored nothing reported zero error.
DEPS-06/TESTS-10: Silero was loaded from an unpinned branch.

Everything runs on stubs: no model, corpus or network.
"""

from __future__ import annotations

import csv
import json
import sys
import types
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation import benchmark_timestamps as bt

_AUDIO = np.zeros(16_000, dtype=np.float32)


def _pipe(chunks, text="hello there"):
    return lambda audio: {"text": text, "chunks": chunks}


class TestUntimedTail:
    def test_an_untimed_final_chunk_is_not_scored_as_a_truncation(self):
        info = {}
        out = bt._predict_boundaries(
            _pipe([{"timestamp": (0.0, 1.2)}, {"timestamp": (1.2, None)}]),
            _AUDIO, info=info)
        assert out is None
        assert info["untimed_tail"] is True
        assert info["skip_reason"] == "untimed_tail"
        assert info["n_chunks"] == 2
        assert info["text"] == "hello there"

    def test_a_single_untimed_chunk_is_skipped_with_its_reason(self):
        info = {}
        assert bt._predict_boundaries(
            _pipe([{"timestamp": (0.0, None)}]), _AUDIO, info=info) is None
        assert info["skip_reason"] == "untimed_tail"

    def test_the_final_chunks_end_is_used_even_without_a_start(self):
        info = {}
        out = bt._predict_boundaries(
            _pipe([{"timestamp": (0.1, 0.5)}, {"timestamp": (None, 0.9)}]),
            _AUDIO, info=info)
        assert out == (0.1, 0.9)
        assert info["skip_reason"] is None and info["untimed_tail"] is False

    def test_other_skip_reasons(self):
        info = {}
        assert bt._predict_boundaries(_pipe([]), _AUDIO, info=info) is None
        assert info["skip_reason"] == "no_chunks"

        def raising(audio):
            raise RuntimeError("decode failed")
        assert bt._predict_boundaries(raising, _AUDIO, info=info) is None
        assert info["skip_reason"] == "asr_error"

        assert bt._predict_boundaries(
            _pipe([{"timestamp": (None, 0.9)}]), _AUDIO, info=info) is None
        assert info["skip_reason"] == "no_start_timestamp"

    def test_every_reason_is_declared(self):
        assert set(bt.SKIP_REASONS) >= {"untimed_tail", "no_chunks",
                                        "asr_error", "no_start_timestamp"}


class TestSelectRows:
    def _rows(self):
        rows = []
        for m in ("EN2002a", "EN2002b", "ES2004a"):
            for u in range(4):
                rows.append({"meeting_id": m, "audio_id": f"{m}-{u}",
                             "begin_time": float(u)})
        return rows

    def test_default_reads_the_stream_from_the_front(self):
        got = [r["audio_id"] for r in bt.select_rows(iter(self._rows()), 5)]
        assert got == ["EN2002a-0", "EN2002a-1", "EN2002a-2", "EN2002a-3",
                       "EN2002b-0"]

    def test_per_meeting_spreads_the_budget(self):
        got = [r["audio_id"] for r in bt.select_rows(iter(self._rows()), 5,
                                                     per_meeting=2)]
        assert got == ["EN2002a-0", "EN2002a-1", "EN2002b-0", "EN2002b-1",
                       "ES2004a-0"]

    def test_a_non_positive_cap_is_refused(self):
        with pytest.raises(ValueError):
            list(bt.select_rows(iter(self._rows()), 5, per_meeting=0))

    def test_meeting_of_reads_the_audio_id_when_needed(self):
        assert bt._meeting_of({"audio_id": "AMI_EN2002a_H00_MEE073_0019663_0019800"}) \
            == "EN2002a"


def test_silero_is_loaded_from_a_release_tag(monkeypatch):
    torch = pytest.importorskip("torch")
    seen = {}

    class _Model:
        def eval(self):
            return self

    def fake_load(**kwargs):
        seen.update(kwargs)
        return _Model(), ("get_speech_timestamps",)

    monkeypatch.setattr(torch.hub, "load", fake_load)
    bt._load_silero_vad()
    repo, _, tag = seen["repo_or_dir"].partition(":")
    assert repo == "snakers4/silero-vad"
    assert tag.startswith("v") and tag[1:2].isdigit()
    assert seen["repo_or_dir"] == bt.SILERO_VAD_REPO


# ---------------------------------------------------------------------------
# run_benchmark end to end on stubs
# ---------------------------------------------------------------------------

def _stub_rows(n=4):
    return [{"audio_id": f"AMI_EN2002a_H00_MEE071_{i:07d}_{i + 100:07d}",
             "meeting_id": "EN2002a",
             "audio": {"array": np.zeros(16_000, dtype=np.float32),
                       "sampling_rate": 16_000}} for i in range(n)]


@pytest.fixture
def stubbed(monkeypatch):
    loads = {}

    class _Dataset(list):
        def cast_column(self, name, feature):
            return self

    def load_dataset(**kwargs):
        loads.update(kwargs)
        return _Dataset(_stub_rows())

    fake = types.ModuleType("datasets")
    fake.load_dataset = load_dataset
    fake.Audio = lambda decode=True: ("Audio", decode)
    monkeypatch.setitem(sys.modules, "datasets", fake)
    monkeypatch.setattr(bt, "_load_hf_token", lambda: None)
    import provenance
    monkeypatch.setattr(provenance, "run_metadata", lambda **_kwargs: {"git_commit": "x"})
    return loads


def _use_pipe(monkeypatch, pipe):
    settings = {"device": "cpu", "gpu": None, "dtype": "float32",
                "chunk_length_s": 30, "stride_length_s": 5,
                "model_revision": "r"}
    monkeypatch.setattr(bt, "_load_whisper", lambda model_id: (pipe, settings))


def test_the_summary_records_sample_decode_and_skips(tmp_path, monkeypatch, stubbed):
    calls = {"n": 0}

    def pipe(audio):
        calls["n"] += 1
        if calls["n"] == 2:        # the second utterance has an untimed tail
            return {"text": "a b", "chunks": [{"timestamp": (0.0, 0.4)},
                                              {"timestamp": (0.4, None)}]}
        return {"text": "a", "chunks": [{"timestamp": (0.0, 0.9)}]}

    _use_pipe(monkeypatch, pipe)
    summary = bt.run_benchmark(tmp_path, "openai/whisper-large-v3", limit=3)

    from evaluation.revisions import revision_for
    assert stubbed["revision"] == revision_for("edinburghcstr/ami") is not None
    assert summary["n"] == 2
    assert summary["n_skipped"] == 1
    assert summary["n_missing_end_timestamp"] == 1
    assert summary["skip_reasons"]["untimed_tail"] == 1
    assert summary["truncation_rate"] == 0.0
    assert summary["sampling"]["limit"] == 3
    assert summary["sampling"]["n_streamed"] == 3
    assert summary["sampling"]["utterances_per_meeting"] == {"EN2002a": 3}
    assert summary["whisper"]["dtype"] == "float32"
    assert "openai/whisper-large-v3" in summary["revisions"]
    assert "edinburghcstr/ami" in summary["revisions"]
    assert summary["vad_applied"] is False

    written = json.loads((tmp_path / "timestamp_summary.json").read_text("utf-8"))
    assert written["n_missing_end_timestamp"] == 1
    with (tmp_path / "timestamp_report.csv").open(encoding="utf-8") as fh:
        report = list(csv.DictReader(fh))
    assert len(report) == 2 and report[0]["n_chunks"] == "1"
    with (tmp_path / "timestamp_skipped.csv").open(encoding="utf-8") as fh:
        skipped = list(csv.DictReader(fh))
    assert [(r["reason"], r["hypothesis"]) for r in skipped] == [("untimed_tail", "a b")]


def test_a_run_that_scores_nothing_fails_and_reports_nulls(tmp_path, monkeypatch, stubbed):
    _use_pipe(monkeypatch, lambda audio: {"text": "", "chunks": []})
    with pytest.raises(bt.TimestampBenchmarkError, match="No utterance was scored"):
        bt.run_benchmark(tmp_path, "m", limit=2)
    written = json.loads((tmp_path / "timestamp_summary.json").read_text("utf-8"))
    assert written["n"] == 0 and written["mae_end"] is None
    assert written["skip_reasons"]["no_chunks"] == 2


def test_main_turns_the_error_into_an_exit_status(tmp_path, monkeypatch, stubbed, capsys):
    _use_pipe(monkeypatch, lambda audio: {"text": "", "chunks": []})
    assert bt.main(["--output-dir", str(tmp_path), "--limit", "1"]) == 1
    assert "No utterance was scored" in capsys.readouterr().err
