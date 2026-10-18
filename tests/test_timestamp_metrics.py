"""
Unit tests for evaluation.timestamp_metrics.

No optional dependencies — timestamp_metrics depends only on the Python
standard library.  All tests use synthetic numeric inputs.
"""

import math
import pytest

from evaluation.timestamp_metrics import boundary_error, aggregate_boundary_errors


class TestBoundaryError:
    def test_perfect_prediction(self):
        result = boundary_error(hyp_start=0.0, hyp_end=5.0, ref_duration=5.0)
        assert result["start_error"] == pytest.approx(0.0)
        assert result["end_error"] == pytest.approx(0.0)
        assert result["abs_start_error"] == pytest.approx(0.0)
        assert result["abs_end_error"] == pytest.approx(0.0)
        assert result["abs_total_error"] == pytest.approx(0.0)

    def test_late_start_gives_positive_start_error(self):
        # Whisper started 0.2 s late.
        result = boundary_error(hyp_start=0.2, hyp_end=3.0, ref_duration=3.0)
        assert result["start_error"] == pytest.approx(0.2)
        assert result["abs_start_error"] == pytest.approx(0.2)
        # end_error = 3.0 - 3.0 = 0.0
        assert result["end_error"] == pytest.approx(0.0)

    def test_early_stop_gives_positive_end_error(self):
        # Whisper stopped 0.3 s early.
        result = boundary_error(hyp_start=0.0, hyp_end=4.7, ref_duration=5.0)
        assert result["end_error"] == pytest.approx(0.3)
        assert result["abs_end_error"] == pytest.approx(0.3)

    def test_overrun_end_gives_negative_end_error(self):
        # Whisper extended 0.5 s beyond the clip end.
        result = boundary_error(hyp_start=0.0, hyp_end=5.5, ref_duration=5.0)
        assert result["end_error"] == pytest.approx(-0.5)
        assert result["abs_end_error"] == pytest.approx(0.5)

    def test_abs_total_error_is_sum_of_absolute_errors(self):
        result = boundary_error(hyp_start=0.1, hyp_end=4.8, ref_duration=5.0)
        expected_total = abs(0.1) + abs(5.0 - 4.8)
        assert result["abs_total_error"] == pytest.approx(expected_total)

    def test_all_required_keys_present(self):
        result = boundary_error(hyp_start=0.0, hyp_end=2.0, ref_duration=2.0)
        required = {
            "start_error", "end_error",
            "abs_start_error", "abs_end_error", "abs_total_error",
        }
        assert required.issubset(result.keys())


class TestAggregateBoundaryErrors:
    def test_empty_reports_every_metric_as_undefined(self):
        """ESTATS-14: zeros at n = 0 read as a perfect run."""
        result = aggregate_boundary_errors([])
        assert result["n"] == 0
        for key in ("mae_start", "mae_end", "mae_total", "rmse_start",
                    "rmse_end", "mean_start_error", "mean_end_error"):
            assert result[key] is None, key
        # The same keys as a non-empty aggregate, so a reader never KeyErrors.
        assert result.keys() == aggregate_boundary_errors(
            [boundary_error(0.0, 1.0, 1.0)]).keys()

    def test_single_record_matches_input(self):
        rec = boundary_error(hyp_start=0.1, hyp_end=4.9, ref_duration=5.0)
        result = aggregate_boundary_errors([rec])
        assert result["n"] == 1
        assert result["mae_start"] == pytest.approx(rec["abs_start_error"])
        assert result["mae_end"] == pytest.approx(rec["abs_end_error"])

    def test_mae_is_mean_of_absolute_errors(self):
        recs = [
            boundary_error(0.0, 3.0, 3.0),   # both 0
            boundary_error(0.2, 2.8, 3.0),   # start=0.2, end=0.2
        ]
        result = aggregate_boundary_errors(recs)
        assert result["mae_start"] == pytest.approx(0.1)  # (0.0 + 0.2) / 2
        assert result["mae_end"] == pytest.approx(0.1)    # (0.0 + 0.2) / 2

    def test_mae_total_is_mean_abs_total_error(self):
        recs = [
            boundary_error(0.0, 5.0, 5.0),  # total = 0
            boundary_error(0.3, 4.5, 5.0),  # total = 0.3 + 0.5 = 0.8
        ]
        result = aggregate_boundary_errors(recs)
        assert result["mae_total"] == pytest.approx(0.4)  # (0 + 0.8) / 2

    def test_rmse_start_equals_sqrt_mean_squared_error(self):
        recs = [
            boundary_error(0.0, 5.0, 5.0),  # start_error = 0
            boundary_error(0.4, 5.0, 5.0),  # start_error = 0.4
        ]
        result = aggregate_boundary_errors(recs)
        expected_rmse = math.sqrt((0.0 ** 2 + 0.4 ** 2) / 2)
        assert result["rmse_start"] == pytest.approx(expected_rmse)

    def test_rmse_end_equals_sqrt_mean_squared_error(self):
        recs = [
            boundary_error(0.0, 4.0, 5.0),  # end_error = 1.0
            boundary_error(0.0, 5.0, 5.0),  # end_error = 0.0
        ]
        result = aggregate_boundary_errors(recs)
        expected_rmse = math.sqrt((1.0 ** 2 + 0.0 ** 2) / 2)
        assert result["rmse_end"] == pytest.approx(expected_rmse)

    def test_mean_signed_error_directions(self):
        # Systematically late starts (positive start_error) and early stops
        # (positive end_error): mean_start_error and mean_end_error should be
        # positive.
        recs = [
            boundary_error(0.1, 4.9, 5.0),
            boundary_error(0.2, 4.8, 5.0),
        ]
        result = aggregate_boundary_errors(recs)
        assert result["mean_start_error"] > 0.0
        assert result["mean_end_error"] > 0.0

    def test_all_required_keys_present(self):
        recs = [boundary_error(0.0, 2.0, 2.0)]
        result = aggregate_boundary_errors(recs)
        required = {
            "n", "mae_start", "mae_end", "mae_total",
            "rmse_start", "rmse_end",
            "mean_start_error", "mean_end_error",
            "median_abs_end_error", "p90_abs_end_error",
            "gross_end_error_rate", "truncation_rate",
        }
        assert required.issubset(result.keys())


class TestRobustSummary:
    """The mean alone misdescribes a tail-driven distribution.

    Measured on the AMI IHM split: median absolute end error 10 ms against
    a mean of 127 ms, because roughly one utterance in twelve is out by
    more than half a second and those few dominate the mean. These tests
    pin the statistics that make the difference visible, and the one that
    names the failure's direction.
    """

    def _tail_case(self):
        """Nine near-perfect utterances and one badly truncated."""
        recs = [boundary_error(0.0, 2.0, 2.0) for _ in range(9)]
        recs.append(boundary_error(0.0, 0.4, 4.0))   # stopped 3.6 s early
        return recs

    def test_median_resists_the_tail_that_moves_the_mean(self):
        result = aggregate_boundary_errors(self._tail_case())
        assert result["median_abs_end_error"] == pytest.approx(0.0)
        assert result["mae_end"] > 0.3          # one outlier moves the mean
        assert result["mae_end"] > result["median_abs_end_error"]

    def test_gross_error_rate_counts_the_tail(self):
        result = aggregate_boundary_errors(self._tail_case())
        assert result["gross_end_error_rate"] == pytest.approx(0.1)

    def test_truncation_rate_separates_early_stops_from_overruns(self):
        """Direction matters: stopping early and running on are different
        failures with different remedies, and only the sign distinguishes
        them. On AMI every gross error was an early stop."""
        early = [boundary_error(0.0, 0.4, 4.0)]          # hypothesis too short
        late = [boundary_error(0.0, 7.6, 4.0)]           # hypothesis too long
        assert aggregate_boundary_errors(early)["truncation_rate"] == 1.0
        assert aggregate_boundary_errors(late)["truncation_rate"] == 0.0
        # Both are gross errors; only the truncation rate tells them apart.
        assert aggregate_boundary_errors(early)["gross_end_error_rate"] == 1.0
        assert aggregate_boundary_errors(late)["gross_end_error_rate"] == 1.0

    def test_percentiles_return_observed_values(self):
        recs = [boundary_error(0.0, 2.0 - d, 2.0) for d in
                (0.0, 0.01, 0.02, 0.03, 1.0)]
        result = aggregate_boundary_errors(recs)
        assert result["p90_abs_end_error"] == pytest.approx(1.0)
        assert result["median_abs_end_error"] == pytest.approx(0.02)

    def test_empty_input_reports_undefined_robust_keys(self):
        result = aggregate_boundary_errors([])
        for key in ("median_abs_end_error", "p90_abs_end_error",
                    "gross_end_error_rate", "truncation_rate"):
            assert result[key] is None, key


class TestPercentileEstimator:
    """ESTATS-16: pin the estimator the published table used.

    It is the observation nearest the linear-interpolation position
    (numpy's method="nearest", ties to even), not textbook nearest-rank,
    so even-length medians alternate between the two middle values.
    """

    def test_even_length_medians_follow_round_half_to_even(self):
        from evaluation.timestamp_metrics import _percentile
        assert _percentile([1, 2], 0.5) == 1
        assert _percentile([1, 2, 3, 4], 0.5) == 3
        assert _percentile([1, 2, 3, 4, 5, 6], 0.5) == 3

    def test_p90_is_one_rank_below_nearest_rank_at_n_499(self):
        from evaluation.timestamp_metrics import _percentile
        values = list(range(1, 500))                  # 1..499
        assert _percentile(values, 0.9) == 449        # nearest-rank: 450

    def test_matches_numpy_nearest(self):
        np = pytest.importorskip("numpy")
        from evaluation.timestamp_metrics import _percentile
        for n in range(1, 40):
            values = list(range(n))
            for q in (0.1, 0.25, 0.5, 0.75, 0.9):
                assert _percentile(values, q) == np.quantile(
                    values, q, method="nearest"), (n, q)

    def test_empty_has_no_percentile(self):
        from evaluation.timestamp_metrics import _percentile
        assert _percentile([], 0.5) is None
