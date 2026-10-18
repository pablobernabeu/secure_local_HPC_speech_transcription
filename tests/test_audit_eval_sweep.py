"""Audit fixes for the sweep driver, the aggregate and the filler audit.

evaluation.sweep_aggregate builds the table the manuscript reads and had
no tests. The sweep's default condition list and SLURM suite order drive
the committed grid, so both are pinned here. Hermetic: synthetic summary
JSON files under tmp_path.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from evaluation import sweep, sweep_aggregate as agg

_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# sweep: defaults, order and shared helpers
# ---------------------------------------------------------------------------

def test_default_conditions_are_every_registered_one():
    """EWER-13: the hand-typed default list had missed pronoun_i_fix.

    If this fails because a condition was registered, decide which layer
    of default_sweep_conditions() it belongs to.
    """
    from evaluation.conditions import default_sweep_conditions, list_conditions
    defaults = default_sweep_conditions()
    registered = {c.name for c in list_conditions()}
    assert defaults[0] == "raw"
    assert len(defaults) == len(set(defaults))
    assert set(defaults) == registered


def test_default_list_follows_the_production_stage_order():
    import transcription
    from evaluation.conditions import default_sweep_conditions
    stages = [f.__name__.lstrip("_") for f in transcription.CLEAN_TEXT_STAGES]
    defaults = list(default_sweep_conditions())
    start = defaults.index(stages[0])
    assert defaults[start:start + len(stages)] == stages
    assert "pronoun_i_fix" in defaults


def test_run_sweep_uses_the_registry_default(monkeypatch):
    from evaluation.conditions import default_sweep_conditions
    seen = []
    monkeypatch.setattr(sweep, "run_suite",
                        lambda **kw: seen.append(kw["conditions"]))
    sweep.run_sweep(sweep._all_suite_specs()[:2], "m", None, Path("o"))
    assert seen == [list(default_sweep_conditions())] * 2
    with pytest.raises(ValueError, match="Unknown"):
        sweep.run_sweep(sweep._all_suite_specs()[:1], "m", ["nope"], Path("o"))


def test_every_cell_writes_qualified_paths_unless_legacy_is_asked_for():
    """EWER-11: the canonical cell shared wer_summary.json with two tools."""
    primary = sweep._all_suite_specs()[0]
    report, summary = sweep._primary_paths(
        primary, "openai/whisper-large-v3", Path("o"))
    assert report == Path("o/wer_report_librispeech_whisper-large-v3.csv")
    assert summary == Path("o/wer_summary_librispeech_whisper-large-v3.json")
    legacy = sweep._primary_paths(primary, "openai/whisper-large-v3",
                                  Path("o"), legacy_primary_paths=True)
    assert legacy == (Path("o/wer_report.csv"), Path("o/wer_summary.json"))
    # Only the default model on the primary suite ever had legacy names.
    assert sweep._primary_paths(primary, "openai/whisper-medium", Path("o"),
                                legacy_primary_paths=True)[0].name == \
        "wer_report_librispeech_whisper-medium.csv"
    assert sweep._build_parser().parse_args([]).legacy_primary_paths is False


def test_slurm_suite_indices_are_frozen():
    names = [s.name for s in sweep._all_suite_specs()]
    assert names[:5] == ["librispeech_clean", "ami", "fleurs",
                         "librispeech_other", "voxpopuli_accented"]


def test_a_new_suite_is_appended_not_inserted(monkeypatch):
    import dataclasses
    from evaluation import challenge_suites
    extra = dataclasses.replace(challenge_suites.get_suite("ami"),
                                name="earnings22", config="earnings22")
    monkeypatch.setitem(challenge_suites._SUITES, "earnings22", extra)
    names = [s.name for s in sweep._all_suite_specs()]
    assert names == ["librispeech_clean", "ami", "fleurs",
                     "librispeech_other", "voxpopuli_accented", "earnings22"]


def test_sweep_helpers_agree_with_benchmark_wer():
    pytest.importorskip("numpy")
    from evaluation import benchmark_wer
    for raw in (None, "", " raw , whisper_norm,raw ", "a,,b"):
        assert sweep._parse_conditions_arg(raw) == \
            benchmark_wer._parse_conditions_arg(raw)
        assert sweep._parse_suites_arg(raw) == \
            benchmark_wer._parse_conditions_arg(raw)
    pr, ps = Path("o/wer_report_ami_x.csv"), Path("o/wer_summary_ami_x.json")
    for first in (True, False):
        assert sweep._condition_paths(pr, ps, "case_fold", first) == \
            benchmark_wer._derive_condition_paths(pr, ps, "case_fold", first)


def test_the_slug_has_one_definition():
    assert agg._model_slug is sweep.model_slug
    assert sweep.model_slug("distil-whisper/distil-large-v3") == \
        "distil-large-v3"


# ---------------------------------------------------------------------------
# sweep_aggregate
# ---------------------------------------------------------------------------

def _summary(d: Path, name: str, *, dataset="librispeech_asr", config="clean",
             model="openai/whisper-large-v3", condition="raw", wer=0.1,
             extra=None, summary=True) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    bench = {"dataset": dataset, "config": config, "split": "test",
             "model": model, "utterances": 3, "seed": 42,
             "condition": condition, **(extra or {})}
    payload = {"benchmark": bench}
    if summary:
        payload["summary"] = {"files": 3, "macro_wer": wer, "macro_mer": wer,
                              "macro_wil": wer, "macro_cer": wer,
                              "total_reference_words": 30}
    p = d / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_the_committed_aggregate_has_the_writer_header():
    """EWER-02: the committed aggregate is the module's own output, so its
    header is the writer's, column for column: the twelve columns of the
    hand-built grid it replaced, then the pooled columns and the
    invisibility flag (EWER-08, EWER-03)."""
    committed = _ROOT / "output" / "evaluation" / "sweep_aggregate.csv"
    if not committed.exists():
        pytest.skip("committed aggregate not present")
    with open(committed, encoding="utf-8") as fh:
        header = next(csv.reader(fh))
    assert header == agg._CSV_FIELDS
    assert header[12:] == [
        "micro_wer", "micro_mer", "total_hits", "total_substitutions",
        "total_deletions", "total_insertions", "total_hypothesis_words",
        "wer_invisible"]


def test_the_corpus_map_is_read_from_the_registries():
    assert agg._CORPUS_TO_SUITE == {
        ("librispeech_asr", "clean"): "librispeech_clean",
        ("librispeech_asr", "other"): "librispeech_other",
        ("google/fleurs", "en_us"): "fleurs",
        ("facebook/voxpopuli", "en_accented"): "voxpopuli_accented",
        ("edinburghcstr/ami", "ihm"): "ami",
    }


def test_suite_inference_by_lookup_and_by_stem(tmp_path):
    assert agg._infer_suite({"dataset": "google/fleurs", "config": "en_us"},
                            Path("x.json")) == "fleurs"
    # Unknown corpus: the longest suite name in the stem wins, so
    # librispeech_other is not mistaken for a shorter match.
    assert agg._infer_suite({}, Path(
        "wer_summary_librispeech_other_whisper-medium.json")) == \
        "librispeech_other"
    assert agg._infer_suite({}, Path("wer_summary_unknown.json")) is None


def test_rows_are_parsed_sorted_and_labelled(tmp_path):
    _summary(tmp_path, "wer_summary.json")
    _summary(tmp_path, "wer_summary_case_fold.json", condition="case_fold")
    _summary(tmp_path / "sub", "wer_summary_ami_x.json",
             dataset="edinburghcstr/ami", config="ihm",
             extra={"pipeline_version": "post-fix (abc)"})
    rows = agg.aggregate_sweep(tmp_path, pipeline_version="cli label")
    assert [(r.suite, r.condition) for r in rows] == [
        ("ami", "raw"), ("librispeech_clean", "case_fold"),
        ("librispeech_clean", "raw")]
    assert rows[0].source_file == "sub/wer_summary_ami_x.json"
    assert rows[0].pipeline_version == "post-fix (abc)"
    assert rows[1].pipeline_version == "cli label"


def test_pooled_metrics_and_counts_are_carried(tmp_path):
    """EWER-08: every summary holds them; the aggregate used to drop them."""
    p = _summary(tmp_path, "wer_summary.json")
    payload = json.loads(p.read_text(encoding="utf-8"))
    payload["summary"].update({
        "micro_wer": 0.05, "micro_mer": 0.049, "total_hits": 28,
        "total_substitutions": 1, "total_deletions": 1,
        "total_insertions": 0, "total_hypothesis_words": 29})
    p.write_text(json.dumps(payload), encoding="utf-8")
    _summary(tmp_path, "wer_summary_case_fold.json", condition="case_fold")
    rows = agg.aggregate_sweep(tmp_path)
    raw = next(r for r in rows if r.condition == "raw")
    assert (raw.micro_wer, raw.total_hits, raw.total_hypothesis_words) == \
        (0.05, 28, 29)
    assert raw.macro_wer == 0.1                      # macro untouched
    folded = next(r for r in rows if r.condition == "case_fold")
    assert folded.micro_wer is None                  # not recorded
    # The flag comes from the registry for summaries that predate it.
    assert folded.wer_invisible is True and raw.wer_invisible is False


def test_pipeline_version_prefers_the_recorded_commit(tmp_path):
    """EWER-02/DEPS-07: a row can be traced to the code that wrote it."""
    for name, meta in (("wer_summary.json",
                        {"git_commit": "abcdef1234", "git_dirty": False}),
                       ("wer_summary_case_fold.json",
                        {"git_commit": "0123456789", "git_dirty": True})):
        p = _summary(tmp_path, name,
                     condition="raw" if name == "wer_summary.json"
                     else "case_fold")
        payload = json.loads(p.read_text(encoding="utf-8"))
        payload["run_metadata"] = meta
        p.write_text(json.dumps(payload), encoding="utf-8")
    rows = agg.aggregate_sweep(tmp_path, pipeline_version="post-fix (x)")
    assert {r.condition: r.pipeline_version for r in rows} == {
        "raw": "abcdef1", "case_fold": "0123456+dirty"}


def test_the_json_keeps_types_and_records_its_inputs(tmp_path):
    """EWER-02/OUTPUTS-04: provenance-dict JSON, typed rows, input digests."""
    _summary(tmp_path, "wer_summary.json")
    out = tmp_path / "out"
    agg.main(["--sweep-dir", str(tmp_path), "--out", str(out / "a.csv"),
              "--out-json", str(out / "a.json"),
              "--pipeline-version", "post-fix (af3bee0)"])
    payload = json.loads((out / "a.json").read_text(encoding="utf-8"))
    assert set(payload) == {"provenance", "rows"}
    row, = payload["rows"]
    assert isinstance(row["n_utterances"], int)
    assert isinstance(row["macro_wer"], float)
    assert row["source_file"] == "wer_summary.json"
    assert row["pipeline_version"] == "post-fix (af3bee0)"
    prov = payload["provenance"]
    assert prov["pipeline_versions"] == ["post-fix (af3bee0)"]
    assert prov["inputs"][0]["source_file"] == "wer_summary.json"
    assert len(prov["inputs"][0]["sha256"]) == 64
    assert "git_commit" in prov["run_metadata"]


def test_pilot_summaries_are_excluded_by_default(tmp_path):
    # The pilot job's layout: the same cells as the full sweep, 200
    # utterances, under pilot/ and named wer_summary_pilot*.json.
    _summary(tmp_path, "wer_summary.json")
    _summary(tmp_path, "wer_summary_case_fold.json", condition="case_fold")
    _summary(tmp_path / "pilot", "wer_summary_pilot.json")
    _summary(tmp_path / "pilot", "wer_summary_pilot_case_fold.json",
             condition="case_fold")
    default = agg.aggregate_sweep(tmp_path)
    assert [(r.suite, r.condition) for r in default] == [
        ("librispeech_clean", "case_fold"), ("librispeech_clean", "raw")]


def test_included_pilot_rows_keep_their_own_cells(tmp_path):
    """EVAL-02: --include-pilot used to be refused as duplicate cells."""
    _summary(tmp_path, "wer_summary.json")
    _summary(tmp_path, "wer_summary_case_fold.json", condition="case_fold")
    _summary(tmp_path / "pilot", "wer_summary_pilot.json")
    _summary(tmp_path / "pilot", "wer_summary_pilot_case_fold.json",
             condition="case_fold")
    rows = agg.aggregate_sweep(tmp_path, include_pilot=True)
    assert [(r.suite, r.condition, r.source_file) for r in rows] == [
        ("librispeech_clean", "case_fold", "wer_summary_case_fold.json"),
        ("librispeech_clean", "raw", "wer_summary.json"),
        ("librispeech_clean@pilot", "case_fold",
         "pilot/wer_summary_pilot_case_fold.json"),
        ("librispeech_clean@pilot", "raw", "pilot/wer_summary_pilot.json")]
    # A pilot covers part of the grid by design, so it is not a hole in it.
    assert agg.missing_cells(rows) == []
    out = tmp_path / "out"
    agg.main(["--sweep-dir", str(tmp_path), "--include-pilot",
              "--out", str(out / "a.csv"), "--out-json", str(out / "a.json")])
    with open(out / "a.csv", encoding="utf-8") as fh:
        assert [r["suite"] for r in csv.DictReader(fh)] == [
            "librispeech_clean", "librispeech_clean",
            "librispeech_clean@pilot", "librispeech_clean@pilot"]


def test_two_pilot_summaries_for_one_cell_are_still_refused(tmp_path):
    _summary(tmp_path / "pilot", "wer_summary_pilot.json")
    _summary(tmp_path / "pilot_b", "wer_summary_pilot.json")
    with pytest.raises(SystemExit, match="@pilot"):
        agg.aggregate_sweep(tmp_path, include_pilot=True)


def test_a_recorded_corpus_outside_the_sweep_is_skipped_not_stem_matched(
        tmp_path, capsys):
    """EVAL-03: multilingual FLEURS files were filed as English 'fleurs'."""
    _summary(tmp_path, "wer_summary_fleurs_whisper-large-v3.json",
             dataset="google/fleurs", config="en_us")
    # What the multilingual job writes into the same directory.
    _summary(tmp_path, "wer_summary_fleurs_fr_fr.json",
             dataset="google/fleurs", config="fr_fr")
    _summary(tmp_path, "wer_summary_fleurs_de_de_pipeline_full.json",
             dataset="google/fleurs", config="de_de", condition="pipeline_full")
    rows = agg.aggregate_sweep(tmp_path)
    assert [(r.suite, r.source_file) for r in rows] == [
        ("fleurs", "wer_summary_fleurs_whisper-large-v3.json")]
    err = capsys.readouterr().err
    assert "wer_summary_fleurs_fr_fr.json" in err
    assert "google/fleurs/fr_fr" in err
    assert "wer_summary_fleurs_de_de_pipeline_full.json" in err


def test_a_summary_without_a_dataset_still_falls_back_to_the_stem():
    assert agg._infer_suite({"dataset": "google/fleurs", "config": "fr_fr"},
                            Path("wer_summary_fleurs_fr_fr.json")) is None
    assert agg._infer_suite({"config": "fr_fr"},
                            Path("wer_summary_fleurs_x.json")) == "fleurs"


def test_repeats_across_directories_name_the_nested_sweep(tmp_path):
    _summary(tmp_path, "wer_summary.json")
    _summary(tmp_path / "postfix", "wer_summary_librispeech_x.json")
    with pytest.raises(SystemExit, match=r"more than one directory \(\., postfix\)"):
        agg.aggregate_sweep(tmp_path)


def test_every_skipped_file_is_announced(tmp_path, capsys):
    _summary(tmp_path, "wer_summary.json")
    _summary(tmp_path, "wer_summary_nosum.json", summary=False)
    (tmp_path / "wer_summary_list.json").write_text("[]", encoding="utf-8")
    rows = agg.aggregate_sweep(tmp_path)
    err = capsys.readouterr().err
    assert len(rows) == 1
    assert "wer_summary_nosum.json" in err
    assert "wer_summary_list.json" in err


def test_a_duplicate_cell_is_refused(tmp_path):
    _summary(tmp_path, "wer_summary.json")
    _summary(tmp_path, "wer_summary_librispeech_whisper-large-v3.json")
    with pytest.raises(SystemExit, match="same"):
        agg.aggregate_sweep(tmp_path)


def test_a_missing_cell_fails_the_cli_unless_allowed(tmp_path):
    _summary(tmp_path, "wer_summary.json")
    _summary(tmp_path, "wer_summary_case_fold.json", condition="case_fold")
    _summary(tmp_path, "wer_summary_ami_x.json",
             dataset="edinburghcstr/ami", config="ihm")
    assert agg.missing_cells(agg.aggregate_sweep(tmp_path)) == [
        ("ami", "whisper-large-v3", "case_fold")]
    out = tmp_path / "out"
    with pytest.raises(SystemExit, match="missing"):
        agg.main(["--sweep-dir", str(tmp_path), "--out",
                  str(out / "a.csv"), "--out-json", str(out / "a.json")])
    agg.main(["--sweep-dir", str(tmp_path), "--out", str(out / "a.csv"),
              "--out-json", str(out / "a.json"), "--allow-incomplete"])
    with open(out / "a.csv", encoding="utf-8") as fh:
        assert next(csv.reader(fh)) == agg._CSV_FIELDS


# ---------------------------------------------------------------------------
# disfluency audit
# ---------------------------------------------------------------------------

def test_the_audit_probes_the_spellings_only_filler_strip_targets():
    from evaluation.disfluency import PROBE_TOKENS, audit_conditions
    for token in ("erm", "uhm", "hm", "ummm"):
        assert token in PROBE_TOKENS
    kept = audit_conditions(("filler_strip",))["filler_strip"]
    assert not kept["erm"] and not kept["uhm"] and not kept["hm"]
