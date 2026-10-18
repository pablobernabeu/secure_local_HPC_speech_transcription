"""Threshold comparisons require a fixed sample and an exact historical control."""

import csv
import ast
import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path

import pytest

pytest.importorskip("jiwer")

from evaluation.repetition_sensitivity import (
    HISTORICAL_CONTRACT_SHA256, HISTORICAL_DECODER_COMMIT, THRESHOLDS,
    _analyse_cell, analyse, main, repair_contract, validate_thresholds,
    verified_repair, write_outputs,
)
from evaluation.wer import PairResult, aggregate, compute_metrics, normalise_text


@pytest.fixture
def repair():
    return verified_repair()[0]


@pytest.mark.parametrize("invalid", [None, (), (0, 5), (-1, 5), (True, 5), (3.0, 5),
                                     (float("inf"), 5), (float("nan"), 5), ("3", 5)])
def test_invalid_thresholds_are_rejected(invalid):
    with pytest.raises(ValueError, match="positive integers"):
        validate_thresholds(invalid)


def test_threshold_grid_is_fixed_and_contains_the_control():
    assert validate_thresholds(THRESHOLDS) == (3, 4, 5, 6, 8, 10)
    with pytest.raises(ValueError, match="unique"):
        validate_thresholds((5, 5))
    with pytest.raises(ValueError, match="default five"):
        validate_thresholds((3, 4))


def test_sentence_word_and_phrase_boundaries_retain_the_tail(repair):
    sentence = "Hello. " * 6 + "Tail."
    assert repair(sentence, max_repetitions=5) == "Hello. Tail."
    assert repair(sentence, max_repetitions=6) == sentence
    word = "GO go Go go GO go tail"
    assert repair(word, max_repetitions=5) == "GO go tail"
    assert repair(word, max_repetitions=6) == word
    phrase = "thank you " * 11 + "tail"
    assert repair(phrase, max_repetitions=5) == "thank you [...] tail"
    assert repair(phrase, max_repetitions=6) == phrase
    assert repair("Hello. " * 11 + "Tail.", max_repetitions=8) == "Hello. [...] Tail."


def test_legitimate_short_emphasis_is_unchanged_at_every_threshold(repair):
    emphasis = "I said that that was very very important."
    phrase = "thank you " * 5 + "for coming"
    for threshold in THRESHOLDS:
        assert repair(emphasis, max_repetitions=threshold) == emphasis
        assert repair(phrase, max_repetitions=threshold) == phrase
    assert repair("", max_repetitions=5) == ""


def test_current_contract_matches_historical_and_ignores_documentation_only():
    source = (Path(__file__).resolve().parents[1] / "transcription.py").read_text(encoding="utf-8")
    original, _ = repair_contract(source)
    assert original == HISTORICAL_CONTRACT_SHA256
    assert repair_contract(source + "\n# Documentation only.\n")[0] == original
    for old, new in (("max_repetitions=5", "max_repetitions=6"),
                     ("PHRASE_REPETITION_LENIENCY = 2", "PHRASE_REPETITION_LENIENCY = 3"),
                     ("SENTENCE_LOOP_MARKER_ABOVE = 10", "SENTENCE_LOOP_MARKER_ABOVE = 11")):
        assert repair_contract(source.replace(old, new))[0] != original


def test_loaded_global_drift_is_rejected(monkeypatch, repair):
    import transcription
    monkeypatch.setattr(transcription, "_PHRASE_LOOP_RE", re.compile("fixture-different-pattern"))
    with pytest.raises(ValueError, match="regex differs"):
        verified_repair()


def test_contract_is_independent_of_python_ast_dump_formatting(monkeypatch):
    monkeypatch.setattr(ast, "dump", lambda *args, **kwargs: "version-dependent formatting")
    _, contract = verified_repair()
    assert contract["ast_sha256"] == HISTORICAL_CONTRACT_SHA256


def test_loaded_function_drift_is_rejected(monkeypatch, repair):
    import transcription

    def changed_repair(text, max_repetitions=5):
        return text

    monkeypatch.setattr(transcription, "detect_and_fix_repetitions", changed_repair)
    with pytest.raises(ValueError, match="loaded repetition repair differs"):
        verified_repair()


def _fixture_cell(repair):
    raw = [("loop", "Hello. Tail.", "Hello. " * 6 + "Tail."),
           ("legitimate", "Hello. " * 6 + "Tail.", "Hello. " * 6 + "Tail."),
           ("silent", "word", ""), ("spacing", "hello", " hello ")]
    pairs = {"raw": raw, "repetition_fix": [(uid, ref, repair(hyp)) for uid, ref, hyp in raw]}
    sources, cells = {}, {}
    for condition, rows in pairs.items():
        scores = [PairResult(name=uid, **compute_metrics(normalise_text(ref, strip_header=False),
                                                       normalise_text(hyp, strip_header=False))) for uid, ref, hyp in rows]
        summary = aggregate(scores)
        sources[condition] = {"benchmark": {"n_streamed": len(rows), "condition": condition, "model": "fixture-model"},
                              "summary": summary, "per_file": [asdict(result) for result in scores],
                              "run_metadata": {"git_commit": HISTORICAL_DECODER_COMMIT}}
        cells[condition] = {"n_utterances": summary["files"], "model": "fixture-model",
                            **{key: value for key, value in summary.items() if key != "files"}}
    return pairs, sources, cells


def test_fixed_sample_counts_improvement_harm_and_invisible_text_change(repair):
    pairs, sources, cells = _fixture_cell(repair)
    result = _analyse_cell(pairs, sources, cells, repair, THRESHOLDS, "fixture")
    baseline = result["raw"]
    assert result["n_raw_scored"] == result["n_scored_at_every_threshold"] == 4
    assert result["n_newly_excluded"] == result["n_newly_included"] == 0
    for candidate in result["thresholds"]:
        summary, counts = candidate["summary"], candidate["changes"]
        assert summary["total_reference_words"] == baseline["total_reference_words"]
        assert sum(counts[key] for key in ("wer_improved_from_raw", "wer_worsened_from_raw", "wer_tied_with_raw")) == 4
    default = next(row for row in result["thresholds"] if row["max_repetitions"] == 5)
    assert default["changes"]["wer_improved_from_raw"] == 1
    assert default["changes"]["wer_worsened_from_raw"] == 1
    assert default["changes"]["wer_tied_with_raw"] == 2
    assert default["changes"]["hypothesis_text_changed_from_raw"] == 3
    assert default["changes"]["normalised_hypothesis_changed_from_raw"] == 2
    assert default["changes"]["metric_fields_changed_from_default"] == 0
    assert default["summary"] == sources["repetition_fix"]["summary"]
    assert default["summary"]["macro_wer"] != default["summary"]["micro_wer"]
    assert default["summary"]["total_deletions"] >= 1  # The empty hypothesis remains scored.
    high = next(row for row in result["thresholds"] if row["max_repetitions"] == 10)
    assert high["summary"] == baseline
    assert high["changes"]["metric_fields_changed_from_raw"] == 0


@pytest.mark.parametrize("mutation,message", [
    ("default_text", "default-five repaired text"), ("reference", "changed the reference"),
    ("default_metric", "per-utterance metrics"), ("raw_aggregate", "committed aggregate"),
    ("missing_pair", "UID sets"), ("duplicate_pair", "duplicate utterance ID"),
])
def test_default_control_and_sample_drift_stop_analysis(repair, mutation, message):
    pairs, sources, cells = _fixture_cell(repair)
    if mutation == "default_text":
        uid, ref, _ = pairs["repetition_fix"][0]
        pairs["repetition_fix"][0] = (uid, ref, "wrong fixture text")
    elif mutation == "reference":
        uid, _, hyp = pairs["repetition_fix"][0]
        pairs["repetition_fix"][0] = (uid, "different reference", hyp)
    elif mutation == "default_metric":
        sources["repetition_fix"]["per_file"][0]["hits"] += 1
    elif mutation == "raw_aggregate":
        cells["raw"]["macro_wer"] += 1e-12
    elif mutation == "missing_pair":
        pairs["repetition_fix"].pop()
    else:
        pairs["raw"].append(pairs["raw"][0])
    with pytest.raises(ValueError, match=message):
        _analyse_cell(pairs, sources, cells, repair, THRESHOLDS, "fixture")


@pytest.fixture
def tiny_snapshot(tmp_path, repair):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    pairs, sources, cells = _fixture_cell(repair)
    records, grid, digests = [], [], []
    for condition in ("raw", "repetition_fix"):
        name = f"wer_summary_fixture_model_{condition}.json"
        content = json.dumps(sources[condition]).encode()
        (inputs / name).write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        records.append({"name": name, "sha256": digest, "bytes": len(content)})
        digests.append({"source_file": name, "sha256": digest})
        grid.append({"suite": "fixture", "model_slug": "model", "condition": condition,
                     "source_file": name, **cells[condition]})
    dump = inputs / "wer_hypotheses_fixture_model.csv"
    with dump.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["uid", "condition", "reference_raw", "reference_transformed", "hypothesis_raw", "hypothesis_transformed", "wer"])
        for condition in ("raw", "repetition_fix"):
            for index, (uid, ref, hyp) in enumerate(pairs[condition]):
                _, raw_ref, raw_hyp = pairs["raw"][index]
                writer.writerow([uid, condition, raw_ref, ref, raw_hyp, hyp, f"{sources[condition]['per_file'][index]['wer']:.6f}"])
    records.append({"name": dump.name, "sha256": hashlib.sha256(dump.read_bytes()).hexdigest(), "bytes": dump.stat().st_size})
    aggregate_path = tmp_path / "aggregate.json"
    aggregate_path.write_text(json.dumps({"rows": grid, "provenance": {"inputs": digests}}))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"decoder_commit": HISTORICAL_DECODER_COMMIT, "files": records}))
    return inputs, aggregate_path, manifest, dump


def test_verified_fixture_writes_only_separate_reports(tmp_path, tiny_snapshot):
    inputs, aggregate_path, manifest, _ = tiny_snapshot
    payload = analyse(inputs, aggregate_path, manifest)
    csv_path, json_path = tmp_path / "repetition_sensitivity.csv", tmp_path / "repetition_sensitivity.json"
    write_outputs(payload, csv_path, json_path)
    with csv_path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 7
    assert rows[0]["condition"] == "raw"
    assert rows[0]["wer_tied_with_raw"] == "4"
    assert rows[0]["hypothesis_text_changed_from_default"] == "3"
    assert rows[0]["normalised_hypothesis_changed_from_default"] == "2"
    assert rows[0]["metric_fields_changed_from_default"] == "2"
    assert payload["design"]["repair_contract"]["historical_contract_verified"]
    assert len(payload["provenance"]["input_files"]) == 3
    assert json.loads(json_path.read_text())["cells"][0]["default_five_original_verified"]


@pytest.mark.parametrize("mutation,message", [
    ("stored_wer", "stored WER differs"), ("truncated_row", "CSV row columns"),
    ("extra_column", "CSV row columns"), ("raw_string", "raw hypothesis was transformed"),
])
def test_changed_dump_is_rejected_even_with_updated_receipt(tiny_snapshot, mutation, message):
    inputs, aggregate_path, manifest, dump = tiny_snapshot
    with dump.open(newline="") as handle:
        rows = list(csv.reader(handle))
    if mutation == "stored_wer":
        rows[1][-1] = "999"
    elif mutation == "truncated_row":
        rows[1].pop()
    elif mutation == "extra_column":
        rows[1].append("unexpected")
    else:
        rows[1][5] += " changed"
    with dump.open("w", newline="") as handle:
        csv.writer(handle).writerows(rows)
    receipt = json.loads(manifest.read_text())
    for record in receipt["files"]:
        if record["name"] == dump.name:
            record.update(sha256=hashlib.sha256(dump.read_bytes()).hexdigest(), bytes=dump.stat().st_size)
    manifest.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match=message):
        analyse(inputs, aggregate_path, manifest)


def test_wrong_historical_decoder_receipt_is_rejected(tiny_snapshot):
    inputs, aggregate_path, manifest, _ = tiny_snapshot
    receipt = json.loads(manifest.read_text())
    receipt["decoder_commit"] = "wrong-source"
    manifest.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="different historical decoder"):
        analyse(inputs, aggregate_path, manifest)


@pytest.mark.parametrize("protected", ["aggregate", "manifest", "input"])
def test_cli_cannot_overwrite_sources(tiny_snapshot, tmp_path, protected):
    inputs, aggregate_path, manifest, dump = tiny_snapshot
    output = {"aggregate": aggregate_path, "manifest": manifest, "input": dump}[protected]
    previous = output.read_bytes()
    with pytest.raises(ValueError, match="overwrite"):
        main(["--inputs", str(inputs), "--aggregate", str(aggregate_path), "--input-manifest", str(manifest),
              "--output-csv", str(output), "--output-json", str(tmp_path / "repetition_sensitivity.json")])
    assert output.read_bytes() == previous


def test_output_names_cannot_target_canonical_reports(tmp_path):
    with pytest.raises(ValueError, match="separate outputs"):
        write_outputs({}, tmp_path / "wer_report.csv", tmp_path / "wer_summary.json")
    with pytest.raises(ValueError, match="different files"):
        write_outputs({}, tmp_path / "same", tmp_path / "same")
