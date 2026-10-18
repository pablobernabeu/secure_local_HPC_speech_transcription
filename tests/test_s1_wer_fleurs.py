"""Stage-1: fleurs_multilingual_summary.json has a build script (OUTPUTS-11).

The file was assembled by hand from six languages' summaries in three
arms. evaluation.fleurs_multilingual rebuilds it; from the 36 ARC
summaries it reproduced the three-arm file byte for byte, and from those
and the audit's re-run (a fourth arm, 48 summaries) it builds the
four-arm file (checked when each was written; the summaries are not in
the repository). These tests use synthetic summaries.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation import fleurs_multilingual as fm


def _summary(directory: Path, config: str, condition: str, wer: float,
             utterances: int = 10, language: str = "polish",
             slug: str | None = None, model: str = "openai/whisper-large-v3",
             commit: str | None = None, gpu: str | None = None) -> None:
    """Write one synthetic summary, named as the submit script names it.

    *slug* gives the layout written since a22a864; *commit* and *gpu* the
    run metadata and decode record the audit's re-run carries.
    """
    directory.mkdir(parents=True, exist_ok=True)
    suffix = "" if condition == "raw" else f"_{condition}"
    stem = f"wer_summary_fleurs_{config}" + (f"_{slug}" if slug else "")
    bench = {"dataset": "google/fleurs", "config": config, "split": "test",
             "model": model, "utterances": utterances,
             "seed": 42, "condition": condition, "language": language}
    payload = {"benchmark": bench, "summary": {"files": utterances,
                                               "macro_wer": wer}}
    if gpu is not None:
        bench["decode"] = {"device": "cuda", "gpu": gpu}
    if commit is not None:
        payload["run_metadata"] = {"git_commit": commit, "git_dirty": False}
    (directory / f"{stem}{suffix}.json").write_text(json.dumps(payload),
                                                    encoding="utf-8")


def _rerun(tmp_path, raw=0.0475, composite=0.0475, **kwargs):
    """A fourth arm in the slugged layout, as job 8917984 wrote it."""
    d = tmp_path / "audit2026" / "fleurs_ml"
    meta = {"slug": "whisper-large-v3", "commit": "6f9bf56a0d58",
            "gpu": "NVIDIA L40S"}
    meta.update(kwargs)
    _summary(d, "pl_pl", "raw", raw, **meta)
    _summary(d, "pl_pl", "pipeline_full", composite, **meta)
    return d


def _arms(tmp_path):
    arms = {}
    for i, (name, composite) in enumerate((("1_before_fix", 0.38291),
                                           ("2_after_fix", 0.0481),
                                           ("3_after_gate", 0.0473))):
        d = tmp_path / f"arm{i}"
        _summary(d, "pl_pl", "raw", 0.04726 + i * 1e-5)
        _summary(d, "pl_pl", "pipeline_full", composite)
        arms[name] = d
    return arms


def test_ratios_are_computed_within_each_arm(tmp_path):
    summary = fm.assemble(_arms(tmp_path), languages=("pl_pl",), exact=True)
    pl = summary["languages"]["pl_pl"]
    assert pl["language"] == "polish" and pl["utterances"] == 10
    assert pl["raw_before_fix"] == 0.0473
    assert pl["ratio_before_fix"] == round(0.38291 / 0.04726, 2)
    assert pl["ratio_after_gate"] == round(0.0473 / 0.04728, 2)
    assert pl["raw"] == pl["raw_before_fix"]
    assert pl["exact"]["ratio_before_fix"] == pytest.approx(0.38291 / 0.04726)
    assert list(summary["benchmark"]["arms"]) == [
        "1_before_fix", "2_after_fix", "3_after_gate"]
    assert summary["benchmark"]["arms"]["2_after_fix"]["code"] == "812552b"


def test_the_committed_key_order_is_kept(tmp_path):
    carry = {"languages": {"pl_pl": {"pct_words_with_diacritic": 88}},
             "finding": {"summary": "kept verbatim"}}
    summary = fm.assemble(_arms(tmp_path), languages=("pl_pl",), carry=carry)
    assert list(summary["languages"]["pl_pl"]) == [
        "language", "utterances", "raw_before_fix", "pipeline_full_before_fix",
        "ratio_before_fix", "raw_after_fix", "pipeline_full_after_fix",
        "ratio_after_fix", "raw_after_gate", "pipeline_full_after_gate",
        "ratio_after_gate", "pct_words_with_diacritic", "raw"]
    assert summary["finding"] == {"summary": "kept verbatim"}
    assert list(summary) == ["benchmark", "languages", "finding"]


def test_a_misplaced_file_is_refused(tmp_path):
    arms = _arms(tmp_path)
    # A German summary saved under the Polish name.
    path = arms["2_after_fix"] / "wer_summary_fleurs_pl_pl.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["benchmark"]["config"] = "de_de"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SystemExit, match="de_de"):
        fm.assemble(arms, languages=("pl_pl",))


def test_arms_that_scored_different_utterances_are_refused(tmp_path):
    arms = _arms(tmp_path)
    _summary(arms["3_after_gate"], "pl_pl", "raw", 0.0473, utterances=9)
    with pytest.raises(SystemExit, match="different numbers"):
        fm.assemble(arms, languages=("pl_pl",))


def test_the_cli_writes_the_committed_layout(tmp_path):
    arms = _arms(tmp_path)
    out = tmp_path / "out" / "fleurs.json"
    argv = [f"--arm={name}={d}" for name, d in arms.items()]
    fm.main(argv + ["--languages", "pl_pl", "--out", str(out),
                    "--record-inputs"])
    raw = out.read_bytes()
    assert not raw.endswith(b"\n") and b"\r\n" not in raw
    payload = json.loads(raw)
    assert len(payload["benchmark"]["inputs"]) == 6
    assert "git_commit" in payload["benchmark"]["assembled_by"]
    assert "pct_words_with_diacritic" not in payload["languages"]["pl_pl"]

# ---------------------------------------------------------------------------
# OUTPUTS-11: the diacritic shares are measured, not carried by hand
# ---------------------------------------------------------------------------

def test_carries_diacritic_is_any_non_ascii_letter():
    from evaluation.fleurs_diacritics import carries_diacritic
    for word in ("źródło", "élève", "straße", "kōan", "coördinatie"):
        assert carries_diacritic(word)
    for word in ("word", "3,5", "l'eau", "—", "...", "«", ""):
        assert not carries_diacritic(word)


def test_shares_count_words_across_utterances():
    from evaluation.fleurs_diacritics import shares
    got = shares(["zażółć gęślą jaźń", "ala ma kota", ""])
    assert got == {"n_utterances": 3, "n_words": 6, "n_words_with_diacritic": 3,
                   "pct_words_with_diacritic": 50}


def test_measure_records_its_provenance():
    from evaluation import fleurs_diacritics as fd
    record = fd.measure(languages=("pl_pl", "nl_nl"),
                        references=lambda c: iter(["źle", "dobrze"] if c == "pl_pl"
                                                  else ["goed"]))
    assert record["languages"]["pl_pl"]["pct_words_with_diacritic"] == 50
    assert record["languages"]["nl_nl"]["pct_words_with_diacritic"] == 0
    assert record["dataset"] == "google/fleurs" and record["split"] == "test"
    assert record["reference_field"] == "transcription"
    assert record["definition"] == fd.DEFINITION
    assert "git_commit" in record["run_metadata"]


def test_measured_shares_replace_the_carried_ones(tmp_path):
    measured = {"dataset": "google/fleurs", "revision": "r", "split": "test",
                "reference_field": "transcription", "definition": "d",
                "languages": {"pl_pl": {"n_utterances": 10, "n_words": 8,
                                        "n_words_with_diacritic": 3,
                                        "pct_words_with_diacritic": 38}}}
    carry = {"languages": {"pl_pl": {"pct_words_with_diacritic": 88}}}
    summary = fm.assemble(_arms(tmp_path), languages=("pl_pl",), carry=carry,
                          exact=True, diacritics=measured)
    pl = summary["languages"]["pl_pl"]
    assert pl["pct_words_with_diacritic"] == 38
    assert (pl["words"], pl["words_with_diacritic"]) == (8, 3)
    assert pl["exact"]["share_words_with_diacritic"] == pytest.approx(3 / 8)
    assert summary["benchmark"]["diacritic_shares"]["definition"] == "d"
    with pytest.raises(SystemExit, match="no entry"):
        fm.assemble(_arms(tmp_path), languages=("pl_pl",),
                    diacritics={"languages": {}})


def test_shares_measured_over_other_utterances_are_refused(tmp_path):
    measured = {"languages": {"pl_pl": {"n_utterances": 9, "n_words": 8,
                                        "n_words_with_diacritic": 3,
                                        "pct_words_with_diacritic": 38}}}
    with pytest.raises(SystemExit, match="counted 9 utterances"):
        fm.assemble(_arms(tmp_path), languages=("pl_pl",), diacritics=measured)

# ---------------------------------------------------------------------------
# The audit's re-run as a fourth arm, named with the model slug (SHELL-13)
# ---------------------------------------------------------------------------

def test_the_rerun_is_read_in_the_slugged_layout(tmp_path):
    arms = {**_arms(tmp_path), "4_after_audit": _rerun(tmp_path)}
    summary = fm.assemble(arms, languages=("pl_pl",), exact=True)
    pl = summary["languages"]["pl_pl"]
    assert (pl["raw_after_audit"], pl["pipeline_full_after_audit"],
            pl["ratio_after_audit"]) == (0.0475, 0.0475, 1.0)
    assert list(pl)[-3:] == ["ratio_after_audit", "raw", "exact"]
    assert pl["raw"] == pl["raw_before_fix"]
    audit = summary["benchmark"]["arms"]["4_after_audit"]
    assert (audit["code"], audit["arc_jobs"]) == ("6f9bf56", ["8917984"])
    # The re-run records its GPUs, so they are read, not typed in.
    assert audit["gpus"] == {"pl_pl": "NVIDIA L40S"}
    assert summary["benchmark"]["arms"]["3_after_gate"]["gpus"] == {
        "pl_pl": "Tesla P100-PCIE-16GB"}


def test_the_design_and_the_raw_spread_follow_the_arms(tmp_path):
    three = fm.assemble(_arms(tmp_path), languages=("pl_pl",))["benchmark"]
    assert three["design"] == ("three arms over the same corpus, isolating "
                               "two defects")
    assert three["ratio_definition"].endswith(
        "Raw is stable to within 0.0000 across the three arms for every "
        "language.")
    arms = {**_arms(tmp_path), "4_after_audit": _rerun(tmp_path)}
    four = fm.assemble(arms, languages=("pl_pl",))["benchmark"]
    assert four["design"].startswith("four arms over the same corpus")
    # 0.0475 against 0.0473, at the four decimals the file holds.
    assert four["ratio_definition"].endswith(
        "Raw is stable to within 0.0002 across the four arms for every "
        "language.")


def test_a_directory_holding_both_layouts_is_refused(tmp_path):
    arms = _arms(tmp_path)
    _summary(arms["3_after_gate"], "pl_pl", "pipeline_full", 0.0473,
             slug="whisper-large-v3")
    with pytest.raises(SystemExit, match="under one name"):
        fm.assemble(arms, languages=("pl_pl",))


def test_two_models_in_one_directory_are_refused(tmp_path):
    rerun = _rerun(tmp_path)
    # A Whisper Medium run written beside the Large v3 one: reading either
    # would be a guess at which model the arm means.
    for condition in ("raw", "pipeline_full"):
        _summary(rerun, "pl_pl", condition, 0.06, slug="whisper-medium",
                 model="openai/whisper-medium")
    arms = {**_arms(tmp_path), "4_after_audit": rerun}
    with pytest.raises(SystemExit,
                       match="under one name.*whisper-large-v3.*whisper-medium"):
        fm.assemble(arms, languages=("pl_pl",))


def test_a_slugged_summary_without_its_partner_is_refused(tmp_path):
    raw_only = tmp_path / "raw_only"
    _summary(raw_only, "pl_pl", "raw", 0.0475, slug="whisper-large-v3")
    with pytest.raises(SystemExit, match="found none"):
        fm.assemble({"4_after_audit": raw_only}, languages=("pl_pl",))
    composite_only = tmp_path / "composite_only"
    _summary(composite_only, "pl_pl", "pipeline_full", 0.0475,
             slug="whisper-large-v3")
    with pytest.raises(SystemExit, match="cannot read"):
        fm.assemble({"4_after_audit": composite_only}, languages=("pl_pl",))


def test_a_slug_naming_another_model_is_refused(tmp_path):
    arms = {**_arms(tmp_path),
            "4_after_audit": _rerun(tmp_path, slug="whisper-medium")}
    with pytest.raises(SystemExit, match="named for whisper-medium"):
        fm.assemble(arms, languages=("pl_pl",))


def test_a_rerun_from_another_commit_is_refused(tmp_path):
    arms = {**_arms(tmp_path), "4_after_audit": _rerun(tmp_path,
                                                         commit="c0f58c5")}
    with pytest.raises(SystemExit, match="registered at 6f9bf56"):
        fm.assemble(arms, languages=("pl_pl",))


def test_a_gpu_other_than_the_registered_one_is_refused(tmp_path):
    arms = _arms(tmp_path)
    _summary(arms["3_after_gate"], "pl_pl", "raw", 0.04728, gpu="NVIDIA L40S")
    with pytest.raises(SystemExit, match="decoded on NVIDIA L40S"):
        fm.assemble(arms, languages=("pl_pl",))
