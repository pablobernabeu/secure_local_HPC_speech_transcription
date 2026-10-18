"""Exploratory repetition-threshold sensitivity from retained raw hypotheses.

The study follow-up specified thresholds 3, 4, 5, 6, 8 and 10 before this
analysis. Only max_repetitions varies. References, the original WER scorer,
phrase leniency, sentence markers and the function's other repairs stay fixed.
The original raw and default-five condition must first reproduce at full
precision. No model is loaded, no reference is corrected and no sampling
confidence interval is estimated. Outputs are separate exploratory reports.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import inspect
import json
import math
import platform
import re
import sys
from textwrap import dedent
from importlib.metadata import version
from pathlib import Path

from evaluation.scorer_sensitivity import (
    _committed_text_record,
    _read_json,
    _sha256,
    _validate_original,
    _validate_output_paths,
)
from evaluation.wer import PairResult, aggregate, compute_metrics, normalise_text
from provenance import run_metadata

THRESHOLDS = (3, 4, 5, 6, 8, 10)
DEFAULT_THRESHOLD = 5
SOURCE_CONDITIONS = ("raw", "repetition_fix")
HISTORICAL_DECODER_COMMIT = "6f9bf56a0d5839920537f23d73a166dc0f1e478b"
HISTORICAL_SOURCE_SHA256_LF = "8da53094674ced70f62281e2dde7e0ea2e5316c49eb23f19a7f91e6dcac44362"
# Verified from the separately archived historical Git blob before analysis.
HISTORICAL_CONTRACT_SHA256 = "ff0faad572e33b81ec2cda67c885b7ebd905525ae14c57c47238a32f5bf2450a"
CONTRACT_NAMES = (
    "PHRASE_REPETITION_LENIENCY", "SENTENCE_LOOP_MARKER_ABOVE",
    "_PHRASE_LOOP_RE", "detect_and_fix_repetitions",
)
DUMP_COLUMNS = {
    "uid", "condition", "reference_raw", "reference_transformed",
    "hypothesis_raw", "hypothesis_transformed", "wer",
}
CHANGE_FIELDS = (
    "hypothesis_text_changed_from_raw", "normalised_hypothesis_changed_from_raw",
    "metric_fields_changed_from_raw", "wer_improved_from_raw", "wer_worsened_from_raw",
    "wer_tied_with_raw", "hypothesis_text_changed_from_default",
    "normalised_hypothesis_changed_from_default", "metric_fields_changed_from_default",
)


def validate_thresholds(thresholds) -> tuple[int, ...]:
    """Require unique positive integer thresholds, including the default control."""
    try:
        values = tuple(thresholds)
    except TypeError as error:
        raise ValueError("thresholds must be positive integers") from error
    if not values or any(isinstance(value, bool) or not isinstance(value, int) or value <= 0
                         for value in values):
        raise ValueError("thresholds must be positive integers")
    if len(set(values)) != len(values):
        raise ValueError("thresholds must be unique")
    if DEFAULT_THRESHOLD not in values:
        raise ValueError("thresholds must include default five for verification")
    return values


def _without_docstring(node):
    if isinstance(node, ast.FunctionDef) and node.body and isinstance(node.body[0], ast.Expr):
        value = node.body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            node.body = node.body[1:]
    return node


def _ast_value(value):
    """Keep every AST field explicitly; ast.dump formatting differs by Python version."""
    if isinstance(value, ast.AST):
        return {"node": type(value).__name__, "fields": {key: _ast_value(item) for key, item in ast.iter_fields(value)}}
    if isinstance(value, list):
        return [_ast_value(item) for item in value]
    return value


def repair_contract(source: str) -> tuple[str, ast.FunctionDef]:
    """Hash the repair and its three globals, ignoring comments and docstrings."""
    selected, names, function = [], [], None
    for node in ast.parse(source).body:
        name = None
        if isinstance(node, ast.FunctionDef):
            name = node.name
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        if name in CONTRACT_NAMES:
            selected.append(_without_docstring(node))
            names.append(name)
            if name == "detect_and_fix_repetitions":
                function = node
    if tuple(names) != CONTRACT_NAMES or function is None:
        raise ValueError("repair contract definitions are missing, repeated or reordered")
    serialised = json.dumps(_ast_value(ast.Module(body=selected, type_ignores=[])),
                            sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest(), function


def verified_repair():
    """Load the current optional CPU helper only after checking historical identity."""
    source_path = Path(__file__).resolve().parents[1] / "transcription.py"
    digest, function = repair_contract(source_path.read_text(encoding="utf-8"))
    if digest != HISTORICAL_CONTRACT_SHA256:
        raise ValueError("current repetition repair differs from the historical decoder contract")
    import transcription  # noqa: PLC0415

    repair = transcription.detect_and_fix_repetitions
    try:
        loaded = _without_docstring(ast.parse(dedent(inspect.getsource(repair))).body[0])
    except (OSError, TypeError, SyntaxError) as error:
        raise ValueError("loaded repetition repair cannot be verified against source") from error
    if _ast_value(loaded) != _ast_value(function):
        raise ValueError("loaded repetition repair differs from the verified source")
    if transcription.PHRASE_REPETITION_LENIENCY != 2 or transcription.SENTENCE_LOOP_MARKER_ABOVE != 10:
        raise ValueError("loaded repetition constants differ from historical defaults")
    if (transcription._PHRASE_LOOP_RE.pattern != r'(\b\w+(?:\s+\w+){1,5}?)\s*(?:\1\s*){4,}'
            or transcription._PHRASE_LOOP_RE.flags != (re.IGNORECASE | re.UNICODE)):
        raise ValueError("loaded repetition regex differs from historical defaults")
    return repair, {
        "historical_decoder_commit": HISTORICAL_DECODER_COMMIT,
        "historical_source_file": "transcription.py",
        "historical_source_sha256_lf": HISTORICAL_SOURCE_SHA256_LF,
        "current_source": _committed_text_record(source_path, "transcription.py"),
        "definitions": list(CONTRACT_NAMES),
        "ast_sha256": digest,
        "ast_policy": "Source-order AST serialised as sorted-key compact UTF-8 JSON of node types and every field, including empty lists and nulls; no locations, comments or function docstrings. All four definitions and the loaded function checked.",
        "default_threshold": DEFAULT_THRESHOLD,
        "phrase_repetition_leniency": 2,
        "sentence_loop_marker_above": 10,
        "historical_contract_verified": True,
    }


def _pair(uid, reference, hypothesis):
    return PairResult(name=uid, **compute_metrics(reference, hypothesis))


def _analyse_cell(pairs, sources, cells, repair, thresholds, name):
    """Hold raw scored IDs/references fixed and validate the retained default control."""
    raw, retained = {}, {}
    for condition, destination in (("raw", raw), ("repetition_fix", retained)):
        for uid, reference, hypothesis in pairs[condition]:
            if not isinstance(uid, str) or not uid.strip() or uid in destination:
                raise ValueError(f"{name}: invalid or duplicate utterance ID")
            if not isinstance(reference, str) or not isinstance(hypothesis, str):
                raise TypeError("reference and hypothesis must be strings")
            destination[uid] = (reference, hypothesis)
    if not raw or set(raw) != set(retained):
        raise ValueError(f"{name}: raw and default scored UID sets must be identical")
    scores, default_scores, references, normalised_raw, default_texts, normalised_default = {}, {}, {}, {}, {}, {}
    for uid, (reference, hypothesis) in raw.items():
        retained_reference, retained_hypothesis = retained[uid]
        if retained_reference != reference:
            raise ValueError(f"{name}/{uid}: repetition condition changed the reference")
        reference_norm = normalise_text(reference, strip_header=False)
        if not reference_norm:
            raise ValueError(f"{name}/{uid}: originally scored reference is empty")
        candidate = repair(hypothesis, max_repetitions=DEFAULT_THRESHOLD)
        if candidate != retained_hypothesis:
            raise ValueError(f"{name}/{uid}: default-five repaired text differs from retained condition")
        references[uid] = reference_norm
        normalised_raw[uid] = normalise_text(hypothesis, strip_header=False)
        default_texts[uid] = candidate
        normalised_default[uid] = normalise_text(candidate, strip_header=False)
        scores[uid] = _pair(uid, reference_norm, normalised_raw[uid])
        default_scores[uid] = _pair(uid, reference_norm, normalised_default[uid])
    baseline = _validate_original(scores, sources["raw"], cells["raw"], f"{name}/raw")
    control = _validate_original(default_scores, sources["repetition_fix"], cells["repetition_fix"], f"{name}/repetition_fix")
    streamed = sources["raw"]["benchmark"]["n_streamed"]
    if isinstance(streamed, bool) or not isinstance(streamed, int) or streamed < len(raw):
        raise ValueError(f"{name}: invalid n_streamed")
    if sources["repetition_fix"]["benchmark"]["n_streamed"] != streamed:
        raise ValueError(f"{name}: source n_streamed differs across conditions")
    results = []
    for threshold in thresholds:
        changed = dict.fromkeys(CHANGE_FIELDS, 0)
        candidate_scores = {}
        for uid, (_, hypothesis) in raw.items():
            text = default_texts[uid] if threshold == DEFAULT_THRESHOLD else repair(hypothesis, max_repetitions=threshold)
            if not isinstance(text, str):
                raise TypeError("repetition repair must return a string")
            normalised = normalise_text(text, strip_header=False)
            # Most candidates have identical scoring strings. Reuse only exact
            # matches, so sparse changes do not require repeated jiwer alignments.
            if normalised == normalised_raw[uid]:
                result = scores[uid]
            elif normalised == normalised_default[uid]:
                result = default_scores[uid]
            else:
                result = _pair(uid, references[uid], normalised)
            if result.reference_words != scores[uid].reference_words:
                raise ValueError("candidate changed the fixed reference denominator")
            candidate_scores[uid] = result
            changed["hypothesis_text_changed_from_raw"] += int(text != hypothesis)
            changed["normalised_hypothesis_changed_from_raw"] += int(normalised != normalised_raw[uid])
            changed["metric_fields_changed_from_raw"] += int(result != scores[uid])
            changed["hypothesis_text_changed_from_default"] += int(text != default_texts[uid])
            changed["normalised_hypothesis_changed_from_default"] += int(normalised != normalised_default[uid])
            changed["metric_fields_changed_from_default"] += int(result != default_scores[uid])
            key = ("wer_improved_from_raw" if result.wer < scores[uid].wer else
                   "wer_worsened_from_raw" if result.wer > scores[uid].wer else "wer_tied_with_raw")
            changed[key] += 1
        summary = aggregate(candidate_scores.values())
        if threshold == DEFAULT_THRESHOLD and summary != control:
            raise ValueError("default-five aggregate drifted after verification")
        results.append({
            "max_repetitions": threshold, "summary": summary, "changes": changed,
            "macro_gain_from_raw": ((baseline["macro_wer"] - summary["macro_wer"]) / baseline["macro_wer"]
                                    if baseline["macro_wer"] else None),
            "micro_gain_from_raw": ((baseline["micro_wer"] - summary["micro_wer"]) / baseline["micro_wer"]
                                    if baseline["micro_wer"] else None),
        })
    return {
        "n_streamed": streamed, "n_raw_scored": len(raw), "n_original_excluded": streamed - len(raw),
        "n_scored_at_every_threshold": len(raw), "n_newly_excluded": 0, "n_newly_included": 0,
        "raw": baseline, "default_five_original_verified": True,
        "original_skip_counts": {condition: {key: value for key, value in sources[condition]["benchmark"].items()
                                             if key.startswith("n_skipped_")} for condition in SOURCE_CONDITIONS},
        "thresholds": results,
    }


def analyse(inputs: Path, aggregate_path: Path, input_manifest: Path, thresholds=THRESHOLDS) -> dict:
    """Check exact inputs and original controls before analysing all retained raw cells."""
    thresholds = validate_thresholds(thresholds)
    repair, contract = verified_repair()
    committed = _read_json(aggregate_path)
    grid = {}
    for row in committed["rows"]:
        key = row["suite"], row["model_slug"], row["condition"]
        if key in grid:
            raise ValueError(f"duplicate aggregate cell: {key}")
        grid[key] = row
    recorded = {item["source_file"]: item["sha256"] for item in committed["provenance"]["inputs"]}
    manifest = _read_json(input_manifest)
    if manifest.get("decoder_commit") != HISTORICAL_DECODER_COMMIT:
        raise ValueError("input manifest identifies a different historical decoder")
    expected = {item["name"]: item for item in manifest["files"]}
    if len(expected) != len(manifest["files"]):
        raise ValueError("duplicate input manifest filenames")
    input_records, results = [], []
    for suite, model in sorted({key[:2] for key in grid}):
        sources, cells = {}, {}
        dump_name = f"wer_hypotheses_{suite}_{model}.csv"
        for condition in SOURCE_CONDITIONS:
            if (suite, model, condition) not in grid:
                raise ValueError(f"missing source condition: {suite}/{model}/{condition}")
            cells[condition] = grid[suite, model, condition]
            filename = cells[condition]["source_file"]
            path = inputs / filename
            if not path.resolve().is_relative_to(inputs.resolve()):
                raise ValueError("summary source lies outside the input snapshot")
            digest = _sha256(path)
            record = expected.get(filename, {})
            if digest != recorded.get(filename) or digest != record.get("sha256") or path.stat().st_size != record.get("bytes"):
                raise ValueError(f"summary input checksum/size differs: {filename}")
            input_records.append({"name": filename, "bytes": path.stat().st_size, "sha256": digest})
            sources[condition] = _read_json(path)
            if sources[condition].get("run_metadata", {}).get("git_commit") != HISTORICAL_DECODER_COMMIT:
                raise ValueError(f"source summary identifies a different historical decoder: {filename}")
            benchmark = sources[condition]["benchmark"]
            if benchmark.get("condition") != condition or benchmark.get("model") != cells[condition].get("model"):
                raise ValueError(f"source summary condition/model differs from aggregate cell: {filename}")
        dump_path = inputs / dump_name
        if not dump_path.resolve().is_relative_to(inputs.resolve()):
            raise ValueError("hypothesis dump lies outside the input snapshot")
        digest = _sha256(dump_path)
        record = expected.get(dump_name, {})
        if digest != record.get("sha256") or dump_path.stat().st_size != record.get("bytes"):
            raise ValueError(f"hypothesis dump checksum/size differs: {dump_name}")
        input_records.append({"name": dump_name, "bytes": dump_path.stat().st_size, "sha256": digest})
        pairs = {condition: [] for condition in SOURCE_CONDITIONS}
        source_wers = {condition: {row["name"]: row["wer"] for row in source["per_file"]}
                       for condition, source in sources.items()}
        raw_strings = {}
        with dump_path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if set(reader.fieldnames or []) != DUMP_COLUMNS or len(reader.fieldnames) != len(DUMP_COLUMNS):
                raise ValueError(f"{dump_name}: missing, extra or repeated dump columns")
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError(f"{dump_name}: incomplete or extra CSV row columns")
                condition = row["condition"]
                if condition not in pairs:
                    continue
                try:
                    stored = float(row["wer"])
                except (ValueError, TypeError) as error:
                    raise ValueError(f"{dump_name}: invalid stored WER") from error
                reference_wer = source_wers[condition].get(row["uid"])
                if not math.isfinite(stored) or stored < 0 or reference_wer is None or stored != float(f"{reference_wer:.6f}"):
                    raise ValueError(f"{dump_name}/{row['uid']}: stored WER differs from original six-decimal score")
                raw_pair = (row["reference_raw"], row["hypothesis_raw"])
                if row["uid"] in raw_strings and raw_strings[row["uid"]] != raw_pair:
                    raise ValueError(f"{dump_name}: raw strings differ across conditions")
                raw_strings[row["uid"]] = raw_pair
                if row["reference_transformed"] != row["reference_raw"]:
                    raise ValueError(f"{dump_name}: raw/repetition reference was transformed")
                if condition == "raw" and row["hypothesis_transformed"] != row["hypothesis_raw"]:
                    raise ValueError(f"{dump_name}: raw hypothesis was transformed")
                pairs[condition].append((row["uid"], row["reference_transformed"], row["hypothesis_transformed"]))
        result = _analyse_cell(pairs, sources, cells, repair, thresholds, f"{suite}/{model}")
        results.append({"suite": suite, "model_slug": model, **result})
        print(f"verified raw/default and analysed {suite}/{model}", flush=True)
    return {
        "schema_version": 1,
        "analysis": "Exploratory repetition-threshold sensitivity; canonical repair and WER results retained.",
        "design": {"study_followup_thresholds": list(THRESHOLDS), "selected_thresholds": list(thresholds),
                   "varied_parameter": "max_repetitions", "fixed_sample": "Every originally scored raw utterance in each suite/model cell",
                   "reference_policy": "Unchanged raw reference at every threshold; each per-utterance and pooled denominator is fixed",
                   "scorer": "evaluation.wer.normalise_text(..., strip_header=False) and compute_metrics; no apostrophe sensitivity rule",
                   "repair_contract": contract},
        "provenance": {
            "digest_policy": {"committed_text_and_input_manifest": "SHA-256 with CRLF normalised to LF", "recovered_arc_inputs": "SHA-256 of exact raw bytes"},
            "aggregate": _committed_text_record(aggregate_path, aggregate_path.as_posix()),
            "input_manifest": _committed_text_record(input_manifest, input_manifest.as_posix()),
            "input_files": input_records,
            "producer": _committed_text_record(Path(__file__), "evaluation/repetition_sensitivity.py"),
            "verification_helpers": _committed_text_record(Path(__file__).with_name("scorer_sensitivity.py"), "evaluation/scorer_sensitivity.py"),
            "original_scorer": _committed_text_record(Path(__file__).with_name("wer.py"), "evaluation/wer.py"),
            "python": platform.python_version(), "jiwer": version("jiwer"), "rapidfuzz": version("rapidfuzz"),
            "suite_model_cells": len(results), "source_condition_cells": len(results) * 2,
            "original_verification": {"raw_and_default_five_per_utterance": "exact", "summary_and_aggregate": "exact at full precision",
                                      "default_repaired_strings": "exact equality to retained repetition_fix strings", "stored_dump_wer": "original score rounded to six decimals"},
        },
        "limits": [
            "Originally excluded raw pairs are not reconstructed; every comparison uses the retained raw scored sample.",
            "References remain unchanged, including their transcription conventions and possible errors.",
            "No decoding, sampling confidence interval or uncertainty about reference correctness is estimated.",
            "Other fixed repairs remain active, including counting-sequence and symbol repairs; this isolates max_repetitions, not every repetition heuristic.",
            "A threshold with lower observed WER is not validated for legitimate repetitions or deployment recordings.",
            "Reproduction requires the separately retained input bundle; public deposit remains pending.",
        ],
        "cells": results,
    }


def _output_names(csv_path: Path, json_path: Path):
    if csv_path.resolve() == json_path.resolve():
        raise ValueError("CSV and JSON outputs must be different files")
    if csv_path.name != "repetition_sensitivity.csv" or json_path.name != "repetition_sensitivity.json":
        raise ValueError("separate outputs must be named repetition_sensitivity.csv and repetition_sensitivity.json")


def write_outputs(payload: dict, csv_path: Path, json_path: Path):
    """Write the separate baseline and threshold rows after all checks pass."""
    _output_names(csv_path, json_path)
    rows = []
    for cell in payload["cells"]:
        common = {"suite": cell["suite"], "model_slug": cell["model_slug"], "n_streamed": cell["n_streamed"],
                  "n_scored": cell["n_raw_scored"], "n_original_excluded": cell["n_original_excluded"], "n_newly_excluded": 0}
        raw_changes = dict.fromkeys(CHANGE_FIELDS, 0)
        raw_changes["wer_tied_with_raw"] = cell["n_raw_scored"]
        control = next(result for result in cell["thresholds"] if result["max_repetitions"] == DEFAULT_THRESHOLD)
        for field in ("hypothesis_text", "normalised_hypothesis", "metric_fields"):
            raw_changes[f"{field}_changed_from_default"] = control["changes"][f"{field}_changed_from_raw"]
        rows.append({**common, "condition": "raw", "max_repetitions": None, **cell["raw"], **raw_changes,
                     "macro_gain_from_raw": 0 if cell["raw"]["macro_wer"] else None,
                     "micro_gain_from_raw": 0 if cell["raw"]["micro_wer"] else None})
        for result in cell["thresholds"]:
            rows.append({**common, "condition": "repetition_fix", "max_repetitions": result["max_repetitions"],
                         **result["summary"], **result["changes"], "macro_gain_from_raw": result["macro_gain_from_raw"],
                         "micro_gain_from_raw": result["micro_gain_from_raw"]})
    fields = list(dict.fromkeys(key for row in rows for key in row))
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--aggregate", type=Path, default=Path("output/evaluation/sweep_aggregate.json"))
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args(argv)
    _validate_output_paths(args.inputs, args.aggregate, args.input_manifest, args.output_csv, args.output_json)
    _output_names(args.output_csv, args.output_json)
    payload = analyse(args.inputs, args.aggregate, args.input_manifest)
    payload["provenance"]["command"] = ["python", "-m", "evaluation.repetition_sensitivity", *(argv if argv is not None else sys.argv[1:])]
    payload["run_metadata"] = run_metadata(ignore=(args.output_csv, args.output_json))
    write_outputs(payload, args.output_csv, args.output_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
