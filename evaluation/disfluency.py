#!/usr/bin/env python3
"""
Score how faithfully each condition preserves non-lexical fillers.

The workflow claims that its post-processing keeps the hesitations,
"um", "uh", "er" and their relatives, that conversation-analytic and
clinical research designs depend on, and that the normaliser used for
benchmark scoring throws them away. Aggregate word error rate cannot
settle that claim. A condition that deleted every filler and a condition
that kept every one can post a similar rate, because the rate says how
many words differ and not which ones.

Two measurements, answering two different questions.

``retention``
    Of the fillers the model actually emitted, how many survive the
    condition's transform? Computed from the untransformed hypothesis and
    the transformed one, so it isolates what the post-processing does and
    is unaffected by how well the model heard the audio. This is the
    claim about the pipeline, stated directly.

``reference_recall``
    Of the fillers the human transcriber recorded, how many appear in the
    transformed hypothesis? This is end-to-end fidelity, and it is
    confounded by recognition error: a filler the model never heard
    cannot be preserved by anything downstream. Reported alongside
    retention rather than instead of it, because a researcher choosing a
    condition needs the first and a researcher trusting a transcript
    needs the second. The denominator is always the transcriber's own
    reference, never the reference a condition such as ``whisper_norm``
    scored against: that normaliser deletes um, uh, hmm, mm and mhm from the
    reference, and dividing by what survives it reported 12.1% recall for
    a condition whose output keeps almost none of the transcriber's
    fillers (audit finding ESTATS-01).

Both are counted per token rather than per utterance, since an utterance
may hold several fillers and losing one of three is not the same as
losing all three.

Each condition is scored over the utterances it holds in the dump (the
summary's ``conditions`` block), and ``n_utterances_dropped`` counts the
scored utterances it lacks. A condition that transforms the reference
can empty it. ``whisper_norm`` empties every filler-only reference, and
the benchmark then skips that utterance under that condition alone. The
discard is one of the normaliser's effects on a filler-bearing analysis,
and on AMI the utterances it removes hold most of the model's fillers,
so scoring every condition only on what the normaliser keeps would leave
the other conditions' figures describing part of the corpus. It would
also make a condition's figures depend on which other conditions were
scored beside it. Each condition's own set is therefore the primary one,
as audit finding ESTATS-01 proposed. Rates over different sets describe
different utterances, though, so the summary also scores every condition
over the ``n_shared_utterances`` utterances all of them hold
(``conditions_shared_set``).

``output_marked`` counts the fillers in a condition's output that are
marked, with every letter inside square brackets as the
``filler_bracket`` stage writes them. Retention cannot show marking,
because the brackets are removed before counting. The bracketing list
also matches exact spellings only, so a lengthened ``Mmm`` or ``Errr``
is kept but left unmarked (audit finding XREF-08).

What counts as a filler is this module's detector, :data:`_FILLER_PATTERN`,
which is deliberately broader than the pipeline's bracketing list
(:data:`transcription.FILLER_TOKENS`) and the ``filler_strip`` pattern,
so that every removal either condition can make is seen; the inventories
and why they differ are tabulated in the :mod:`evaluation.conditions`
docstring. Bracketed forms, ``[uh]`` from the ``filler_bracket`` stage and
whole bracketed backchannels such as ``[uh-huh]``, count as the filler
they wrap. The summary JSON records the pattern it counted with.

Input is the CSV written by ``benchmark_wer.py --dump-hypotheses``, in
either layout: with ``reference_raw`` and ``reference_transformed``
columns, or, from dumps written before that split (audit finding
EWER-22), a single ``reference`` column holding the transformed
reference, in which case the transcriber's reference is taken from the
same utterance's row under a condition that leaves references alone
(``raw``, ``pipeline_full``).

Usage::

    python -m evaluation.disfluency output/evaluation/wer_hypotheses.csv \\
        --json output/evaluation/disfluency_summary.json \\
        --csv  output/evaluation/disfluency_report.csv

``--conditions`` scores only the named conditions, and the shared
utterance set is then taken over those alone. A sweep dump holds every
registered condition, and the summary the manuscript reads covers three.
The summary records the dump's SHA-256 (``source_sha256``), because the
dump holds transcript text and is not committed.

The committed ``output/evaluation/disfluency_summary.json`` and
``disfluency_report.csv`` score the AMI dump written by the Large v3 task
of the audit's sweep (ARC job 8917985, code 6f9bf56), so the filler figures
rest on the same decoding as that sweep's AMI word error rates. The dump
stays on ARC, at ``audit2026/sweep/wer_hypotheses_ami_whisper-large-v3.csv``
under ``$DATA/speech_transcription_env/output/evaluation``. From that
directory, with the repository on ``PYTHONPATH``, both files are rebuilt
by::

    python -m evaluation.disfluency \\
        audit2026/sweep/wer_hypotheses_ami_whisper-large-v3.csv \\
        --conditions raw,pipeline_full,whisper_norm \\
        --json repro/disfluency/disfluency_summary.json \\
        --csv  repro/disfluency/disfluency_report.csv

and differ from the committed pair only in ``run_metadata``. Run from
elsewhere, ``source`` records the path given instead. The outputs go under
``repro/`` because the evaluation directory itself still holds the August
2026 summary (job 8555165), which a reproduction must not overwrite.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from transcription import FILLER_TOKENS  # noqa: E402

#: The vocabulary this benchmark detects, deliberately broader than either
#: production list.
#:
#: The workflow holds two, and neither contains the other.
#: ``transcription.FILLER_TOKENS``, which drives the bracketing stage, has
#: the backchannels ``uhuh`` and ``uhhuh``. The pattern behind the
#: ``filler_strip`` condition has ``erm``, ``uhm`` and ``hm`` instead,
#: along with lengthened spellings such as ``ummm`` and ``uhhh`` that a
#: transcriber or a model readily produces.
#:
#: A measurement must see everything either condition might remove.
#: Detecting only the narrower list would silently shrink the
#: denominator: a condition that deleted every ``erm`` would score as
#: having preserved the fillers, because none had been counted. Being
#: broader than both is the safe direction, since an over-broad detector
#: can only report removals that did happen.
#:
#: This does not change what either condition does. Reconciling the two
#: production lists would move published word error rates, so it is
#: reported rather than done here.
#:
#: One hesitation that can open a filler. Ordered longest first, because
#: regular-expression alternation takes the first branch that matches and
#: a shorter one placed earlier would truncate the token: ``uh+`` ahead of
#: ``uhuh`` would consume only the first half. ``mm+hm+`` is the
#: unhyphenated backchannel ("mmhmm"), which the ``_canonical`` docstring
#: always claimed to unify with "mm-hmm" but which never matched (audit
#: finding ESTATS-08).
_OPENING_STEMS = ("uhhuh", "uhuh", "mm+hm+", "uhm+", "um+", "uh+", "erm+",
                  "er+", "ah+", "mhm+", "hmm+", "hm+", "mm+")
_FIRST_STEM = "(?:" + "|".join(_OPENING_STEMS) + ")"

#: Any element of a hyphenated compound: an opening stem, or ``huh``.
#: ``huh`` is in neither production list and is not a filler on its own
#: (standalone it is a question tag or an interjection, "huh?"); it counts
#: only as the second half of the backchannel ``uh-huh``. It used to be a
#: free alternative, so every standalone "huh" was counted (ESTATS-08).
_FILLER_STEM = "(?:" + "|".join(_OPENING_STEMS + ("huh+",)) + ")"

#: The two backchannels transcribers also write with a space, "uh huh"
#: and "mm hmm". Each is one filler, as it is when hyphenated; counted
#: element by element, "Uh huh" in a hypothesis would not match "UH-HUH" in
#: an AMI reference. A space joins only these pairs, so "uh, um" and
#: "um uh" stay two fillers.
_SPACED_BACKCHANNEL = r"(?:uh+\s+huh+|mm+\s+hm+)"

#: A filler: a spaced backchannel, or an opening stem followed by any
#: number of hyphenated elements. AMI writes its backchannels hyphenated,
#: "MM-HMM" and "UH-HUH", and a pattern treating the hyphen as a word
#: boundary would not see them at all. Hyphens are consumed inside the
#: match but excluded at its edges, so a hyphenated ordinary word cannot
#: end in a filler and be counted as one.
_FILLER_PATTERN = re.compile(
    r"(?<![\w-])(?:" + _SPACED_BACKCHANNEL + r"|" + _FIRST_STEM
    + r"(?:-" + _FILLER_STEM + r")*)(?![\w-])",
    flags=re.IGNORECASE,
)


def _canonical(token: str) -> str:
    """Collapse a filler's spelling to a canonical key.

    The same hesitation is written many ways: at whatever length the
    speaker held it ("um", "umm", "ummm"), and hyphenated, spaced or
    joined ("mm-hmm", "mm hmm", "mmhmm"). Without a canonical form, a
    transform that rewrote one spelling as another would look like a
    deletion and an insertion rather than a preserved token.

    Hyphens and spaces are dropped and consecutive repeated letters
    collapse to one. That unifies the spellings which differ only by
    length or joining ("mm-hmm", "mm hmm" and "mmhmm" with "mhm", "uh-huh"
    with "uhuh") while leaving genuinely different fillers apart ("mm" and
    "mhm" do not merge).
    """
    lowered = re.sub(r"[\s-]+", "", token.lower())
    return "".join(char for i, char in enumerate(lowered)
                   if i == 0 or char != lowered[i - 1])


def _unbracket(text: str) -> str:
    """Remove the brackets the ``filler_bracket`` stage adds.

    That stage marks fillers rather than removing them, and brackets a
    hyphenated backchannel whole: "Mm-hmm" becomes "[Mm-hmm]". Dumps
    written before audit finding T1-18 hold the element-by-element form
    ("[Mm]-[hmm]", "[uh]-huh"); every form, and the bare one, unbrackets
    to the same "Mm-hmm" and so counts as one filler. Counting the forms
    differently would make the detector asymmetric across the very
    transform it is measuring, and retention would then report more
    fillers leaving a stage than entered it.
    """
    return (text or "").replace("[", "").replace("]", "")


def count_fillers(text: str) -> Counter:
    """Return a count of each canonical filler in *text*.

    Counting rather than merely detecting matters: an utterance may carry
    several fillers, and a transform that drops two of three has not
    preserved them.
    """
    return Counter(_canonical(m.group(0))
                   for m in _FILLER_PATTERN.finditer(_unbracket(text)))


def _bracket_mask(text: str) -> tuple[str, list[bool]]:
    """Return *text* without its square brackets, and for each character
    left whether it stood inside a pair of them.

    The characters removed are the ones :func:`_unbracket` removes, so the
    detector finds the same fillers in the result as :func:`count_fillers`
    does.
    """
    chars: list[str] = []
    inside: list[bool] = []
    depth = 0
    for char in text or "":
        if char == "[":
            depth += 1
        elif char == "]":
            depth = max(depth - 1, 0)
        else:
            chars.append(char)
            inside.append(depth > 0)
    return "".join(chars), inside


def count_marked(text: str) -> int:
    """Return how many of the fillers in *text* are marked.

    A filler is marked when every letter of it stands inside square
    brackets. That covers ``[uh]``, a whole ``[Mm-hmm]`` and the older
    element-by-element ``[Mm]-[hmm]``, but not a half-marked ``[uh]-huh``.
    :func:`count_fillers` removes the brackets before counting, so a
    marking stage that missed a spelling would still retain every filler;
    this count is what shows the miss.
    """
    plain, inside = _bracket_mask(text)
    return sum(
        all(inside[i] for i in range(m.start(), m.end()) if plain[i].isalpha())
        for m in _FILLER_PATTERN.finditer(plain))


def _surviving(before: Counter, after: Counter) -> int:
    """How many of *before*'s tokens are still present in *after*.

    Multiset intersection, so three "uh" reduced to one counts as one
    survivor and two losses, not as full survival because the type is
    still represented.
    """
    return sum(min(n, after[token]) for token, n in before.items())


def score_pair(reference: str | None, hypothesis_raw: str,
               hypothesis_transformed: str) -> dict:
    """Score one (utterance, condition) row.

    Parameters
    ----------
    reference:
        The transcriber's reference, untransformed; ``None`` when it is not
        known (a legacy dump row with no reference-preserving condition),
        in which case the reference counts are ``None`` and the row is left
        out of reference recall.
    hypothesis_raw, hypothesis_transformed:
        The model's output and the condition's output.

    Returns
    -------
    dict
        ``reference_fillers``, ``raw_fillers`` and ``output_fillers``: the
        filler counts in the reference, the untransformed hypothesis and
        the transformed one. ``output_marked``: how many of the output's
        fillers are bracketed (see :func:`count_marked`). ``retained``:
        how many of the raw hypothesis's fillers survive in the output, by
        multiset intersection (see :func:`_surviving`).
        ``reference_recovered``: the same intersection taken against the
        reference.
    """
    raw = count_fillers(hypothesis_raw)
    out = count_fillers(hypothesis_transformed)
    ref = count_fillers(reference) if reference is not None else None
    return {
        "reference_fillers": sum(ref.values()) if ref is not None else None,
        "raw_fillers": sum(raw.values()),
        "output_fillers": sum(out.values()),
        "output_marked": count_marked(hypothesis_transformed),
        "retained": _surviving(raw, out),
        "reference_recovered": _surviving(ref, out) if ref is not None else None,
    }


def aggregate(rows) -> dict:
    """Combine per-row scores into the two headline rates.

    Rates are undefined when their denominator is zero, and are reported
    as ``None`` rather than as 0.0 or 1.0. A corpus whose references hold
    no fillers cannot say anything about preserving them, and a rate
    invented for that case would read as a measurement. Rows whose
    reference is unknown (``None`` counts) are left out of the reference
    totals and counted in ``n_reference_unknown``.
    """
    totals = Counter()
    n = 0
    n_reference_unknown = 0
    for row in rows:
        n += 1
        if row.get("reference_fillers") is None:
            n_reference_unknown += 1
        for key, value in row.items():
            if value is not None:
                totals[key] += value

    def _rate(numerator, denominator):
        return (round(totals[numerator] / totals[denominator], 4)
                if totals[denominator] else None)

    return {
        "n_utterances": n,
        "n_reference_unknown": n_reference_unknown,
        "reference_fillers": totals["reference_fillers"],
        "raw_fillers": totals["raw_fillers"],
        "output_fillers": totals["output_fillers"],
        "output_marked": totals["output_marked"],
        "retained": totals["retained"],
        "reference_recovered": totals["reference_recovered"],
        # Of the fillers the model emitted, the share the condition kept.
        "retention": _rate("retained", "raw_fillers"),
        # Of the fillers the transcriber recorded, the share that survive.
        "reference_recall": _rate("reference_recovered", "reference_fillers"),
        # Ratio of all fillers in the output to all fillers in the
        # references. Every output filler counts, not only insertions, so
        # a value below 1 can still include invented fillers.
        "output_over_reference": (
            round(totals["output_fillers"] / totals["reference_fillers"], 4)
            if totals["reference_fillers"] else None),
    }


def _leaves_reference(condition: str) -> bool:
    """Whether *condition* scores against the untransformed reference.

    Read from the condition registry (``apply_to_reference`` false); an
    unregistered name is not trusted to have left the reference alone.
    """
    from evaluation.conditions import get_condition  # noqa: PLC0415
    try:
        return not get_condition(condition).apply_to_reference
    except KeyError:
        return False


def _read_dump(path: Path, conditions=None) -> tuple[list[dict], dict[str, str], str]:
    """Read a dump and return ``(rows, {uid: transcriber reference}, source)``.

    A dump with a ``reference_raw`` column gives the reference directly. An
    older dump's ``reference`` column holds the reference each condition
    scored against, transformed for ``whisper_norm``, ``punct_strip`` and
    ``case_fold``; for those the transcriber's reference is taken from the
    same utterance's row under a condition that leaves references alone.
    *source* says which, for the summary.

    *conditions*, when given, keeps only those conditions' rows. The
    references are still read from every row, so a selection that leaves
    out ``raw`` and ``pipeline_full`` keeps recall anchored on the
    transcriber's reference in an older dump. The file is streamed, so a
    selection also keeps a seventeen-condition sweep dump out of memory.
    """
    wanted = set(conditions) if conditions is not None else None
    rows: list[dict] = []
    references: dict[str, str] = {}
    with Path(path).open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        has_raw_column = "reference_raw" in (reader.fieldnames or [])
        for row in reader:
            if has_raw_column:
                references.setdefault(row["uid"], row["reference_raw"])
            elif _leaves_reference(row["condition"]):
                references.setdefault(row["uid"], row.get("reference", ""))
            if wanted is None or row["condition"] in wanted:
                rows.append(row)
    source = ("reference_raw column" if has_raw_column else
              "reference column of conditions that leave the reference alone")
    return rows, references, source


def score_dump_sets(path: Path, conditions=None) -> dict:
    """Score the conditions in a dump, each on its own set and on a shared one.

    Parameters
    ----------
    path:
        The dump.
    conditions:
        Condition names to score; ``None`` scores every condition in the
        dump. The shared set, ``n_utterances`` and ``n_utterances_dropped``
        are then taken over these conditions alone, since a condition left
        out of the comparison should not shrink the set it is made on.

    Returns
    -------
    dict
        ``conditions``: ``{condition: aggregate}`` over each condition's
        own rows, each with ``n_utterances_dropped``, the number of the
        scored utterances that condition lacks; the module docstring says
        why this set is the primary one. ``conditions_shared_set``: the
        same over the utterances present under every scored condition,
        for like-for-like comparisons. ``n_shared_utterances`` and
        ``n_utterances`` (all utterances under any scored condition), and
        ``reference_source`` (see :func:`_read_dump`). Empty blocks for an
        empty dump scored without a selection.

    Raises
    ------
    ValueError
        When *conditions* names a condition the dump holds no rows for, so
        that a misspelt name cannot pass for a condition that scored
        nothing.
    """
    rows, references, source = _read_dump(path, conditions)
    by_condition: dict[str, dict[str, dict]] = {}
    for row in rows:
        by_condition.setdefault(row["condition"], {})[row["uid"]] = row
    if conditions is not None:
        missing = sorted(set(conditions) - set(by_condition))
        if missing:
            raise ValueError(f"{path} holds no rows for the condition(s) "
                             f"{', '.join(missing)}")
    all_uids = set().union(*(set(v) for v in by_condition.values())) \
        if by_condition else set()
    shared = set.intersection(*(set(v) for v in by_condition.values())) \
        if by_condition else set()

    own_block, shared_block = {}, {}
    for name in sorted(by_condition):
        # Each row is scored once and aggregated into both sets.
        scores = {uid: score_pair(references.get(uid),
                                  row.get("hypothesis_raw", ""),
                                  row.get("hypothesis_transformed", ""))
                  for uid, row in by_condition[name].items()}
        own = aggregate(scores.values())
        own["n_utterances_dropped"] = len(all_uids - set(scores))
        own_block[name] = own
        shared_block[name] = aggregate(scores[uid] for uid in sorted(shared))
    return {"n_utterances": len(all_uids),
            "n_shared_utterances": len(shared),
            "reference_source": source,
            "conditions": own_block,
            "conditions_shared_set": shared_block}


def score_dump(path: Path, conditions=None) -> dict:
    """Score the conditions in a dump, each over its own utterances.

    Returns ``{condition: aggregate}``, the ``conditions`` block of
    :func:`score_dump_sets` (which also explains *conditions*): reference
    recall against the transcriber's reference, and each condition with
    the number of utterances it lacks.
    """
    return score_dump_sets(path, conditions)["conditions"]


#: Spellings probed by :func:`audit_conditions` beyond FILLER_TOKENS. They
#: are the forms the detector comment above names as removable by
#: ``filler_strip`` but absent from the bracketing list, so an audit over
#: FILLER_TOKENS alone could not show a condition deleting them, and the
#: backchannel spellings the detector unifies.
_EXTRA_PROBE_TOKENS = ("erm", "uhm", "hm", "ummm", "uhhh", "mm-hmm", "uh-huh",
                       "mmhmm")

#: Every token the condition audit probes, production list first.
PROBE_TOKENS = tuple(FILLER_TOKENS) + tuple(
    t for t in _EXTRA_PROBE_TOKENS if t not in FILLER_TOKENS)


def audit_conditions(condition_names=("raw", "pipeline_full", "whisper_norm",
                                      "filler_strip", "filler_bracket"),
                     language: str = "english",
                     tokens=PROBE_TOKENS) -> dict:
    """Report, per condition, which fillers survive it.

    This half of the question needs no audio and no GPU, because whether a
    transform deletes "um" is a property of the transform. Each filler is
    probed inside a carrier sentence, so a stage that only acts on
    sentence-initial or isolated tokens is not mistaken for one that acts
    everywhere.

    Worth running against a new release of the scoring normaliser: the
    reference implementation removes some hesitations and keeps others,
    and which ones is not something a version number announces.

    Parameters
    ----------
    condition_names:
        Registered condition names to probe; unregistered names are
        skipped.
    language:
        Passed to language-aware conditions.
    tokens:
        The fillers to probe. Defaults to :data:`PROBE_TOKENS`, the
        production list plus the spellings only ``filler_strip`` targets.

    Returns
    -------
    dict
        ``{condition: {token: kept}}``, where *kept* is True when the
        detector still finds a filler after the transform. A condition
        that cannot run here (``whisper_norm`` without openai-whisper's
        spelling map) is left out, with a note on stderr.
    """
    from evaluation.conditions import get_condition

    result: dict[str, dict[str, bool]] = {}
    for name in condition_names:
        try:
            condition = get_condition(name)
        except Exception:  # noqa: BLE001 - an unregistered name is not fatal
            continue
        kept: dict[str, bool] = {}
        try:
            for token in tokens:
                probe = f"yes {token} really"
                transformed = (condition.transform(probe, language)
                               if getattr(condition, "language_aware", False)
                               else condition.transform(probe))
                kept[token] = sum(count_fillers(transformed).values()) > 0
        except ImportError as exc:
            print(f"  {name} cannot run here and is left out: {exc}",
                  file=sys.stderr)
            continue
        result[name] = kept
    return result


def _warn_if_unmeasurable(summary: dict) -> bool:
    """Say plainly when the corpus cannot answer the question.

    Returns True when at least one condition had fillers to score.
    """
    any_reference = any(s["reference_fillers"] for s in summary.values())
    any_raw = any(s["raw_fillers"] for s in summary.values())
    if not any_raw:
        print("\n  The model emitted no fillers anywhere in this dump, so "
              "retention is undefined.\n  Nothing here supports or refutes a "
              "claim about preserving them.", file=sys.stderr)
    if not any_reference:
        print("\n  The references contain no fillers, so reference recall is "
              "undefined.\n  Most benchmark corpora are transcribed from "
              "prepared speech or are normalised;\n  a verbatim "
              "conversational corpus such as AMI is needed for that half of "
              "the measurement.", file=sys.stderr)
    return bool(any_raw or any_reference)


def print_report(summary: dict) -> None:
    """Print the per-condition counts and rates of *summary* to stdout."""
    def _pct(value):
        return f"{value * 100:.1f}%" if value is not None else "n/a"

    print(f"\n  {'condition':<22}{'utts':>7}{'ref':>7}{'raw':>7}{'out':>7}"
          f"{'marked':>8}{'retention':>12}{'ref recall':>12}")
    print("  " + "-" * 82)
    for name, s in summary.items():
        print(f"  {name:<22}{s['n_utterances']:>7}{s['reference_fillers']:>7}"
              f"{s['raw_fillers']:>7}{s['output_fillers']:>7}"
              f"{s['output_marked']:>8}{_pct(s['retention']):>12}"
              f"{_pct(s['reference_recall']):>12}")


def _condition_list(text: str) -> list[str]:
    """Parse ``--conditions``: comma-separated names, blanks ignored."""
    names = [name.strip() for name in text.split(",") if name.strip()]
    if not names:
        raise argparse.ArgumentTypeError("name at least one condition")
    return names


def main(argv=None) -> int:
    """Run the command-line interface.

    Returns ``0`` on success, ``1`` when the dump holds no filler to
    measure in either the hypotheses or the references, and ``2`` when the
    dump is missing or empty or lacks a condition named in
    ``--conditions``. Writes the ``--json`` and ``--csv`` outputs when
    asked for (overwriting them) and prints the table of each condition's
    own utterances, then that of the shared set when the two differ. The
    JSON holds both blocks of :func:`score_dump_sets`, the dump's path as
    given and its SHA-256, the conditions selected (``None`` for all), the
    production list, the detector pattern it counted with, where the
    references came from and :func:`provenance.run_metadata` (which runs
    ``git``); the CSV holds one row per condition and utterance set
    (``set`` is ``own`` or ``shared``).
    """
    parser = argparse.ArgumentParser(
        description="Score filler preservation from a hypothesis dump.")
    parser.add_argument("dump", type=Path, nargs="?", default=None,
                        help="CSV written by benchmark_wer.py --dump-hypotheses")
    parser.add_argument("--audit-conditions", action="store_true",
                        help="report which fillers each condition removes.  "
                             "Needs no audio, no model and no dump, because "
                             "whether a transform deletes a token is a "
                             "property of the transform.")
    parser.add_argument("--conditions", type=_condition_list, default=None,
                        help="comma-separated conditions to score, for "
                             "example raw,pipeline_full,whisper_norm "
                             "(default: every condition in the dump).  The "
                             "shared utterance set is taken over these alone.")
    parser.add_argument("--json", dest="json_out", type=Path, default=None,
                        help="write the per-condition summary here")
    parser.add_argument("--csv", dest="csv_out", type=Path, default=None,
                        help="write the same summary as a CSV table")
    args = parser.parse_args(argv)

    if args.audit_conditions:
        audit = audit_conditions()
        width = max(len(n) for n in audit) + 2
        header = "  " + "filler".ljust(8) + "".join(
            n.rjust(width) for n in audit)
        print()
        print(header)
        print("  " + "-" * (len(header) - 2))
        for token in PROBE_TOKENS:
            print("  " + token.ljust(8) + "".join(
                ("kept" if audit[n][token] else "removed").rjust(width)
                for n in audit))
        print("\n  A condition that removes only some hesitations cannot be "
              "used to score\n  an analysis that depends on them.")
        if args.json_out:
            args.json_out.parent.mkdir(parents=True, exist_ok=True)
            args.json_out.write_text(json.dumps(
                {"filler_tokens": list(FILLER_TOKENS),
                 "probe_tokens": list(PROBE_TOKENS),
                 "conditions": audit},
                indent=2), encoding="utf-8")
            print(f"\n  written to {args.json_out}")
        return 0

    if args.dump is None:
        parser.error("a dump path is required unless --audit-conditions is given")
    if not args.dump.exists():
        print(f"  no such dump: {args.dump}", file=sys.stderr)
        return 2

    try:
        sets = score_dump_sets(args.dump, args.conditions)
    except ValueError as exc:
        print(f"  {exc}", file=sys.stderr)
        return 2
    summary = sets["conditions"]
    shared = sets["conditions_shared_set"]
    if not summary:
        print(f"  {args.dump} holds no rows", file=sys.stderr)
        return 2

    print(f"Hypothesis dump: {args.dump}")
    print("  Each condition over the utterances it holds, of "
          f"{sets['n_utterances']}:")
    print_report(summary)
    if sets["n_shared_utterances"] < sets["n_utterances"]:
        print(f"\n  Over the {sets['n_shared_utterances']} utterances every "
              "condition holds:")
        print_report(shared)
    measurable = _warn_if_unmeasurable(summary)

    if args.json_out:
        from provenance import run_metadata, sha256_file  # noqa: PLC0415
        # Read before either output is written, leaving both out of the
        # dirty check, as provenance.write_sidecar does for the CSV-only
        # writers. Without the ignore list, a second run in place counted
        # the first one's rewritten summary and table as uncommitted code
        # (audit finding OUTPUTS-12).
        run_meta = run_metadata(ignore=tuple(
            path for path in (args.json_out, args.csv_out) if path is not None))
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            # The dump holds transcript text and is not committed, so the
            # digest is what ties a summary to the file it scored; the raw
            # bytes' digest is the one sha256sum prints beside the dump.
            json.dumps({"source": args.dump.as_posix(),
                        "source_sha256": sha256_file(args.dump),
                        "conditions_selected": args.conditions,
                        "run_metadata": run_meta,
                        # The production bracketing list, for reference;
                        # the counts come from detector_pattern (XREF-08).
                        "filler_tokens": list(FILLER_TOKENS),
                        "detector_pattern": _FILLER_PATTERN.pattern,
                        "reference_source": sets["reference_source"],
                        "n_utterances": sets["n_utterances"],
                        "n_shared_utterances": sets["n_shared_utterances"],
                        "conditions": summary,
                        "conditions_shared_set": shared},
                       indent=2),
            encoding="utf-8")
        print(f"\n  summary: {args.json_out}")
    if args.csv_out:
        args.csv_out.parent.mkdir(parents=True, exist_ok=True)
        fields = ["condition", "set"] + list(next(iter(summary.values())))
        with args.csv_out.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for name, s in summary.items():
                writer.writerow({"condition": name, "set": "own", **s})
            for name, s in shared.items():
                writer.writerow({"condition": name, "set": "shared", **s})
        print(f"  table:   {args.csv_out}")

    return 0 if measurable else 1


if __name__ == "__main__":
    raise SystemExit(main())
