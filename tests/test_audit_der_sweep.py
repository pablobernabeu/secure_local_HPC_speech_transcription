"""An unset sweep axis means the pipeline default, and the record says so.

``apply_hyperparameters`` skips ``None``, so a cell that leaves an axis
unset used to inherit whatever the previous cell had set: a defaults cell
placed after a tuned one was scored at the tuned value and labelled the
baseline. The values each cell actually ran with were also thrown away.
The pipeline here is the honest fake from test_benchmark_der, and
pyannote's scoring is replaced, so nothing needs a GPU.
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

from evaluation import der_metrics as dm
from evaluation import sweep_der as sd
from test_benchmark_der import FakePipeline  # pytest puts tests/ on sys.path

DEFAULT_THRESHOLD = 0.7045654963945799


class TestRestoreUnset:
    DEFAULTS = {"clustering_threshold": 0.70, "min_cluster_size": 12,
                "min_duration_off": 0.0}

    def test_an_axis_moved_by_an_earlier_cell_is_set_back(self):
        current = dict(self.DEFAULTS, clustering_threshold=0.6)
        cell = dict.fromkeys(self.DEFAULTS)
        assert sd._restore_unset(cell, self.DEFAULTS, current)[
            "clustering_threshold"] == 0.70

    def test_an_axis_already_at_its_default_stays_unset(self):
        """So the calls made for every command-line grid are unchanged."""
        cell = dict.fromkeys(self.DEFAULTS)
        assert sd._restore_unset(cell, self.DEFAULTS, dict(self.DEFAULTS)) == cell

    def test_a_set_axis_is_passed_through(self):
        cell = {"clustering_threshold": 0.8, "min_cluster_size": None,
                "min_duration_off": None}
        current = dict(self.DEFAULTS, clustering_threshold=0.6)
        assert sd._restore_unset(cell, self.DEFAULTS, current) == cell


@pytest.fixture
def sweep_env(monkeypatch):
    seen = []

    def diarise(pipe, audio, sample_rate):
        seen.append(pipe.parameters()["clustering"]["threshold"])
        return [{"start": 0.0, "end": 1.0, "speaker": "X"}]

    stats = {"duration_s": 60.0, "n_speakers": 2}
    monkeypatch.setattr(sd, "build_corpus", lambda **kw: iter(
        [("M0", [0.0], [{"start": 0.0, "end": 1.0, "speaker": "A"}], stats)]))
    monkeypatch.setattr(sd, "load_pipeline", lambda *a, **k: FakePipeline())
    monkeypatch.setattr(sd, "_load_hf_token", lambda: None)
    monkeypatch.setattr(sd, "diarise", diarise)
    monkeypatch.setattr(dm, "annotation_from_segments", lambda segs, uri="": segs)
    monkeypatch.setattr(dm, "compute_der", lambda r, h, collar=0.25: {
        "uri": "", "der": 0.2, "missed_speech": 0.1, "false_alarm": 0.05,
        "speaker_confusion": 0.05, "total_ref_duration": 1.0,
        "_missed_abs": 0.1, "_fa_abs": 0.05, "_confusion_abs": 0.05})
    return seen


class TestMixedGridFromPython:
    def test_a_trailing_defaults_cell_runs_at_the_default(self, tmp_path, sweep_env):
        """The finding's own example: thresholds=(0.6, None)."""
        sd.run_sweep(tmp_path, thresholds=(0.6, None))
        assert sweep_env == [pytest.approx(0.6), pytest.approx(DEFAULT_THRESHOLD)]

    def test_the_resolved_values_are_written(self, tmp_path, sweep_env):
        sd.run_sweep(tmp_path, thresholds=(0.6, None))
        rows = list(csv.DictReader(
            (tmp_path / "der_sweep_summary.csv").open(encoding="utf-8")))
        assert [float(r["resolved_clustering_threshold"]) for r in rows] == [
            pytest.approx(0.6), pytest.approx(DEFAULT_THRESHOLD)]
        assert {r["resolved_min_cluster_size"] for r in rows} == {"12"}


class TestSelectionRecord:
    def test_the_grid_and_environment_are_recorded(self, tmp_path, sweep_env):
        sd.run_sweep(tmp_path, thresholds=(0.6, 0.7), model_id="some/model")
        selection = json.loads((tmp_path / "der_sweep_selection.json")
                               .read_text(encoding="utf-8"))
        assert selection["model"] == "some/model"
        assert selection["grid"]["clustering_threshold"] == [0.6, 0.7]
        assert selection["pipeline_defaults"]["clustering"]["threshold"] == \
            pytest.approx(DEFAULT_THRESHOLD)
        assert "git_commit" in selection and "argv" in selection

    def test_an_output_prefix_names_all_three_files(self, tmp_path, sweep_env):
        sd.run_sweep(tmp_path, thresholds=(0.6,), output_prefix="der_sweep2")
        for name in ("der_sweep2.csv", "der_sweep2_summary.csv",
                     "der_sweep2_selection.json"):
            assert (tmp_path / name).exists()
        assert not (tmp_path / "der_sweep.csv").exists()

    @pytest.mark.parametrize("bad", ["", "sub/der", "../der"])
    def test_a_prefix_that_is_a_path_is_refused(self, tmp_path, bad):
        with pytest.raises(SystemExit, match="output-prefix"):
            sd.run_sweep(tmp_path, output_prefix=bad)

    def test_the_default_prefix_keeps_the_historical_names(self):
        assert sd._parse_args([]).output_prefix == "der_sweep"
