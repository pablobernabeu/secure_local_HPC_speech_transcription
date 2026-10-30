#!/usr/bin/env python3
"""
Paired bootstrap confidence intervals for post-processing condition deltas.

The condition sweep reports one macro-WER per condition, which says
nothing about whether the differences between conditions are larger than
the noise in the estimates. Comparing two independent corpus-level
intervals is the wrong test here: every condition is scored on the *same*
utterances, so the between-utterance variance that dominates an unpaired
comparison is shared and cancels. Pairing by utterance and resampling a
single index vector per replicate exploits that, and in practice
tightens the interval on a difference by roughly an order of magnitude
relative to the interval on either level (Bisani & Ney, 2004; Koehn,
2004).

This module walks a directory of per-utterance ``wer_report*.csv`` files
written by ``evaluation/sweep.py``, pairs every condition against a
chosen baseline, and writes one row per condition to a CSV that the
manuscript reads at render time. The heavy lifting is delegated to
:mod:`evaluation.bootstrap_ci`; this module only supplies the file
discovery and the baseline pairing.

Usage::

    python -m evaluation.condition_ci \\
        --reports output/evaluation/sweep_reports_postfix \\
        --baseline raw --bootstrap 10000 --seed 42 \\
        --output output/evaluation/condition_ci_postfix.csv

``--output`` is required. It used to default to
``output/evaluation/condition_ci.csv``, which holds the pre-repair
intervals the manuscript quotes as history, so a run on the repaired
sweep without the flag silently replaced them (REGEN-01, ESTATS-07).

The report directory is expected to hold ``{prefix}_{condition}.csv``
for each non-primary condition, plus ``{prefix}.csv`` for whichever
condition ran first (the sweep writes the first condition to the
unsuffixed primary path). ``--prefix`` defaults to ``wer_report``, the
layout of the committed ``sweep_reports/`` and ``sweep_reports_postfix/``
directories. A sweep now names every cell
(``wer_report_librispeech_whisper-large-v3``, audit finding EWER-11), so
one cell of a sweep directory is selected by passing that stem. The
committed ``sweep_reports_postfix_ami/`` keeps the sweep's names, so it
needs ``--prefix wer_report_ami_whisper-large-v3``, as the default finds
no baseline there. The primary file's condition is read from the matching
``wer_summary*.json`` beside it when present, taken from
``--primary-condition`` when given, and otherwise assumed to be the
baseline only when the baseline has no file of its own; any other case
is refused. ``--baseline-file`` names an explicit baseline report.

Two conditions are not always scored on the same utterances: an
utterance whose reference normalises to nothing under a condition is
skipped for that condition only, so ``whisper_norm``, whose normaliser
removes hesitations, scores fewer AMI utterances than ``raw``. A gain
computed from the two corpus-level rates then mixes the effect of the
condition with the removal of a subset (audit finding EWER-09).
:func:`normaliser_gain` computes it on the shared utterances instead, and
``--gains-output`` writes it for every condition.

References
----------
Bisani, M., & Ney, H. (2004). Bootstrap estimates for confidence
    intervals in ASR performance evaluation. *ICASSP 2004*.
Koehn, P. (2004). Statistical significance tests for machine translation
    evaluation. *EMNLP 2004*.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from evaluation.bootstrap_ci import (
    DEFAULT_BOOTSTRAP,
    DEFAULT_SEED,
    align_reports,
    paired_delta,
    read_wer_report,
)

_REPORT_STEM = "wer_report"
_PRIMARY_NAME = f"{_REPORT_STEM}.csv"
_FIELDS = [
    "condition", "n", "macro_condition", "macro_baseline",
    "delta", "ci_lo", "ci_hi", "p_value", "excludes_zero",
    "bootstrap", "seed",
]
_GAIN_FIELDS = [
    "condition", "n_shared", "n_baseline_only", "n_condition_only",
    "macro_baseline_shared", "macro_condition_shared", "macro_gain_shared",
    "micro_baseline_shared", "micro_condition_shared", "micro_gain_shared",
    "macro_baseline_all", "macro_condition_all", "macro_gain_all",
]


def discover_reports(directory: Path,
                     prefix: str = _REPORT_STEM) -> dict[str, Path]:
    """Map condition name to report path for one sweep cell.

    ``{prefix}.csv`` holds whichever condition ran first and is recorded
    under the key ``"__primary__"``; every ``{prefix}_{condition}.csv``
    contributes its condition name.
    """
    found: dict[str, Path] = {}
    for path in sorted(directory.glob(f"{prefix}*.csv")):
        if path.name == f"{prefix}.csv":
            found["__primary__"] = path
        elif path.stem.startswith(prefix + "_"):
            found[path.stem[len(prefix) + 1:]] = path
    return found


def _primary_condition_from_summary(primary: Path) -> str | None:
    """Return the condition recorded beside the primary report, if any.

    ``benchmark_wer`` writes ``benchmark.condition`` into every summary
    JSON, and the primary report's summary sits beside it, named as the
    report with ``wer_summary`` for ``wer_report`` (``wer_summary.json``
    beside ``wer_report.csv``). When that file is present it settles which
    condition the primary report holds without any inference.
    """
    stem = primary.stem
    if stem.startswith(_REPORT_STEM):
        stem = "wer_summary" + stem[len(_REPORT_STEM):]
    summary = primary.with_name(stem + ".json")
    if not summary.is_file():
        return None
    try:
        payload = json.loads(summary.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    condition = (payload.get("benchmark") or {}).get("condition")
    return str(condition) if condition else None


def _resolve_primary(
    reports: dict[str, Path],
    directory: Path,
    baseline: str,
    primary_condition: str | None,
) -> None:
    """Replace the ``__primary__`` key of *reports* by its real condition.

    ``wer_report.csv`` carries no condition column, so its identity must
    come from somewhere. In order of preference: the caller's
    *primary_condition*; the sibling summary JSON; and, only when the
    baseline has no file of its own, the sweep's convention that the
    first condition (conventionally the baseline) is written to the
    primary path. Any other case is ambiguous, and guessing there once
    dropped a condition from the table or relabelled one as the
    baseline, so it raises instead.

    Mutates *reports* in place.

    Raises
    ------
    ValueError
        When the primary's identity cannot be established, when the
        inferred baseline is not a registered condition name (a typo such
        as ``Raw`` would otherwise relabel the primary as the baseline),
        or when the primary's condition also has a file of its own.
    """
    primary = reports.pop("__primary__", None)
    if primary is None:
        return
    stem = primary.stem
    name = primary_condition or _primary_condition_from_summary(primary)
    if name is None:
        if baseline in reports:
            raise ValueError(
                f"{directory}: cannot tell which condition {primary.name} "
                f"holds, because {baseline!r} has a file of its own. Pass "
                "--primary-condition NAME."
            )
        from evaluation.conditions import get_condition
        try:
            get_condition(baseline)
        except KeyError as exc:
            raise ValueError(
                f"baseline {baseline!r} is not a registered condition, so "
                f"{primary.name} cannot be assumed to hold it. Pass "
                "--primary-condition NAME or --baseline-file PATH."
            ) from exc
        print(
            f"  assuming {primary.name} holds {baseline!r}: it has no file "
            "of its own and the sweep writes its first condition to the "
            "primary path. Pass --primary-condition to make this explicit.",
            file=sys.stderr,
        )
        name = baseline
    if name in reports:
        raise ValueError(
            f"{directory}: {primary.name} is recorded as {name!r}, but "
            f"{stem}_{name}.csv also exists; remove one of them."
        )
    reports[name] = primary


def _baseline_and_reports(
    directory: Path,
    baseline: str,
    baseline_file: Path | None,
    primary_condition: str | None,
    prefix: str,
) -> tuple[Path, dict[str, Path]]:
    """Return the baseline report and ``{condition: report}`` for the rest.

    Shared by :func:`compare_all` and :func:`gain_rows`; see
    :func:`compare_all` for the parameters and the errors raised.
    """
    reports = discover_reports(directory, prefix)
    if not reports:
        raise FileNotFoundError(f"no {prefix}*.csv files under {directory}")

    _resolve_primary(reports, directory, baseline, primary_condition)

    if baseline_file is not None:
        base_path = baseline_file
        for name in [n for n, p in reports.items()
                     if p.resolve() == Path(baseline_file).resolve()]:
            reports.pop(name)
    elif baseline in reports:
        base_path = reports.pop(baseline)
    else:
        raise FileNotFoundError(f"baseline {baseline!r} not found under {directory}")
    return base_path, reports


def compare_all(
    directory: Path,
    baseline: str = "raw",
    baseline_file: Path | None = None,
    b: int = DEFAULT_BOOTSTRAP,
    seed: int = DEFAULT_SEED,
    primary_condition: str | None = None,
    prefix: str = _REPORT_STEM,
) -> list[dict]:
    """Pair every condition in *directory* against *baseline*.

    Parameters
    ----------
    directory:
        A directory of ``{prefix}*.csv`` files from one sweep cell.
    baseline:
        Name of the baseline condition.
    baseline_file:
        An explicit baseline report. Any report in *directory* that is the
        same file is excluded, so the baseline is never compared with
        itself.
    b, seed:
        Bootstrap replicate count and seed, passed to
        :func:`evaluation.bootstrap_ci.paired_delta`.
    primary_condition:
        The condition held by ``{prefix}.csv``, when neither a sibling
        summary JSON nor the sweep convention can establish it.
    prefix:
        The cell's report stem: ``wer_report`` (the default, the layout of
        the committed ``sweep_reports/`` and ``sweep_reports_postfix/``) or
        a sweep cell's qualified stem such as
        ``wer_report_librispeech_whisper-large-v3``. The committed
        ``sweep_reports_postfix_ami/`` keeps the sweep's names, so its stem
        is ``wer_report_ami_whisper-large-v3``.

    Returns
    -------
    list of dict
        One row per condition other than the baseline, sorted by name,
        with the keys in :data:`_FIELDS`. Every pair is restricted to the
        utterances both reports scored.

    Raises
    ------
    FileNotFoundError
        No reports under *directory*, or the baseline cannot be found.
    ValueError
        The primary report's condition cannot be established (see
        :func:`_resolve_primary`); two reports share no utterance; a
        report repeats an utterance name or holds a non-finite ``wer``.

    Side effects
    ------------
    Prints skipped-row counts and any assumption about the primary file
    to stderr. RNG use is local to each bootstrap call.
    """
    base_path, reports = _baseline_and_reports(
        directory, baseline, baseline_file, primary_condition, prefix)

    base_names, base_wers = read_wer_report(base_path)

    rows: list[dict] = []
    for condition, path in sorted(reports.items()):
        names, wers = read_wer_report(path)
        # align_reports raises when no utterance is shared, so every pair
        # reaching paired_delta is non-empty.
        _, a, bvals = align_reports(names, wers, base_names, base_wers)
        res = paired_delta(a, bvals, b=b, seed=seed)
        rows.append({
            "condition": condition,
            "n": res["n"],
            "macro_condition": round(res["macro_a"], 6),
            "macro_baseline": round(res["macro_b"], 6),
            "delta": round(res["delta"], 6),
            "ci_lo": round(res["ci_lo"], 6),
            "ci_hi": round(res["ci_hi"], 6),
            "p_value": round(res["p_value"], 6),
            "excludes_zero": int(bool(res["ci_excludes_zero"])),
            # The settings travel with the estimate. A percentile bound
            # carries Monte Carlo error of its own, so the same paired
            # data under a different replicate count moves the interval
            # in the fourth decimal, and a bound that cannot be traced
            # to the b and seed that produced it cannot be reproduced.
            "bootstrap": b,
            "seed": seed,
        })
    return rows


def _read_counts(path: Path) -> dict[str, tuple[float, int, int]]:
    """Return ``{name: (wer, errors, reference_words)}`` from a report.

    *errors* is substitutions + deletions + insertions. Rows with an empty
    or unparsable field are skipped, as :func:`read_wer_report` skips them.

    Raises
    ------
    ValueError
        If the report lacks one of the columns
        :func:`evaluation.wer.write_csv` writes, or if an utterance name
        repeats.
    """
    needed = ("name", "wer", "substitutions", "deletions", "insertions",
              "reference_words")
    out: dict[str, tuple[float, int, int]] = {}
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in needed if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path}: missing column(s) {', '.join(missing)}")
        for row in reader:
            try:
                wer = float(row["wer"])
                errors = (int(row["substitutions"]) + int(row["deletions"])
                          + int(row["insertions"]))
                ref_words = int(row["reference_words"])
            except (TypeError, ValueError):
                continue
            name = str(row["name"])
            if name in out:
                raise ValueError(f"{path}: utterance {name!r} repeats")
            out[name] = (wer, errors, ref_words)
    return out


def _rel_gain(baseline: float | None, condition: float | None) -> float | None:
    """``(baseline - condition) / baseline``, or ``None`` when undefined."""
    if baseline is None or condition is None or baseline == 0:
        return None
    return (baseline - condition) / baseline


def normaliser_gain(baseline_report: Path, condition_report: Path) -> dict:
    """Relative WER gain of a condition over the baseline, on shared utterances.

    A condition that also transforms the reference can empty it, and the
    utterance is then skipped for that condition alone: ``whisper_norm``
    scored 11,653 AMI utterances against raw's 12,643 in the post-fix
    grid. The gain computed from the two corpus rates, ``(raw - norm) /
    raw``, then mixes the normaliser's effect with the removal of those
    utterances (audit finding EWER-09). This computes it on the utterances
    both reports scored, as macro (mean per-utterance WER) and pooled
    (errors over reference words) rates, and also returns the all-utterance
    figures for comparison.

    Parameters
    ----------
    baseline_report, condition_report:
        Per-utterance reports as :func:`evaluation.wer.write_csv` writes
        them.

    Returns
    -------
    dict
        The keys of :data:`_GAIN_FIELDS` except ``condition``. Gains are
        relative reductions (positive when the condition lowers WER),
        ``None`` when the baseline rate is zero.

    Raises
    ------
    ValueError
        If the reports share no utterance, lack a needed column, or
        repeat an utterance name.
    """
    base = _read_counts(Path(baseline_report))
    cond = _read_counts(Path(condition_report))
    shared = sorted(set(base) & set(cond))
    if not shared:
        raise ValueError(f"{baseline_report} and {condition_report} share "
                         "no utterance names; cannot pair them.")

    def _macro(table, names):
        return sum(table[n][0] for n in names) / len(names) if names else None

    def _micro(table, names):
        ref = sum(table[n][2] for n in names)
        return sum(table[n][1] for n in names) / ref if ref else None

    macro_b, macro_c = _macro(base, shared), _macro(cond, shared)
    micro_b, micro_c = _micro(base, shared), _micro(cond, shared)
    all_b, all_c = _macro(base, list(base)), _macro(cond, list(cond))
    return {
        "n_shared": len(shared),
        "n_baseline_only": len(set(base) - set(cond)),
        "n_condition_only": len(set(cond) - set(base)),
        "macro_baseline_shared": macro_b,
        "macro_condition_shared": macro_c,
        "macro_gain_shared": _rel_gain(macro_b, macro_c),
        "micro_baseline_shared": micro_b,
        "micro_condition_shared": micro_c,
        "micro_gain_shared": _rel_gain(micro_b, micro_c),
        "macro_baseline_all": all_b,
        "macro_condition_all": all_c,
        "macro_gain_all": _rel_gain(all_b, all_c),
    }


def gain_rows(
    directory: Path,
    baseline: str = "raw",
    baseline_file: Path | None = None,
    primary_condition: str | None = None,
    prefix: str = _REPORT_STEM,
) -> list[dict]:
    """Return :func:`normaliser_gain` for every condition in *directory*.

    Parameters and errors are those of :func:`compare_all`; each row holds
    the keys of :data:`_GAIN_FIELDS`, sorted by condition, with rates
    rounded to six decimals.
    """
    base_path, reports = _baseline_and_reports(
        directory, baseline, baseline_file, primary_condition, prefix)
    rows = []
    for condition, path in sorted(reports.items()):
        gain = normaliser_gain(base_path, path)
        rows.append({"condition": condition,
                     **{k: (round(v, 6) if isinstance(v, float) else v)
                        for k, v in gain.items()}})
    return rows


def write_gain_rows(rows: list[dict], path: Path) -> None:
    """Write *rows* (from :func:`gain_rows`) to *path* as CSV.

    Creates the parent directory and overwrites any existing file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_GAIN_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_rows(rows: list[dict], path: Path) -> None:
    """Write *rows* (from :func:`compare_all`) to *path* as CSV.

    Creates the parent directory and overwrites any existing file. The
    columns are :data:`_FIELDS`, in that order.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="evaluation.condition_ci",
        description=(
            "Paired bootstrap CIs for post-processing condition deltas "
            "against a baseline condition."
        ),
    )
    p.add_argument("--reports", type=Path, required=True, metavar="DIR",
                   help="Directory of per-utterance wer_report*.csv files.")
    p.add_argument("--baseline", default="raw", metavar="NAME",
                   help="Baseline condition name (default: %(default)s).")
    p.add_argument("--baseline-file", type=Path, default=None, metavar="PATH",
                   help="Explicit baseline report, overriding --baseline.")
    p.add_argument("--primary-condition", default=None, metavar="NAME",
                   help=("Condition held by the unsuffixed primary report. "
                         "Needed only when no summary JSON sits beside it "
                         "and the baseline has a file of its own."))
    p.add_argument("--prefix", default=_REPORT_STEM, metavar="STEM",
                   help=("Report stem of the cell: the primary report is "
                         "STEM.csv and each other condition STEM_<name>.csv "
                         "(default: %(default)s; a sweep cell is e.g. "
                         "wer_report_librispeech_whisper-large-v3)."))
    p.add_argument("--bootstrap", type=int, default=DEFAULT_BOOTSTRAP,
                   metavar="B", help="Replicates (default: %(default)s).")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED,
                   help="Random seed (default: %(default)s).")
    p.add_argument("--output", type=Path, required=True, metavar="PATH",
                   help=("Destination CSV. Required: there is no default, so a "
                         "run cannot overwrite a committed interval table by "
                         "omission."))
    p.add_argument("--gains-output", type=Path, default=None, metavar="PATH",
                   help=("Also write each condition's relative WER gain over "
                         "the baseline on the utterances both scored, with "
                         "the all-utterance gain beside it (see "
                         "normaliser_gain)."))
    return p


def main(argv: list[str] | None = None) -> int:
    """Run the command-line interface.

    Parameters
    ----------
    argv:
        Argument list; ``None`` reads ``sys.argv``.

    Returns
    -------
    int
        ``0`` on success, ``2`` on an input error, with the reason on
        stderr. :func:`compare_all` and the readers raise ``ValueError``
        (or ``FileNotFoundError`` for a missing report) for these.

    Side effects
    ------------
    Writes the CSV to ``--output`` (overwriting it), and the gains CSV to
    ``--gains-output`` when given, each with a ``<stem>_provenance.json``
    beside it (:func:`provenance.write_sidecar`), and prints the table to
    stdout.
    """
    args = _build_parser().parse_args(argv)
    try:
        return _run(args)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _write_provenance(args, output: Path, run_meta: dict) -> None:
    """Write ``<output stem>_provenance.json`` beside *output* (OUTPUTS-12).

    Records the arguments that shape the numbers (not the output paths),
    every report of the cell with its digest, and *run_meta*, the code
    commit as :func:`_run` read it before writing anything.
    """
    from provenance import write_sidecar

    inputs = list(discover_reports(args.reports, args.prefix).values())
    if args.baseline_file is not None and Path(args.baseline_file) not in inputs:
        inputs.append(Path(args.baseline_file))
    write_sidecar(output, tool="evaluation.condition_ci", inputs=inputs, arguments={
        "reports": Path(args.reports).as_posix(),
        "baseline": args.baseline,
        "baseline_file": (Path(args.baseline_file).as_posix()
                          if args.baseline_file is not None else None),
        "primary_condition": args.primary_condition,
        "prefix": args.prefix,
        "bootstrap": args.bootstrap,
        "seed": args.seed,
    }, run_meta=run_meta)


def _run(args) -> int:
    """Carry out the parsed command; input errors propagate as exceptions."""
    from provenance import SIDECAR_PACKAGES, run_metadata, sidecar_path

    # The git state both sidecars record is read once, before either table
    # is written, and leaves out the files this run rewrites. Read after
    # writing, it counted this run's own output as a change to the tree: a
    # regenerated table that differed from the committed one, the main
    # table and its new sidecar in the gains sidecar's record, and on a
    # second regeneration the sidecars the first had rewritten.
    outputs = [p for p in (args.output, args.gains_output) if p is not None]
    run_meta = run_metadata(packages=SIDECAR_PACKAGES,
                            ignore=[f for p in outputs for f in (p, sidecar_path(p))])
    rows = compare_all(
        args.reports, baseline=args.baseline,
        baseline_file=args.baseline_file,
        b=args.bootstrap, seed=args.seed,
        primary_condition=args.primary_condition,
        prefix=args.prefix,
    )
    write_rows(rows, args.output)
    _write_provenance(args, args.output, run_meta)
    if args.gains_output is not None:
        write_gain_rows(gain_rows(
            args.reports, baseline=args.baseline,
            baseline_file=args.baseline_file,
            primary_condition=args.primary_condition, prefix=args.prefix,
        ), args.gains_output)
        _write_provenance(args, args.gains_output, run_meta)
        print(f"  Wrote shared-utterance gains to {args.gains_output}")
    print(f"Paired condition deltas against {args.baseline!r} "
          f"({args.bootstrap} replicates)")
    print("-" * 62)
    for r in rows:
        mark = "*" if r["excludes_zero"] else " "
        print(f"  {r['condition']:22s} delta={r['delta']:+.4f} "
              f"[{r['ci_lo']:+.4f}, {r['ci_hi']:+.4f}] "
              f"p={r['p_value']:.4f} {mark}")
    print(f"\n  Wrote {len(rows)} row(s) to {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
