"""Tests for the bootstrap confidence intervals in ``evaluation.bootstrap_ci``.

These exercise the statistical contract of the module without any audio
or scoring stack: the macro-WER CI must bracket the observed mean and
should narrow as the number of replicates grows or the spread of the
per-utterance WERs shrinks, and the paired delta CI on two identical
conditions must contain zero.

The module depends only on ``numpy`` and the standard library, so the
tests run without the optional ``jiwer``/``torch``/``transformers`` deps.
"""

from __future__ import annotations

import csv

import pytest

np = pytest.importorskip("numpy")

from evaluation.bootstrap_ci import (  # noqa: E402
    align_reports,
    bootstrap_macro,
    paired_delta,
    read_wer_report,
    write_ci_csv,
)


def _ci_width(lo: float, hi: float) -> float:
    return hi - lo


def test_macro_ci_brackets_the_observed_mean():
    """The percentile CI must straddle the observed macro-WER."""
    rng = np.random.default_rng(0)
    wers = rng.uniform(0.0, 0.4, size=500)
    mean, lo, hi = bootstrap_macro(wers, b=2000, seed=42)
    assert np.isclose(mean, wers.mean())
    assert lo <= mean <= hi


def test_macro_ci_is_reproducible_under_seed():
    wers = np.linspace(0.0, 0.5, 200)
    a = bootstrap_macro(wers, b=1000, seed=7)
    b = bootstrap_macro(wers, b=1000, seed=7)
    assert a == b


def test_macro_ci_narrows_as_variance_shrinks():
    """Lower per-utterance spread gives a tighter interval on the mean."""
    rng = np.random.default_rng(1)
    base = rng.uniform(0.0, 1.0, size=400)
    wide = 0.5 + (base - 0.5) * 0.40   # spread around 0.5
    tight = 0.5 + (base - 0.5) * 0.05  # same shape, much smaller spread
    _, lo_wide, hi_wide = bootstrap_macro(wide, b=3000, seed=42)
    _, lo_tight, hi_tight = bootstrap_macro(tight, b=3000, seed=42)
    assert _ci_width(lo_tight, hi_tight) < _ci_width(lo_wide, hi_wide)


def test_macro_ci_stabilises_as_replicates_grow():
    """More replicates give a more stable percentile estimate: two runs
    with different seeds agree more closely at large B than at small B."""
    rng = np.random.default_rng(2)
    wers = rng.uniform(0.0, 0.6, size=300)

    def _spread_between_seeds(b: int) -> float:
        _, lo1, hi1 = bootstrap_macro(wers, b=b, seed=1)
        _, lo2, hi2 = bootstrap_macro(wers, b=b, seed=2)
        return abs(lo1 - lo2) + abs(hi1 - hi2)

    small = _spread_between_seeds(100)
    large = _spread_between_seeds(8000)
    assert large < small


def test_macro_ci_collapses_to_point_when_no_variance():
    """A constant WER vector has no sampling variance: the CI is a point."""
    wers = np.full(50, 0.2)
    mean, lo, hi = bootstrap_macro(wers, b=1000, seed=42)
    assert np.isclose(mean, 0.2)
    assert np.isclose(lo, 0.2)
    assert np.isclose(hi, 0.2)


def test_paired_delta_on_identical_arrays_contains_zero():
    """Two identical conditions have a zero delta on every resample, so
    the CI is a point at zero and trivially contains zero."""
    rng = np.random.default_rng(3)
    wers = rng.uniform(0.0, 0.5, size=400)
    res = paired_delta(wers, wers.copy(), b=2000, seed=42)
    assert np.isclose(res["delta"], 0.0)
    assert res["ci_lo"] <= 0.0 <= res["ci_hi"]
    assert res["ci_excludes_zero"] is False


def test_paired_delta_detects_a_uniform_shift():
    """When B is uniformly better than A by a clear margin, the paired CI
    excludes zero and the delta equals the shift."""
    rng = np.random.default_rng(4)
    wers_b = rng.uniform(0.05, 0.45, size=400)
    wers_a = wers_b + 0.10  # A is uniformly 0.10 worse
    res = paired_delta(wers_a, wers_b, b=2000, seed=42)
    assert np.isclose(res["delta"], 0.10)
    assert res["ci_excludes_zero"] is True
    assert res["ci_lo"] > 0.0
    assert res["p_value"] < 0.05


def test_paired_delta_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        paired_delta(np.zeros(3), np.zeros(4))


def test_align_reports_intersects_on_shared_names():
    names_a = ["u1", "u2", "u3"]
    wers_a = np.array([0.1, 0.2, 0.3])
    names_b = ["u3", "u2", "u4"]  # different order, partial overlap
    wers_b = np.array([0.9, 0.8, 0.7])
    shared, a, b = align_reports(names_a, wers_a, names_b, wers_b)
    assert shared == ["u2", "u3"]
    assert np.allclose(a, [0.2, 0.3])   # from report A, reordered
    assert np.allclose(b, [0.8, 0.9])   # from report B, reordered


# The library functions raise ValueError; main() turns it into exit
# status 2 (ESTATS-14).
_INPUT_ERROR = ValueError


def test_align_reports_raises_without_overlap():
    with pytest.raises(_INPUT_ERROR):
        align_reports(["a"], np.array([0.1]), ["b"], np.array([0.2]))


def test_read_wer_report_roundtrip(tmp_path):
    """A minimal CSV with name/wer columns is read back as aligned arrays."""
    path = tmp_path / "wer_report.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "wer", "cer"])
        writer.writerow(["u1", "0.0", "0.0"])
        writer.writerow(["u2", "0.5", "0.2"])
        writer.writerow(["u3", "", "0.0"])   # blank wer: skipped
    names, wers = read_wer_report(path)
    assert names == ["u1", "u2"]
    assert np.allclose(wers, [0.0, 0.5])


def test_written_ci_csv_records_the_replicate_count_and_seed(tmp_path):
    """The settings that produced an interval must be in the artefact.

    A percentile bound is itself an estimate and carries Monte Carlo
    error, so the same data under a different replicate count gives a
    slightly different interval. Writing ``bootstrap`` and ``seed``
    into the CSV lets a reader, and the manuscript, recover the
    settings instead of taking a caption's word for them.
    """
    out = tmp_path / "nested" / "wer_ci.csv"
    rows = [{"file": "a.csv", "n": 3, "macro_wer": 0.1,
             "ci_lo": 0.05, "ci_hi": 0.15}]
    write_ci_csv(rows, out, b=1234, seed=99)
    with open(out, encoding="utf-8") as f:
        back = list(csv.DictReader(f))
    assert list(back[0]) == ["file", "n", "macro_wer", "ci_lo", "ci_hi",
                             "bootstrap", "seed"]
    assert back[0]["bootstrap"] == "1234"
    assert back[0]["seed"] == "99"


def test_written_ci_csv_prefers_settings_carried_on_the_row(tmp_path):
    """A row that already names its own settings keeps them."""
    out = tmp_path / "wer_ci.csv"
    rows = [{"file": "a.csv", "n": 3, "macro_wer": 0.1,
             "ci_lo": 0.05, "ci_hi": 0.15, "bootstrap": 7, "seed": 3}]
    write_ci_csv(rows, out, b=1234, seed=99)
    with open(out, encoding="utf-8") as f:
        back = list(csv.DictReader(f))
    assert back[0]["bootstrap"] == "7"
    assert back[0]["seed"] == "3"


def test_read_wer_report_rejects_missing_wer_column(tmp_path):
    path = tmp_path / "bad.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "cer"])
        writer.writerow(["u1", "0.0"])
    with pytest.raises(_INPUT_ERROR):
        read_wer_report(path)
