#!/usr/bin/env python3
"""
Compare transcription across hardware: the same decode on different machines.

:mod:`evaluation.determinism` asks whether one machine repeats itself. The
claim a collaboration relies on is wider: that a transcript made on one
machine can be recovered on another, a desktop processor against a cluster
GPU, or one cluster card against the next. This module measures that from
the outputs of runs on different hardware, utterance by utterance.

Each run has a label and up to three files:

``--dump LABEL=PATH``
    Its hypothesis dump (``benchmark_wer --dump-hypotheses``), in either
    layout: a single ``reference`` column before audit finding EWER-22,
    ``reference_raw`` after. Runs with dumps are compared on the text with
    :func:`evaluation.determinism.compare`, and their references are
    checked to agree, which shows they streamed the same utterances.
``--report LABEL=PATH``
    Its per-utterance WER report (``--report``), whose error counts give
    the pooled WER over the compared utterances exactly.
``--log LABEL=PATH``
    Its job log, for a run whose dump was not kept. ``benchmark_wer``
    prints each utterance's WER to three decimals as it decodes, so such a
    run can still be compared at the level of its error rate. Two runs
    whose WER differs on an utterance cannot have produced the same words
    there, but equal error rates do not prove equal words, so a comparison
    from a log is a lower bound on the utterances that differ.

and, for a run with a dump, optionally

``--repeat LABEL=PATH``
    A second decode under the run's own configuration (same card model,
    code and seed), compared with the run's text under ``within_run``. A
    difference between two machines means little unless each machine
    repeats itself, and a run that decoded once says nothing about that.
    The repeat may hold only some of the compared utterances, as a short
    preflight beside a full sweep does, so the result says which it
    covers, including how many of the utterances on which the runs differ
    from one another.

The utterances compared are those of one run (``--subset``): the
determinism check decodes the first 200 AMI test utterances, the sweep the
whole split, so the sweep's dump is read for the check's 200. Every run
must hold every one of them. A run missing some is refused, since agreement
measured on the part of a run that survived is not agreement. A repeat is
the exception, because its coverage is reported beside its agreement.

A run's outputs do not say what the run was: its card, code commit and
seed, and how each of those is known. ``--meta`` takes a JSON file that
does and copies it into the result unchanged. The committed comparison,
``output/evaluation/determinism/determinism_cross_accelerator.json``,
reads ``determinism_cross_accelerator_runs.json`` beside it, which also
names the ARC file each input was copied from.

Usage::

    python -m evaluation.determinism_cross \\
        --dump l40s=seed0_run1.csv --report l40s=wer_seed0_run1.csv \\
        --dump v100=wer_hypotheses_ami_whisper-large-v3.csv \\
        --report v100=wer_report_ami_whisper-large-v3.csv \\
        --log h100=determinism_8554985.out \\
        --repeat l40s=seed0_run2.csv \\
        --subset l40s --meta runs.json --json cross.json

The output names each input by file name and two SHA-256 digests, never by
path. ``sha256`` is of the bytes, which is what ``sha256sum`` prints for
the original on the cluster, whose CSV writer ends rows with CRLF.
``sha256_lf`` reads every CRLF as LF (:func:`provenance.sha256_text_file`),
so it also identifies a copy committed to the repository, which git stores
with LF and checks out with either line ending. The output holds no
transcript text: the differing utterances are listed by id, with their
word edits and error rates.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import statistics
import sys
from itertools import combinations
from pathlib import Path

from evaluation.determinism import compare, word_edit_distance

#: Decimals ``benchmark_wer`` prints a per-utterance WER to in its log.
LOG_PLACES = 3
#: Decimals a hypothesis dump stores a per-utterance WER to.
DUMP_PLACES = 6
#: The packages the result's run metadata records: the comparison computes
#: with numpy alone.
_PACKAGES = ("numpy",)

# A per-utterance progress line of benchmark_wer: the id, then one
# "<condition>=<wer>" score per condition, each to three decimals.
_LOG_LINE = re.compile(r"^  (?P<uid>\S+)  (?P<scores>\S+=\d+\.\d{3}(?:  \S+=\d+\.\d{3})*)$")
# A decode's header in a determinism job log.
_LOG_BLOCK = re.compile(r"^--- (?P<name>seed \S+, run \S+) ---$")
# The job's own summary line for a condition: "  [raw]  n=200  WER=1.4905  ...".
_LOG_SUMMARY = re.compile(r"^  \[(?P<condition>[^\]]+)\]\s+n=(?P<n>\d+)\s+WER=(?P<wer>\d+\.\d+)")


def _digests(path: Path) -> dict:
    """Name an input by file name and both digests (see the module notes)."""
    from provenance import sha256_file, sha256_text_file
    return {"file": Path(path).name, "sha256": sha256_file(path),
            "sha256_lf": sha256_text_file(path)}


def read_dump(path, condition: str = "raw") -> dict:
    """Return ``{uid: {"reference", "hypothesis", "wer"}}`` from a dump.

    Parameters
    ----------
    path:
        A CSV written by ``benchmark_wer --dump-hypotheses``.
    condition:
        Only rows of this condition are read; the raw hypothesis repeats
        across conditions, and the error rate is the condition's own.

    The reference is the corpus's own, ``reference_raw``. A dump written
    before EWER-22 has only ``reference``, the reference the condition
    scored against, which is the corpus's own for ``raw`` and for every
    condition that leaves references alone, but not for ``whisper_norm``.

    Raises
    ------
    ValueError
        If a required column is missing or a uid repeats within the
        condition.
    """
    rows: dict[str, dict] = {}
    with Path(path).open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames or ()
        ref_col = "reference_raw" if "reference_raw" in fields else "reference"
        missing = [c for c in ("uid", "condition", ref_col, "hypothesis_raw", "wer")
                   if c not in fields]
        if missing:
            raise ValueError(f"{path}: missing column(s) {missing}")
        for row in reader:
            if row["condition"] != condition:
                continue
            uid = row["uid"]
            if uid in rows:
                raise ValueError(f"{path}: uid {uid!r} occurs twice for condition {condition!r}")
            rows[uid] = {"reference": row[ref_col], "hypothesis": row["hypothesis_raw"],
                         "wer": float(row["wer"])}
    return rows


def read_report(path) -> dict:
    """Return ``{uid: {"wer", "errors", "reference_words"}}`` from a WER report.

    ``errors`` is substitutions plus deletions plus insertions, so that a
    pooled WER over any set of utterances is exact.

    Raises
    ------
    ValueError
        If a required column is missing or a name repeats.
    """
    rows: dict[str, dict] = {}
    with Path(path).open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        needed = ("name", "wer", "substitutions", "deletions", "insertions",
                  "reference_words")
        missing = [c for c in needed if c not in (reader.fieldnames or ())]
        if missing:
            raise ValueError(f"{path}: missing column(s) {missing}")
        for row in reader:
            uid = row["name"]
            if uid in rows:
                raise ValueError(f"{path}: name {uid!r} occurs twice")
            rows[uid] = {
                "wer": float(row["wer"]),
                "errors": (int(row["substitutions"]) + int(row["deletions"])
                           + int(row["insertions"])),
                "reference_words": int(row["reference_words"]),
            }
    return rows


def read_log(path, condition: str = "raw", block: str | None = None) -> dict:
    """Read the per-utterance WERs one decode printed into its log.

    A determinism job's log holds several decodes, each under a header
    such as ``--- seed 0, run 1 ---``. *block* names the decode to read
    (``"seed 0, run 1"``); ``None`` reads the first. A log without headers,
    from a plain ``benchmark_wer`` run, is read whole.

    Returns
    -------
    dict
        ``{"block": the decode read or None, "wer": {uid: float},
        "logged_macro_wer": the job's own summary WER for *condition*, or
        None, "logged_n": its utterance count, or None}``.

    Raises
    ------
    ValueError
        If the named block is absent, a uid repeats within the block, or the
        block holds no per-utterance line for *condition*.
    """
    blocks: list[tuple[str | None, list[str]]] = [(None, [])]
    with Path(path).open(encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.rstrip("\r\n")
            header = _LOG_BLOCK.match(line)
            if header:
                blocks.append((header.group("name"), []))
            else:
                blocks[-1][1].append(line)
    named = [b for b in blocks if b[0] is not None]
    if block is not None:
        chosen = [b for b in named if b[0] == block]
        if not chosen:
            raise ValueError(f"{path}: no decode headed '--- {block} ---'")
        name, lines = chosen[0]
    elif named:
        name, lines = named[0]
    else:
        name, lines = blocks[0]

    wers: dict[str, float] = {}
    macro = n = None
    for line in lines:
        summary = _LOG_SUMMARY.match(line)
        if summary and summary.group("condition") == condition:
            macro, n = float(summary.group("wer")), int(summary.group("n"))
            continue
        match = _LOG_LINE.match(line)
        if not match:
            continue
        scores = dict(s.split("=", 1) for s in match.group("scores").split("  "))
        if condition not in scores:
            continue
        uid = match.group("uid")
        if uid in wers:
            raise ValueError(f"{path}: uid {uid!r} printed twice in one decode")
        wers[uid] = float(scores[condition])
    if not wers:
        raise ValueError(f"{path}: no per-utterance {condition!r} line in the decode read")
    return {"block": name, "wer": wers, "logged_macro_wer": macro, "logged_n": n}


def _pairs(labels):
    return [(a, b) for a, b in combinations(labels, 2)]


def compare_text(label_a: str, dump_a: dict, label_b: str, dump_b: dict,
                 uids) -> dict:
    """Compare two runs' raw hypotheses on *uids*.

    Returns :func:`evaluation.determinism.compare`'s summary, with every
    differing utterance listed under ``differing_utterances``: its id, the
    word edits between the two hypotheses, the longer hypothesis's word
    count, their ratio (the divergence ``compare`` reports) and each run's
    WER there. Ids and counts only; the text stays out.
    """
    summary = compare({label_a: {u: dump_a[u]["hypothesis"] for u in uids},
                       label_b: {u: dump_b[u]["hypothesis"] for u in uids}})
    details = []
    for uid in uids:
        left, right = dump_a[uid]["hypothesis"], dump_b[uid]["hypothesis"]
        if left == right:
            continue
        edits = word_edit_distance(left, right)
        longer = max(len(left.split()), len(right.split()), 1)
        details.append({"uid": uid, "word_edits": edits, "words_longer": longer,
                        "divergence": round(edits / longer, 6),
                        "wer": {label_a: dump_a[uid]["wer"], label_b: dump_b[uid]["wer"]}})
    details.sort(key=lambda d: (-d["divergence"], d["uid"]))
    summary["differing_utterances"] = details
    return summary


def compare_wer(label_a: str, wer_a: dict, label_b: str, wer_b: dict, uids,
                places: int = LOG_PLACES) -> dict:
    """Count the utterances on which two runs' WER differs at *places* decimals.

    The bound runs one way only: a WER that differs proves the words
    differ, a WER that agrees proves nothing, so the count is a lower bound
    on the utterances whose text differs.
    """
    differing = []
    for uid in uids:
        a, b = round(wer_a[uid], places), round(wer_b[uid], places)
        if a != b:
            differing.append({"uid": uid, "wer": {label_a: a, label_b: b}})
    n = len(uids)
    return {"runs": [label_a, label_b], "utterances_compared": n,
            "decimals": places, "wer_differs": len(differing),
            "wer_differs_rate": round(len(differing) / n, 6) if n else None,
            "is_lower_bound_on_text_differences": True,
            "differing_utterances": differing}


def compare_repeat(label: str, dump: dict, repeat: dict, uids,
                   differing_across_runs=()) -> dict:
    """Compare a run's hypotheses with a second decode of the same run.

    Returns :func:`compare_text`'s summary over the compared utterances the
    repeat holds, with a ``coverage`` block: how many it holds, whether
    they are the first ones in the compared order, and how many of
    *differing_across_runs*, the utterances on which runs on other hardware
    differ, are among them. A repeat that agrees everywhere it was decoded
    says nothing about the utterances it never reached, and those are the
    ones a difference between machines rests on.

    ``references_differing`` counts the covered utterances whose reference
    differs between the two, which would mean they did not decode the same
    audio.

    Raises
    ------
    ValueError
        If the repeat holds none of *uids*.
    """
    covered = [u for u in uids if u in repeat]
    if not covered:
        raise ValueError(f"the repeat of run {label!r} holds none of the "
                         f"{len(uids)} utterances compared")
    summary = compare_text(label, dump, f"{label}_repeat", repeat, covered)
    across = sorted(set(differing_across_runs))
    summary["references_differing"] = sum(
        dump[u]["reference"] != repeat[u]["reference"] for u in covered)
    summary["coverage"] = {
        "utterances_covered": len(covered),
        "of_compared": len(uids),
        "covers_the_first_n": covered == list(uids)[:len(covered)],
        "differing_across_runs": len(across),
        "differing_across_runs_covered": sum(u in repeat for u in across),
    }
    return summary


def subset_wer(per_utterance: dict, uids, report: dict | None = None,
               reference_words: dict | None = None,
               places: int | None = None) -> dict:
    """WER over *uids*: the macro mean and, where it can be had, the pooled.

    Parameters
    ----------
    per_utterance:
        ``{uid: wer}`` for the run.
    report:
        The run's :func:`read_report`, which gives the pooled WER exactly.
    reference_words:
        ``{uid: reference word count}`` from another run's report, for a
        run that has none of its own (one read from its log). Its error
        counts are then rebuilt as ``round(wer * words)``, exact when the
        WERs carry *places* decimals and every utterance has fewer than
        ``10 ** places`` reference words, since the rounding error is then
        under half an error; otherwise the pooled WER is left out.
    places:
        Decimals *per_utterance* carries, for the check above.
    """
    out = {"utterances": len(uids),
           "macro_wer": round(statistics.fmean(per_utterance[u] for u in uids), 6)}
    if report is not None:
        errors = sum(report[u]["errors"] for u in uids)
        words = sum(report[u]["reference_words"] for u in uids)
        out.update(errors=errors, reference_words=words,
                   micro_wer=round(errors / words, 6), micro_source="report")
    elif reference_words is not None and places is not None:
        if max(reference_words[u] for u in uids) < 10 ** places:
            counts = {u: round(per_utterance[u] * reference_words[u]) for u in uids}
            errors = sum(counts.values())
            words = sum(reference_words[u] for u in uids)
            out.update(errors=errors, reference_words=words,
                       micro_wer=round(errors / words, 6),
                       micro_source=(f"rebuilt from {places}-decimal per-utterance WER "
                                     "and the shared reference word counts"))
            # The macro mean of the rebuilt rates is exact, where the mean of
            # the printed rates carries their rounding.
            out["macro_wer"] = round(statistics.fmean(
                counts[u] / reference_words[u] for u in uids), 6)
    return out


def build(dumps: dict, reports: dict, logs: dict, subset: str,
          condition: str = "raw", log_block: str | None = None,
          meta: dict | None = None, meta_file: Path | None = None,
          repeats: dict | None = None, run_meta: dict | None = None) -> dict:
    """Compare the runs and return the result as a dict.

    Runs are reported in the order of their labels, so the result does not
    depend on the order the inputs were named in.

    Parameters
    ----------
    dumps, reports, logs:
        ``{label: path}`` for each kind of input.
    subset:
        The label whose utterances are compared.
    condition:
        The condition whose rows and log lines are read.
    log_block:
        Passed to :func:`read_log`.
    meta:
        Copied into the result under ``meta``.
    meta_file:
        The file *meta* was read from, recorded by name and digest.
    repeats:
        ``{label: path}``, a second decode of a run that has a dump,
        compared with it by :func:`compare_repeat`.
    run_meta:
        Recorded as ``run_metadata``: the :func:`provenance.run_metadata`
        a caller about to write the result read first, leaving the
        result's own file out of the dirty check (:func:`main` does).
        ``None`` reads it here, with numpy as the one package recorded.

    Raises
    ------
    ValueError
        If *subset* is not a run, a run lacks one of its utterances, a
        repeat names a run without a dump, or a repeat holds none of the
        compared utterances.
    """
    repeats = dict(repeats or {})
    labels = sorted(set(dumps) | set(reports) | set(logs))
    if subset not in labels:
        raise ValueError(f"--subset {subset!r} is not one of the runs {labels}")
    orphans = sorted(set(repeats) - set(dumps))
    if orphans:
        raise ValueError(f"a repeat is compared with its run's text, and run(s) "
                         f"{orphans} have no dump")

    read_dumps = {k: read_dump(p, condition) for k, p in dumps.items()}
    read_reports = {k: read_report(p) for k, p in reports.items()}
    read_logs = {k: read_log(p, condition, log_block) for k, p in logs.items()}
    read_repeats = {k: read_dump(p, condition) for k, p in repeats.items()}

    def wers_of(label: str) -> tuple[dict, int | None]:
        # The most precise per-utterance WER the run offers, and the
        # decimals it carries (None: full precision).
        if label in read_reports:
            return {u: r["wer"] for u, r in read_reports[label].items()}, None
        if label in read_dumps:
            return {u: r["wer"] for u, r in read_dumps[label].items()}, DUMP_PLACES
        return read_logs[label]["wer"], LOG_PLACES

    if subset in read_dumps:
        uids = list(read_dumps[subset])
    elif subset in read_reports:
        uids = list(read_reports[subset])
    else:
        uids = list(read_logs[subset]["wer"])

    for label in labels:
        held = [set(src[label]) for src in (read_dumps, read_reports) if label in src]
        if label in read_logs:
            held.append(set(read_logs[label]["wer"]))
        for have in held:
            lost = [u for u in uids if u not in have]
            if lost:
                raise ValueError(
                    f"run {label!r} lacks {len(lost)} of the {len(uids)} utterances "
                    f"compared (first: {lost[0]!r}); agreement on the rest would "
                    "overstate it")

    runs: dict = {}
    for label in labels:
        inputs = {}
        for role, given in (("dump", dumps), ("report", reports), ("log", logs),
                            ("repeat", repeats)):
            if label in given:
                inputs[role] = _digests(given[label])
        if label in read_logs:
            inputs["log"]["decode_read"] = read_logs[label]["block"]
            inputs["log"]["logged_n"] = read_logs[label]["logged_n"]
            inputs["log"]["logged_macro_wer"] = read_logs[label]["logged_macro_wer"]
        runs[label] = {"evidence": "text" if label in read_dumps else "wer",
                       "inputs": inputs}

    # The references must agree, or the runs did not decode the same audio.
    with_text = [k for k in labels if k in read_dumps]
    ref_disagree = sorted({u for a, b in _pairs(with_text) for u in uids
                           if read_dumps[a][u]["reference"] != read_dumps[b][u]["reference"]})
    with_counts = [k for k in labels if k in read_reports]
    words_disagree = sorted({u for a, b in _pairs(with_counts) for u in uids
                             if read_reports[a][u]["reference_words"]
                             != read_reports[b][u]["reference_words"]})

    text = {f"{a}_vs_{b}": compare_text(a, read_dumps[a], b, read_dumps[b], uids)
            for a, b in _pairs(with_text)}
    wer_level = {}
    for a, b in _pairs(labels):
        if a in read_dumps and b in read_dumps:
            continue
        wa, _ = wers_of(a)
        wb, _ = wers_of(b)
        wer_level[f"{a}_vs_{b}"] = compare_wer(a, wa, b, wb, uids)

    # Every utterance on which some pair of runs is known to differ, in
    # text or in error rate: what a repeat has to reach to speak to them.
    differing_across = {d["uid"] for block in (*text.values(), *wer_level.values())
                        for d in block["differing_utterances"]}
    within_run = {k: compare_repeat(k, read_dumps[k], read_repeats[k], uids,
                                    differing_across)
                  for k in sorted(read_repeats)}

    # A run without a report borrows the reference word counts, which the
    # agreeing references make shared, to rebuild its pooled WER.
    shared_words = (read_reports[with_counts[0]] if with_counts and not words_disagree
                    and not ref_disagree else None)
    summary_wer = {}
    for label in labels:
        per_utt, places = wers_of(label)
        summary_wer[label] = subset_wer(
            per_utt, uids, report=read_reports.get(label),
            reference_words=({u: shared_words[u]["reference_words"] for u in uids}
                             if shared_words is not None else None),
            places=places)
        if label in read_logs:
            # The job's own figure, printed to four decimals, checks the
            # per-utterance lines read here.
            summary_wer[label]["logged_macro_wer"] = read_logs[label]["logged_macro_wer"]

    from provenance import run_metadata, sha256_text_file
    result = {
        "description": (
            "The same decode on different hardware, utterance by utterance. "
            "'text' compares runs whose hypotheses were kept; 'within_run' "
            "compares a run with a second decode of its own, on the compared "
            "utterances that decode holds; 'wer_level' compares per-utterance "
            "error rates where one run's text was not kept, a lower bound on "
            "the utterances whose text differs. 'meta' says what each run was "
            "and how that is known."),
        "condition": condition,
        "subset": {"from_run": subset, "utterances": len(uids),
                   "uids_sha256": hashlib.sha256("\n".join(uids).encode("utf-8")).hexdigest(),
                   "first_uid": uids[0] if uids else None,
                   "last_uid": uids[-1] if uids else None},
        "references": {"runs_with_text": with_text,
                       "utterances_whose_reference_differs": len(ref_disagree),
                       "runs_with_reports": with_counts,
                       "utterances_whose_reference_word_count_differs": len(words_disagree)},
        "runs": runs,
        "text": text,
        "within_run": within_run,
        "wer_level": wer_level,
        "subset_wer": summary_wer,
        "meta": meta,
    }
    if meta_file is not None:
        # The meta file is committed, so its digest is the line-ending-free
        # one every checkout reproduces.
        result["meta_file"] = {"file": Path(meta_file).name,
                               "sha256_lf": sha256_text_file(meta_file)}
    result["run_metadata"] = (run_meta if run_meta is not None
                              else run_metadata(packages=_PACKAGES))
    return result


def _labelled(values, option: str) -> dict:
    """Parse repeated ``LABEL=PATH`` values into ``{label: Path}``.

    Raises
    ------
    ValueError
        If a value is not ``LABEL=PATH`` or a label is given twice.
    """
    out: dict[str, Path] = {}
    for value in values or ():
        label, sep, path = value.partition("=")
        if not sep or not label or not path:
            raise ValueError(f"{option} takes LABEL=PATH, not {value!r}")
        if label in out:
            raise ValueError(f"{option} names {label!r} twice")
        out[label] = Path(path)
    return out


def print_report(result: dict) -> None:
    """Print the comparison to stdout."""
    print(f"\n  utterances compared: {result['subset']['utterances']} "
          f"(those of {result['subset']['from_run']})")
    refs = result["references"]
    print(f"  references differing: {refs['utterances_whose_reference_differs']}")
    for name, summary in result["text"].items():
        print(f"  {name}: {summary['identical']} identical, "
              f"{summary['differing']} differing (text)")
    for label, summary in result["within_run"].items():
        cover = summary["coverage"]
        print(f"  {label} repeated: {summary['identical']} identical, "
              f"{summary['differing']} differing, over {cover['utterances_covered']} "
              f"of {cover['of_compared']} utterances and "
              f"{cover['differing_across_runs_covered']} of the "
              f"{cover['differing_across_runs']} on which runs differ")
    for name, summary in result["wer_level"].items():
        print(f"  {name}: WER differs on {summary['wer_differs']} "
              "(at least that many differ in text)")
    for label, wer in result["subset_wer"].items():
        micro = wer.get("micro_wer")
        print(f"  {label}: macro WER {wer['macro_wer']:.6f}"
              + (f", pooled {micro:.6f}" if micro is not None else ""))


def main(argv=None) -> int:
    """Run the command-line interface.

    Returns ``0`` on success and ``2`` when an input is missing or
    malformed, a run lacks a compared utterance, fewer than two runs are
    given, or a repeat has no run's text to be compared with or none of
    the compared utterances. Writes ``--json`` when asked for.
    """
    parser = argparse.ArgumentParser(
        prog="evaluation.determinism_cross",
        description="Compare one decode across hardware, utterance by utterance.")
    parser.add_argument("--dump", action="append", metavar="LABEL=PATH",
                        help="a run's hypothesis dump (repeatable)")
    parser.add_argument("--report", action="append", metavar="LABEL=PATH",
                        help="a run's per-utterance WER report (repeatable)")
    parser.add_argument("--log", action="append", metavar="LABEL=PATH",
                        help="a run's job log, for a run whose dump was not "
                             "kept (repeatable)")
    parser.add_argument("--repeat", action="append", metavar="LABEL=PATH",
                        help="a second decode of a run that has a --dump, "
                             "under the same configuration (repeatable, one "
                             "per run)")
    parser.add_argument("--subset", required=True, metavar="LABEL",
                        help="compare on this run's utterances")
    parser.add_argument("--condition", default="raw",
                        help="condition to read (default: %(default)s)")
    parser.add_argument("--log-block", default=None, metavar="NAME",
                        help="the decode to read from each log, as its header "
                             "names it ('seed 0, run 1'); default: the first")
    parser.add_argument("--meta", type=Path, default=None,
                        help="JSON describing the runs, copied into the result")
    parser.add_argument("--json", dest="json_out", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        dumps = _labelled(args.dump, "--dump")
        reports = _labelled(args.report, "--report")
        logs = _labelled(args.log, "--log")
        repeats = _labelled(args.repeat, "--repeat")
    except ValueError as exc:
        print(f"  {exc}", file=sys.stderr)
        return 2
    labels = set(dumps) | set(reports) | set(logs)
    if len(labels) < 2:
        print("  comparing hardware needs at least two runs", file=sys.stderr)
        return 2
    missing = [str(p) for p in (*dumps.values(), *reports.values(), *logs.values(),
                                *repeats.values(),
                                *([args.meta] if args.meta else []))
               if not p.exists()]
    if missing:
        print(f"  no such input(s): {missing}", file=sys.stderr)
        return 2
    from provenance import run_metadata
    # Read before the result is written, leaving it out of the dirty check,
    # as provenance.write_sidecar does for the CSV-only writers. Read inside
    # build without the ignore list, as it was, a second comparison in
    # place counted the first one's result as uncommitted code (audit
    # finding OUTPUTS-12).
    run_meta = run_metadata(packages=_PACKAGES,
                            ignore=(args.json_out,) if args.json_out else ())
    try:
        meta = (json.loads(args.meta.read_text(encoding="utf-8"))
                if args.meta is not None else None)
        result = build(dumps, reports, logs, args.subset, args.condition,
                       args.log_block, meta, args.meta, repeats, run_meta)
    except ValueError as exc:
        # json.JSONDecodeError is a ValueError, so a malformed --meta lands here.
        print(f"  {exc}", file=sys.stderr)
        return 2
    print_report(result)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        print(f"\n  written: {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
