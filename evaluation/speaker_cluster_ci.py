"""Reader-cluster sensitivity intervals for LibriSpeech macro WER.

Whole readers are sampled with replacement, retaining every utterance of
each selected reader. Each replicate divides the total of the per-utterance
WERs by the number of sampled utterances: this preserves the utterance-level
macro estimand instead of replacing it with an unweighted mean of readers.
For a paired comparison, the same reader draw applies to both conditions.

This is a sensitivity analysis of sampling uncertainty within the observed
reader population. It does not account for corpus selection, recording
conditions or errors in the reference. IDs must use LibriSpeech's numeric
reader-chapter-utterance format; it is unsafe to infer readers in other
corpora from an arbitrary filename prefix. No audio or scoring stack is
needed, and no historical interval file is overwritten by default.

Example::

    python -m evaluation.speaker_cluster_ci \
        --report output/evaluation/wer_report.csv \
        --baseline output/evaluation/sweep_reports/wer_report.csv \
        --condition output/evaluation/sweep_reports/wer_report_contraction_fix.csv \
                    output/evaluation/sweep_reports/wer_report_pipeline_full.csv \
        --bootstrap 10000 --seed 42 \
        --output output/evaluation/speaker_cluster_sensitivity.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

import numpy as np

from evaluation.bootstrap_ci import DEFAULT_BOOTSTRAP, DEFAULT_SEED

_LIBRISPEECH_ID = re.compile(r"([0-9]+)-[0-9]+-[0-9]+\Z")
_BATCH_SIZE = 1000


def read_librispeech_report(path: Path) -> dict[str, float]:
    """Load every row, refusing duplicate IDs or unusable WERs.

    An empty-reference exclusion would change the sampled population, so
    this analysis refuses missing or invalid rows instead of dropping them.
    WERs above one are valid because insertions have no reference-length cap.
    """
    values: dict[str, float] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not {"name", "wer"}.issubset(reader.fieldnames or []):
            raise ValueError(f"{path}: 'name' and 'wer' columns are required")
        for line, row in enumerate(reader, 2):
            name = row["name"] or ""
            if not _LIBRISPEECH_ID.fullmatch(name):
                raise ValueError(f"{path}:{line}: invalid LibriSpeech ID {name!r}")
            if name in values:
                raise ValueError(f"{path}:{line}: duplicate utterance {name!r}")
            try:
                value = float(row["wer"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{path}:{line}: unusable WER") from exc
            if not np.isfinite(value) or value < 0:
                raise ValueError(f"{path}:{line}: WER must be finite and non-negative")
            values[name] = value
    if not values:
        raise ValueError(f"{path}: no utterances")
    return values


def cluster_interval(
    names: list[str], values, bootstrap: int = DEFAULT_BOOTSTRAP,
    seed: int = DEFAULT_SEED,
) -> dict:
    """Compute a two-sided 95% percentile interval over whole readers.

    Clusters and utterances are sorted for independence from CSV row order.
    Resampling is batched so memory grows with clusters and batch size, not
    with the product of replicates and utterances. At least two readers are
    required: one reader supplies no estimate of between-reader variation.
    """
    if isinstance(bootstrap, bool) or not isinstance(bootstrap, int) or bootstrap < 1:
        raise ValueError("bootstrap must be a positive integer")
    data = np.asarray(values, dtype=float)
    if data.ndim != 1 or len(names) != len(data) or not len(names):
        raise ValueError("names and values must be non-empty aligned vectors")
    if not np.isfinite(data).all():
        raise ValueError("values must be finite")
    if len(set(names)) != len(names):
        raise ValueError("duplicate utterance IDs")
    grouped: dict[str, list[tuple[str, float]]] = {}
    for name, value in zip(names, data, strict=True):
        match = _LIBRISPEECH_ID.fullmatch(name)
        if match is None:
            raise ValueError(f"invalid LibriSpeech ID {name!r}")
        grouped.setdefault(match[1], []).append((name, float(value)))
    readers = sorted(grouped)
    if len(readers) < 2:
        raise ValueError("at least two readers are required")
    sums = np.array([sum(value for _, value in sorted(grouped[r])) for r in readers])
    counts = np.array([len(grouped[r]) for r in readers])
    rng = np.random.default_rng(seed)
    replicates = np.empty(bootstrap)
    for begin in range(0, bootstrap, _BATCH_SIZE):
        end = min(begin + _BATCH_SIZE, bootstrap)
        draw = rng.integers(0, len(readers), size=(end - begin, len(readers)))
        replicates[begin:end] = sums[draw].sum(axis=1) / counts[draw].sum(axis=1)
    low, high = np.quantile(replicates, [0.025, 0.975])
    return {
        "n_utterances": len(names), "n_readers": len(readers),
        "estimate": float(sums.sum() / counts.sum()),
        "ci_lo": float(low), "ci_hi": float(high),
        "bootstrap": bootstrap, "seed": seed,
    }


def paired_cluster_interval(
    condition: dict[str, float], baseline: dict[str, float],
    bootstrap: int = DEFAULT_BOOTSTRAP, seed: int = DEFAULT_SEED,
) -> dict:
    """Condition minus baseline on exactly the same utterances.

    No intersection is taken silently: different exclusions change the
    population and need a separate design rather than a guessed alignment.
    """
    if condition.keys() != baseline.keys():
        raise ValueError("condition and baseline must contain exactly the same utterances")
    names = sorted(baseline)
    delta = [condition[name] - baseline[name] for name in names]
    return cluster_interval(names, delta, bootstrap, seed)


def _source(path: Path) -> dict:
    resolved = path.resolve()
    root = Path(__file__).resolve().parents[1]
    try:
        name = resolved.relative_to(root).as_posix()
    except ValueError:
        name = path.as_posix()
    # CSV line endings follow the checkout; normalise them so the same
    # input has the same digest on Windows and Linux.
    canonical = path.read_bytes().replace(b"\r\n", b"\n")
    return {"path": name, "sha256": hashlib.sha256(canonical).hexdigest(),
            "hash_normalisation": "CRLF to LF"}


def main(argv: list[str] | None = None) -> int:
    """Write a separate sensitivity report, with hashed inputs and settings."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--condition", type=Path, nargs="+", default=[])
    parser.add_argument("--bootstrap", type=int, default=DEFAULT_BOOTSTRAP)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.condition and args.baseline is None:
        parser.error("--condition requires --baseline")
    inputs = [args.report, *args.condition]
    if args.baseline is not None:
        inputs.append(args.baseline)
    if args.output.resolve() in {path.resolve() for path in inputs}:
        parser.error("--output must not replace an input report")
    if len(set(args.condition)) != len(args.condition):
        parser.error("--condition contains duplicate report paths")
    try:
        report = read_librispeech_report(args.report)
        names = sorted(report)
        level = cluster_interval(names, [report[n] for n in names], args.bootstrap, args.seed)
        comparisons = []
        if args.baseline is not None:
            baseline = read_librispeech_report(args.baseline)
            for path in args.condition:
                interval = paired_cluster_interval(
                    read_librispeech_report(path), baseline, args.bootstrap, args.seed,
                )
                comparisons.append({"condition": _source(path),
                                    "baseline": _source(args.baseline), **interval})
        result = {
            "schema_version": 1, "resampling_unit": "LibriSpeech reader",
            "estimand": "mean per-utterance WER; paired deltas are condition minus baseline",
            "interval": "95% percentile; whole readers sampled with replacement",
            "limits": "Exploratory sampling sensitivity within the observed reader population; "
                      "no corpus-selection or reference-error uncertainty is estimated.",
            "macro_wer": {"source": _source(args.report), **level},
            "paired_deltas": comparisons,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                               encoding="utf-8")
    except (OSError, ValueError) as exc:
        parser.exit(2, f"{exc}\n")
    print(f"Wrote reader-cluster sensitivity to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
