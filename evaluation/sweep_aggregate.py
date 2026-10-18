#!/usr/bin/env python3
"""
Aggregate all per-suite, per-condition WER summaries from a completed sweep
into a single cross-tabulation CSV and JSON for the manuscript.

The script scans *sweep-dir* for ``wer_summary*.json`` files produced by
:mod:`evaluation.sweep` or :mod:`evaluation.benchmark_wer`.  Each file
contributes one row to the aggregate table.  The row contains the suite
name, the condition, the model slug, the utterance count, the four macro
metrics (macro WER, MER, WIL, CER), the total reference-word count, the
source summary (relative to *sweep-dir*) and the pipeline version, in the
column order of the committed aggregate; then the pooled (micro) WER and
MER with the alignment counts behind them, and whether the condition is
invisible to normalised WER.

Macro WER is the unweighted mean of per-utterance rates, and on a corpus of
short utterances such as AMI a few hallucinated hypotheses against one- or
two-word references dominate it.  The pooled columns, errors over reference
words, are what shows that; every summary already held them and the
aggregate used to drop them (audit finding EWER-08).  They are additive:
no macro column changes.

``pipeline_version`` is, in order of preference, the summary's own
``benchmark.pipeline_version``; the short commit of the code that wrote the
summary (``run_metadata.git_commit``, with ``+dirty`` when the tree had
uncommitted changes); or the ``--pipeline-version`` label for summaries that
record neither, such as the post-fix grid's, which predate run metadata.

Suite names are inferred from the JSON ``benchmark`` block using the
``dataset`` + ``config`` pair if present; where the file also carries a
``condition`` key that information is used directly.  Files that cannot be
parsed as valid sweep summaries are skipped with a warning, as are
summaries of a corpus that is not one of the sweep's suites (the
multilingual FLEURS runs, which share the output directory).

Output files::

    {out}/sweep_aggregate.csv    tidy CSV, one row per (suite, condition, model)
    {out}/sweep_aggregate.json   {"provenance": {...}, "rows": [...]}: the
                                 same rows with typed values, plus the input
                                 files' digests and the run metadata

The committed aggregate is this module's output over the 255 summaries of
the sweep in ``hpc/runs/sweep.env``.  The post-fix grid it replaced
(53378ba, aa6e61d) was built outside the module, as a bare JSON list of
string-valued rows with absolute ``C:\\tmp`` source paths (audit findings
EWER-02, REGEN-05, OUTPUTS-04, DEPS-07); rebuilt here from its 240
summaries with ``--pipeline-version "post-fix (af3bee0)"`` it reproduces
every macro value.  The JSON's ``generated`` time stamp and run metadata
differ between runs, so compare ``rows``, not bytes.

Usage::

    python -m evaluation.sweep_aggregate
    python -m evaluation.sweep_aggregate --sweep-dir output/evaluation
    python -m evaluation.sweep_aggregate \\
        --sweep-dir output/evaluation \\
        --out       output/evaluation/sweep_aggregate.csv
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, UTC
from pathlib import Path

from evaluation.sweep import model_slug as _model_slug

_DEFAULT_SWEEP_DIR = Path("output/evaluation")
_DEFAULT_OUT_CSV   = Path("output/evaluation/sweep_aggregate.csv")
_DEFAULT_OUT_JSON  = Path("output/evaluation/sweep_aggregate.json")

def _corpus_to_suite() -> dict[tuple[str, str], str]:
    """Map (dataset, config) to suite name, read from the suite registries.

    Built from :func:`evaluation.sweep._all_suite_specs` (the synthetic
    ``librispeech_clean`` entry plus every registered challenge suite), so
    a newly registered suite is labelled without a second list to update.
    """
    from evaluation.sweep import _all_suite_specs  # noqa: PLC0415
    return {(s.dataset, s.config): s.name for s in _all_suite_specs()}


_CORPUS_TO_SUITE: dict[tuple[str, str], str] = _corpus_to_suite()

# Pilot subdirectory prefix: summaries under output/evaluation/pilot/ are
# labelled as pilot runs and excluded from the main aggregate by default.
_PILOT_MARKER = "pilot"
# Appended to a pilot row's suite under --include-pilot. The pilot job
# (hpc/submit_pilot_benchmark.sh) scores 200 utterances of cells the full
# sweep also scores, so under the same (suite, model, condition) label a
# reader keyed on the cell would pick one of the two arbitrarily, and the
# duplicate-cell check would refuse the pair.
_PILOT_SUFFIX = "@pilot"

# The first twelve columns are those of the committed aggregate, in its
# order, so that a rebuild of it can be compared column for column; the
# pooled metrics and the invisibility flag follow.
_CSV_FIELDS = [
    "suite",
    "condition",
    "model",
    "model_slug",
    "n_utterances",
    "macro_wer",
    "macro_mer",
    "macro_wil",
    "macro_cer",
    "total_reference_words",
    "source_file",
    "pipeline_version",
    "micro_wer",
    "micro_mer",
    "total_hits",
    "total_substitutions",
    "total_deletions",
    "total_insertions",
    "total_hypothesis_words",
    "wer_invisible",
]

#: Pooled-metric keys copied from each summary's ``summary`` block.
_POOLED_FIELDS = ("micro_wer", "micro_mer", "total_hits",
                  "total_substitutions", "total_deletions",
                  "total_insertions", "total_hypothesis_words")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SweepRow:
    """One row in the aggregate table (see the module docstring)."""

    suite:                 str
    condition:             str
    model:                 str
    model_slug:            str
    n_utterances:          int
    macro_wer:             float
    macro_mer:             float
    macro_wil:             float
    macro_cer:             float
    total_reference_words: int
    source_file:           str
    # Which pipeline revision produced the cell (see _pipeline_version).
    pipeline_version:      str = ""
    # Pooled metrics and alignment counts (audit finding EWER-08); None
    # when a summary does not record them.
    micro_wer:              float | None = None
    micro_mer:              float | None = None
    total_hits:             int | None = None
    total_substitutions:    int | None = None
    total_deletions:        int | None = None
    total_insertions:       int | None = None
    total_hypothesis_words: int | None = None
    # True when the condition scores exactly as raw by construction
    # (evaluation.conditions.Condition.wer_invisible, audit finding
    # EWER-03); None for a condition the registry does not know.
    wer_invisible:          bool | None = None


# ---------------------------------------------------------------------------
# Suite-name inference
# ---------------------------------------------------------------------------

def _infer_suite(benchmark: dict, source_path: Path) -> str | None:
    """Return the canonical suite name for a parsed benchmark block.

    Tries the (dataset, config) lookup table first. Only a block that
    records no dataset falls back to probing the file-name stem for a
    recognised suite slug. Returns ``None`` when the suite cannot be
    determined, including for a recorded corpus that is not one of the
    sweep's suites.
    """
    dataset = benchmark.get("dataset", "")
    config  = benchmark.get("config",  "")
    key = (dataset, config)
    if key in _CORPUS_TO_SUITE:
        return _CORPUS_TO_SUITE[key]
    if dataset:
        # A summary that names its corpus, and names one the sweep does not
        # score, is not a sweep cell. The multilingual FLEURS runs record
        # google/fleurs with fr_fr, de_de and so on, and write into the same
        # directory; the stem probe below would file each of them under the
        # English 'fleurs' suite, where they collide with the English cell
        # and with one another.
        return None

    # Try to infer from the file stem (e.g. wer_summary_fleurs_whisper-large-v3.json)
    stem = source_path.stem  # wer_summary_fleurs_whisper-large-v3
    known_suites = set(_CORPUS_TO_SUITE.values())
    for suite_name in sorted(known_suites, key=len, reverse=True):
        if suite_name in stem:
            return suite_name
    return None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _parse_summary_file(
    path: Path,
    sweep_dir: Path | None = None,
    pipeline_version: str = "",
) -> SweepRow | None:
    """Parse *path* and return a :class:`SweepRow`, or ``None`` on failure.

    Every ``None`` is announced on stderr with its reason, as the module
    docstring promises. ``source_file`` is stored relative to *sweep_dir*
    when *path* lies under it, so the aggregate does not depend on where
    the sweep directory happened to be mounted.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"  warning: could not read {path.name}: {exc}", file=sys.stderr)
        return None

    if not isinstance(payload, dict):
        print(f"  warning: {path.name} is not a JSON object; skipping.",
              file=sys.stderr)
        return None

    benchmark = payload.get("benchmark", {})
    summary   = payload.get("summary",   {})

    if not benchmark or not summary:
        print(f"  warning: {path.name} lacks a benchmark or summary block; "
              "skipping.", file=sys.stderr)
        return None

    # Required benchmark fields.
    model_id = benchmark.get("model")
    if not model_id:
        print(f"  warning: {path.name} records no model; skipping.",
              file=sys.stderr)
        return None

    suite = _infer_suite(benchmark, path)
    if suite is None:
        if benchmark.get("dataset"):
            print(
                f"  warning: {path.name} scores {benchmark.get('dataset')}/"
                f"{benchmark.get('config', '')}, which is not one of the "
                "sweep's suites; skipping.",
                file=sys.stderr,
            )
        else:
            print(
                f"  warning: cannot determine suite for {path.name}; skipping.",
                file=sys.stderr,
            )
        return None

    condition     = benchmark.get("condition", "raw")
    n_utterances  = benchmark.get("utterances", summary.get("files", 0))

    macro_wer = summary.get("macro_wer")
    macro_mer = summary.get("macro_mer")
    macro_wil = summary.get("macro_wil")
    macro_cer = summary.get("macro_cer")
    ref_words = summary.get("total_reference_words", 0)

    if any(v is None for v in (macro_wer, macro_mer, macro_wil, macro_cer)):
        print(
            f"  warning: missing metric fields in {path.name}; skipping.",
            file=sys.stderr,
        )
        return None

    pooled = {}
    for key in _POOLED_FIELDS:
        value = summary.get(key)
        cast = float if key.startswith("micro_") else int
        pooled[key] = None if value is None else cast(value)

    return SweepRow(
        suite=suite,
        condition=condition,
        model=model_id,
        model_slug=_model_slug(model_id),
        n_utterances=int(n_utterances),
        macro_wer=float(macro_wer),
        macro_mer=float(macro_mer),
        macro_wil=float(macro_wil),
        macro_cer=float(macro_cer),
        total_reference_words=int(ref_words),
        source_file=_source_label(path, sweep_dir),
        pipeline_version=_pipeline_version(payload, benchmark,
                                           pipeline_version),
        wer_invisible=_wer_invisible(benchmark, condition),
        **pooled,
    )


def _pipeline_version(payload: dict, benchmark: dict, fallback: str) -> str:
    """Return the pipeline version of one summary.

    In order: ``benchmark.pipeline_version``; the first seven characters of
    ``run_metadata.git_commit``, with ``+dirty`` appended when
    ``run_metadata.git_dirty`` is true, so a row can always be traced to the
    commit that wrote it; and otherwise *fallback*, the ``--pipeline-version``
    label for summaries that record neither.
    """
    explicit = benchmark.get("pipeline_version")
    if explicit:
        return str(explicit)
    meta = payload.get("run_metadata")
    commit = meta.get("git_commit") if isinstance(meta, dict) else None
    if commit:
        return str(commit)[:7] + ("+dirty" if meta.get("git_dirty") else "")
    return fallback


def _wer_invisible(benchmark: dict, condition: str) -> bool | None:
    """Whether *condition* scores exactly as raw by construction.

    Read from the summary when it records ``benchmark.wer_invisible``, and
    otherwise from the condition registry, so the flag also labels
    summaries written before it existed. ``None`` for an unregistered
    condition.
    """
    recorded = benchmark.get("wer_invisible")
    if isinstance(recorded, bool):
        return recorded
    from evaluation.conditions import get_condition  # noqa: PLC0415
    try:
        return bool(get_condition(condition).wer_invisible)
    except KeyError:
        return None


def _source_label(path: Path, sweep_dir: Path | None) -> str:
    """Return *path* relative to *sweep_dir* (POSIX separators) when possible."""
    if sweep_dir is not None:
        try:
            return path.resolve().relative_to(sweep_dir.resolve()).as_posix()
        except ValueError:
            pass
    return str(path)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def aggregate_sweep(
    sweep_dir:   Path,
    include_pilot: bool = False,
    pipeline_version: str = "",
) -> list[SweepRow]:
    """Collect all :class:`SweepRow` objects from *sweep_dir*.

    Pilot summaries (those whose path below *sweep_dir* contains
    ``'pilot'``: the ``pilot/`` directory, and the
    ``wer_summary_pilot*.json`` names the pilot job writes) are excluded
    unless *include_pilot* is ``True``, in which case their suite is
    labelled ``<suite>@pilot`` so that they never share a cell with the
    full sweep. Results are sorted by (suite, model_slug, condition) for a
    stable canonical order. *pipeline_version* fills the column of the
    same name for summaries that do not record one.

    Raises
    ------
    SystemExit
        If no summary file is found, or if two files describe the same
        (suite, model, condition) cell. A repeated cell would otherwise
        appear twice in the table and whichever row a reader picked would
        be arbitrary.
    """
    pattern = "wer_summary*.json"
    candidates = sorted(sweep_dir.rglob(pattern))
    if not candidates:
        raise SystemExit(
            f"No {pattern!r} files found under {sweep_dir}.  "
            "Run the sweep first with:  python -m evaluation.sweep"
        )

    rows: list[SweepRow] = []
    for path in candidates:
        # Skip pilot subdirectory unless requested.
        # Only the part of the path below sweep_dir is inspected: a sweep
        # directory that itself sits under a folder whose name contains
        # "pilot" would otherwise have every summary excluded.
        pilot = any(_PILOT_MARKER in part
                    for part in path.relative_to(sweep_dir).parts)
        if pilot and not include_pilot:
            continue

        row = _parse_summary_file(path, sweep_dir, pipeline_version)
        if row is not None:
            if pilot:
                row.suite += _PILOT_SUFFIX
            rows.append(row)

    rows.sort(key=lambda r: (r.suite, r.model_slug, r.condition))
    duplicates = _duplicate_cells(rows)
    if duplicates:
        lines = [f"  {cell}: {', '.join(srcs)}"
                 for cell, srcs in sorted(duplicates.items())]
        raise SystemExit(
            "More than one summary for the same (suite, model, condition) "
            "cell:\n" + "\n".join(lines) + _nested_sweep_hint(duplicates)
        )
    return rows


def _nested_sweep_hint(duplicates: dict[tuple, list[str]]) -> str:
    """Name the directories behind *duplicates* when there is more than one.

    Repeats spread over several directories usually mean that whole sweeps
    were stored beneath the one being aggregated (as ``postfix/`` and
    ``preflight_postfix/`` sit under ARC's ``output/evaluation``), which
    this function says, instead of leaving the reader to infer it from a
    long list of cells.
    """
    dirs = sorted({Path(src).parent.as_posix()
                   for srcs in duplicates.values() for src in srcs})
    if len(dirs) < 2:
        return ""
    return ("\nThe repeats come from more than one directory ("
            + ", ".join(dirs) + "), so this directory holds more than one "
            "sweep; point --sweep-dir (SWEEP_DIR in hpc/aggregate_sweep.sh) "
            "at the sweep you mean to aggregate.")


def _duplicate_cells(rows: list[SweepRow]) -> dict[tuple, list[str]]:
    """Return ``{(suite, model_slug, condition): [source, ...]}`` for repeats."""
    seen: dict[tuple, list[str]] = {}
    for r in rows:
        seen.setdefault((r.suite, r.model_slug, r.condition), []).append(
            r.source_file)
    return {k: v for k, v in seen.items() if len(v) > 1}


def missing_cells(rows: list[SweepRow]) -> list[tuple[str, str, str]]:
    """Return the (suite, model_slug, condition) cells absent from *rows*.

    The expected grid is every suite, model and condition that appears
    anywhere in *rows*, crossed. A condition that one array task failed to
    write therefore shows up as missing for that suite and model, instead
    of leaving the table short without comment. Pilot rows (suite ending
    in ``@pilot``, present only under ``--include-pilot``) are left out on
    both sides: a pilot scores part of the grid by design.
    """
    rows = [r for r in rows if not r.suite.endswith(_PILOT_SUFFIX)]
    suites = sorted({r.suite for r in rows})
    models = sorted({r.model_slug for r in rows})
    conditions = sorted({r.condition for r in rows})
    present = {(r.suite, r.model_slug, r.condition) for r in rows}
    return [(s, m, c) for s in suites for m in models for c in conditions
            if (s, m, c) not in present]


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def write_aggregate_csv(rows: list[SweepRow], path: Path) -> None:
    """Write *rows* to *path* as a tidy CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))
    print(f"  aggregate CSV:  {path}")


def _input_digests(rows: list[SweepRow], sweep_dir: Path) -> list[dict]:
    """Return ``[{"source_file", "sha256"}]`` for the summaries behind *rows*.

    A manifest of the inputs, so that a later rebuild can show it read the
    same files (audit finding REGEN-05). A file that cannot be read is
    recorded with a ``None`` digest.
    """
    digests = []
    for r in rows:
        path = Path(r.source_file)
        if not path.is_absolute():
            path = sweep_dir / path
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            digest = None
        digests.append({"source_file": r.source_file, "sha256": digest})
    return digests


def write_aggregate_json(
    rows:      list[SweepRow],
    path:      Path,
    sweep_dir: Path,
    run_meta:  dict | None = None,
) -> None:
    """Write *rows* to *path* as ``{"provenance": ..., "rows": ...}``.

    The rows keep their types (numbers stay numbers). The provenance block
    names the sweep directory, the generation time, the suites, conditions,
    models and pipeline versions present, the SHA-256 of every input
    summary, and *run_meta*, the :func:`provenance.run_metadata` of the
    aggregation run. :func:`main` reads it before writing either output and
    passes it in. Without it, it is read here, leaving *path* out of the
    dirty check, which is right only when nothing else of the run has been
    written yet. Creates the parent directory, overwrites *path* and, when
    *run_meta* is not given, runs ``git``.
    """
    if run_meta is None:
        from provenance import run_metadata  # noqa: PLC0415
        run_meta = run_metadata(ignore=(path,))

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "provenance": {
            "sweep_dir":   str(sweep_dir),
            "generated":   datetime.now(tz=UTC).isoformat(),
            "n_rows":      len(rows),
            "suites":      sorted({r.suite      for r in rows}),
            "conditions":  sorted({r.condition  for r in rows}),
            "models":      sorted({r.model_slug for r in rows}),
            "pipeline_versions": sorted({r.pipeline_version for r in rows}),
            "inputs":      _input_digests(rows, sweep_dir),
            "run_metadata": run_meta,
        },
        "rows": [asdict(r) for r in rows],
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    print(f"  aggregate JSON: {path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="evaluation.sweep_aggregate",
        description=(
            "Aggregate all per-suite WER summary JSONs from a completed sweep "
            "into a single tidy CSV and JSON for the manuscript."
        ),
    )
    p.add_argument(
        "--sweep-dir", type=Path, default=_DEFAULT_SWEEP_DIR, dest="sweep_dir",
        metavar="DIR",
        help=(
            "Directory containing wer_summary*.json files "
            "(default: %(default)s)."
        ),
    )
    p.add_argument(
        "--out", type=Path, default=_DEFAULT_OUT_CSV, dest="out_csv",
        metavar="CSV",
        help="Output CSV path  (default: %(default)s).",
    )
    p.add_argument(
        "--out-json", type=Path, default=_DEFAULT_OUT_JSON, dest="out_json",
        metavar="JSON",
        help="Output JSON path  (default: %(default)s).",
    )
    p.add_argument(
        "--include-pilot", action="store_true", dest="include_pilot",
        help=(
            "Include pilot-run summaries (those under a 'pilot' subdirectory) "
            "in the aggregate, with their suite labelled '<suite>@pilot'.  By "
            "default they are excluded so that the 200-utterance pilot "
            "numbers do not dilute the full-sweep results."
        ),
    )
    p.add_argument(
        "--pipeline-version", default="", dest="pipeline_version",
        metavar="LABEL",
        help=(
            "Value for the pipeline_version column, e.g. 'post-fix (af3bee0)', "
            "used only for summaries that record neither a pipeline_version "
            "nor a run_metadata commit (the post-fix grid's summaries record "
            "neither)."
        ),
    )
    p.add_argument(
        "--allow-incomplete", action="store_true", dest="allow_incomplete",
        help=(
            "Write the aggregate even when the suite x model x condition "
            "grid has missing cells.  By default a missing cell is an error, "
            "since a failed array task otherwise leaves the table short "
            "without comment."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> None:
    """Run the command-line interface.

    Scans ``--sweep-dir``, checks the grid (duplicate cells always fail;
    missing cells fail unless ``--allow-incomplete``), and writes the CSV
    and JSON aggregates, overwriting them. Raises ``SystemExit`` on any
    failure.
    """
    args = _build_parser().parse_args(argv)

    print(f"Scanning {args.sweep_dir} for wer_summary*.json …")
    rows = aggregate_sweep(args.sweep_dir, include_pilot=args.include_pilot,
                           pipeline_version=args.pipeline_version)

    if not rows:
        raise SystemExit(
            "No parseable summary files found.  "
            "Check --sweep-dir and ensure the sweep has completed."
        )

    print(f"  found {len(rows)} rows across "
          f"{len({r.suite for r in rows})} suite(s), "
          f"{len({r.condition for r in rows})} condition(s), "
          f"{len({r.model_slug for r in rows})} model(s).")

    missing = missing_cells(rows)
    if missing:
        for cell in missing:
            print(f"  missing cell: {cell}", file=sys.stderr)
        if not args.allow_incomplete:
            raise SystemExit(
                f"{len(missing)} cell(s) of the grid are missing; rerun the "
                "failed tasks or pass --allow-incomplete."
            )

    # The git state the JSON records is read once, before either output is
    # written, and leaves both out, as provenance.write_sidecar does for the
    # CSV-only writers. It used to be read after the CSV had been written,
    # so a regeneration in place counted the CSV as a change to the tree
    # whenever it differed from the committed one, and the JSON from the
    # second regeneration on, since every run rewrites its time stamp.
    from provenance import run_metadata  # noqa: PLC0415
    run_meta = run_metadata(ignore=(args.out_csv, args.out_json))
    write_aggregate_csv(rows, args.out_csv)
    write_aggregate_json(rows, args.out_json, args.sweep_dir, run_meta=run_meta)

    print("\nDone.")


if __name__ == "__main__":
    main()
