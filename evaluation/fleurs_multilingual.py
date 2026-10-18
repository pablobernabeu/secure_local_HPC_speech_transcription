#!/usr/bin/env python3
"""
Assemble the multilingual FLEURS summary from its per-language summaries.

``output/evaluation/fleurs_multilingual_summary.json`` compares the
production composite (``pipeline_full``) with the raw hypothesis on six
non-English FLEURS test splits, scored with Whisper Large v3 in four
passes ("arms") over the same audio: before the Unicode-strip fix, after
it, after the English-only clean-text stages were gated on language, and
the re-run of the repaired code after the September 2026 audit. The
manuscript's multilingual section reads its ratios. The file used to be
assembled by hand from the arms' summaries (audit finding OUTPUTS-11);
this module builds it from them, so the ratios can be regenerated and
checked.

Inputs
------
One directory per arm, each holding what
``hpc/submit_benchmark_wer_multilingual.sh`` writes per language: a
summary of the ``raw`` condition, run first, and one of
``pipeline_full``. The first three arms were written as
``wer_summary_fleurs_<config>.json`` and
``wer_summary_fleurs_<config>_pipeline_full.json``. Since a22a864
(SHELL-13) the script puts the model slug after the configuration
(``wer_summary_fleurs_<config>_<slug>.json``, the slug as
:func:`evaluation.sweep.model_slug` derives it), so that runs of two
models cannot overwrite each other; the fourth arm is named so. Either
layout is read, and a directory holding both, or two slugs, for one
language is refused. The files are, on ARC under
``$DATA/speech_transcription_env/output/evaluation/`` (all 48 read on
2026-10-04):

==================  ==========================  ==========================
Arm                 Directory                   Code, ARC jobs
==================  ==========================  ==========================
``1_before_fix``    ``prefix_baseline/``        9ae40a2, 8166513/8166514
``2_after_fix``     ``afterfix_pregate/``       812552b, 8174224/8174225
``3_after_gate``    the directory itself        c0f58c5, 8245204/8245205
``4_after_audit``   ``audit2026/fleurs_ml/``    6f9bf56, 8917984
==================  ==========================  ==========================

The 48 summaries are not in the repository. The first three arms'
summaries predate run metadata, so their code commits and job ids are
those recorded in commits 812552b, bef0db9 and 8f24032 and in
``.hpc-plan.yaml``, and the GPU each language ran on is the one its job
log names. Every task prints ``nvidia-smi``'s GPU name on the line after
``GPU:``, in ``logs/wer_fleurs_ml_<job>_<task>.out`` of the ARC clone
``~/paper_speech_transcription``; tasks 0 to 5 are fr_fr, de_de, es_419,
it_it, nl_nl and pl_pl, the first three under the first job of each
pair. The fourth arm's summaries record their own code commit and GPU. A
recorded commit must match the arm's in :data:`ARMS`, and a recorded GPU
the one the registry names, if it names one, so a directory cannot be
assembled under the wrong arm.

Output
------
The layout of the committed file: a ``benchmark`` block, and per language
the raw and composite macro WER of each arm (four decimals), the ratio of
composite to raw within each arm (two decimals, computed from the
unrounded rates, so no ratio mixes arms), the utterance count, and
``raw``, the first arm's raw WER (a key the first version of the file
had). The ``design`` sentence is chosen by the arms given (see
:data:`_DESIGNS`), and the ``ratio_definition`` states how far the raw
rate moves across them, computed from the four-decimal rates the file
holds. Rebuilt from the ARC inputs with the same options, carrying the
prose from the committed file, the file comes back unchanged except for
``benchmark.assembled_by``, which records the rebuild's own run.
``--exact`` adds the
unrounded rates and ratios under ``exact``, for statistics such as the
manuscript's rank correlation, which rounding to two decimals can tie.
``--record-inputs`` adds the input files' digests and this run's
metadata.

Two parts of the file are not computed here and are carried over from
``--carry-from`` (by default the output file, if it exists):
``pct_words_with_diacritic`` per language, and the prose ``finding``
block. The first committed diacritic percentages were measured outside
the repository, on "a representative sample" (the manuscript's table
caption); the sample and the method were not recorded. ``--diacritics``
replaces them with the shares :mod:`evaluation.fleurs_diacritics`
measures on the whole test split, and records how (OUTPUTS-11).

Usage::

    python -m evaluation.fleurs_multilingual \\
        --arm 1_before_fix=/path/prefix_baseline \\
        --arm 2_after_fix=/path/afterfix_pregate \\
        --arm 3_after_gate=/path \\
        --arm 4_after_audit=/path/audit2026/fleurs_ml \\
        --diacritics output/evaluation/fleurs_diacritic_shares.json \\
        --exact --record-inputs \\
        --out output/evaluation/fleurs_multilingual_summary.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from evaluation.sweep import model_slug

_DEFAULT_OUT = Path("output/evaluation/fleurs_multilingual_summary.json")

#: The six splits, in the committed file's order.
LANGUAGES = ("pl_pl", "es_419", "fr_fr", "de_de", "it_it", "nl_nl")

#: How the composite's summary name ends; the raw one ends in ".json".
_COMPOSITE = "_pipeline_full.json"

_P100 = "Tesla P100-PCIE-16GB"
_V100 = "Tesla V100-SXM2-32GB"
_RTX8000 = "Quadro RTX 8000"

#: What each arm of the comparison ran. For the first three, the commits
#: and job ids are those recorded in 812552b, bef0db9 and 8f24032 and in
#: .hpc-plan.yaml, and the GPUs those the tasks' job logs name (the module
#: docstring says where); their summaries predate run metadata and record
#: none of it. The fourth arm's summaries record their commit, checked
#: against the one here, and their GPUs, which are taken from them. The
#: GPUs are kept to attribute the raw rate's movement (audit finding
#: EWER-10). Across the first three arms, raw decodes on GPUs of the same
#: architecture agree exactly and those on different architectures
#: disagree on a few utterances. The fourth arm ran on architectures none
#: of the others used, so no pair of arms isolates its GPU. Its packages
#: and its model and dataset commits are the third arm's, and its decoding
#: code differs only by pinning those commits, which leaves the GPU as the
#: only known difference.
ARMS = {
    "1_before_fix": {
        "code": "9ae40a2",
        "arc_jobs": ["8166513", "8166514"],
        "state": "unicode_strip deleted all non-ASCII; no language gate",
        "gpus": {"pl_pl": _V100, "es_419": _V100, "fr_fr": _RTX8000,
                 "de_de": _V100, "it_it": _RTX8000, "nl_nl": _RTX8000},
    },
    "2_after_fix": {
        "code": "812552b",
        "arc_jobs": ["8174224", "8174225"],
        "state": "diacritics preserved (f6e708e); still no language gate",
        "gpus": {"pl_pl": _P100, "es_419": _P100, "fr_fr": _P100,
                 "de_de": "Tesla V100-PCIE-16GB", "it_it": _P100,
                 "nl_nl": _P100},
    },
    "3_after_gate": {
        "code": "c0f58c5",
        "arc_jobs": ["8245204", "8245205"],
        "state": "diacritics preserved AND English-only stages gated",
        "gpus": {"pl_pl": _P100, "es_419": _V100, "fr_fr": _P100,
                 "de_de": _P100, "it_it": _P100, "nl_nl": _P100},
    },
    "4_after_audit": {
        "code": "6f9bf56",
        "arc_jobs": ["8917984"],
        "state": ("English-only stages gated, at the code after the "
                  "September 2026 audit; unicode_strip keeps every script, "
                  "number and currency sign (748ae6b)"),
    },
}

#: The comparison each set of arms makes. The committed three isolate the
#: two defects; the audit's re-run adds a fourth.
_DESIGNS = {
    ("1_before_fix", "2_after_fix", "3_after_gate"):
        "three arms over the same corpus, isolating two defects",
    ("1_before_fix", "2_after_fix", "3_after_gate", "4_after_audit"):
        ("four arms over the same corpus: three isolating two defects, and "
         "a re-run of the repaired code after the September 2026 audit"),
}
_RATIO_DEFINITION = (
    "Each ratio divides the composite's macro WER by the raw macro WER "
    "measured in the same arm, so no ratio mixes arms.")
_COUNT_WORDS = ("zero", "one", "two", "three", "four", "five", "six",
                "seven", "eight", "nine")


def _count(n: int) -> str:
    """A count in words below ten, in digits from ten on."""
    return _COUNT_WORDS[n] if 0 <= n < len(_COUNT_WORDS) else str(n)


def _arm_suffix(arm: str) -> str:
    """``"1_before_fix"`` -> ``"before_fix"``: the arm's key suffix."""
    head, _, rest = arm.partition("_")
    return rest if head.isdigit() and rest else arm


def _load(path: Path) -> dict:
    """Read one benchmark summary.

    Raises
    ------
    SystemExit
        If the file is missing or lacks a ``benchmark`` or ``summary``
        block with ``macro_wer``.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read {path}: {exc}") from exc
    if (not isinstance(payload, dict) or "benchmark" not in payload
            or "macro_wer" not in (payload.get("summary") or {})):
        raise SystemExit(f"{path} is not a benchmark summary with macro_wer")
    return payload


def _summary_stem(directory: Path, config: str) -> tuple[str, str | None]:
    """Find which of the two file layouts *directory* holds for *config*.

    Returns the file stem the two summaries share and the model slug it
    carries (``None`` for the unslugged layout of the first three arms).
    The slugged stem is found from the composite's name, which ends the
    stem with the condition, so the unslugged composite cannot be taken
    for a slug.

    Raises
    ------
    SystemExit
        If the directory holds neither layout for *config*, or more than
        one, since reading one of them would then be a guess.
    """
    stem = f"wer_summary_fleurs_{config}"
    found: dict[str, str | None] = {}
    if any((directory / f"{stem}{end}").is_file()
           for end in (".json", _COMPOSITE)):
        found[stem] = None
    for path in sorted(directory.glob(f"{stem}_*{_COMPOSITE}")):
        slug = path.name[len(stem) + 1:-len(_COMPOSITE)]
        found[f"{stem}_{slug}"] = slug
    if len(found) != 1:
        raise SystemExit(
            f"{directory}: expected the {config} summaries under one name, "
            f"{stem}[_<model slug>].json and ..._pipeline_full.json; found "
            f"{sorted(found) or 'none'}")
    return next(iter(found.items()))


def _cell(directory: Path, config: str) -> dict:
    """Load the raw and composite summaries of one language in one arm.

    Checks that each file records the corpus configuration and condition
    its name says, so a misplaced file cannot be read as another
    language's (the slip a hand assembly could make silently), and that a
    file named with a model slug records that model.
    """
    stem, slug = _summary_stem(directory, config)
    out = {}
    for condition, name in (("raw", f"{stem}.json"),
                            ("pipeline_full", f"{stem}{_COMPOSITE}")):
        path = directory / name
        payload = _load(path)
        bench = payload["benchmark"]
        recorded = (bench.get("config"), bench.get("condition", "raw"))
        if recorded != (config, condition):
            raise SystemExit(f"{path} records {recorded}, not "
                             f"{(config, condition)}")
        if slug is not None and model_slug(str(bench.get("model"))) != slug:
            raise SystemExit(f"{path} is named for {slug} but records the "
                             f"model {bench.get('model')}")
        out[condition] = payload
        out[condition + "_path"] = path
    return out


def _arm_record(arm: str, by_lang: dict, languages) -> dict:
    """The ``benchmark.arms`` entry of *arm*: :data:`ARMS`, checked.

    A summary that records the code commit or the GPU it ran on must
    agree with the registry, so a directory assembled under the wrong arm
    is refused. GPUs a summary records are taken from it; those of the
    first three arms, whose summaries record none, come from the registry.
    """
    record = dict(ARMS.get(arm, {"code": None, "arc_jobs": [], "state": None}))
    code = record.get("code")
    gpus = dict(record.get("gpus") or {})
    for config in languages:
        for condition in ("raw", "pipeline_full"):
            payload = by_lang[config][condition]
            path = by_lang[config][condition + "_path"]
            commit = (payload.get("run_metadata") or {}).get("git_commit")
            if commit and code and not commit.startswith(code):
                raise SystemExit(f"{path} ran at {commit}, but arm {arm} is "
                                 f"registered at {code}")
            gpu = (payload["benchmark"].get("decode") or {}).get("gpu")
            if gpu is None:
                continue
            if gpus.setdefault(config, gpu) != gpu:
                raise SystemExit(f"{path} decoded on {gpu}, but arm {arm} "
                                 f"records {gpus[config]} for {config}")
    if gpus:
        record["gpus"] = {c: gpus[c] for c in languages if c in gpus}
    return record


def assemble(arms: dict[str, Path], languages=LANGUAGES,
             carry: dict | None = None, exact: bool = False,
             record_inputs: bool = False,
             diacritics: dict | None = None) -> dict:
    """Build the summary from the arms' per-language summaries.

    Parameters
    ----------
    arms:
        ``{arm name: directory}``, in arm order; the names give the key
        suffixes (``1_before_fix`` -> ``raw_before_fix``).
    languages:
        FLEURS configurations, in output order.
    carry:
        A previous summary to take ``pct_words_with_diacritic`` and the
        ``finding`` block from (see the module docstring); ``None`` leaves
        them out.
    exact, record_inputs:
        Add the unrounded values, and the inputs' digests and run
        metadata (see the module docstring).
    diacritics:
        A record written by :mod:`evaluation.fleurs_diacritics`. When
        given, each language's ``pct_words_with_diacritic`` is taken from
        it, not from *carry*, and the measurement's definition, revision
        and word counts are recorded (audit finding OUTPUTS-11).

    Returns
    -------
    dict
        The summary, keys in the committed file's order.

    Raises
    ------
    SystemExit
        If an input is missing or mislabelled, an input records a code
        commit or GPU other than its arm's (see :data:`ARMS`), the arms
        disagree on the model, split, seed or a language's utterance count,
        or the diacritic record counted other utterances than the arms
        scored.
    """
    carry = carry or {}
    carried_langs = carry.get("languages") or {}
    cells = {arm: {c: _cell(Path(d), c) for c in languages}
             for arm, d in arms.items()}

    first = next(iter(cells.values()))[languages[0]]["raw"]["benchmark"]
    shared = {k: first.get(k) for k in ("dataset", "split", "model", "seed")}
    inputs = []
    for arm, by_lang in cells.items():
        for cell in by_lang.values():
            for condition in ("raw", "pipeline_full"):
                bench = cell[condition]["benchmark"]
                got = {k: bench.get(k) for k in shared}
                if got != shared:
                    raise SystemExit(f"{cell[condition + '_path']} records "
                                     f"{got}, the other inputs {shared}")
                path = cell[condition + "_path"]
                inputs.append({"arm": arm, "file": path.name,
                               "sha256": hashlib.sha256(
                                   path.read_bytes()).hexdigest()})

    benchmark = {
        "corpus": shared["dataset"],
        "split": shared["split"],
        "model": shared["model"],
        "seed": shared["seed"],
        "conditions": ["raw", "pipeline_full"],
        "design": _DESIGNS.get(tuple(arms),
                               f"{_count(len(arms))} arms over the same corpus"),
        "arms": {arm: _arm_record(arm, cells[arm], languages) for arm in arms},
        # Completed below, once the raw rates' spread is known.
        "ratio_definition": _RATIO_DEFINITION,
    }
    measured = (diacritics or {}).get("languages") or {}
    if diacritics is not None:
        missing = [c for c in languages if c not in measured]
        if missing:
            raise SystemExit(f"the diacritic record has no entry for {missing}")
        benchmark["diacritic_shares"] = {
            k: diacritics.get(k) for k in ("dataset", "revision", "split",
                                           "reference_field", "definition")}
    if record_inputs:
        from provenance import run_metadata  # noqa: PLC0415
        benchmark["inputs"] = inputs
        benchmark["assembled_by"] = run_metadata()

    languages_out = {}
    for config in languages:
        entry: dict = {}
        exact_block: dict = {}
        counts = set()
        for arm, by_lang in cells.items():
            cell = by_lang[config]
            raw = float(cell["raw"]["summary"]["macro_wer"])
            composite = float(cell["pipeline_full"]["summary"]["macro_wer"])
            counts.add(int(cell["raw"]["benchmark"].get(
                "utterances", cell["raw"]["summary"].get("files", 0))))
            if not entry:
                entry["language"] = cell["raw"]["benchmark"].get("language")
            suffix = _arm_suffix(arm)
            ratio = composite / raw if raw else None
            entry[f"raw_{suffix}"] = round(raw, 4)
            entry[f"pipeline_full_{suffix}"] = round(composite, 4)
            entry[f"ratio_{suffix}"] = (round(ratio, 2)
                                        if ratio is not None else None)
            exact_block[f"raw_{suffix}"] = raw
            exact_block[f"pipeline_full_{suffix}"] = composite
            exact_block[f"ratio_{suffix}"] = ratio
        if len(counts) != 1:
            raise SystemExit(f"{config}: the arms scored different numbers "
                             f"of utterances {sorted(counts)}")
        # Committed key order: language, utterances, the arms' values,
        # the carried diacritic share, then the first arm's raw rate.
        ordered = {"language": entry.pop("language"),
                   "utterances": counts.pop(), **entry}
        if config in measured:
            m = measured[config]
            # A share measured over other utterances than the benchmark
            # scored would not describe the split the ratios come from.
            scored = ordered["utterances"]
            if m.get("n_utterances", scored) != scored:
                raise SystemExit(f"{config}: the diacritic record counted "
                                 f"{m['n_utterances']} utterances, the arms "
                                 f"scored {scored}")
            pct = m["pct_words_with_diacritic"]
            ordered["words"] = m["n_words"]
            ordered["words_with_diacritic"] = m["n_words_with_diacritic"]
            if m["n_words"]:
                exact_block["share_words_with_diacritic"] = (
                    m["n_words_with_diacritic"] / m["n_words"])
        else:
            pct = (carried_langs.get(config) or {}).get("pct_words_with_diacritic")
        if pct is not None:
            ordered["pct_words_with_diacritic"] = pct
        ordered["raw"] = ordered[f"raw_{_arm_suffix(next(iter(arms)))}"]
        if exact:
            ordered["exact"] = exact_block
        languages_out[config] = ordered

    if len(arms) > 1:
        # Read from the four-decimal rates the file holds, as the
        # manuscript reads them, so the sentence and the paper agree.
        spread = max(
            max(rates) - min(rates)
            for rates in ([entry[f"raw_{_arm_suffix(a)}"] for a in arms]
                          for entry in languages_out.values()))
        benchmark["ratio_definition"] = (
            f"{_RATIO_DEFINITION} Raw is stable to within {spread:.4f} "
            f"across the {_count(len(arms))} arms for every language.")

    summary = {"benchmark": benchmark, "languages": languages_out}
    if "finding" in carry:
        summary["finding"] = carry["finding"]
    return summary


def write_summary(summary: dict, path: Path) -> None:
    """Write *summary* as the committed file is laid out.

    Two-space indentation, ASCII escapes, LF line endings and no trailing
    newline, so a rebuild can be compared with the committed file byte for
    byte. Creates the parent directory and overwrites *path*.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(summary, indent=2))


def _parse_arm(value: str) -> tuple[str, Path]:
    name, sep, directory = value.partition("=")
    if not sep or not name or not directory:
        raise argparse.ArgumentTypeError(
            f"--arm expects NAME=DIRECTORY, got {value!r}")
    return name, Path(directory)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="evaluation.fleurs_multilingual",
        description=("Assemble fleurs_multilingual_summary.json from the "
                     "per-language FLEURS summaries of each arm."))
    p.add_argument("--arm", action="append", type=_parse_arm, required=True,
                   metavar="NAME=DIR",
                   help=("An arm and the directory of its summaries, in arm "
                         "order (e.g. 1_before_fix=.../prefix_baseline); "
                         "repeat for each arm."))
    p.add_argument("--languages", default=",".join(LANGUAGES),
                   help="FLEURS configurations, in order (default: %(default)s).")
    p.add_argument("--out", type=Path, default=_DEFAULT_OUT,
                   help="Output JSON (default: %(default)s).")
    p.add_argument("--carry-from", type=Path, default=None, dest="carry_from",
                   help=("Summary to carry pct_words_with_diacritic and the "
                         "finding block from (default: --out, if it exists)."))
    p.add_argument("--diacritics", type=Path, default=None,
                   help=("Diacritic shares measured by evaluation.fleurs_diacritics; "
                         "used in place of the carried pct_words_with_diacritic."))
    p.add_argument("--exact", action="store_true",
                   help="Also record the unrounded rates and ratios.")
    p.add_argument("--record-inputs", action="store_true",
                   dest="record_inputs",
                   help="Also record the inputs' SHA-256 and run metadata.")
    return p


def main(argv: list[str] | None = None) -> int:
    """Run the command-line interface.

    Returns ``0``. Writes ``--out`` (overwriting it) and prints each
    language's ratios. Raises ``SystemExit`` on a missing or inconsistent
    input.
    """
    args = _build_parser().parse_args(argv)
    arms = dict(args.arm)
    carry_path = args.carry_from or args.out
    carry = None
    if carry_path.is_file():
        carry = json.loads(carry_path.read_text(encoding="utf-8"))
    else:
        print(f"  no {carry_path} to carry the diacritic shares and the "
              "finding from; they are left out", file=sys.stderr)
    diacritics = (json.loads(args.diacritics.read_text(encoding="utf-8"))
                  if args.diacritics is not None else None)
    summary = assemble(arms, tuple(c.strip() for c in args.languages.split(",")
                                   if c.strip()),
                       carry=carry, exact=args.exact,
                       record_inputs=args.record_inputs, diacritics=diacritics)
    write_summary(summary, args.out)
    for config, entry in summary["languages"].items():
        ratios = "  ".join(f"{k[len('ratio_'):]}={v}" for k, v in entry.items()
                           if k.startswith("ratio_"))
        print(f"  {config:<7} {ratios}")
    print(f"  written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
