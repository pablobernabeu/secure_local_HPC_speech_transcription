"""The canonical normaliser's gain on AMI, and the reports behind it.

``output/evaluation/sweep_reports_postfix_ami/`` holds two per-utterance
reports from the audit's Large v3 sweep (ARC job 8917985, task 1, code
6f9bf56) on the AMI test split, ``raw`` and ``whisper_norm``, under the
sweep's own names. The normaliser strips hesitations from the reference as
well as from the hypothesis, so an utterance whose reference is only a
hesitation is empty under it and is scored under ``raw`` alone. A gain
computed from the two corpus rates in ``sweep_aggregate.csv`` therefore
mixes the normaliser's effect with the removal of those utterances (audit
finding EWER-09). ``normaliser_gain_ami.csv``, which ``condition_ci
--gains-output`` wrote from the two reports, gives the gain on the
utterances both conditions scored, beside the all-utterance figure.

These tests tie each report to the cell of the matrix it is named for, so
that it cannot be another decode or another scoring than the one the
manuscript's figures describe, and the gains to the reports, recomputed
here without :mod:`evaluation.condition_ci`. They read committed files
only; rerunning the producer is left to ``tools/verify_regeneration.py``.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path

import pytest

_EVAL = Path(__file__).resolve().parents[1] / "output" / "evaluation"
_REPORTS = _EVAL / "sweep_reports_postfix_ami"
_STEM = "wer_report_ami_whisper-large-v3"
_CELLS = {"raw": _REPORTS / f"{_STEM}.csv",
          "whisper_norm": _REPORTS / f"{_STEM}_whisper_norm.csv"}
_AGGREGATE = _EVAL / "sweep_aggregate.json"
_GAINS = _EVAL / "normaliser_gain_ami.csv"
_GAINS_SIDECAR = _EVAL / "normaliser_gain_ami_provenance.json"
# The report directory as the producer was given it, relative to the
# repository root, as output/evaluation/README.md gives the command.
_REPORTS_ARG = "output/evaluation/sweep_reports_postfix_ami"
# The utterances scored under raw whose reference the normaliser empties.
_DROPPED = 990


def _rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _lf(path: Path) -> bytes:
    """The file's bytes with every CRLF read as LF.

    Git stores these files with LF, and a Windows checkout writes them back
    with CRLF, so a raw digest would depend on the checkout.
    """
    return path.read_bytes().replace(b"\r\n", b"\n")


@pytest.fixture(scope="module")
def reports() -> dict[str, list[dict]]:
    return {condition: _rows(path) for condition, path in _CELLS.items()}


@pytest.fixture(scope="module")
def aggregate() -> dict:
    return json.loads(_AGGREGATE.read_text(encoding="utf-8"))


def _cell(aggregate: dict, condition: str) -> dict:
    (row,) = [r for r in aggregate["rows"]
              if (r["suite"], r["model_slug"], r["condition"])
              == ("ami", "whisper-large-v3", condition)]
    return row


def test_the_directory_holds_the_two_reports_only() -> None:
    assert sorted(p.name for p in _REPORTS.iterdir()) == \
        sorted(p.name for p in _CELLS.values())


@pytest.mark.parametrize("condition", sorted(_CELLS))
def test_each_report_is_the_matrix_cell_it_is_named_for(
        reports: dict, aggregate: dict, condition: str) -> None:
    """Its count, macro and pooled WER and alignment totals are the cell's.

    sweep_aggregate.json was built from the cell's summary, whose SHA-256
    it records. The summary stays on ARC, so the totals are the check.
    """
    rows, cell = reports[condition], _cell(aggregate, condition)
    suffix = "" if condition == "raw" else f"_{condition}"
    assert cell["source_file"] == f"wer_summary_ami_whisper-large-v3{suffix}.json"
    assert cell["pipeline_version"] == "6f9bf56"
    errors = sum(int(r["substitutions"]) + int(r["deletions"]) + int(r["insertions"])
                 for r in rows)
    words = sum(int(r["reference_words"]) for r in rows)
    assert len(rows) == cell["n_utterances"]
    assert math.isclose(sum(float(r["wer"]) for r in rows) / len(rows),
                        cell["macro_wer"], rel_tol=0, abs_tol=1e-12)
    assert math.isclose(errors / words, cell["micro_wer"], rel_tol=0, abs_tol=1e-12)
    for field in ("reference_words", "hits", "substitutions", "deletions",
                  "insertions", "hypothesis_words"):
        assert sum(int(r[field]) for r in rows) == cell[f"total_{field}"], field


def test_the_normaliser_scores_the_raw_utterances_less_the_hesitations(
        reports: dict) -> None:
    """Every utterance scored under the normaliser is scored under raw,
    in the same order, and raw alone scores the 990 it empties, whose raw
    references are one to four words long."""
    raw = [r["name"] for r in reports["raw"]]
    norm = [r["name"] for r in reports["whisper_norm"]]
    assert len(set(raw)) == len(raw) == 12643
    assert len(set(norm)) == len(norm) == 12643 - _DROPPED
    kept = set(norm)
    assert [name for name in raw if name in kept] == norm
    dropped = [r for r in reports["raw"] if r["name"] not in kept]
    assert len(dropped) == _DROPPED
    assert max(int(r["reference_words"]) for r in dropped) == 4


@pytest.mark.parametrize("model", ["whisper-large-v3", "whisper-medium",
                                   "distil-large-v3"])
def test_only_ami_loses_utterances_to_the_normaliser(aggregate: dict,
                                                     model: str) -> None:
    """Why only AMI's reports are committed for the gain.

    On the other four corpora the normaliser scores as many utterances as
    raw, so a gain computed from the matrix's two rates is already over one
    set of utterances there. When these reports were committed, the sweep's
    reports for those corpora, fetched from ARC, were compared by name as
    well, and the two conditions scored the same utterances for every model.
    """
    n = {(r["suite"], r["condition"]): r["n_utterances"]
         for r in aggregate["rows"] if r["model_slug"] == model}
    suites = {suite for suite, _ in n}
    assert len(suites) == 5
    assert {s: n[(s, "raw")] - n[(s, "whisper_norm")] for s in suites} == \
        {s: (_DROPPED if s == "ami" else 0) for s in suites}


# ---------------------------------------------------------------------------
# The gains table
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def gain() -> dict:
    (row,) = _rows(_GAINS)
    return row


def test_the_table_holds_the_normaliser_alone(gain: dict) -> None:
    assert list(gain) == [
        "condition", "n_shared", "n_baseline_only", "n_condition_only",
        "macro_baseline_shared", "macro_condition_shared", "macro_gain_shared",
        "micro_baseline_shared", "micro_condition_shared", "micro_gain_shared",
        "macro_baseline_all", "macro_condition_all", "macro_gain_all"]
    assert gain["condition"] == "whisper_norm"
    assert (int(gain["n_shared"]), int(gain["n_baseline_only"]),
            int(gain["n_condition_only"])) == (12643 - _DROPPED, _DROPPED, 0)


def test_the_gains_follow_from_the_reports(reports: dict, gain: dict) -> None:
    """Each rate and gain, recomputed from the committed reports.

    Macro is the mean per-utterance WER and pooled the errors over the
    reference words, both over the utterances the two reports share; the
    ``_all`` columns take each report whole. Gains are relative reductions.
    """
    raw = {r["name"]: r for r in reports["raw"]}
    norm = {r["name"]: r for r in reports["whisper_norm"]}
    shared = [name for name in raw if name in norm]

    def macro(table: dict, names: list) -> float:
        return sum(float(table[n]["wer"]) for n in names) / len(names)

    def pooled(table: dict, names: list) -> float:
        errors = sum(int(table[n]["substitutions"]) + int(table[n]["deletions"])
                     + int(table[n]["insertions"]) for n in names)
        return errors / sum(int(table[n]["reference_words"]) for n in names)

    rates = {
        "macro_baseline_shared": macro(raw, shared),
        "macro_condition_shared": macro(norm, shared),
        "micro_baseline_shared": pooled(raw, shared),
        "micro_condition_shared": pooled(norm, shared),
        "macro_baseline_all": macro(raw, list(raw)),
        "macro_condition_all": macro(norm, list(norm)),
    }
    for kind in ("macro_{}_shared", "micro_{}_shared", "macro_{}_all"):
        base, cond = rates[kind.format("baseline")], rates[kind.format("condition")]
        rates[kind.format("gain")] = (base - cond) / base
    for field, value in rates.items():
        assert float(gain[field]) == round(value, 6), field


def test_the_all_utterance_columns_are_the_matrix_cells(aggregate: dict,
                                                        gain: dict) -> None:
    """``macro_gain_all`` is the figure the two rates of sweep_aggregate.csv
    give, the one the manuscript computed before this table existed."""
    assert float(gain["macro_baseline_all"]) == round(_cell(aggregate, "raw")["macro_wer"], 6)
    assert float(gain["macro_condition_all"]) == \
        round(_cell(aggregate, "whisper_norm")["macro_wer"], 6)


def test_pinned_gains(gain: dict) -> None:
    # On the 11,653 utterances both conditions score, the normaliser lowers
    # the macro WER from 0.306127 to 0.285246, by 6.82%. Over each
    # condition's own utterances the reduction is 12.06%, because the 990
    # utterances raw alone scores average a raw WER of 0.54 (EWER-09). The
    # pooled rates divide by each condition's own reference words, and the
    # normaliser changes those as well.
    assert (float(gain["macro_baseline_shared"]),
            float(gain["macro_condition_shared"])) == (0.306127, 0.285246)
    assert float(gain["macro_gain_shared"]) == 0.068211
    assert float(gain["macro_gain_all"]) == 0.120553
    assert float(gain["micro_gain_shared"]) == 0.203889


def test_the_sidecar_names_the_committed_reports() -> None:
    """The sidecar's digests are of the reports and the table committed
    beside it, so a table left over from other inputs fails here."""
    sidecar = json.loads(_GAINS_SIDECAR.read_text(encoding="utf-8"))
    assert sidecar["tool"] == "evaluation.condition_ci"
    assert sidecar["artefact"] == _GAINS.name
    assert sidecar["artefact_sha256_lf"] == hashlib.sha256(_lf(_GAINS)).hexdigest()
    assert sidecar["arguments"] == {
        "reports": _REPORTS_ARG, "baseline": "raw", "baseline_file": None,
        "primary_condition": "raw", "prefix": _STEM, "bootstrap": 10000, "seed": 42}
    assert sidecar["inputs"] == [
        {"path": f"{_REPORTS_ARG}/{path.name}",
         "sha256_lf": hashlib.sha256(_lf(path)).hexdigest()}
        for path in sorted(_CELLS.values(), key=lambda p: p.name)]
    assert sidecar["run_metadata"]["git_dirty"] is False
