"""Sensitivity must preserve lexical marks and account for its scored sample."""

import csv
import hashlib
import json
from dataclasses import asdict

import pytest

pytest.importorskip("jiwer")

from evaluation.scorer_sensitivity import (
    _analyse_cell, _committed_text_record, analyse, gains_on_common, normalise_for_rule,
    main, score_pairs, strip_edge_apostrophes, write_outputs,
)
from evaluation.wer import aggregate


def test_internal_unicode_contractions_and_digit_apostrophes_are_preserved():
    text = "‘don't’ o’clock l’homme c’était 1990’s _x'y_"
    assert normalise_for_rule(text, "edge_apostrophe") == "don't o'clock l'homme c'était 1990's _x'y_"


def test_quotes_edge_elisions_and_terminal_possessives_are_removed_symmetrically():
    assert strip_edge_apostrophes("  'now ' 'tis hours' anders'  ") == "now tis hours anders"
    original, _ = score_pairs([("dialogue", "'now' she said", "now she said")], "original")
    revised, _ = score_pairs([("dialogue", "'now' she said", "now she said")], "edge_apostrophe")
    assert original["dialogue"].substitutions == 1
    assert revised["dialogue"].wer == 0
    reversed_sides, _ = score_pairs([("dialogue", "now she said", "'now' she said")], "edge_apostrophe")
    assert reversed_sides["dialogue"].wer == 0


@pytest.mark.parametrize("reference,hypothesis", [
    ("0.05", "0.5"), ("10", "100"), ("1990's", "1990s"),
])
def test_numerical_or_lexical_distinctions_are_not_erased(reference, hypothesis):
    scores, _ = score_pairs([("one", reference, hypothesis)], "edge_apostrophe")
    assert scores["one"].wer > 0


def test_historical_fraction_fold_is_outside_this_sensitivity():
    assert normalise_for_rule("29¾", "edge_apostrophe") == "293 4"


def test_committed_text_metadata_accepts_line_endings_but_rejects_content_changes(tmp_path):
    source = tmp_path / "source.py"
    source.write_bytes(b"value = 1\n# same source\n")
    lf = _committed_text_record(source, "source.py")
    source.write_bytes(b"value = 1\r\n# same source\r\n")
    assert _committed_text_record(source, "source.py") == lf
    source.write_bytes(b"value = 2\r\n# same source\r\n")
    assert _committed_text_record(source, "source.py") != lf


@pytest.mark.parametrize("bad", [None, 5, [], {}])
def test_invalid_text_is_rejected(bad):
    with pytest.raises(TypeError, match="string"):
        strip_edge_apostrophes(bad)
    with pytest.raises(TypeError, match="string"):
        score_pairs([("x", bad, "ok")], "edge_apostrophe")


def test_empty_references_and_hypotheses_have_distinct_meanings():
    scores, excluded = score_pairs([
        ("empty", "  ", "text"), ("quote", "'", "text"), ("silent", "word", ""),
    ], "edge_apostrophe")
    assert excluded == ["empty", "quote"]
    assert scores["silent"].deletions == 1
    assert scores["silent"].wer == 1


@pytest.mark.parametrize("pairs", [
    [("x", "word", "word"), ("x", "word", "word")],
    [("", "word", "word")], [(" ", "word", "word")], [(3, "word", "word")],
])
def test_invalid_or_repeated_ids_cannot_silently_change_the_sample(pairs):
    with pytest.raises(ValueError, match="ID"):
        score_pairs(pairs, "original")


def test_unknown_rule_is_rejected_even_for_an_empty_input():
    with pytest.raises(ValueError, match="unknown"):
        score_pairs([], "guessed")


def test_gain_pairs_the_common_sample_and_retains_each_denominator():
    raw, _ = score_pairs([
        ("common", "one two", "one"), ("raw_only", "word", ""),
    ], "original")
    condition, _ = score_pairs([("common", "one two three", "one two")], "original")
    gain = gains_on_common(raw, condition)
    assert gain["n_shared"] == 1
    assert gain["n_baseline_only"] == 1
    assert gain["n_condition_only"] == 0
    assert gain["macro_baseline_shared"] == 0.5
    assert gain["macro_condition_shared"] == pytest.approx(1 / 3)
    assert gain["macro_gain_shared"] == pytest.approx(1 / 3)
    assert gain["micro_gain_shared"] == pytest.approx(1 / 3)
    assert gain["reference_words_baseline_shared"] == 2
    assert gain["reference_words_condition_shared"] == 3


def test_fixed_sample_and_undefined_relative_gains_are_explicit():
    raw, _ = score_pairs([("perfect", "word", "word"), ("error", "word", "bad")], "original")
    condition, _ = score_pairs([("perfect", "word", "word"), ("error", "word", "word")], "original")
    gain = gains_on_common(raw, condition, {"perfect"})
    assert gain["n_shared"] == 1
    assert gain["macro_gain_shared"] is None
    assert gain["micro_gain_shared"] is None
    with pytest.raises(ValueError, match="unscored"):
        gains_on_common(raw, condition, {"missing"})
    with pytest.raises(ValueError, match="no common"):
        gains_on_common(raw, {})


def _source(pairs):
    scores, excluded = score_pairs(pairs, "original")
    assert not excluded
    summary = aggregate(scores.values())
    source = {"benchmark": {"n_streamed": len(pairs), "n_skipped_empty_reference": 0},
              "summary": summary, "per_file": [asdict(r) for r in scores.values()]}
    cell = {"n_utterances": summary["files"], **{k: v for k, v in summary.items() if k != "files"}}
    return source, cell


def test_new_empty_reference_changes_both_condition_and_cross_rule_sample():
    pairs = {condition: [("quote", "'", ""), ("valid", "word", "word")]
             for condition in ("raw", "whisper_norm")}
    source, cell = _source(pairs["raw"])
    result = _analyse_cell(pairs, {c: source for c in pairs}, {c: cell for c in pairs}, "fixture")
    for condition in pairs:
        detail = result["conditions"][condition]
        assert detail["n_newly_excluded"] == 1
        assert detail["newly_excluded_uids"] == ["quote"]
        assert detail["original"]["files"] == 2
        assert detail["edge_apostrophe"]["files"] == 1
    assert result["paired_gains"]["original"]["n_shared"] == 2
    assert result["paired_gains"]["edge_apostrophe"]["n_shared"] == 1
    assert result["cross_rule_sample"] == {
        "n_common": 1, "newly_excluded_shared_uids": ["quote"], "newly_included_shared_uids": [],
    }
    assert result["paired_gains_on_fixed_cross_rule_sample"]["original"]["n_shared"] == 1


def test_original_metric_drift_stops_analysis():
    pairs = {condition: [("one", "word", "word")] for condition in ("raw", "whisper_norm")}
    source, cell = _source(pairs["raw"])
    source["per_file"][0]["hits"] = 99
    with pytest.raises(ValueError, match="original per-utterance"):
        _analyse_cell(pairs, {c: source for c in pairs}, {c: cell for c in pairs}, "fixture")


@pytest.fixture
def tiny_snapshot(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    pairs = [("one", "now she said", "'now' she said")]
    source, cell = _source(pairs)
    records, grid, digests = [], [], []
    for condition in ("raw", "whisper_norm"):
        name = f"wer_summary_fixture_model_{condition}.json"
        data = json.dumps(source).encode()
        (inputs / name).write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        records.append({"name": name, "sha256": digest})
        digests.append({"source_file": name, "sha256": digest})
        grid.append({"suite": "fixture", "model_slug": "model", "condition": condition,
                     "source_file": name, **cell})
    dump = inputs / "wer_hypotheses_fixture_model.csv"
    with dump.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["uid", "condition", "reference_transformed", "hypothesis_transformed", "wer"])
        for condition in ("raw", "whisper_norm"):
            writer.writerow([*pairs[0][:1], condition, *pairs[0][1:], f"{source['per_file'][0]['wer']:.6f}"])
    records.append({"name": dump.name, "sha256": hashlib.sha256(dump.read_bytes()).hexdigest()})
    aggregate_path = tmp_path / "aggregate.json"
    aggregate_path.write_text(json.dumps({"rows": grid, "provenance": {"inputs": digests}}))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"files": records, "source": "synthetic test fixture"}))
    return inputs, aggregate_path, manifest, dump


def test_tiny_recovered_snapshot_is_checked_and_written_separately(tmp_path, tiny_snapshot):
    inputs, aggregate_path, manifest, dump = tiny_snapshot
    payload = analyse(inputs, aggregate_path, manifest)
    csv_path, json_path = tmp_path / "separate.csv", tmp_path / "separate.json"
    write_outputs(payload, csv_path, json_path)
    assert len(list(csv.DictReader(csv_path.open()))) == 4
    saved = json.loads(json_path.read_text())
    assert saved["provenance"]["original_scoring_verified"] is True
    assert "source" not in saved["provenance"]
    assert saved["cells"][0]["conditions"]["raw"]["edge_apostrophe"]["macro_wer"] == 0
    dump.write_text(dump.read_text() + "changed")
    with pytest.raises(ValueError, match="checksum"):
        analyse(inputs, aggregate_path, manifest)


@pytest.mark.parametrize("change,message", [
    ("wrong_wer", "stored WER differs"), ("nan_wer", "invalid stored WER"),
    ("missing_column", "CSV row columns"), ("extra_column", "CSV row columns"),
])
def test_mutated_dump_cannot_pass_by_updating_its_local_hash(tiny_snapshot, change, message):
    inputs, aggregate_path, manifest, dump = tiny_snapshot
    lines = dump.read_text().splitlines()
    if change == "wrong_wer":
        lines[1] = lines[1].rsplit(",", 1)[0] + ",0.0"
    elif change == "nan_wer":
        lines[1] = lines[1].rsplit(",", 1)[0] + ",NaN"
    elif change == "missing_column":
        lines[1] = lines[1].rsplit(",", 1)[0]
    else:
        lines[1] += ",extra"
    dump.write_text("\n".join(lines) + "\n")
    recovery = json.loads(manifest.read_text())
    for record in recovery["files"]:
        if record["name"] == dump.name:
            record["sha256"] = hashlib.sha256(dump.read_bytes()).hexdigest()
    manifest.write_text(json.dumps(recovery))
    with pytest.raises(ValueError, match=message):
        analyse(inputs, aggregate_path, manifest)


def test_output_writers_reject_identical_destinations_without_writing(tmp_path):
    path = tmp_path / "both.txt"
    with pytest.raises(ValueError, match="different files"):
        write_outputs({}, path, path)
    assert not path.exists()


@pytest.mark.parametrize("protected", ["aggregate", "manifest", "input"])
def test_cli_cannot_overwrite_its_source_files(tiny_snapshot, tmp_path, protected):
    inputs, aggregate_path, manifest, dump = tiny_snapshot
    destination = {"aggregate": aggregate_path, "manifest": manifest, "input": dump}[protected]
    before = destination.read_bytes()
    with pytest.raises(ValueError, match="overwrite"):
        main(["--inputs", str(inputs), "--aggregate", str(aggregate_path),
              "--input-manifest", str(manifest), "--output-csv", str(destination),
              "--output-json", str(tmp_path / "separate.json")])
    assert destination.read_bytes() == before
    assert not (tmp_path / "separate.json").exists()
