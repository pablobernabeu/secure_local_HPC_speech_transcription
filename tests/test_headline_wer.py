"""The manuscript's headline WER files are the condition sweep's raw cell.

``output/evaluation/wer_report.csv`` and ``wer_summary.json`` feed the
corpus table, the per-utterance and per-speaker dispersion figures and
Appendix C, and ``wer_ci.csv`` the interval in that table. Until October
2026 they held a May 2026 decode from the retired benchmark script and its
interval, while the paired condition intervals beside them read the sweep,
so the table and the condition analysis rested on two decodes that score
five utterances differently (audit findings OUTPUTS-03 and MS-12). These
tests tie the headline files to the sweep, and the interval to the report
it was computed from, so that they cannot drift apart again unnoticed. They
read committed files only, and need neither a GPU nor the scoring stack;
recomputing the interval is left to ``tools/verify_regeneration.py``.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path

import pytest

_EVAL = Path(__file__).resolve().parents[1] / "output" / "evaluation"
_REPORT = _EVAL / "wer_report.csv"
_SUMMARY = _EVAL / "wer_summary.json"
_SWEEP_RAW = _EVAL / "sweep_reports_postfix" / "wer_report.csv"
_AGGREGATE = _EVAL / "sweep_aggregate.json"
_CI = _EVAL / "wer_ci.csv"
_CI_SIDECAR = _EVAL / "wer_ci_provenance.json"
_RAW_CELL = ("librispeech_clean", "whisper-large-v3", "raw")
_PILOT = _EVAL / "pilot_may2026"
_MAY_REPORT = _PILOT / "wer_report_librispeech_whisper-large-v3_raw.csv"
_MAY_SUMMARY = _PILOT / "wer_summary_librispeech_whisper-large-v3_raw.json"
# The utterances the May decode and the sweep's score differently, in file
# order.
_CHANGED = ("1995-1836-0004", "5142-33396-0055", "8224-274381-0009",
            "8555-284447-0015", "3570-5694-0020")
# The path the interval's producer was given, relative to the repository
# root, as the manuscript's Data availability section gives the command.
_REPORT_ARG = "output/evaluation/wer_report.csv"


def _lf(path: Path) -> bytes:
    """The file's bytes with every CRLF read as LF.

    The text artefacts are stored with LF, a Windows checkout writes them
    back with CRLF, and the csv writers emit CRLF on every platform, so a
    raw byte comparison would depend on the checkout, not on the content.
    """
    return path.read_bytes().replace(b"\r\n", b"\n")


def _rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="module")
def summary() -> dict:
    return json.loads(_SUMMARY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def report() -> list[dict]:
    return _rows(_REPORT)


def test_the_report_is_the_sweeps_raw_report() -> None:
    # Every paired interval in condition_ci_postfix.csv takes this report
    # as its baseline, so the headline table must describe the same decode.
    assert _lf(_REPORT) == _lf(_SWEEP_RAW)


def test_the_summary_describes_the_raw_large_v3_test_clean_run(summary: dict) -> None:
    # The manuscript's load-wer-ci chunk refuses any other run (EWER-11);
    # failing here says so before a render does.
    bench = summary["benchmark"]
    assert (bench["dataset"], bench["config"], bench["split"], bench["model"],
            bench["condition"]) == ("librispeech_asr", "clean", "test",
                                    "openai/whisper-large-v3", "raw")
    assert summary["run_metadata"]["git_dirty"] is False


def test_the_summary_agrees_with_its_report(summary: dict, report: list[dict]) -> None:
    s = summary["summary"]
    errors = sum(int(r["substitutions"]) + int(r["deletions"]) + int(r["insertions"])
                 for r in report)
    words = sum(int(r["reference_words"]) for r in report)
    macro = sum(float(r["wer"]) for r in report) / len(report)
    assert s["files"] == len(report) == len(summary["per_file"])
    assert s["total_reference_words"] == words
    assert math.isclose(s["macro_wer"], macro, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(s["micro_wer"], errors / words, rel_tol=0, abs_tol=1e-12)
    assert [p["name"] for p in summary["per_file"]] == [r["name"] for r in report]


def test_the_summary_is_the_one_the_matrix_was_built_from(summary: dict) -> None:
    """The grid and the headline table read one summary, not two runs.

    sweep_aggregate.json records the SHA-256 of every summary it
    aggregated. The committed headline summary must be the raw Large v3
    test-clean one, byte for byte up to line endings.
    """
    aggregate = json.loads(_AGGREGATE.read_text(encoding="utf-8"))
    (cell,) = [row for row in aggregate["rows"]
               if (row["suite"], row["model_slug"], row["condition"]) == _RAW_CELL]
    digests = {entry["source_file"]: entry["sha256"]
               for entry in aggregate["provenance"]["inputs"]}
    assert hashlib.sha256(_lf(_SUMMARY)).hexdigest() == digests[cell["source_file"]]
    s = summary["summary"]
    assert (cell["n_utterances"], cell["macro_wer"], cell["micro_wer"]) == \
        (s["files"], s["macro_wer"], s["micro_wer"])
    assert summary["run_metadata"]["git_commit"].startswith(cell["pipeline_version"])


def test_pinned_headline_values(summary: dict) -> None:
    # Regression anchors for the figures @tbl-corpus-summary prints. The
    # May 2026 decode these replaced scored the same 2,620 utterances and
    # 52,576 reference words at macro 0.062210 and micro 0.038630, with one
    # insertion more (515); five utterances differed (OUTPUTS-03).
    s = summary["summary"]
    assert (s["files"], s["total_reference_words"]) == (2620, 52576)
    assert round(s["macro_wer"], 6) == 0.062132
    assert round(s["micro_wer"], 6) == 0.038611
    assert (s["total_substitutions"], s["total_deletions"],
            s["total_insertions"]) == (1367, 149, 514)


def test_the_interval_is_over_the_committed_report(summary: dict) -> None:
    """wer_ci.csv describes the report beside it, at the recorded settings.

    The sidecar holds the digest of the report the interval was computed
    from, so an interval left over from an earlier report fails here even
    when its n and macro happen to agree.
    """
    (row,) = _rows(_CI)
    assert row["file"] == _REPORT_ARG
    assert int(row["n"]) == summary["summary"]["files"]
    assert float(row["macro_wer"]) == round(summary["summary"]["macro_wer"], 6)
    assert (int(row["bootstrap"]), int(row["seed"])) == (10000, 42)
    sidecar = json.loads(_CI_SIDECAR.read_text(encoding="utf-8"))
    assert sidecar["tool"] == "evaluation.bootstrap_ci"
    assert sidecar["arguments"] == {"report": [_REPORT_ARG], "bootstrap": 10000,
                                    "seed": 42}
    assert sidecar["inputs"] == [{"path": _REPORT_ARG,
                                  "sha256_lf": hashlib.sha256(_lf(_REPORT)).hexdigest()}]
    assert sidecar["artefact_sha256_lf"] == hashlib.sha256(_lf(_CI)).hexdigest()
    assert sidecar["run_metadata"]["git_dirty"] is False


def test_pinned_interval() -> None:
    # 10,000 replicates, seed 42, over the sweep's raw report. The same
    # settings over the May 2026 decode gave [0.057521, 0.067064]. Both
    # bounds fell by 0.000063 and the width, 0.009543, did not change.
    # The corpus table now prints the lower bound as 0.057, not 0.058, but
    # that third decimal is set by the seed. Pooled over two sets of
    # 2,000,000 replicates the bound is 0.057500 and 0.057498, on the
    # rounding threshold, against 0.057576 and 0.057573 for the May decode,
    # so the data moved it by about 0.000076. Of 400 seeds (0-199 and
    # 5000-5199), 204 print 0.058 (OUTPUTS-03).
    (row,) = _rows(_CI)
    assert (float(row["ci_lo"]), float(row["ci_hi"])) == (0.057458, 0.067001)


def test_the_may_decode_is_kept_for_comparison(report: list[dict]) -> None:
    """The May 2026 pair these files replaced stays in pilot_may2026/.

    hpc/legacy/README.md traces it to ARC: the report's digest, read with
    LF line endings, is that of the wer_report_gpu.csv job 7668730 wrote.
    The two decodes share every utterance and reference, and their rows
    differ only for the five utterances the replacement commit lists.
    """
    assert hashlib.sha256(_lf(_MAY_REPORT)).hexdigest() == (
        "5283a0ca42449c6b7d435de1149963332c7c08c6b9180dd8ca231b763d3b6ac3")
    assert hashlib.sha256(_lf(_MAY_SUMMARY)).hexdigest() == (
        "71346c287acd6466946fd86ce7d306004a3562dc485dfa69ea781cd1713d35c9")
    may = _rows(_MAY_REPORT)
    assert [(r["name"], r["reference_words"]) for r in may] == \
        [(r["name"], r["reference_words"]) for r in report]
    changed = tuple(m["name"] for m, s in zip(may, report, strict=True) if m != s)
    assert changed == _CHANGED
