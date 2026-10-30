"""Exploratory apostrophe-scoring sensitivity from archived hypothesis dumps.

The production scorer and condition transformations are left unchanged. This
analysis reads the strings each condition retained after transformation,
reconstructs the original raw and whisper_norm scores at full precision, then
replaces apostrophes not flanked by Unicode word characters with spaces on
both sides. It removes quotation marks, edge elisions and terminal possessive
marks as well. That rule is a sensitivity analysis, not a validated gold scorer.

Hypothesis dumps contain originally scored pairs only. Historical exclusions
come from the source summaries; newly empty references are excluded separately.
The analysis cannot infer uncertainty about reference correctness, other
corpora or model decoding. It loads no model and requires only jiwer and the
standard library. Outputs are separate exploratory artefacts.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import re
import sys
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path

from evaluation.wer import PairResult, aggregate, compute_metrics, normalise_text
from provenance import run_metadata, sha256_text_file

EDGE_APOSTROPHE_RE = re.compile(r"(?<!\w)'|'(?!\w)")
CONDITIONS = ("raw", "whisper_norm")
RULES = ("original", "edge_apostrophe")


def strip_edge_apostrophes(text: str) -> str:
    """Apply the exploratory rule to an already normalised string.

    Internal apostrophes in don't, o'clock, l'homme and 1990's remain.
    Edge marks in 'tis and hours', and stand-alone quote tokens, disappear.
    The Unicode word-character rule also retains adjacent digits/underscores.
    """
    if not isinstance(text, str):
        raise TypeError("normalised text must be a string")
    return " ".join(EDGE_APOSTROPHE_RE.sub(" ", text).split())


def normalise_for_rule(text: str, rule: str) -> str:
    """Normalise a stored condition-transformed string under one scoring rule."""
    if rule not in RULES:
        raise ValueError(f"unknown scoring rule: {rule!r}")
    if not isinstance(text, str):
        raise TypeError("stored text must be a string")
    normalised = normalise_text(text, strip_header=False)
    return strip_edge_apostrophes(normalised) if rule == "edge_apostrophe" else normalised


def score_pairs(pairs, rule: str) -> tuple[dict[str, PairResult], list[str]]:
    """Score (uid, transformed reference, transformed hypothesis) triples.

    Returns the UID-indexed results and IDs excluded for an empty reference.
    Raises on repeated/empty IDs, malformed strings or an unknown rule.
    """
    if rule not in RULES:
        raise ValueError(f"unknown scoring rule: {rule!r}")
    scores, excluded, seen = {}, [], set()
    for uid, reference, hypothesis in pairs:
        if not isinstance(uid, str) or not uid.strip():
            raise ValueError("utterance ID must be a nonempty string")
        if uid in seen:
            raise ValueError(f"repeated utterance ID: {uid}")
        seen.add(uid)
        ref = normalise_for_rule(reference, rule)
        hyp = normalise_for_rule(hypothesis, rule)
        if not ref:
            excluded.append(uid)
            continue
        scores[uid] = PairResult(name=uid, **compute_metrics(ref, hyp))
    return scores, excluded


def _relative_gain(baseline, condition):
    """Return the relative reduction from *baseline* to *condition*.

    ``None`` when *baseline* is zero, where the ratio is undefined.
    """
    return (baseline - condition) / baseline if baseline else None


def gains_on_common(baseline: dict, condition: dict, names=None) -> dict:
    """Compare macro and pooled WER on exactly the same utterance IDs.

    Each side retains its own reference-word denominator after condition
    normalisation. An optional *names* fixes the sample across scoring rules.
    Undefined relative gains have value None. No sampling CI is estimated.
    """
    common = set(baseline) & set(condition)
    if names is not None:
        requested = set(names)
        if not requested <= common:
            raise ValueError("fixed sample contains an unscored utterance")
        common = requested
    if not common:
        raise ValueError("no common scored utterances")
    ordered = sorted(common)
    first = aggregate(baseline[name] for name in ordered)
    second = aggregate(condition[name] for name in ordered)
    return {
        "n_shared": len(common),
        "n_baseline_only": len(set(baseline) - set(condition)),
        "n_condition_only": len(set(condition) - set(baseline)),
        "macro_baseline_shared": first["macro_wer"],
        "macro_condition_shared": second["macro_wer"],
        "macro_gain_shared": _relative_gain(first["macro_wer"], second["macro_wer"]),
        "micro_baseline_shared": first["micro_wer"],
        "micro_condition_shared": second["micro_wer"],
        "micro_gain_shared": _relative_gain(first["micro_wer"], second["micro_wer"]),
        "reference_words_baseline_shared": first["total_reference_words"],
        "reference_words_condition_shared": second["total_reference_words"],
    }


def _sha256(path: Path) -> str:
    """Return the hex SHA-256 of the exact bytes of *path*, read in chunks.

    Used for the recovered ARC inputs, whose digests the aggregate and the
    input manifest record over the raw bytes. Kept here, not taken from
    provenance.sha256_file, which computes the same digest, because
    evaluation.repetition_sensitivity imports it from this module.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path):
    """Return the parsed JSON document at *path*, read as UTF-8."""
    return json.loads(path.read_text(encoding="utf-8"))


def _committed_text_record(path: Path, label: str) -> dict:
    """Identify committed text independently of checkout line endings."""
    return {"file": label, "sha256_lf": sha256_text_file(path)}


def _validate_output_paths(inputs: Path, aggregate_path: Path, input_manifest: Path,
                           csv_path: Path, json_path: Path):
    """Keep the two output files separate from each other and their sources."""
    outputs = (csv_path.resolve(), json_path.resolve())
    if outputs[0] == outputs[1]:
        raise ValueError("CSV and JSON outputs must be different files")
    protected = {aggregate_path.resolve(), input_manifest.resolve()}
    if any(path in protected or path.is_relative_to(inputs.resolve()) for path in outputs):
        raise ValueError(
            "outputs must not overwrite the aggregate, input manifest or input snapshot")


def _validate_original(scores, source, cell, name):
    """Check a rescoring under the original rule against its source records.

    *scores* maps each UID to its :class:`PairResult`; *source* is the
    condition's recovered summary and *cell* its row of the committed
    aggregate. The scored UIDs and every per-utterance field must equal the
    summary's ``per_file`` rows, and the aggregate of *scores* must equal
    the summary's ``summary`` block and the committed row, all at full
    precision. Returns that aggregate; raises ``ValueError`` naming *name*
    at the first difference.
    """
    recorded = {row["name"]: row for row in source["per_file"]}
    if len(recorded) != len(source["per_file"]) or set(scores) != set(recorded):
        raise ValueError(f"{name}: original scored UID set differs")
    for uid, result in scores.items():
        if asdict(result) != recorded[uid]:
            raise ValueError(f"{name}/{uid}: original per-utterance metrics differ")
    summary = aggregate(scores.values())
    if summary != source["summary"]:
        raise ValueError(f"{name}: original full-precision summary differs")
    for key, value in summary.items():
        target = "n_utterances" if key == "files" else key
        if cell.get(target) != value:
            raise ValueError(f"{name}: committed aggregate differs in {target}")
    return summary


def _analyse_cell(pairs, sources, cells, name):
    """Score one suite/model cell under both rules and compare them.

    *pairs*, *sources* and *cells* are keyed by condition (raw and
    whisper_norm): the dump's (UID, transformed reference, transformed
    hypothesis) triples, the recovered summaries and the committed
    aggregate rows. The original rule must reproduce the committed scores
    (:func:`_validate_original`) before the edge-apostrophe rule is
    applied. Returns the cell's per-condition detail, the whisper_norm
    gains over raw under each rule, both on each rule's own shared sample
    and on the sample both rules score, and the UIDs that the rule moves
    in or out of the shared sample. Raises ``ValueError`` when an
    originally scored reference is empty, when no reference survives the
    new rule or when the source's ``n_streamed`` is not a count at least as
    large as the scored set.
    """
    scores, detail = {}, {}
    for condition in CONDITIONS:
        original, excluded = score_pairs(pairs[condition], "original")
        if excluded:
            raise ValueError(f"{name}/{condition}: originally scored reference is empty")
        original_summary = _validate_original(original, sources[condition], cells[condition],
                                               f"{name}/{condition}")
        revised, empty = score_pairs(pairs[condition], "edge_apostrophe")
        if not revised:
            raise ValueError(f"{name}/{condition}: no references remain under sensitivity rule")
        counts = {"reference_strings_changed": 0, "hypothesis_strings_changed": 0,
                  "error_counts_lower": 0, "error_counts_higher": 0,
                  "error_counts_equal": 0}
        for uid, reference, hypothesis in pairs[condition]:
            counts["reference_strings_changed"] += int(
                normalise_for_rule(reference, "original")
                != normalise_for_rule(reference, "edge_apostrophe"))
            counts["hypothesis_strings_changed"] += int(
                normalise_for_rule(hypothesis, "original")
                != normalise_for_rule(hypothesis, "edge_apostrophe"))
            if uid in revised:
                old = original[uid]
                new = revised[uid]
                old_errors = old.substitutions + old.deletions + old.insertions
                new_errors = new.substitutions + new.deletions + new.insertions
                field = ("error_counts_lower" if new_errors < old_errors else
                         "error_counts_higher" if new_errors > old_errors else "error_counts_equal")
                counts[field] += 1
        scores[condition] = {"original": original, "edge_apostrophe": revised}
        benchmark = sources[condition]["benchmark"]
        streamed = benchmark["n_streamed"]
        if not isinstance(streamed, int) or isinstance(streamed, bool) or streamed < len(original):
            raise ValueError(f"{name}: invalid source n_streamed")
        detail[condition] = {
            "n_streamed": streamed, "n_original_scored": len(original),
            "n_original_excluded": streamed - len(original),
            "original_skip_counts": {key: value for key, value in benchmark.items()
                                     if key.startswith("n_skipped_")},
            "original": original_summary, "edge_apostrophe": aggregate(revised.values()),
            "n_newly_excluded": len(empty), "newly_excluded_uids": empty,
            "n_newly_included": 0, "changes": counts,
            "original_per_utterance_and_aggregate_verified": True,
        }
    shared = {rule: set(scores["raw"][rule]) & set(scores["whisper_norm"][rule])
              for rule in RULES}
    fixed = shared["original"] & shared["edge_apostrophe"]
    paired = {rule: gains_on_common(scores["raw"][rule], scores["whisper_norm"][rule])
              for rule in RULES}
    fixed_paired = {rule: gains_on_common(scores["raw"][rule], scores["whisper_norm"][rule], fixed)
                    for rule in RULES}
    return {
        "conditions": detail, "paired_gains": paired,
        "cross_rule_sample": {"n_common": len(fixed),
                              "newly_excluded_shared_uids": sorted(
                                  shared["original"] - shared["edge_apostrophe"]),
                              "newly_included_shared_uids": sorted(
                                  shared["edge_apostrophe"] - shared["original"])},
        "paired_gains_on_fixed_cross_rule_sample": fixed_paired,
    }


def analyse(inputs: Path, aggregate_path: Path, input_manifest: Path) -> dict:
    """Verify the snapshot and analyse raw/whisper_norm in every suite/model cell.

    Summary hashes must match the aggregate, and all selected files must match
    the checksum manifest. Missing/duplicate rows, changed source counts or
    original-score discrepancies stop the analysis before any output is written.
    """
    committed = _read_json(aggregate_path)
    grid = {}
    for row in committed["rows"]:
        key = row["suite"], row["model_slug"], row["condition"]
        if key in grid:
            raise ValueError(f"duplicate committed aggregate cell: {key}")
        grid[key] = row
    recorded_hashes = {entry["source_file"]: entry["sha256"]
                       for entry in committed["provenance"]["inputs"]}
    manifest = _read_json(input_manifest)
    expected = {entry["name"]: entry["sha256"] for entry in manifest["files"]}
    if len(expected) != len(manifest["files"]):
        raise ValueError("duplicate input manifest filenames")
    input_records, results = [], []
    for suite, model in sorted({key[:2] for key in grid}):
        sources, cells = {}, {}
        dump_name = f"wer_hypotheses_{suite}_{model}.csv"
        dump_path = inputs / dump_name
        for condition in CONDITIONS:
            cells[condition] = grid[suite, model, condition]
            name = cells[condition]["source_file"]
            path = inputs / name
            if not path.resolve().is_relative_to(inputs.resolve()):
                raise ValueError("summary source_file lies outside the input snapshot")
            digest = _sha256(path)
            if digest != recorded_hashes.get(name) or digest != expected.get(name):
                raise ValueError(f"summary input checksum differs: {name}")
            input_records.append({"name": name, "sha256": digest})
            sources[condition] = _read_json(path)
        dump_digest = _sha256(dump_path)
        if dump_digest != expected.get(dump_name):
            raise ValueError(f"hypothesis dump checksum differs: {dump_name}")
        input_records.append({"name": dump_name, "sha256": dump_digest})
        pairs = {condition: [] for condition in CONDITIONS}
        recorded_wers = {condition: {row["name"]: row["wer"] for row in source["per_file"]}
                         for condition, source in sources.items()}
        required = {"uid", "condition", "reference_transformed", "hypothesis_transformed", "wer"}
        with dump_path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if not required <= set(reader.fieldnames or []):
                raise ValueError(f"{dump_name}: missing hypothesis dump columns")
            if len(reader.fieldnames) != len(set(reader.fieldnames)):
                raise ValueError(f"{dump_name}: repeated hypothesis dump columns")
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError(f"{dump_name}: incomplete or extra CSV row columns")
                condition = row["condition"]
                if condition not in pairs:
                    continue
                try:
                    stored_wer = float(row["wer"])
                except (ValueError, TypeError) as exc:
                    raise ValueError(f"{dump_name}: invalid stored WER") from exc
                if not math.isfinite(stored_wer) or stored_wer < 0:
                    raise ValueError(f"{dump_name}: invalid stored WER")
                recorded = recorded_wers[condition].get(row["uid"])
                if recorded is None or stored_wer != float(f"{recorded:.6f}"):
                    raise ValueError(f"{dump_name}/{row['uid']}: stored WER differs "
                                     "from the original six-decimal score")
                pairs[condition].append((row["uid"], row["reference_transformed"],
                                         row["hypothesis_transformed"]))
        result = _analyse_cell(pairs, sources, cells, f"{suite}/{model}")
        results.append({"suite": suite, "model_slug": model, **result})
        print(f"verified and analysed {suite}/{model}", flush=True)
    return {
        "schema_version": 1,
        "analysis": ("Exploratory sensitivity to edge apostrophes; "
                     "original scorer retained in canonical results."),
        "transform": {"after": "evaluation.wer.normalise_text(..., strip_header=False)",
                      "pattern": EDGE_APOSTROPHE_RE.pattern, "replacement": " ",
                      "whitespace": "collapse and strip", "sides": ["reference", "hypothesis"],
                      "word_characters": "Python Unicode \\w (letters, digits and underscore)",
                      "limits": ("Also removes edge elisions and terminal possessive marks. "
                                 "This is not an established gold scorer.")},
        "provenance": {
            "digest_policy": {
                "committed_text_and_input_manifest": "SHA-256 with CRLF normalised to LF",
                "recovered_arc_inputs": "SHA-256 of exact raw bytes"},
            "aggregate": _committed_text_record(aggregate_path, aggregate_path.as_posix()),
            "input_manifest": _committed_text_record(input_manifest, input_manifest.as_posix()),
            "input_files": input_records,
            "producer": _committed_text_record(Path(__file__), "evaluation/scorer_sensitivity.py"),
            "original_scorer": _committed_text_record(Path(__file__).with_name("wer.py"),
                                                      "evaluation/wer.py"),
            "python": platform.python_version(), "jiwer": version("jiwer"),
            "rapidfuzz": version("rapidfuzz"),
            "original_scoring_verified": True, "suite_model_cells": len(results),
            "condition_cells": len(results) * len(CONDITIONS),
            "original_verification": {
                "per_utterance_fields": "exact",
                "summary_and_aggregate": "exact at full precision",
                "stored_dump_wer": "matches the original score rounded to six decimals"},
        },
        "limits": [
            "Hypothesis dumps retain originally scored pairs only; "
            "historical exclusions are read from the source summaries.",
            "Removing apostrophes cannot restore an originally empty reference; "
            "newly empty references are counted separately.",
            "Condition transformations and model decoding are not rerun. "
            "Historical fraction handling (NEW-03) remains unchanged.",
            "No sampling confidence interval, reference-correctness uncertainty "
            "or effect in other benchmark waves is estimated.",
            "The source inputs are not yet in the public repository; "
            "reproducing this artefact requires the recovered input bundle.",
        ],
        "cells": results,
    }


def write_outputs(payload: dict, csv_path: Path, json_path: Path):
    """Write separate exploratory outputs only after complete verification."""
    if csv_path.resolve() == json_path.resolve():
        raise ValueError("CSV and JSON outputs must be different files")
    rows = []
    for cell in payload["cells"]:
        for condition in CONDITIONS:
            detail = cell["conditions"][condition]
            for rule in RULES:
                summary = detail[rule]
                row = {"suite": cell["suite"], "model_slug": cell["model_slug"],
                       "condition": condition, "scoring_rule": rule,
                       "n_streamed": detail["n_streamed"],
                       "n_original_scored": detail["n_original_scored"],
                       "n_scored": summary["files"],
                       "n_excluded": detail["n_streamed"] - summary["files"],
                       "n_original_excluded": detail["n_original_excluded"],
                       "n_newly_excluded": detail["n_newly_excluded"] if rule != "original" else 0,
                       "n_newly_included": 0,
                       **{key: value for key, value in summary.items() if key != "files"}}
                if condition == "whisper_norm":
                    row.update(cell["paired_gains"][rule])
                rows.append(row)
    fields = list(dict.fromkeys(key for row in rows for key in row))
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False)
                         + "\n", encoding="utf-8")


def main(argv=None):
    """Run :func:`analyse` on the recovered inputs and write the two outputs.

    *argv* replaces ``sys.argv[1:]``. Returns 0. Raises ``ValueError``
    before anything is written when the two outputs are one file or would
    overwrite the aggregate, the input manifest or a file in the input
    snapshot, or when an input fails verification. Side effects: reads the
    input snapshot, the aggregate and the input manifest; runs ``git``
    through :func:`provenance.run_metadata`; writes the CSV and the JSON,
    replacing them; prints a line per cell.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--inputs", type=Path, required=True,
                        help="Recovered sweep input directory")
    parser.add_argument("--aggregate", type=Path,
                        default=Path("output/evaluation/sweep_aggregate.json"))
    parser.add_argument("--input-manifest", type=Path, required=True,
                        help="Checksum receipt with original file hashes")
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args(argv)
    _validate_output_paths(args.inputs, args.aggregate, args.input_manifest,
                           args.output_csv, args.output_json)
    payload = analyse(args.inputs, args.aggregate, args.input_manifest)
    payload["provenance"]["command"] = ["python", "-m", "evaluation.scorer_sensitivity", *(
        argv if argv is not None else sys.argv[1:])]
    payload["run_metadata"] = run_metadata(ignore=(args.output_csv, args.output_json))
    write_outputs(payload, args.output_csv, args.output_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
