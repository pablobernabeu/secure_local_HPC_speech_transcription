"""Benchmark and sweep outputs are replaced as a set, and an empty run stops.

A job killed part-way used to leave a new, partial der_report.csv beside
the previous run's der_summary.json, and the manuscript reads numbers from
both. A run that scored nothing wrote a macro DER of 0.0. The pipeline and
pyannote's scoring are replaced by fakes, so these tests run anywhere.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation import benchmark_der as bd
from evaluation import der_metrics as dm
from evaluation import sweep_der as sd


def _stats(n_speakers=2):
    return {"n_utterances": 2, "n_speakers": n_speakers, "duration_s": 60.0,
            "speech_s": 50.0, "overlap_s": 5.0, "overlap_fraction": 0.1,
            "silence_fraction": 0.17}


def _meeting(mid, reference=True):
    ref = [{"start": 0.0, "end": 1.0, "speaker": "A"}] if reference else []
    return mid, [0.0], ref, _stats()


def _fake_der(reference, hypothesis, collar=0.25):
    return {"uri": "", "der": 0.2, "missed_speech": 0.1, "false_alarm": 0.05,
            "speaker_confusion": 0.05, "total_ref_duration": 1.0,
            "_missed_abs": 0.1, "_fa_abs": 0.05, "_confusion_abs": 0.05}


@pytest.fixture
def fakes(monkeypatch):
    monkeypatch.setattr(dm, "annotation_from_segments", lambda segs, uri="": segs)
    monkeypatch.setattr(dm, "compute_der", _fake_der)
    for module in (bd, sd):
        monkeypatch.setattr(module, "load_pipeline", lambda *a, **k: object())
        monkeypatch.setattr(module, "apply_hyperparameters",
                            lambda pipe, **kw: {
                                "clustering": {"threshold": 0.7,
                                               "min_cluster_size": 12},
                                "segmentation": {"min_duration_off": 0.0}})
        monkeypatch.setattr(module, "_load_hf_token", lambda: None)
    monkeypatch.setattr(bd, "diarise", lambda *a, **k: [
        {"start": 0.0, "end": 1.0, "speaker": "X"}])
    monkeypatch.setattr(sd, "diarise", lambda *a, **k: [
        {"start": 0.0, "end": 1.0, "speaker": "X"}])


def _seed_previous_run(out: Path, names):
    for name in names:
        (out / name).write_text("previous run", encoding="utf-8")


class TestBenchmarkReplacesReportAndSummaryTogether:
    NAMES = ("der_report.csv", "der_summary.json")

    def test_an_interrupted_run_leaves_the_previous_pair(self, tmp_path, fakes,
                                                         monkeypatch):
        _seed_previous_run(tmp_path, self.NAMES)

        def dying_corpus(**kwargs):
            yield _meeting("M0")
            raise MemoryError("killed")

        monkeypatch.setattr(bd, "build_corpus", dying_corpus)
        with pytest.raises(MemoryError):
            bd.run_benchmark(tmp_path)
        for name in self.NAMES:
            assert (tmp_path / name).read_text(encoding="utf-8") == "previous run"
        partial = tmp_path / "der_report.csv.partial"
        assert len(list(csv.DictReader(partial.open(encoding="utf-8")))) == 1

    def test_a_finished_run_replaces_both_and_leaves_no_partial(
            self, tmp_path, fakes, monkeypatch):
        _seed_previous_run(tmp_path, self.NAMES)
        monkeypatch.setattr(bd, "build_corpus",
                            lambda **kw: iter([_meeting("M0"), _meeting("M1")]))
        summary = bd.run_benchmark(tmp_path)
        assert summary["n_meetings"] == 2
        rows = list(csv.DictReader((tmp_path / "der_report.csv").open(encoding="utf-8")))
        assert len(rows) == json.loads(
            (tmp_path / "der_summary.json").read_text(encoding="utf-8"))["n_meetings"]
        assert not list(tmp_path.glob("*.partial"))
        # DEPS-04, OUTPUTS-12: the snapshots and the code behind the figures.
        from evaluation.revisions import revision_for
        pipeline = "pyannote/speaker-diarization-3.1"
        assert summary["revisions"][pipeline] == revision_for(pipeline)
        assert summary["revisions"]["edinburghcstr/ami"] == revision_for("edinburghcstr/ami")
        assert summary["revisions_not_enforced"] == list(bd._DEFAULT_SUB_MODELS)
        assert {"git_commit", "packages"} <= set(summary["run_metadata"])

    def test_a_run_that_scores_nothing_stops(self, tmp_path, fakes, monkeypatch):
        _seed_previous_run(tmp_path, self.NAMES)
        monkeypatch.setattr(bd, "build_corpus",
                            lambda **kw: iter([_meeting("M0", reference=False)]))
        with pytest.raises(SystemExit, match="no meeting was scored"):
            bd.run_benchmark(tmp_path)
        for name in self.NAMES:
            assert (tmp_path / name).read_text(encoding="utf-8") == "previous run"


class TestSweepReplacesItsOutputsTogether:
    NAMES = ("der_sweep.csv", "der_sweep_summary.csv", "der_sweep_selection.json")

    def test_an_interrupted_sweep_leaves_the_previous_set(self, tmp_path, fakes,
                                                          monkeypatch):
        _seed_previous_run(tmp_path, self.NAMES)
        monkeypatch.setattr(sd, "build_corpus",
                            lambda **kw: iter([_meeting("M0")]))
        calls = {"n": 0}

        def dying_diarise(*a, **k):
            calls["n"] += 1
            if calls["n"] > 1:
                raise MemoryError("killed")
            return []

        monkeypatch.setattr(sd, "diarise", dying_diarise)
        with pytest.raises(MemoryError):
            sd.run_sweep(tmp_path, thresholds=(0.6, 0.7))
        for name in self.NAMES:
            assert (tmp_path / name).read_text(encoding="utf-8") == "previous run"

    def test_a_finished_sweep_replaces_all_three(self, tmp_path, fakes, monkeypatch):
        _seed_previous_run(tmp_path, self.NAMES)
        monkeypatch.setattr(sd, "build_corpus",
                            lambda **kw: iter([_meeting("M0")]))
        sd.run_sweep(tmp_path, thresholds=(0.6, 0.7))
        for name in self.NAMES:
            assert (tmp_path / name).read_text(encoding="utf-8") != "previous run"
        assert not list(tmp_path.glob("*.partial"))

    def test_an_empty_corpus_stops_before_any_cell(self, tmp_path, fakes,
                                                   monkeypatch):
        monkeypatch.setattr(sd, "build_corpus",
                            lambda **kw: iter([_meeting("M0", reference=False)]))
        with pytest.raises(SystemExit, match="no meeting was scored"):
            sd.run_sweep(tmp_path, thresholds=(0.6,))
        assert not (tmp_path / "der_sweep_selection.json").exists()
