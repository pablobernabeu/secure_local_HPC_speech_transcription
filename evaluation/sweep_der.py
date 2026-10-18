#!/usr/bin/env python3
"""
Sweep diarisation hyperparameters over a grid and report every cell.

The point of a sweep, as opposed to trying a value and keeping it, is
that the shape of the response matters.  A DER minimum sitting on a sharp
spike is a property of the development set rather than of the model, and
only the neighbouring cells reveal which of the two one is looking at.
Every cell is therefore written out, not just the winner.

The pipeline and the reconstructed corpus are loaded once and reused
across the whole grid, so the cost is one diarisation pass per
(configuration, meeting) rather than a fresh model download per meeting.

Tuning belongs on the AMI development split.  Choosing a configuration on
the test split and then reporting that split's DER would report the best
of *n* draws as if it were a single measurement.

Usage::

    python -m evaluation.sweep_der \\
        --split validation --cache-dir "$DATA/ami_cache" \\
        --clustering-threshold 0.55 0.60 0.65 0.70 0.75 0.80 \\
        --output-dir output/evaluation

The committed sweeps
--------------------
The two sweeps in ``output/evaluation`` are ARC jobs 8976358 and 8976362,
run at 9cb43e3 (``hpc/runs/der_sweep.env`` and ``der_sweep2.env``). Neither
is the default grid of ``hpc/submit_der_sweep.sh``. The equivalent
commands are::

    # der_sweep.csv, der_sweep_summary.csv, der_sweep_selection.json
    # (ARC job 8976358). The defaults cell and five thresholds.
    python -m evaluation.sweep_der --split validation \\
        --cache-dir "$DATA/ami_cache" \\
        --clustering-threshold 0.50 0.60 0.70 0.80 0.90 \\
        --min-cluster-size 12 --min-duration-off 0.0

    # der_sweep2.csv, der_sweep2_summary.csv, der_sweep2_selection.json
    # (ARC job 8976362). The defaults cell and a 3 x 3 grid.
    python -m evaluation.sweep_der --split validation \\
        --cache-dir "$DATA/ami_cache" --output-prefix der_sweep2 \\
        --clustering-threshold 0.65 0.70 0.75 \\
        --min-cluster-size 12 --min-duration-off 0.0 0.25 0.5

Each selection file records the grid, argv, model, pyannote.audio version
and git commit, and each summary the values every cell actually ran with
(``resolved_*``). The August sweeps they replaced, jobs 8534758 and
8534792, predated that record and the output stem; the first also
predated the defaults cell, so it scored the five thresholds alone, which
``--no-default-cell`` repeats.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from evaluation.benchmark_der import (  # noqa: E402
    AUDIO_SIGNAL,
    SAMPLE_RATE,
    _DEFAULT_MODEL,
    _TUNABLE,
    _load_hf_token,
    _partial,
    _require_scored,
    apply_hyperparameters,
    build_corpus,
    diarise,
    exit_without_finalising,
    load_pipeline,
    refuse_cap_in_concat,
)
from evaluation.der_metrics import COLLAR_CONVENTION, DEFAULT_COLLAR_S  # noqa: E402

#: The swept axes, taken from the benchmark's own table so that a knob
#: added there cannot be missing from the sweep's columns or baseline test.
_AXES = list(_TUNABLE)

_SWEEP_FIELDS = [
    "config_id", *_AXES,
    "meeting_id", "duration_s", "n_speakers", "hyp_n_speakers",
    "der", "missed_speech", "false_alarm", "speaker_confusion",
]

_SUMMARY_FIELDS = [
    "config_id", *_AXES,
    "n_meetings", "macro_der", "micro_der",
    "macro_missed", "macro_fa", "macro_confusion",
    "mean_hyp_speakers",
    *(f"resolved_{axis}" for axis in _AXES),
]


def _grid(thresholds, cluster_sizes, durations_off,
          include_default: bool = True) -> list[dict]:
    """Return the Cartesian product of the swept values, in a stable order.

    The pipeline's own defaults are scored first unless the grid already
    contains them. Without that cell the sweep can say which of its
    configurations is best but not whether any of them beats leaving the
    pipeline alone, which is the question the sweep is being run to
    answer.
    """
    # strict: one value per axis. A knob added to _TUNABLE without a
    # matching argument here would otherwise be silently left out.
    cells = [
        dict(zip(_AXES, values, strict=True))
        for values in itertools.product(thresholds, cluster_sizes, durations_off)
    ]
    default = dict.fromkeys(_AXES)
    if include_default and default not in cells:
        cells.insert(0, default)
    return cells


def _describe(config: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in config.items() if v is not None)


def _resolved(record: dict) -> dict:
    """Read the swept values out of an instantiated parameter record."""
    return {name: record[group][key] for name, (group, key) in _TUNABLE.items()}


def _restore_unset(config: dict, defaults: dict, current: dict) -> dict:
    """Make a cell's unset axes mean "the pipeline default".

    ``apply_hyperparameters`` skips ``None`` values, which leaves whatever
    the previous cell set in place. Every axis this cell leaves unset but
    an earlier cell moved away from its default is therefore set back
    explicitly. Axes still at their default are left as ``None``, so a
    grid whose axes are all set or all unset (every grid the command line
    can build) issues exactly the calls it always did.

    Parameters
    ----------
    config:
        The cell, one value or ``None`` per axis.
    defaults, current:
        Swept values of the freshly loaded pipeline and of the pipeline as
        the previous cell left it, as returned by :func:`_resolved`.

    Returns
    -------
    dict
        Overrides to pass to ``apply_hyperparameters``.
    """
    overrides = dict(config)
    for name, value in config.items():
        if value is None and current[name] != defaults[name]:
            overrides[name] = defaults[name]
    return overrides


def _git_commit() -> str | None:
    """Return the checked-out commit, or ``None`` outside a git checkout."""
    from provenance import git_commit

    return git_commit(_ROOT)[0]


def _pyannote_version() -> str | None:
    try:
        import pyannote.audio as _pa
        return _pa.__version__
    except Exception:  # noqa: BLE001 - provenance only
        return None


def run_sweep(
    output_dir: Path,
    split: str = "validation",
    mix_mode: str = "timeline",
    cache_dir: Path | None = None,
    limit_meetings: int | None = None,
    max_minutes: float | None = None,
    model_id: str = _DEFAULT_MODEL,
    collar: float = DEFAULT_COLLAR_S,
    thresholds=(None,),
    cluster_sizes=(None,),
    durations_off=(None,),
    include_default: bool = True,
    output_prefix: str = "der_sweep",
) -> list[dict]:
    """Score every grid cell and write per-meeting and per-cell reports.

    Parameters
    ----------
    output_dir:
        Directory for the three output files.
    split, mix_mode, cache_dir, limit_meetings, max_minutes:
        Passed to :func:`evaluation.benchmark_der.build_corpus`. Concat
        mode uses the benchmark's default utterance cap and refuses
        *max_minutes*, which does not bound concat-mode meetings.
    model_id:
        Diarisation pipeline to load.
    collar:
        Scoring collar in seconds, the total width centred on each
        reference boundary (pyannote.metrics), so 0.25 leaves ±0.125 s
        unscored; see :mod:`evaluation.der_metrics`.
    thresholds, cluster_sizes, durations_off:
        Values to try per axis; ``(None,)`` keeps the pipeline default.
    include_default:
        Score the all-defaults cell first (see :func:`_grid`).
    output_prefix:
        Stem of the output files (``der_sweep`` by default).

    Returns
    -------
    list of dict
        One summary row per cell, as written to ``<prefix>_summary.csv``.

    Side effects
    ------------
    Reads the HF token, loads the corpus into memory and the pipeline
    onto the GPU when present. Writes ``<prefix>.csv`` (per meeting and
    cell), ``<prefix>_summary.csv`` (per cell) and
    ``<prefix>_selection.json`` (best cell, baseline and run record)
    under ``.partial`` names, replacing the three files together once the
    grid is finished.

    Raises
    ------
    SystemExit
        On a bad prefix, an empty corpus, a cache mismatch or a parameter
        that does not take effect.
    """
    if not output_prefix or Path(output_prefix).name != output_prefix:
        raise SystemExit(f"--output-prefix must be a bare file-name stem, "
                         f"got {output_prefix!r}")
    # Before any output directory or download, so that a cap concat mode
    # would ignore is refused, not recorded in the selection file.
    refuse_cap_in_concat(mix_mode, max_minutes)
    from evaluation.der_metrics import (
        aggregate_der, annotation_from_segments, compute_der)

    output_dir.mkdir(parents=True, exist_ok=True)
    hf_token = _load_hf_token()

    print("Loading corpus...", flush=True)
    corpus = list(build_corpus(
        split=split, mix_mode=mix_mode, limit_meetings=limit_meetings,
        max_minutes=max_minutes, cache_dir=cache_dir, hf_token=hf_token))
    corpus = [m for m in corpus if m[2]]
    # An empty corpus would give every cell a macro DER of 0.0 and make
    # an arbitrary one the "best" configuration.
    _require_scored(len(corpus), "meeting")
    audio_hours = sum(s["duration_s"] for _, _, _, s in corpus) / 3600
    print(f"  {len(corpus)} meetings, {audio_hours:.2f} h of audio", flush=True)

    configs = _grid(thresholds, cluster_sizes, durations_off, include_default)
    print(f"  {len(configs)} configurations "
          f"→ {len(configs) * audio_hours:.1f} h of audio to diarise", flush=True)

    pipe = load_pipeline(model_id, hf_token)
    # The pipeline's own values, read once before any cell changes them:
    # what "defaults" means for every later cell, and for the record.
    defaults_record = apply_hyperparameters(pipe)
    defaults = _resolved(defaults_record)
    current = dict(defaults)

    sweep_path = output_dir / f"{output_prefix}.csv"
    summary_path = output_dir / f"{output_prefix}_summary.csv"
    selection_path = output_dir / f"{output_prefix}_selection.json"
    # Written under .partial names and moved into place together once the
    # whole grid is scored, so an interrupted sweep cannot leave a partial
    # grid beside the previous sweep's selection.
    outputs = [(_partial(p), p) for p in (sweep_path, summary_path, selection_path)]
    summaries: list[dict] = []

    with outputs[0][0].open("w", newline="", encoding="utf-8") as detail_fh, \
            outputs[1][0].open("w", newline="", encoding="utf-8") as summary_fh:
        detail = csv.DictWriter(detail_fh, fieldnames=_SWEEP_FIELDS)
        detail.writeheader()
        summary_writer = csv.DictWriter(summary_fh, fieldnames=_SUMMARY_FIELDS)
        summary_writer.writeheader()

        for index, config in enumerate(configs):
            config_id = f"cfg{index:03d}"
            print(f"\n[{index + 1}/{len(configs)}] {config_id}: "
                  f"{_describe(config) or 'pipeline defaults'}", flush=True)
            applied = apply_hyperparameters(
                pipe, **_restore_unset(config, defaults, current))
            current = _resolved(applied)

            results, hyp_speakers = [], []
            for mid, audio, reference, stats in corpus:
                hypothesis = diarise(pipe, audio, SAMPLE_RATE)
                result = compute_der(
                    annotation_from_segments(reference, uri=mid),
                    annotation_from_segments(hypothesis, uri=mid),
                    collar=collar)
                results.append(result)
                n_hyp = len({s["speaker"] for s in hypothesis})
                hyp_speakers.append(n_hyp)
                row = dict(config)
                row.update({
                    "config_id": config_id, "meeting_id": mid,
                    "duration_s": stats["duration_s"],
                    "n_speakers": stats["n_speakers"], "hyp_n_speakers": n_hyp,
                    "der": round(result["der"], 6),
                    "missed_speech": round(result["missed_speech"], 6),
                    "false_alarm": round(result["false_alarm"], 6),
                    "speaker_confusion": round(result["speaker_confusion"], 6),
                })
                detail.writerow(row)
                detail_fh.flush()

            aggregate = aggregate_der(results)
            summary = dict(config)
            summary.update({
                "config_id": config_id,
                "n_meetings": aggregate["n_meetings"],
                "macro_der": round(aggregate["macro_der"], 6),
                "micro_der": round(aggregate["micro_der"], 6),
                "macro_missed": round(aggregate["macro_missed"], 6),
                "macro_fa": round(aggregate["macro_fa"], 6),
                "macro_confusion": round(aggregate["macro_confusion"], 6),
                "mean_hyp_speakers": round(
                    sum(hyp_speakers) / len(hyp_speakers), 2) if hyp_speakers else 0,
            })
            # The values the pipeline actually ran with, so a blank axis
            # column (the default) can be read without the job log.
            summary.update({f"resolved_{k}": v for k, v in current.items()})
            summaries.append(summary)
            summary_writer.writerow(summary)
            summary_fh.flush()
            print(f"    macro DER {summary['macro_der']:.4f}  "
                  f"micro {summary['micro_der']:.4f}  "
                  f"(miss {summary['macro_missed']:.3f}, "
                  f"FA {summary['macro_fa']:.3f}, "
                  f"conf {summary['macro_confusion']:.3f})", flush=True)

    if summaries:
        best = min(summaries, key=lambda s: s["macro_der"])
        baseline = next((s for s in summaries
                         if all(s[k] is None for k in _AXES)), None)
        selection = {
            "split": split, "mix_mode": mix_mode, "collar_s": collar,
            "collar_convention": COLLAR_CONVENTION,
            "audio_signal": AUDIO_SIGNAL,
            "n_configurations": len(summaries),
            "criterion": "macro_der",
            "best": best,
            "baseline_in_grid": baseline,
            # Enough to rerun this exact grid without the job log.
            "model": model_id,
            "pyannote_audio_version": _pyannote_version(),
            "pipeline_defaults": defaults_record,
            "grid": {"clustering_threshold": list(thresholds),
                     "min_cluster_size": list(cluster_sizes),
                     "min_duration_off": list(durations_off),
                     "include_default": include_default},
            "max_minutes": max_minutes,
            "limit_meetings": limit_meetings,
            "argv": sys.argv[1:],
            "git_commit": _git_commit(),
        }
        outputs[2][0].write_text(json.dumps(selection, indent=2), encoding="utf-8")
        for partial, final in outputs:
            os.replace(partial, final)
        print(f"\nBest on {split}: {best['config_id']}  "
              f"macro DER {best['macro_der']:.4f}  "
              f"({_describe({k: best[k] for k in _AXES})})")
        print("Selected on the development split only.  Score it on test "
              "before reporting it.")

    print(f"\nPer-meeting: {sweep_path}")
    print(f"Per-cell:    {summary_path}")
    return summaries


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Sweep pyannote diarisation hyperparameters on AMI.")
    p.add_argument("--output-dir", type=Path,
                   default=_ROOT / "output" / "evaluation")
    p.add_argument("--split", default="validation",
                   choices=["train", "validation", "test"],
                   help="tune on validation (default: %(default)s)")
    p.add_argument("--mix-mode", default="timeline",
                   choices=["timeline", "concat"])
    p.add_argument("--cache-dir", type=Path, default=None)
    p.add_argument("--limit-meetings", type=int, default=None)
    p.add_argument("--max-minutes", type=float, default=None)
    p.add_argument("--model", dest="model_id", default=_DEFAULT_MODEL)
    p.add_argument("--collar", type=float, default=DEFAULT_COLLAR_S,
                   help="total collar width in seconds, centred on each "
                        "reference boundary (pyannote.metrics), so 0.25 "
                        "leaves 0.125 s either side unscored "
                        "(default: %(default)s)")
    p.add_argument("--clustering-threshold", type=float, nargs="+",
                   default=[None], metavar="T",
                   help="values to try (default: the pipeline default alone)")
    p.add_argument("--min-cluster-size", type=int, nargs="+", default=[None],
                   metavar="N")
    p.add_argument("--min-duration-off", type=float, nargs="+", default=[None],
                   metavar="S")
    p.add_argument("--no-default-cell", dest="include_default",
                   action="store_false",
                   help="skip the pipeline-defaults cell.  It is scored first "
                        "by default, because without it the sweep cannot say "
                        "whether tuning beats leaving the pipeline alone.")
    p.add_argument("--output-prefix", default="der_sweep", metavar="STEM",
                   help="stem of the three output files, <STEM>.csv, "
                        "<STEM>_summary.csv and <STEM>_selection.json, so a "
                        "second sweep need not be renamed by hand "
                        "(default: %(default)s)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    run_sweep(
        output_dir=args.output_dir, split=args.split, mix_mode=args.mix_mode,
        cache_dir=args.cache_dir, limit_meetings=args.limit_meetings,
        max_minutes=args.max_minutes, model_id=args.model_id,
        collar=args.collar,
        thresholds=args.clustering_threshold,
        cluster_sizes=args.min_cluster_size,
        durations_off=args.min_duration_off,
        include_default=args.include_default,
        output_prefix=args.output_prefix,
    )
    return 0


if __name__ == "__main__":
    try:
        _status = main()
    except SystemExit as _exc:
        if _exc.code not in (0, None):
            print(f"error: {_exc}", file=sys.stderr)
        _status = _exc.code if isinstance(_exc.code, int) else 1
    exit_without_finalising(_status or 0)
