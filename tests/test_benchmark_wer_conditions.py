"""Tests for the ``--conditions`` plumbing in ``evaluation.benchmark_wer``.

These tests cover the pure helper functions that translate CLI arguments
into a list of per-condition run specifications and corresponding output
paths.  They do not exercise the dataset-streaming or model-inference
path, which requires GPU and network access.

``benchmark_wer`` imports its scoring dependencies (jiwer, datasets,
transformers) lazily, so the module and these pure helpers load without
them and the tests run in any environment.
"""

from __future__ import annotations

from pathlib import Path

from evaluation import benchmark_wer as b  # noqa: E402


# ---------------------------------------------------------------------------
# _parse_conditions_arg
# ---------------------------------------------------------------------------

def test_parse_conditions_none_returns_empty():
    assert b._parse_conditions_arg(None) == []


def test_parse_conditions_empty_string_returns_empty():
    assert b._parse_conditions_arg("") == []
    assert b._parse_conditions_arg("   ") == []


def test_parse_conditions_single_value():
    assert b._parse_conditions_arg("raw") == ["raw"]


def test_parse_conditions_strips_whitespace():
    assert b._parse_conditions_arg(" raw , repetition_fix ") == [
        "raw", "repetition_fix",
    ]


def test_parse_conditions_deduplicates_preserving_order():
    assert b._parse_conditions_arg("raw,raw,whisper_norm,raw") == [
        "raw", "whisper_norm",
    ]


# ---------------------------------------------------------------------------
# _derive_condition_paths
# ---------------------------------------------------------------------------

def test_derive_paths_first_condition_uses_primary():
    pr = Path("output/evaluation/wer_report.csv")
    ps = Path("output/evaluation/wer_summary.json")
    report, summary = b._derive_condition_paths(pr, ps, "raw", is_first=True)
    assert report == pr
    assert summary == ps


def test_derive_paths_subsequent_condition_appends_suffix():
    pr = Path("output/evaluation/wer_report.csv")
    ps = Path("output/evaluation/wer_summary.json")
    report, summary = b._derive_condition_paths(
        pr, ps, "whisper_norm", is_first=False,
    )
    assert report == Path("output/evaluation/wer_report_whisper_norm.csv")
    assert summary == Path(
        "output/evaluation/wer_summary_whisper_norm.json",
    )


def test_derive_paths_handles_none_summary():
    pr = Path("a/wer_report.csv")
    report, summary = b._derive_condition_paths(
        pr, None, "repetition_fix", is_first=False,
    )
    assert report == Path("a/wer_report_repetition_fix.csv")
    assert summary is None


# ---------------------------------------------------------------------------
# _build_runs
# ---------------------------------------------------------------------------

def test_build_runs_empty_conditions_single_raw_run():
    pr = Path("a/wer_report.csv")
    ps = Path("a/wer_summary.json")
    runs = b._build_runs([], pr, ps)
    assert len(runs) == 1
    assert runs[0].condition_name == "raw"
    assert runs[0].report_path == pr
    assert runs[0].summary_path == ps


def test_build_runs_conditions_first_writes_to_primary():
    pr = Path("a/wer_report.csv")
    ps = Path("a/wer_summary.json")
    runs = b._build_runs(
        ["raw", "repetition_fix", "whisper_norm"], pr, ps,
    )
    assert [r.condition_name for r in runs] == [
        "raw", "repetition_fix", "whisper_norm",
    ]
    assert runs[0].report_path == pr
    assert runs[0].summary_path == ps
    assert runs[1].report_path == Path("a/wer_report_repetition_fix.csv")
    assert runs[1].summary_path == Path("a/wer_summary_repetition_fix.json")
    assert runs[2].report_path == Path("a/wer_report_whisper_norm.csv")
    assert runs[2].summary_path == Path("a/wer_summary_whisper_norm.json")


def test_the_repetition_fix_run_uses_the_condition_naming_rule():
    """The removed legacy flags had a naming rule of their own (EWER-16);
    --conditions raw,repetition_fix now gives the same run with the one
    rule every other condition follows."""
    pr = Path("a/wer_report.csv")
    ps = Path("a/wer_summary.json")
    runs = b._build_runs(["raw", "repetition_fix"], pr, ps)
    assert runs[1].report_path == Path("a/wer_report_repetition_fix.csv")
    assert runs[1].summary_path == Path("a/wer_summary_repetition_fix.json")
    assert len({r.report_path for r in runs}) == len(runs)
