"""Tests for ``evaluation.condition_ci``.

The module's job is file discovery and baseline pairing; the statistics
belong to ``evaluation.bootstrap_ci`` and are tested there. What matters
here is that the right files are paired against the right baseline, that
the sweep's habit of writing its first condition to the unsuffixed
primary path is handled, and that a condition scored on a different set
of utterances is intersected rather than silently misaligned.

Like the bootstrap tests, these need only ``numpy`` and the standard
library.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

pytest.importorskip("numpy")

from evaluation.condition_ci import (
    compare_all,
    discover_reports,
    write_rows,
)


def _write_report(path: Path, rows: list[tuple[str, float]]) -> None:
    """Write a minimal per-utterance report of the shape the sweep emits."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["name", "wer"])
        writer.writerows(rows)


@pytest.fixture()
def sweep_dir(tmp_path: Path) -> Path:
    """A directory shaped like one cell of the condition sweep."""
    d = tmp_path / "sweep_reports"
    base = [(f"utt{i:03d}", 0.10) for i in range(60)]
    _write_report(d / "wer_report.csv", base)                       # raw
    _write_report(d / "wer_report_costly.csv",
                  [(n, w + 0.05) for n, w in base])
    _write_report(d / "wer_report_identical.csv", base)
    return d


class TestDiscovery:
    def test_the_primary_file_is_recorded_separately(self, sweep_dir: Path):
        found = discover_reports(sweep_dir)
        assert found["__primary__"].name == "wer_report.csv"
        assert set(found) == {"__primary__", "costly", "identical"}

    def test_an_empty_directory_yields_nothing(self, tmp_path: Path):
        assert discover_reports(tmp_path) == {}


class TestBaselinePairing:
    def test_the_unsuffixed_file_is_used_when_the_baseline_has_no_file(
        self, sweep_dir: Path
    ):
        """The sweep writes its first condition to the primary path.

        ``raw`` therefore has no ``wer_report_raw.csv`` of its own, and
        must fall back to ``wer_report.csv`` rather than failing.
        """
        rows = compare_all(sweep_dir, baseline="raw", b=400)
        assert {r["condition"] for r in rows} == {"costly", "identical"}

    def test_the_baseline_is_never_compared_against_itself(
        self, sweep_dir: Path
    ):
        rows = compare_all(sweep_dir, baseline="raw", b=400)
        assert "raw" not in {r["condition"] for r in rows}
        assert "__primary__" not in {r["condition"] for r in rows}

    def test_a_named_baseline_file_overrides_the_default(
        self, sweep_dir: Path
    ):
        rows = compare_all(sweep_dir, baseline="raw", b=400,
                           baseline_file=sweep_dir / "wer_report_costly.csv")
        by = {r["condition"]: r for r in rows}
        # Scored against the costly arm, the others come out 0.05 better.
        assert by["identical"]["delta"] == pytest.approx(-0.05, abs=1e-9)

    def test_a_missing_baseline_is_an_error(self, tmp_path: Path):
        _write_report(tmp_path / "wer_report_only.csv", [("a", 0.1)])
        # A missing baseline is a FileNotFoundError from the library;
        # main() turns it into exit status 2 (ESTATS-14).
        with pytest.raises(FileNotFoundError):
            compare_all(tmp_path, baseline="absent", b=100)


class TestDeltas:
    def test_an_identical_condition_has_a_zero_delta(self, sweep_dir: Path):
        rows = compare_all(sweep_dir, baseline="raw", b=800)
        identical = next(r for r in rows if r["condition"] == "identical")
        assert identical["delta"] == pytest.approx(0.0, abs=1e-12)
        assert identical["excludes_zero"] == 0

    def test_a_uniform_penalty_is_recovered_and_is_significant(
        self, sweep_dir: Path
    ):
        rows = compare_all(sweep_dir, baseline="raw", b=800)
        costly = next(r for r in rows if r["condition"] == "costly")
        assert costly["delta"] == pytest.approx(0.05, abs=1e-9)
        assert costly["ci_lo"] <= 0.05 <= costly["ci_hi"]
        assert costly["excludes_zero"] == 1

    def test_only_shared_utterances_are_compared(self, tmp_path: Path):
        """A condition that dropped utterances must be intersected.

        ``whisper_norm`` discards utterances whose reference normalises
        to empty, so its report is shorter than the baseline's. Pairing
        must restrict to the overlap rather than aligning by position.
        """
        base = [(f"utt{i:03d}", 0.20) for i in range(40)]
        _write_report(tmp_path / "wer_report.csv", base)
        _write_report(tmp_path / "wer_report_short.csv", base[:25])
        rows = compare_all(tmp_path, baseline="raw", b=400)
        assert rows[0]["n"] == 25


class TestOutput:
    def test_the_written_csv_round_trips(self, sweep_dir: Path,
                                         tmp_path: Path):
        rows = compare_all(sweep_dir, baseline="raw", b=400)
        out = tmp_path / "nested" / "condition_ci.csv"
        write_rows(rows, out)
        with open(out, encoding="utf-8") as handle:
            back = list(csv.DictReader(handle))
        assert len(back) == len(rows)
        assert back[0]["condition"] == rows[0]["condition"]
        assert set(back[0]) == {
            "condition", "n", "macro_condition", "macro_baseline",
            "delta", "ci_lo", "ci_hi", "p_value", "excludes_zero",
            "bootstrap", "seed",
        }

    def test_the_replicate_count_and_seed_are_recorded_in_the_artefact(
        self, sweep_dir: Path, tmp_path: Path
    ):
        """The settings must travel with the estimate.

        A percentile bound carries Monte Carlo error of its own, so an
        interval quoted without the replicate count that produced it
        cannot be reproduced. Recording ``bootstrap`` and ``seed`` in
        the CSV lets the manuscript read them from the artefact instead
        of asserting them in a caption.
        """
        rows = compare_all(sweep_dir, baseline="raw", b=613, seed=11)
        assert all(r["bootstrap"] == 613 and r["seed"] == 11 for r in rows)
        out = tmp_path / "condition_ci.csv"
        write_rows(rows, out)
        with open(out, encoding="utf-8") as handle:
            back = list(csv.DictReader(handle))
        assert {r["bootstrap"] for r in back} == {"613"}
        assert {r["seed"] for r in back} == {"11"}

    def test_results_are_deterministic_under_a_fixed_seed(
        self, sweep_dir: Path
    ):
        first = compare_all(sweep_dir, baseline="raw", b=500, seed=7)
        second = compare_all(sweep_dir, baseline="raw", b=500, seed=7)
        assert first == second
