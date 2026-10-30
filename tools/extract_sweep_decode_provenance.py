"""Extract recorded decode/environment metadata without redistributing corpus text.

This deterministic receipt uses the frozen summary digests, verifies that all
17 conditions in each suite/model cell share a recorded decode/environment,
and retains the actual recorded fields. It neither loads models nor fills
unrecorded settings from today's defaults.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path


def _digest(path: Path, *, text: bool = False) -> str:
    """Return the hex SHA-256 of *path*.

    With *text*, every CRLF is read as LF first, so that a committed text
    file has one digest on every checkout; otherwise the exact bytes are
    hashed, as the input receipt records the recovered files. The tool runs
    as a script, without the repository root on ``sys.path``, so it keeps
    this copy of provenance.sha256_file and sha256_text_file.
    """
    digest = hashlib.sha256()
    if text:
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    else:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def extract(inputs: Path, aggregate_path: Path, receipt_path: Path) -> dict:
    """Verify the recovered summaries and return their recorded decode profiles.

    Each aggregate row's summary in *inputs* must be a local file the
    receipt lists, match its size and SHA-256 there and in the aggregate,
    name the row's condition and model, and come from the receipt's decoder
    commit on a clean tree. The grid must be complete (five suites, three
    models, seventeen conditions), and every condition of a suite/model must
    record the same dataset, revisions, decode settings and run metadata.
    Returns the receipt: one profile per suite/model with the digests of its
    source summaries, and the LF digests of the aggregate, the receipt and
    this file. Raises ``ValueError`` at the first failed check, and
    ``KeyError`` or ``FileNotFoundError`` for a missing field or file.
    """
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    fingerprints = {row["name"]: row for row in receipt["files"]}
    if len(fingerprints) != len(receipt["files"]):
        raise ValueError("input receipt contains duplicate names")
    original_inputs = aggregate["provenance"]["inputs"]
    original_digests = {row["source_file"]: row["sha256"] for row in original_inputs}
    if len(original_digests) != len(original_inputs):
        raise ValueError("aggregate contains duplicate source names")
    expected_conditions = set(receipt["grid"]["conditions"])
    grouped = defaultdict(list)
    seen = set()
    fields = ("dataset", "config", "split", "model", "seed", "language",
              "n_streamed", "revisions", "decode")
    for cell in aggregate["rows"]:
        key = (cell["suite"], cell["model"], cell["condition"])
        if key in seen:
            raise ValueError(f"duplicate aggregate cell: {key}")
        seen.add(key)
        name = cell["source_file"]
        if Path(name).name != name or "/" in name or "\\" in name or name not in fingerprints:
            raise ValueError(f"unreceipted or nonlocal summary: {name}")
        path = inputs / name
        entry = fingerprints[name]
        if path.stat().st_size != entry["bytes"] or _digest(path) != entry["sha256"]:
            raise ValueError(f"summary bytes differ from input receipt: {name}")
        original_digest = original_digests.get(name)
        if original_digest != entry["sha256"]:
            raise ValueError(f"aggregate and receipt digests disagree: {name}")
        summary = json.loads(path.read_text(encoding="utf-8"))
        benchmark = summary["benchmark"]
        environment = summary["run_metadata"]
        if benchmark["condition"] != cell["condition"] or benchmark["model"] != cell["model"]:
            raise ValueError(f"summary identity differs: {name}")
        if (environment["git_commit"] != receipt["decoder_commit"]
                or environment["git_dirty"] is not False):
            raise ValueError(f"unexpected or dirty decoder: {name}")
        recorded = {field: benchmark[field] for field in fields}
        recorded["run_metadata"] = environment
        grouped[key[:2]].append((cell["condition"], name, entry["sha256"], recorded))

    expected_groups = {(suite, model) for suite in receipt["grid"]["suites"]
                       for model in {row["model"] for row in aggregate["rows"]}}
    if (len(expected_conditions) != 17 or len(expected_groups) != 15
            or set(grouped) != expected_groups
            or {row["model_slug"] for row in aggregate["rows"]} != set(receipt["grid"]["models"])):
        raise ValueError("expected complete five-suite, three-model, seventeen-condition grid")
    records = []
    for (suite, model), cells in sorted(grouped.items()):
        if len(cells) != 17 or {cell[0] for cell in cells} != expected_conditions:
            raise ValueError(f"incomplete condition grid: {suite}/{model}")
        metadata = cells[0][3]
        if any(cell[3] != metadata for cell in cells):
            raise ValueError("recorded decode/environment changes across conditions: "
                             f"{suite}/{model}")
        records.append({
            "suite": suite, "model": model,
            "recorded_decode_and_environment": metadata,
            "source_summaries": [{"condition": condition, "file": name, "sha256": digest}
                                 for condition, name, digest, _ in sorted(cells)],
        })
    return {
        "schema_version": 1,
        "decoder_commit": receipt["decoder_commit"],
        "digest_policy": ("Exact recovered summary bytes; "
                          "LF-normalised committed aggregate and input receipt."),
        "aggregate_sha256_lf": _digest(aggregate_path, text=True),
        "input_receipt_sha256_lf": _digest(receipt_path, text=True),
        "extractor_sha256_lf": _digest(Path(__file__), text=True),
        "cells_verified": len(seen), "decode_profiles": len(records),
        "scope": ("Recorded metadata extracted from all 255 hash-verified summaries. "
                  "Each suite/model profile is identical across its 17 conditions. "
                  "Corpus text and deployment locators are omitted."),
        "limits": ("This is a verified extraction of recorded metadata, not a new decode "
                   "or a direct inspection of the historical runtime. "
                   "Settings absent from the source summaries are not inferred."),
        "profiles": records,
    }


def main() -> None:
    """Write the receipt that :func:`extract` returns to ``--output``.

    Exits with argparse's status 2 and the reason when ``--output`` is
    inside the inputs or is the aggregate or the receipt, or when
    :func:`extract` fails a check or meets a missing file, field or
    unreadable JSON. Side effects: creates the output's directory, replaces
    the output and prints the counts verified.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--aggregate", type=Path,
                        default=Path("output/evaluation/sweep_aggregate.json"))
    parser.add_argument("--input-manifest", type=Path,
                        default=Path("output/evaluation/sweep_input_manifest.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.is_relative_to(args.inputs.resolve()) or output in {
        args.aggregate.resolve(), args.input_manifest.resolve()
    }:
        parser.error("output must be separate from inputs, aggregate and receipt")
    try:
        result = extract(args.inputs, args.aggregate, args.input_manifest)
    except (KeyError, ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Verified {result['cells_verified']} cells in "
          f"{result['decode_profiles']} recorded profiles")


if __name__ == "__main__":
    main()
