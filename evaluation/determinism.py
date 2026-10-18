#!/usr/bin/env python3
"""
Quantify run-to-run variation in transcription.

The workflow's reproducibility claim rests on a transcript being
recoverable from the recording. That is only true to the extent that the
same audio, model and settings produce the same words twice, and on a GPU
that is not automatic: reduction order in floating-point kernels varies
between launches unless deterministic algorithms are requested, and a
difference of one logit can change a decoded token.

The benchmark exposes ``--seed``, which seeds Python, NumPy and PyTorch
and asks cuDNN for deterministic kernels. This module measures what that
buys, from the hypothesis dumps of two or more runs:

* **Repeat runs, same seed.** Any disagreement is non-determinism in the
  stack, since nothing else differed. The honest target is exact
  agreement, and anything less is worth reporting as a bound on
  reproducibility rather than explaining away.
* **Runs under different seeds.** Disagreement here is expected wherever
  sampling is involved, and its size says how much of a reported figure
  is seed noise rather than signal. A word error rate difference smaller
  than the seed spread is not a difference.

Agreement is reported at two granularities, because they answer different
questions. The exact-match rate is what a reader reproducing a quoted
transcript experiences. The word-level divergence says how far apart the
disagreeing utterances actually are, since one substituted word in a
hundred is a different matter from a wholly different transcript.

Usage::

    python -m evaluation.determinism run_seed0.csv run_seed1.csv \\
        --json output/evaluation/determinism_summary.json
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from itertools import combinations
from pathlib import Path


def word_edit_distance(a: str, b: str) -> int:
    """Word-level Levenshtein distance.

    Implemented here rather than taken from ``jiwer`` so that the module,
    and its tests, run wherever Python does. The corpus-scale scoring
    still belongs to ``jiwer``; this is a per-utterance divergence
    measure over two short token lists.
    """
    first, second = (a or "").split(), (b or "").split()
    if not first:
        return len(second)
    if not second:
        return len(first)
    previous = list(range(len(second) + 1))
    for i, left in enumerate(first, 1):
        current = [i]
        for j, right in enumerate(second, 1):
            current.append(min(
                previous[j] + 1,            # deletion
                current[j - 1] + 1,         # insertion
                previous[j - 1] + (left != right),   # substitution
            ))
        previous = current
    return previous[-1]


_REQUIRED_COLUMNS = ("uid", "hypothesis_raw")


def read_hypotheses(path: Path, condition: str = "raw") -> dict:
    """Return ``{uid: hypothesis_raw}`` for one run.

    The untransformed hypothesis is the right column: it is what the
    model produced, before any condition could mask a difference by
    normalising it away.

    Parameters
    ----------
    path:
        A CSV written by ``benchmark_wer --dump-hypotheses``.
    condition:
        Keep only rows whose ``condition`` column equals this. The dump
        holds one row per (utterance, condition), and ``hypothesis_raw``
        repeats across conditions, so one condition is enough. A false
        value keeps every row, which then requires one row per uid.

    Returns
    -------
    dict
        ``{uid: hypothesis_raw}``.

    Raises
    ------
    ValueError
        If a required column is missing, or if a uid occurs twice among
        the kept rows. A missing ``hypothesis_raw`` column would otherwise
        read as the empty string in every run and report perfect
        agreement; a repeated uid would keep only its last row.
    """
    hypotheses: dict[str, str] = {}
    with Path(path).open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        required = _REQUIRED_COLUMNS + (("condition",) if condition else ())
        missing = [c for c in required if c not in (reader.fieldnames or ())]
        if missing:
            raise ValueError(f"{path}: missing column(s) {missing}")
        for row in reader:
            if condition and row["condition"] != condition:
                continue
            uid = row["uid"]
            if uid in hypotheses:
                raise ValueError(
                    f"{path}: uid {uid!r} occurs more than once for "
                    f"condition {condition!r}; runs cannot be compared "
                    "utterance by utterance."
                )
            hypotheses[uid] = row["hypothesis_raw"]
    return hypotheses


def compare(runs: dict) -> dict:
    """Compare the hypotheses of two or more runs.

    *runs* maps a label to a ``{uid: hypothesis}`` dict. Only utterances
    present in every run are compared, and the number dropped is
    reported rather than passed over: a run that failed half way would
    otherwise show perfect agreement on the half it managed.
    """
    labels = sorted(runs)
    if len(labels) < 2:
        raise ValueError("comparing determinism needs at least two runs")

    shared = set(runs[labels[0]])
    for label in labels[1:]:
        shared &= set(runs[label])
    dropped = {label: len(runs[label]) - len(shared) for label in labels}

    identical = 0
    divergences: list[tuple[float, str]] = []
    for uid in sorted(shared):
        texts = [runs[label][uid] for label in labels]
        if all(text == texts[0] for text in texts):
            identical += 1
            continue
        # Worst pairwise divergence for this utterance, as a fraction of
        # the longer token count, so a long utterance is not flattered.
        worst = 0.0
        for left, right in combinations(texts, 2):
            length = max(len(left.split()), len(right.split()), 1)
            worst = max(worst, word_edit_distance(left, right) / length)
        divergences.append((worst, uid))

    divergences.sort(reverse=True)
    n = len(shared)
    return {
        "runs": labels,
        "utterances_compared": n,
        "utterances_dropped_per_run": dropped,
        "identical": identical,
        "exact_match_rate": round(identical / n, 6) if n else None,
        "differing": len(divergences),
        "mean_word_divergence_over_differing": (
            round(statistics.fmean(d for d, _ in divergences), 6)
            if divergences else 0.0),
        "max_word_divergence": round(divergences[0][0], 6) if divergences else 0.0,
        "most_divergent": [uid for _, uid in divergences[:10]],
    }


def compare_files(paths, condition: str = "raw") -> dict:
    """Read each dump in *paths* and :func:`compare` them.

    Runs are labelled by file stem, which is how the JSON's ``runs`` list
    names them.

    Raises
    ------
    ValueError
        If two paths share a stem (for example ``seed0_run1.csv`` from two
        output directories). Labelling by stem would merge them into one
        run and turn a three-run comparison into a two-run one.
    """
    runs: dict[str, dict] = {}
    for p in paths:
        label = Path(p).stem
        if label in runs:
            raise ValueError(
                f"two dumps share the label {label!r}; rename one so each "
                "run keeps its own entry.")
        runs[label] = read_hypotheses(p, condition)
    return compare(runs)


def print_report(summary: dict) -> None:
    """Print a :func:`compare` summary to stdout."""
    print(f"\n  runs compared:        {', '.join(summary['runs'])}")
    print(f"  utterances compared:  {summary['utterances_compared']}")
    dropped = {k: v for k, v in summary["utterances_dropped_per_run"].items() if v}
    if dropped:
        print(f"  dropped (not in all): {dropped}")
    rate = summary["exact_match_rate"]
    print(f"  identical everywhere: {summary['identical']} "
          f"({rate * 100:.3f}%)" if rate is not None else "  identical: n/a")
    if summary["differing"]:
        print(f"  differing:            {summary['differing']}")
        print(f"  mean word divergence: "
              f"{summary['mean_word_divergence_over_differing'] * 100:.2f}% "
              "of the longer utterance, over the differing ones")
        print(f"  worst utterance:      "
              f"{summary['max_word_divergence'] * 100:.2f}%")
        print(f"  most divergent ids:   {', '.join(summary['most_divergent'][:5])}")
    else:
        print("  every compared utterance agreed exactly.")


def main(argv=None) -> int:
    """Run the command-line interface.

    Returns ``0`` on success; ``2`` when a dump is missing, fewer than two
    are given, or a dump is malformed; ``1`` when no utterance is shared by
    every run (for example a ``--condition`` absent from the dumps), in
    which case no JSON is written, since an agreement rate over nothing is
    not a result. Writes the ``--json`` summary when asked for.
    """
    parser = argparse.ArgumentParser(
        description="Compare transcription hypotheses across runs.")
    parser.add_argument("dumps", nargs="+", type=Path,
                        help="two or more CSVs from benchmark_wer "
                             "--dump-hypotheses")
    parser.add_argument("--condition", default="raw",
                        help="which condition's rows to compare "
                             "(default: %(default)s, the model's own output)")
    parser.add_argument("--json", dest="json_out", type=Path, default=None)
    args = parser.parse_args(argv)

    missing = [p for p in args.dumps if not p.exists()]
    if missing:
        print(f"  no such dump(s): {missing}", file=sys.stderr)
        return 2
    if len(args.dumps) < 2:
        print("  determinism needs at least two runs to compare",
              file=sys.stderr)
        return 2

    try:
        summary = compare_files(args.dumps, args.condition)
    except ValueError as exc:
        print(f"  {exc}", file=sys.stderr)
        return 2
    print(f"Condition compared: {args.condition}")
    print_report(summary)
    if summary["utterances_compared"] == 0:
        print(f"  no utterance of condition {args.condition!r} is present "
              "in every run; nothing was compared", file=sys.stderr)
        return 1

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(summary, indent=2),
                                 encoding="utf-8")
        print(f"\n  summary: {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
