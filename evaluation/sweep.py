#!/usr/bin/env python3
"""
Full cross-suite × cross-condition WER benchmark sweep.

Runs the primary LibriSpeech test-clean corpus and all registered challenge
suites for a single ASR model, scoring all selected post-processing
conditions in a single audio pass per suite.  Conditions are defined in
:mod:`evaluation.conditions`; suites are defined in
:mod:`evaluation.challenge_suites`.

The suite named ``librispeech_clean`` is a synthetic entry that maps to
the canonical LibriSpeech ``test-clean`` split.  It is not in the
``challenge_suites`` registry because it is the primary benchmark corpus
rather than a supplementary challenge suite.

Output paths name the suite and the model for every cell:

* The first condition of a (suite, model) cell writes
  ``wer_report_{suite}_{slug}.csv`` / ``wer_summary_{suite}_{slug}.json``
  (the primary LibriSpeech suite uses ``librispeech`` in place of the
  suite name, as it always has).
* Each subsequent condition appends ``_{condition}`` to those stems.

The canonical cell (``openai/whisper-large-v3`` on ``librispeech_clean``)
used to write the unqualified ``wer_report.csv`` / ``wer_summary.json``,
the names ``evaluation.benchmark_wer`` and ``evaluation.wer`` also wrote
by default, so one run could silently overwrite another's headline file
(audit finding EWER-11). ``benchmark_wer`` now requires its output paths
and ``evaluation.wer`` defaults to ``*_transcripts`` names. Those names are now written only with
``--legacy-primary-paths``.

Usage::

    # Full sweep, all suites, all conditions, default model
    python -m evaluation.sweep

    # Single suite by index (used by the SLURM array)
    python -m evaluation.sweep --suite-index 2

    # Explicit customisation
    python -m evaluation.sweep \\
        --model      openai/whisper-large-v3 \\
        --suites     librispeech_clean,fleurs,ami \\
        --conditions raw,whisper_norm \\
        --output-dir output/evaluation \\
        --limit      500 \\
        --seed       42

    # List available suites and their array indices
    python -m evaluation.sweep --list-suites
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_MODEL      = "openai/whisper-large-v3"
_DEFAULT_OUTPUT_DIR = Path("output/evaluation")
_DEFAULT_SEED       = 42

# The default condition list is evaluation.conditions.default_sweep_conditions(),
# which reads the production stages from transcription.CLEAN_TEXT_STAGES.
# A hand-typed copy here once omitted pronoun_i_fix, so the post-fix grid
# (53378ba, aa6e61d) has no pronoun_i_fix cells although the stage existed
# (audit finding EWER-13).

# SLURM array order of the suites.  Index 0 is the primary corpus and the
# rest follow the challenge registry's alphabetical order as it stood when
# the committed grid ran.  Frozen here so that registering a new suite
# appends it at the end instead of shifting the index of an existing one;
# an index that silently changed corpus would re-decode the wrong suite on
# resubmission.
_SUITE_ARRAY_ORDER = (
    "librispeech_clean",
    "ami",
    "fleurs",
    "librispeech_other",
    "voxpopuli_accented",
)


# ---------------------------------------------------------------------------
# Suite specification
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _SuiteSpec:
    """Uniform representation of one corpus within the sweep.

    ``dataset``, ``config``, ``split``, ``ref_field`` and ``uid_field``
    mirror the corresponding fields of
    :class:`evaluation.challenge_suites.Suite`.  ``name`` is the URL-safe
    slug used in output file-name stems.  ``is_primary`` marks the one
    synthetic suite that maps to the canonical LibriSpeech test-clean
    corpus; its output stems say ``librispeech`` rather than the suite
    name, and only it can write the legacy unqualified paths (see
    :func:`_primary_paths`).
    """

    name:       str
    dataset:    str
    config:     str
    split:      str
    ref_field:  str | None
    uid_field:  str | None
    is_primary: bool = False


_LIBRISPEECH_CLEAN_SPEC = _SuiteSpec(
    name="librispeech_clean",
    dataset="librispeech_asr",
    config="clean",
    split="test",
    ref_field="text",
    uid_field="id",
    is_primary=True,
)


def _all_suite_specs() -> list[_SuiteSpec]:
    """Return all suite specs in canonical sweep order.

    The order is :data:`_SUITE_ARRAY_ORDER` (``librispeech_clean`` at index
    0, then ``ami``, ``fleurs``, ``librispeech_other`` and
    ``voxpopuli_accented``), followed by any suite registered since, in
    alphabetical order.  Existing SLURM array indices therefore never move
    when a suite is added.
    """
    from evaluation.challenge_suites import list_suites  # noqa: PLC0415
    by_name: dict[str, _SuiteSpec] = {
        _LIBRISPEECH_CLEAN_SPEC.name: _LIBRISPEECH_CLEAN_SPEC,
    }
    for s in list_suites():
        by_name[s.name] = _SuiteSpec(
            name=s.name,
            dataset=s.dataset,
            config=s.config,
            split=s.split,
            ref_field=s.ref_field,
            uid_field=s.uid_field,
            is_primary=False,
        )
    ordered = [by_name.pop(n) for n in _SUITE_ARRAY_ORDER if n in by_name]
    return ordered + [by_name[n] for n in sorted(by_name)]


def _resolve_suites(names: list[str]) -> list[_SuiteSpec]:
    """Return the :class:`_SuiteSpec` objects for the given *names*.

    Raises :class:`KeyError` if a name is not recognised.
    """
    all_specs = {s.name: s for s in _all_suite_specs()}
    specs: list[_SuiteSpec] = []
    for name in names:
        if name not in all_specs:
            available = ", ".join(sorted(all_specs))
            raise KeyError(
                f"Unknown suite {name!r}.  Available suites: {available}"
            )
        specs.append(all_specs[name])
    return specs


# ---------------------------------------------------------------------------
# Path derivation
# ---------------------------------------------------------------------------

def model_slug(model_id: str) -> str:
    """Derive a filesystem-safe slug from a HuggingFace model identifier.

    The single definition of the slug: output file names here and the
    ``model_slug`` column of :mod:`evaluation.sweep_aggregate` both use it.

    Examples::

        model_slug("openai/whisper-large-v3")        == "whisper-large-v3"
        model_slug("distil-whisper/distil-large-v3") == "distil-large-v3"
        model_slug("openai/whisper-medium")           == "whisper-medium"
    """
    return model_id.rsplit("/", 1)[-1].lower()


# Retained name for existing callers.
_model_slug = model_slug


def _primary_paths(
    spec:       _SuiteSpec,
    model_id:   str,
    output_dir: Path,
    legacy_primary_paths: bool = False,
) -> tuple[Path, Path]:
    """Return ``(report_csv, summary_json)`` primary paths for *spec* / *model_id*.

    Every (suite, model) cell receives stems that encode both the suite
    and the model slug.  With *legacy_primary_paths*, the default model
    (``openai/whisper-large-v3``) on the primary suite instead gets the
    unqualified ``wer_report.csv`` / ``wer_summary.json`` that the sweep
    wrote before audit finding EWER-11.  Those are the names of the
    manuscript's headline files, so a run into ``output/evaluation`` with
    the opt-in replaces them; it exists only to reproduce an older
    directory layout.
    """
    if legacy_primary_paths and spec.is_primary and model_id == _DEFAULT_MODEL:
        return (
            output_dir / "wer_report.csv",
            output_dir / "wer_summary.json",
        )
    slug = _model_slug(model_id)
    if spec.is_primary:
        report  = output_dir / f"wer_report_librispeech_{slug}.csv"
        summary = output_dir / f"wer_summary_librispeech_{slug}.json"
    else:
        report  = output_dir / f"wer_report_{spec.name}_{slug}.csv"
        summary = output_dir / f"wer_summary_{spec.name}_{slug}.json"
    return report, summary


def _condition_paths(
    primary_report:  Path,
    primary_summary: Path,
    condition_name:  str,
    is_first:        bool,
) -> tuple[Path, Path]:
    """Return ``(report_csv, summary_json)`` for *condition_name*.

    The first condition uses the primary paths unchanged; subsequent
    conditions append ``_{condition_name}`` to the file stem.  This
    reproduces :func:`evaluation.benchmark_wer._derive_condition_paths`;
    it is kept local because this module must import without the audio
    stack (tests substitute a stub for benchmark_wer), and
    tests/test_audit_eval_sweep.py checks that the two agree.
    """
    if is_first:
        return primary_report, primary_summary
    report = primary_report.with_name(
        f"{primary_report.stem}_{condition_name}{primary_report.suffix}"
    )
    summary = primary_summary.with_name(
        f"{primary_summary.stem}_{condition_name}{primary_summary.suffix}"
    )
    return report, summary


# ---------------------------------------------------------------------------
# Core sweep function
# ---------------------------------------------------------------------------

def run_suite(
    spec:       _SuiteSpec,
    model_id:   str,
    conditions: list[str],
    output_dir: Path,
    limit:      int | None = None,
    seed:       int        = _DEFAULT_SEED,
    dump_hypotheses: bool  = False,
    legacy_primary_paths: bool = False,
) -> None:
    """Score *conditions* against *spec* for *model_id* and write outputs.

    Delegates to :func:`evaluation.benchmark_wer.run_benchmark`.  The audio
    is iterated once and every condition is scored in memory on the same
    hypotheses, so adding conditions to the list costs no extra audio
    passes.  *legacy_primary_paths* is passed to :func:`_primary_paths`.

    With *dump_hypotheses*, the raw and transformed text of every
    (utterance, condition) pair is written beside the reports. That makes
    the expensive half of this job reusable: the decode is what needs a
    GPU, and a condition is a pure function of the text it produces, so a
    stage can be changed and every condition rescored on a processor
    afterwards. Off by default, because the dump holds transcript text
    and so carries whatever the recording carried.

    Side effects: creates *output_dir*; writes (overwriting) one report
    CSV and summary JSON per condition, plus the dump when asked for; and,
    through :func:`evaluation.benchmark_wer.run_benchmark`, sets
    ``CUBLAS_WORKSPACE_CONFIG`` and reseeds the global RNGs. Raises
    ``SystemExit`` if any condition scored no utterance.
    """
    from evaluation.benchmark_wer import run_benchmark, _ConditionRun  # noqa: PLC0415

    output_dir.mkdir(parents=True, exist_ok=True)
    report_primary, summary_primary = _primary_paths(
        spec, model_id, output_dir, legacy_primary_paths)

    runs: list[_ConditionRun] = []
    for i, name in enumerate(conditions):
        r, s = _condition_paths(report_primary, summary_primary, name, is_first=(i == 0))
        runs.append(_ConditionRun(condition_name=name, report_path=r, summary_path=s))

    print(
        f"\n{'═' * 60}\n"
        f"  Suite:  {spec.name}\n"
        f"  Model:  {model_id}\n"
        f"{'═' * 60}",
        flush=True,
    )

    run_benchmark(
        dataset_name=spec.dataset,
        config=spec.config,
        split=spec.split,
        model_id=model_id,
        limit=limit,
        runs=runs,
        ref_field=spec.ref_field,
        uid_field=spec.uid_field,
        seed=seed,
        # The model slug belongs in this name for the same reason it is in
        # the report names: three models write into one directory, and a
        # dump keyed on the suite alone means the last model to finish
        # silently overwrites the others. That happened once, and cost the
        # Large v3 text on all five suites.
        dump_hypotheses=(
            report_primary.with_name(
                f"wer_hypotheses_{spec.name}_{_model_slug(model_id)}.csv")
            if dump_hypotheses else None
        ),
    )


def run_sweep(
    specs:      list[_SuiteSpec],
    model_id:   str,
    conditions: list[str] | None,
    output_dir: Path,
    limit:      int | None = None,
    seed:       int        = _DEFAULT_SEED,
    dump_hypotheses: bool  = False,
    legacy_primary_paths: bool = False,
) -> None:
    """Run the full sweep across *specs* for *model_id*.

    When *conditions* is ``None``, every suite receives the same default
    list, :func:`evaluation.conditions.default_sweep_conditions` (every
    registered condition, ``raw`` first).  Unknown condition names raise
    :class:`ValueError` before any suite runs.

    Side effects are those of :func:`run_suite`, once per suite: the
    output directory is created and every report, summary and optional
    dump is written, and the global RNGs are reseeded.
    """
    from evaluation.conditions import (  # noqa: PLC0415
        default_sweep_conditions,
        list_conditions,
    )

    all_condition_names = [c.name for c in list_conditions()]
    suite_conditions = (list(conditions) if conditions is not None
                        else list(default_sweep_conditions()))

    # Validate all condition names before any suite runs.
    unknown = [c for c in suite_conditions if c not in all_condition_names]
    if unknown:
        raise ValueError(
            f"Unknown condition(s): {', '.join(unknown)}.  "
            f"Available: {', '.join(all_condition_names)}"
        )

    for spec in specs:
        run_suite(
            spec=spec,
            model_id=model_id,
            conditions=suite_conditions,
            output_dir=output_dir,
            limit=limit,
            seed=seed,
            dump_hypotheses=dump_hypotheses,
            legacy_primary_paths=legacy_primary_paths,
        )


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def _parse_csv_names(raw: str | None) -> list[str]:
    """Parse a comma-separated list of names, de-duplicated in first-seen order.

    Mirrors :func:`evaluation.benchmark_wer._parse_conditions_arg`, which
    is not imported so that this module stays importable without the
    audio stack; tests/test_audit_eval_sweep.py checks the two agree.
    """
    if not raw:
        return []
    seen: list[str] = []
    for tok in raw.split(","):
        name = tok.strip()
        if name and name not in seen:
            seen.append(name)
    return seen


# Conditions and suites are parsed identically.
_parse_conditions_arg = _parse_csv_names
_parse_suites_arg = _parse_csv_names


def _build_parser() -> argparse.ArgumentParser:
    all_specs = _all_suite_specs()
    default_suites = ",".join(s.name for s in all_specs)

    p = argparse.ArgumentParser(
        prog="evaluation.sweep",
        description=(
            "Run a full cross-suite × cross-condition WER benchmark sweep "
            "for a single ASR model."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--model", default=_DEFAULT_MODEL,
        help="HuggingFace model identifier  (default: %(default)s).",
    )
    p.add_argument(
        "--suites", default=None, metavar="LIST",
        help=(
            f"Comma-separated suite names to run  "
            f"(default: all — {default_suites}).  "
            f"Use --list-suites to see available names and SLURM array indices."
        ),
    )
    p.add_argument(
        "--suite-index", type=int, default=None, dest="suite_index",
        metavar="N",
        help=(
            "Run a single suite identified by its 0-based index in the "
            "canonical suite list.  Intended for SLURM array dispatch: "
            "set --array=0-N in the job script and pass "
            "$SLURM_ARRAY_TASK_ID as this argument.  Mutually exclusive "
            "with --suites."
        ),
    )
    p.add_argument(
        "--conditions", default=None, metavar="LIST",
        help=(
            "Comma-separated post-processing conditions to score "
            "(default: every registered condition, raw first, the same "
            "list for every suite).  Use --list-conditions to see "
            "available names."
        ),
    )
    p.add_argument(
        "--legacy-primary-paths", action="store_true",
        dest="legacy_primary_paths",
        help=(
            "Write the default model's LibriSpeech test-clean cell to the "
            "unqualified wer_report.csv / wer_summary.json, as sweeps did "
            "before, instead of wer_report_librispeech_<model>.csv.  Those "
            "are the names of the manuscript's headline files, so a run "
            "into output/evaluation replaces them; use only to reproduce "
            "the older layout."
        ),
    )
    p.add_argument(
        "--output-dir", type=Path, default=_DEFAULT_OUTPUT_DIR, dest="output_dir",
        metavar="DIR",
        help="Directory for all output CSVs and JSON summaries  (default: %(default)s).",
    )
    p.add_argument(
        "--limit", type=int, default=None,
        help="Maximum utterances to score per suite (omit for the full split).",
    )
    p.add_argument(
        "--seed", type=int, default=_DEFAULT_SEED,
        help="Random seed passed to benchmark_wer  (default: %(default)s).",
    )
    p.add_argument(
        "--dump-hypotheses", action="store_true", dest="dump_hypotheses",
        help=(
            "Also write the reference and the raw and transformed hypothesis "
            "of every (utterance, condition) pair to "
            "wer_hypotheses_<suite>_<model>.csv.  This makes the decode "
            "reusable: a "
            "condition is a pure function of the text, so any stage can be "
            "changed and rescored without a GPU.  Off by default because "
            "the dump holds transcript text."
        ),
    )
    p.add_argument(
        "--list-suites", action="store_true", dest="list_suites",
        help="Print all available suite names with their SLURM array indices, then exit.",
    )
    p.add_argument(
        "--list-conditions", action="store_true", dest="list_conditions",
        help="Print all available condition names, then exit.",
    )
    return p


def main(argv: list[str] | None = None) -> bool:
    """Run the command-line interface.

    Returns
    -------
    bool
        ``True`` when suites were run (and an ASR pipeline was built),
        ``False`` for the listing flags. The ``__main__`` block uses it to
        decide whether the hard exit below is needed.

    Raises
    ------
    SystemExit
        For conflicting or out-of-range suite selections, and from
        :func:`run_sweep` when a condition scored nothing.
    """
    args = _build_parser().parse_args(argv)

    all_specs = _all_suite_specs()

    if args.list_suites:
        print(f"  {'Index':<6}  {'Suite':<30}  {'Dataset / config / split'}")
        print("  " + "─" * 80)
        for i, s in enumerate(all_specs):
            corpus = f"{s.dataset}  {s.config}/{s.split}"
            print(f"  {i:<6}  {s.name:<30}  {corpus}")
        return False

    if args.list_conditions:
        from evaluation.benchmark_wer import _print_conditions  # noqa: PLC0415
        _print_conditions()
        return False

    # Resolve which suites to run.
    if args.suite_index is not None and args.suites is not None:
        raise SystemExit("--suite-index and --suites are mutually exclusive.")

    if args.suite_index is not None:
        if not (0 <= args.suite_index < len(all_specs)):
            raise SystemExit(
                f"--suite-index {args.suite_index} is out of range; "
                f"valid range is 0 to {len(all_specs) - 1}."
            )
        specs_to_run = [all_specs[args.suite_index]]
    elif args.suites is not None:
        suite_names = _parse_suites_arg(args.suites)
        specs_to_run = _resolve_suites(suite_names)
    else:
        specs_to_run = list(all_specs)

    # Resolve conditions (None selects default_sweep_conditions()).
    conditions = _parse_conditions_arg(args.conditions) or None

    run_sweep(
        specs=specs_to_run,
        model_id=args.model,
        conditions=conditions,
        output_dir=args.output_dir,
        limit=args.limit,
        seed=args.seed,
        dump_hypotheses=args.dump_hypotheses,
        legacy_primary_paths=args.legacy_primary_paths,
    )
    return True


if __name__ == "__main__":
    if not main():
        # Nothing was decoded, so there are no pipeline threads to race.
        raise SystemExit(0)
    # Leave without running interpreter finalisation.
    #
    # The work is complete and on disk by this point: every report and
    # summary is written and closed inside run_benchmark, and the
    # hypothesis dump is flushed row by row and closed there too. What
    # remains is teardown, and teardown is where this job kept dying.
    # Finalising the interpreter while the transformers pipeline's worker
    # threads are still alive raises "PyGILState_Release: thread state
    # must be current when releasing" and aborts with a core dump, which
    # Slurm records as a failed task. It struck three of five array tasks
    # in one pre-flight and left two untouched, so it is a race rather
    # than a fault in any suite.
    #
    # A task that has written all of its output should not be reported as
    # failed, both because it is misleading and because an --afterok
    # dependency on the aggregation step would not fire. Flushing the
    # streams and exiting hard makes the outcome deterministic.
    #
    # Provenance and removal. Added in 25068a8 after the abort struck ARC
    # array tasks; no upstream transformers or PyTorch issue was recorded,
    # and the versions installed on ARC at the time were not committed (an
    # audit read transformers 4.56.2 from an uncommitted pip freeze).
    # Remove this block once a sweep on a newer transformers/torch pair
    # finishes all array tasks without the abort when exiting normally.
    #
    # What it costs: os._exit skips atexit handlers and does not flush file
    # objects other than stdout and stderr. Every output is closed inside
    # run_benchmark today; a writer left open at this point would lose its
    # tail. A failed run never reaches this line, because run_benchmark
    # raises SystemExit, so failures still exit non-zero.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
