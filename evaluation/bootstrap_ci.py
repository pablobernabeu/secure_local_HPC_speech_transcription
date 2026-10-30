#!/usr/bin/env python3
"""
Bootstrap confidence intervals for macro-WER and condition deltas.

A single point estimate of macro-WER conveys nothing about how much it
would move if the test set had been a slightly different sample of
utterances. The non-parametric bootstrap (Efron, 1979; Bisani & Ney,
2004) quantifies that sampling uncertainty by resampling the scored
utterances with replacement, recomputing the statistic on each resample,
and reading the 2.5th and 97.5th percentiles of the resulting
distribution as a 95% confidence interval.

This module operates on the per-utterance ``wer_report*.csv`` files
written by ``evaluation/wer.py`` and ``evaluation/benchmark_wer.py``.
Each row carries a ``name`` (utterance id) and a ``wer`` column; the
macro-WER is the unweighted mean of that column, matching
``evaluation.wer.aggregate``.

Two quantities are produced:

* The macro-WER of a single report with a percentile bootstrap CI.
* The paired delta in macro-WER between two conditions scored on the
  *same* utterances. Pairing by utterance and resampling the shared
  index once per replicate cancels the between-utterance variance that
  dominates an unpaired comparison, giving a much tighter interval on
  the difference (Bisani & Ney, 2004; Koehn, 2004).

The module depends only on ``numpy`` and the standard library, so it
runs on an HPC head node or a laptop without the audio or scoring
stack installed.

Usage::

    python -m evaluation.bootstrap_ci --report output/evaluation/wer_report.csv
    python -m evaluation.bootstrap_ci --report a.csv b.csv --bootstrap 5000
    python -m evaluation.bootstrap_ci --compare raw.csv postprocessed.csv

References
----------
Efron, B. (1979). Bootstrap methods: another look at the jackknife.
    *Annals of Statistics*, 7(1), 1-26.
Bisani, M., & Ney, H. (2004). Bootstrap estimates for confidence
    intervals in ASR performance evaluation. *ICASSP 2004*.
Koehn, P. (2004). Statistical significance tests for machine translation
    evaluation. *EMNLP 2004*.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

try:
    import numpy as np
except ImportError as exc:  # pragma: no cover - import-time guard
    raise SystemExit("numpy is required for evaluation.bootstrap_ci.") from exc


_DEFAULT_BOOTSTRAP = 2000
_DEFAULT_SEED = 42
_DEFAULT_OUTPUT = Path("output/evaluation/wer_ci.csv")
_CI_LOW_PCT = 2.5
_CI_HIGH_PCT = 97.5
_CI_FIELDS = ["file", "n", "macro_wer", "ci_lo", "ci_hi", "bootstrap", "seed"]
# The per-row statistics copied from each row dict. Named explicitly so a
# column added to _CI_FIELDS cannot shift which keys are copied.
_CI_ROW_KEYS = ("file", "n", "macro_wer", "ci_lo", "ci_hi")

# Public names for the defaults, so evaluation.condition_ci can share them
# without importing underscore-private constants.
DEFAULT_BOOTSTRAP = _DEFAULT_BOOTSTRAP
DEFAULT_SEED = _DEFAULT_SEED


# ---------------------------------------------------------------------------
# CSV loading
# ---------------------------------------------------------------------------

def read_wer_report(path: Path) -> tuple[list[str], np.ndarray]:
    """Read a per-utterance WER report.

    Parameters
    ----------
    path:
        Path to a ``wer_report*.csv`` file with at least a ``name`` and a
        ``wer`` column (the format written by :func:`evaluation.wer.write_csv`).

    Returns
    -------
    names:
        The utterance identifiers, in file order.
    wers:
        The per-utterance WER values as a float array, aligned to *names*.

    Raises
    ------
    ValueError
        If the file lacks a ``wer`` column or contains no usable rows,
        or if a ``wer`` value parses to a non-finite number (``nan``,
        ``inf``). ``float`` accepts those spellings, and one of them would
        otherwise flow into the bootstrap as a NaN delta whose p-value is
        still printed as a number.

    Side effects
    ------------
    Prints to stderr how many rows were skipped for an empty or
    unparsable ``wer``, so a shortened report is visible at the point it
    is read, not only through a smaller ``n`` downstream.
    """
    names: list[str] = []
    wers: list[float] = []
    skipped = 0
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or "wer" not in reader.fieldnames:
            raise ValueError(f"{path}: no 'wer' column found.")
        has_name = "name" in reader.fieldnames
        for i, row in enumerate(reader):
            raw = row.get("wer", "")
            if raw is None or str(raw).strip() == "":
                skipped += 1
                continue
            try:
                value = float(raw)
            except ValueError:
                skipped += 1
                continue
            if not np.isfinite(value):
                raise ValueError(
                    f"{path}: row {i} has a non-finite wer ({raw!r}); a "
                    "benchmark report never writes one, so the file is "
                    "damaged or was produced by something else."
                )
            names.append(str(row["name"]) if has_name else f"row_{i:05d}")
            wers.append(value)
    if skipped:
        print(f"  {path}: skipped {skipped} row(s) with an empty or "
              "unparsable wer", file=sys.stderr)
    if not wers:
        raise ValueError(f"{path}: no usable 'wer' rows.")
    return names, np.asarray(wers, dtype=float)


# ---------------------------------------------------------------------------
# Bootstrap statistics
# ---------------------------------------------------------------------------

def bootstrap_macro(
    wers: np.ndarray,
    b: int = _DEFAULT_BOOTSTRAP,
    seed: int = _DEFAULT_SEED,
) -> tuple[float, float, float]:
    """Bootstrap a 95% percentile CI for the macro-WER.

    Utterances are resampled with replacement *b* times; the macro-WER
    (the mean of the per-utterance WERs) is recomputed on each resample,
    and the 2.5th and 97.5th percentiles of those *b* means form the
    interval.

    Parameters
    ----------
    wers:
        Per-utterance WER values.
    b:
        Number of bootstrap replicates.
    seed:
        Seed for the random number generator, for reproducibility.

    Returns
    -------
    mean, lo, hi:
        The observed macro-WER and the lower and upper bounds of its
        95% percentile confidence interval.
    """
    wers = np.asarray(wers, dtype=float)
    n = wers.size
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    observed = float(wers.mean())
    rng = np.random.default_rng(seed)
    # Vectorised resampling: draw a (b, n) matrix of indices in one call,
    # then average along the utterance axis to get b resampled macro-WERs.
    idx = rng.integers(0, n, size=(b, n))
    replicates = wers[idx].mean(axis=1)
    lo = float(np.percentile(replicates, _CI_LOW_PCT))
    hi = float(np.percentile(replicates, _CI_HIGH_PCT))
    return observed, lo, hi


def paired_delta(
    wers_a: np.ndarray,
    wers_b: np.ndarray,
    b: int = _DEFAULT_BOOTSTRAP,
    seed: int = _DEFAULT_SEED,
) -> dict:
    """Paired bootstrap CI for the macro-WER delta between two conditions.

    Both arrays must be aligned to the *same* utterances (see
    :func:`align_reports`). A single index vector is resampled per
    replicate and applied to both conditions, so the difference
    ``macro_a - macro_b`` is taken on the same draw. This pairing removes
    the between-utterance variance shared by the two conditions and
    yields a tighter interval than comparing two independent bootstraps
    (Bisani & Ney, 2004; Koehn, 2004).

    A two-sided bootstrap p-value is reported as twice the smaller tail
    mass of the replicate deltas about zero, clipped to ``[0, 1]``. The
    ``ci_excludes_zero`` flag is the interval-based companion to that
    test: the delta is significant at the 5% level when the 95% CI does
    not straddle zero.

    Parameters
    ----------
    wers_a, wers_b:
        Per-utterance WER values for the two conditions, aligned index by
        index to the same utterances.
    b:
        Number of bootstrap replicates.
    seed:
        Seed for the random number generator.

    Returns
    -------
    dict
        Keys: ``macro_a``, ``macro_b``, ``delta`` (= macro_a - macro_b),
        ``ci_lo``, ``ci_hi``, ``p_value``, ``ci_excludes_zero``, ``n``.
    """
    wers_a = np.asarray(wers_a, dtype=float)
    wers_b = np.asarray(wers_b, dtype=float)
    if wers_a.shape != wers_b.shape:
        raise ValueError(
            "paired_delta requires equal-length, index-aligned arrays "
            f"(got {wers_a.shape} and {wers_b.shape})."
        )
    n = wers_a.size
    macro_a = float(wers_a.mean()) if n else float("nan")
    macro_b = float(wers_b.mean()) if n else float("nan")
    observed_delta = macro_a - macro_b
    if n == 0:
        return {
            "macro_a": macro_a, "macro_b": macro_b, "delta": float("nan"),
            "ci_lo": float("nan"), "ci_hi": float("nan"),
            "p_value": float("nan"), "ci_excludes_zero": False, "n": 0,
        }
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(b, n))
    deltas = wers_a[idx].mean(axis=1) - wers_b[idx].mean(axis=1)
    lo = float(np.percentile(deltas, _CI_LOW_PCT))
    hi = float(np.percentile(deltas, _CI_HIGH_PCT))
    # Two-sided bootstrap p-value: twice the smaller tail mass about zero.
    frac_le = float(np.mean(deltas <= 0.0))
    frac_ge = float(np.mean(deltas >= 0.0))
    p_value = min(1.0, 2.0 * min(frac_le, frac_ge))
    return {
        "macro_a": macro_a,
        "macro_b": macro_b,
        "delta": observed_delta,
        "ci_lo": lo,
        "ci_hi": hi,
        "p_value": p_value,
        "ci_excludes_zero": (lo > 0.0) or (hi < 0.0),
        "n": n,
    }


def align_reports(
    names_a: list[str],
    wers_a: np.ndarray,
    names_b: list[str],
    wers_b: np.ndarray,
) -> tuple[list[str], np.ndarray, np.ndarray]:
    """Restrict two reports to their shared utterances, in a common order.

    The paired bootstrap is only valid on utterances scored under both
    conditions. This intersects the two ``name`` columns and returns the
    WER arrays reordered to the shared, sorted set of names.

    Parameters
    ----------
    names_a, wers_a:
        Names and WERs of the first report.
    names_b, wers_b:
        Names and WERs of the second report.

    Returns
    -------
    shared, aligned_a, aligned_b:
        The sorted shared utterance names and the two WER arrays indexed
        to them.

    Raises
    ------
    ValueError
        If the two reports share no utterance names, or if either
        report repeats an utterance name. Pairing is by name, so
        a repeated name would silently keep only its last row and drop the
        rest from the pairing while the reported ``n`` still looked
        plausible. FLEURS reports written before the benchmark made its
        ids unique carry such repeats (several speakers read the same
        sentence id).
    """
    for label, names in (("first", names_a), ("second", names_b)):
        if len(set(names)) != len(names):
            seen: set[str] = set()
            repeats = sorted({n for n in names if n in seen or seen.add(n)})
            raise ValueError(
                f"The {label} report repeats {len(repeats)} utterance "
                f"name(s) (e.g. {repeats[:3]}); pairing by name would drop "
                "rows silently."
            )
    map_a = dict(zip(names_a, np.asarray(wers_a, dtype=float), strict=True))
    map_b = dict(zip(names_b, np.asarray(wers_b, dtype=float), strict=True))
    shared = sorted(set(map_a) & set(map_b))
    if not shared:
        raise ValueError(
            "The two reports share no utterance names; cannot pair them."
        )
    aligned_a = np.asarray([map_a[k] for k in shared], dtype=float)
    aligned_b = np.asarray([map_b[k] for k in shared], dtype=float)
    return shared, aligned_a, aligned_b


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def write_ci_csv(
    rows: list[dict],
    path: Path,
    b: int = _DEFAULT_BOOTSTRAP,
    seed: int = _DEFAULT_SEED,
) -> None:
    """Write per-report macro-WER CIs to *path*.

    Columns: ``file``, ``n``, ``macro_wer``, ``ci_lo``, ``ci_hi``,
    ``bootstrap``, ``seed``.

    The replicate count and the seed are recorded in the artefact
    itself, not left to be asserted by whatever prose quotes it. A
    percentile bound is an estimate of a quantile and carries Monte
    Carlo error of its own, so the same data under a different *b*
    moves the interval in the fourth decimal, and an interval whose
    settings cannot be recovered from the file cannot be reproduced or
    checked. Values already present on a row take precedence over the
    *b* and *seed* arguments, so a caller that mixes settings across
    rows records each row's own.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CI_FIELDS)
        writer.writeheader()
        for r in rows:
            out = {k: r[k] for k in _CI_ROW_KEYS}
            out["bootstrap"] = r.get("bootstrap", b)
            out["seed"] = r.get("seed", seed)
            writer.writerow(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="evaluation.bootstrap_ci",
        description=(
            "Bootstrap 95% confidence intervals for macro-WER and paired "
            "condition deltas from per-utterance wer_report*.csv files."
        ),
    )
    p.add_argument(
        "--report", nargs="+", type=Path, metavar="PATH",
        help="One or more per-utterance WER report CSVs to summarise.",
    )
    p.add_argument(
        "--compare", nargs=2, type=Path, metavar=("A", "B"),
        help=(
            "Two report CSVs scored on the same utterances; report the "
            "paired delta in macro-WER (A - B) with its 95% CI."
        ),
    )
    p.add_argument(
        "--bootstrap", type=int, default=_DEFAULT_BOOTSTRAP, metavar="B",
        help="Number of bootstrap replicates (default: %(default)s).",
    )
    p.add_argument(
        "--seed", type=int, default=_DEFAULT_SEED,
        help="Random seed for reproducibility (default: %(default)s).",
    )
    p.add_argument(
        "--output", type=Path, default=_DEFAULT_OUTPUT, metavar="PATH",
        help="Destination CSV for per-report CIs (default: %(default)s).",
    )
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
        ``0`` on success, ``2`` on an input error (missing ``wer``
        column, no usable rows, no shared utterances, non-finite ``wer``,
        repeated utterance names), with the reason on stderr. The library
        functions raise ``ValueError`` for these, so callers can handle them.

    Side effects
    ------------
    With ``--report``, writes the per-report CI table to ``--output``
    (overwriting it), with a ``<stem>_provenance.json`` beside it
    (:func:`provenance.write_sidecar`). Both modes print to stdout. The bootstrap draws from
    a local ``numpy.random.default_rng(seed)``; no global RNG is touched.
    """
    args = _build_parser().parse_args(argv)
    if not args.report and not args.compare:
        _build_parser().error("supply --report PATHS... and/or --compare A B.")
    try:
        return _run(args)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _run(args) -> int:
    """Carry out the parsed command; input errors propagate as exceptions."""

    rows: list[dict] = []

    if args.report:
        from provenance import (
            SIDECAR_PACKAGES, run_metadata, sidecar_path, write_sidecar)
        # The git state is read before the table is written and leaves out
        # the table and its sidecar, so regenerating a committed table in
        # place does not mark the run dirty (see condition_ci._run).
        run_meta = run_metadata(packages=SIDECAR_PACKAGES,
                                ignore=(args.output, sidecar_path(args.output)))
        print("Macro-WER with 95% bootstrap CI")
        print("-------------------------------")
        for path in args.report:
            names, wers = read_wer_report(path)
            mean, lo, hi = bootstrap_macro(wers, b=args.bootstrap, seed=args.seed)
            rows.append({
                # POSIX spelling, so the artefact's bytes do not depend
                # on the platform that wrote it (REGEN-10).
                "file": Path(path).as_posix(),
                "n": len(names),
                "macro_wer": round(mean, 6),
                "ci_lo": round(lo, 6),
                "ci_hi": round(hi, 6),
            })
            print(
                f"  {path}\n"
                f"      n={len(names)}  macro-WER={mean:.4f}  "
                f"95% CI [{lo:.4f}, {hi:.4f}]"
            )
        write_ci_csv(rows, args.output, b=args.bootstrap, seed=args.seed)
        # The table has nowhere to hold what produced it (OUTPUTS-12).
        write_sidecar(args.output, tool="evaluation.bootstrap_ci",
                      inputs=args.report,
                      arguments={"report": [Path(p).as_posix() for p in args.report],
                                 "bootstrap": args.bootstrap, "seed": args.seed},
                      run_meta=run_meta)
        print(f"\n  Wrote {len(rows)} row(s) to {args.output}")

    if args.compare:
        path_a, path_b = args.compare
        names_a, wers_a = read_wer_report(path_a)
        names_b, wers_b = read_wer_report(path_b)
        shared, aligned_a, aligned_b = align_reports(
            names_a, wers_a, names_b, wers_b,
        )
        res = paired_delta(
            aligned_a, aligned_b, b=args.bootstrap, seed=args.seed,
        )
        verdict = (
            "excludes 0 (significant at 5%)"
            if res["ci_excludes_zero"]
            else "contains 0 (not significant at 5%)"
        )
        print("\nPaired delta in macro-WER (A - B)")
        print("---------------------------------")
        print(f"  A: {path_a}  macro-WER={res['macro_a']:.4f}")
        print(f"  B: {path_b}  macro-WER={res['macro_b']:.4f}")
        print(f"  shared utterances: {res['n']}")
        print(
            f"  delta={res['delta']:+.4f}  "
            f"95% CI [{res['ci_lo']:+.4f}, {res['ci_hi']:+.4f}]  "
            f"p={res['p_value']:.4f}"
        )
        print(f"  {verdict}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
