"""Tests for the parts of the DER benchmark that need no GPU.

The pyannote packages are not installable under the local Python, so the
pipeline is stood in for by fakes that reproduce the interface the
benchmark relies on. The fakes include a *lying* pipeline, which accepts
a hyperparameter and then reports the old value: that is the failure the
benchmark must refuse to run through, because a sweep over a parameter
that never applies reports that the parameter has no effect.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.benchmark_der import (
    _cache_paths,
    _corpus_summary,
    apply_hyperparameters,
    uses_powerset,
)


class FakePipeline:
    """Enough of pyannote's Pipeline surface for the parameter logic."""

    def __init__(self, params=None, honest=True, powerset=True):
        self._params = params if params is not None else {
            "segmentation": {"min_duration_off": 0.0},
            "clustering": {"method": "centroid", "min_cluster_size": 12,
                           "threshold": 0.7045654963945799},
        }
        self._honest = honest
        self._powerset = powerset
        self.instantiate_calls = 0

    def parameters(self, instantiated=False):
        # A copy, as pyannote's own accessor returns a live tree the
        # caller is expected to mutate before handing it back.
        return {group: dict(values) for group, values in self._params.items()}

    def instantiate(self, params):
        self.instantiate_calls += 1
        if self._honest:
            self._params = {g: dict(v) for g, v in params.items()}

    class _Spec:
        def __init__(self, powerset):
            self.powerset = powerset

    class _Model:
        def __init__(self, powerset):
            self.specifications = FakePipeline._Spec(powerset)

    class _Seg:
        def __init__(self, powerset):
            self.model = FakePipeline._Model(powerset)

    @property
    def _segmentation(self):
        return FakePipeline._Seg(self._powerset)


class TestApplyHyperparameters:
    def test_no_overrides_leaves_the_pipeline_untouched(self):
        pipe = FakePipeline()
        record = apply_hyperparameters(pipe)
        assert pipe.instantiate_calls == 0
        assert record["clustering"]["threshold"] == pytest.approx(0.70456549)

    def test_a_float_override_is_written_and_reported(self):
        pipe = FakePipeline()
        record = apply_hyperparameters(pipe, clustering_threshold=0.55)
        assert pipe.instantiate_calls == 1
        assert record["clustering"]["threshold"] == pytest.approx(0.55)

    def test_an_integer_override_reaches_the_right_group(self):
        pipe = FakePipeline()
        record = apply_hyperparameters(pipe, min_cluster_size=20)
        assert record["clustering"]["min_cluster_size"] == 20
        assert record["segmentation"]["min_duration_off"] == 0.0

    def test_segmentation_and_clustering_can_be_set_together(self):
        pipe = FakePipeline()
        record = apply_hyperparameters(pipe, clustering_threshold=0.6,
                                       min_duration_off=0.5)
        assert record["clustering"]["threshold"] == pytest.approx(0.6)
        assert record["segmentation"]["min_duration_off"] == pytest.approx(0.5)

    def test_none_values_are_ignored_rather_than_written(self):
        pipe = FakePipeline()
        apply_hyperparameters(pipe, clustering_threshold=None,
                              min_cluster_size=None, min_duration_off=None)
        assert pipe.instantiate_calls == 0

    def test_an_override_that_does_not_take_effect_stops_the_run(self):
        """The whole point of the read-back check."""
        pipe = FakePipeline(honest=False)
        with pytest.raises(SystemExit, match="did not take effect"):
            apply_hyperparameters(pipe, clustering_threshold=0.55)

    def test_a_silently_ignored_integer_also_stops_the_run(self):
        pipe = FakePipeline(honest=False)
        with pytest.raises(SystemExit, match="did not take effect"):
            apply_hyperparameters(pipe, min_cluster_size=30)

    def test_an_unknown_parameter_name_is_refused(self):
        pipe = FakePipeline()
        with pytest.raises(SystemExit, match="not tunable"):
            apply_hyperparameters(pipe, segmentation_threshold=0.5)

    def test_a_parameter_absent_from_this_pipeline_is_refused(self):
        """Guards against a pipeline version that drops a knob."""
        pipe = FakePipeline(params={"clustering": {"threshold": 0.7}})
        with pytest.raises(SystemExit, match="does not expose"):
            apply_hyperparameters(pipe, min_duration_off=0.5)


class TestUsesPowerset:
    def test_detects_a_powerset_segmentation_head(self):
        assert uses_powerset(FakePipeline(powerset=True)) is True

    def test_detects_a_binary_segmentation_head(self):
        assert uses_powerset(FakePipeline(powerset=False)) is False

    def test_an_unfamiliar_pipeline_is_not_assumed_to_be_powerset(self):
        class Bare:
            pass

        assert uses_powerset(Bare()) is False


class TestCachePaths:
    """Reading the wrong cache would silently score the wrong corpus, so
    everything that limits a meeting's extent must reach the name."""

    def test_a_duration_cap_names_the_directory(self):
        root = Path("/cache")
        full = _cache_paths(root, "test", "timeline", None)
        capped = _cache_paths(root, "test", "timeline", 10)
        assert full.name == "test_timeline_full"
        assert capped.name == "test_timeline_10min"
        assert full != capped

    def test_the_utterance_cap_names_a_concatenation(self):
        """The duration cap does not apply to concat, the utterance cap does."""
        root = Path("/cache")
        twenty_five = _cache_paths(root, "test", "concat", None, 25)
        fifty = _cache_paths(root, "test", "concat", None, 50)
        assert twenty_five.name == "test_concat_25utt"
        assert fifty.name == "test_concat_50utt"
        assert twenty_five != fifty

    def test_splits_and_modes_stay_separate(self):
        root = Path("/cache")
        names = {
            _cache_paths(root, "test", "timeline", None),
            _cache_paths(root, "validation", "timeline", None),
            _cache_paths(root, "test", "concat", None, 25),
        }
        assert len(names) == 3

    def test_an_uncapped_concatenation_is_named_rather_than_left_blank(self):
        assert _cache_paths(Path("/c"), "test", "concat", None, None).name \
            == "test_concat_all"


class TestCorpusSummary:
    def _stats(self, duration, speech, overlap, speakers):
        return {"duration_s": duration, "speech_s": speech,
                "overlap_s": overlap, "n_speakers": speakers}

    def test_aggregates_across_meetings(self):
        summary = _corpus_summary([
            self._stats(3600, 1800, 180, 4),
            self._stats(3600, 3600, 720, 3),
        ])
        assert summary["audio_hours"] == pytest.approx(2.0)
        assert summary["speech_hours"] == pytest.approx(1.5)
        assert summary["overlap_fraction"] == pytest.approx(900 / 5400, abs=1e-4)
        assert summary["silence_fraction"] == pytest.approx(1800 / 7200, abs=1e-4)
        assert summary["mean_speakers_per_meeting"] == pytest.approx(3.5)

    def test_empty_input_is_not_a_division_by_zero(self):
        assert _corpus_summary([]) == {}


class TestSweepGrid:
    """The grid must be able to answer whether tuning beats the default."""

    def _grid(self, *args, **kwargs):
        from evaluation.sweep_der import _grid
        return _grid(*args, **kwargs)

    def test_the_default_cell_is_scored_first(self):
        cells = self._grid([0.6, 0.7], [None], [None])
        assert cells[0] == {"clustering_threshold": None,
                            "min_cluster_size": None, "min_duration_off": None}
        assert len(cells) == 3

    def test_the_default_cell_is_not_duplicated(self):
        cells = self._grid([None], [None], [None])
        assert len(cells) == 1

    def test_it_can_be_turned_off(self):
        cells = self._grid([0.6, 0.7], [None], [None], include_default=False)
        assert len(cells) == 2
        assert all(c["clustering_threshold"] is not None for c in cells)

    def test_the_product_covers_every_combination(self):
        cells = self._grid([0.6, 0.7], [12, 15], [0.0, 0.5],
                           include_default=False)
        assert len(cells) == 8
        assert len({tuple(sorted(c.items())) for c in cells}) == 8

    def test_the_order_is_stable_across_calls(self):
        first = self._grid([0.6, 0.7], [12], [0.0, 0.5])
        second = self._grid([0.6, 0.7], [12], [0.0, 0.5])
        assert first == second
