#!/usr/bin/env python3
"""
Word Error Rate (WER) evaluation for hypothesis transcripts.

This module benchmarks the system's hypothesis transcripts against a
reference ("ground truth") corpus using ``jiwer``. To make comparisons
scientifically valid, both sides are passed through a shared
normalisation layer (Unicode folding, lower-casing, punctuation stripping,
whitespace collapsing, optional number-word handling) *before* scoring.

Typical use::

    python -m evaluation.wer \
        --hypothesis output/transcripts \
        --reference   data/ground_truth \
        --report      output/wer_report.csv

Transcripts may be ``.txt``, ``.json`` (the ``text`` field, or the
segments' texts) or ``.vtt`` (the cue text; the header, cue timings,
identifiers, notes and markup are dropped). When a directory holds one
recording in several formats, as ``transcription.py``'s output directory
does (``<stem>_transcript.txt``, ``.json`` and ``.vtt``), only one of them
is scored, ``.txt`` first unless ``--hypothesis-format`` says otherwise,
so a recording is not counted twice.

The default outputs are ``output/evaluation/wer_report_transcripts.csv``
and ``wer_summary_transcripts.json``, deliberately not
``wer_report.csv`` / ``wer_summary.json``. Those names hold the
manuscript's headline pair, the condition sweep's raw Whisper Large v3
cell on LibriSpeech test-clean, copied under them (audit findings EWER-11
and OUTPUTS-03).

The module is deliberately small and import-light so it can run on an
HPC head node, inside a SLURM job, or on a laptop without the audio
stack installed.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import Path
from collections.abc import Iterable, Mapping

try:
    import jiwer
except ImportError:  # pragma: no cover - depends on the environment
    # Only the scoring step needs jiwer. Deferring the failure to
    # compute_metrics lets normalise_text, the aggregation and the writers
    # be imported and tested where jiwer is absent; the failure is still an
    # ImportError (never SystemExit, which once crashed pytest collection
    # with INTERNALERROR). A benchmark that loads a model before it scores
    # anything calls require_jiwer first, so that a missing scorer still
    # stops it before the GPU work, as the import-time failure used to.
    jiwer = None


def require_jiwer() -> None:
    """Raise ImportError when jiwer is not installed.

    Called by :func:`compute_metrics`, and at the top of the benchmarks
    that load an ASR model, so that they fail before loading it.
    """
    if jiwer is None:
        raise ImportError(
            "jiwer is required for WER scoring. Install it with "
            "`pip install jiwer`."
        )


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

# The same character class as evaluation.conditions._PUNCT_RE (the
# punct_strip condition); each module keeps its own copy because each
# pins committed numbers, and neither may move without the other being
# rescored.
_PUNCT_RE = re.compile(r"[^\w\s']", flags=re.UNICODE)
_WS_RE = re.compile(r"\s+")
# Used only by the --remove-fillers flag of this module's CLI. It is not
# the production list (transcription.FILLER_TOKENS) nor the filler_strip
# pattern (evaluation.conditions._FILLER_RE); the three differ, and
# reconciling them would move committed filler_strip cells.
_FILLER_WORDS = {"uh", "um", "erm", "ah", "eh", "mm", "hmm"}
# Strip ``[SPEAKER_00]``, ``SPEAKER_00:``, ``SPEAKER-01`` and similar
# diarisation tags so that speaker attribution does not inflate WER. The
# regex covers the bracketed form emitted by ``apply_speaker_labels_to_transcript``
# and the bare/voice-tag forms that may appear in VTT or hand-edited
# references.
_SPEAKER_RE = re.compile(r"\[?SPEAKER[_-]?\d+\]?:?", re.IGNORECASE)


def _strip_transcript_header(text: str) -> str:
    """Remove the metadata header produced by ``save_transcript_file``.

    Headers are delimited by a line of ``=`` characters. If two such
    separators are present we keep only the body that follows the second.
    """
    parts = re.split(r"\n=+\n", text)
    if len(parts) >= 3:
        return parts[-1]
    return text


def normalise_text(
    text: str,
    *,
    lowercase: bool = True,
    strip_punctuation: bool = True,
    remove_fillers: bool = False,
    strip_header: bool = True,
) -> str:
    """Return a normalised version of ``text`` suitable for WER scoring.

    The steps run in this order, and the order matters, because the same
    function is applied to reference and hypothesis and the score is only
    fair if both sides go through identical steps:

    1. With *strip_header*, drop the ``save_transcript_file`` metadata
       header (see :func:`_strip_transcript_header`).
    2. Replace diarisation speaker tags with a space, before punctuation
       stripping could splinter them into stray tokens.
    3. Apply Unicode NFKC normalisation.
    4. Map the curly single quotation marks U+2018 and U+2019 to ``'``.
    5. With *lowercase*, lower-case.
    6. With *strip_punctuation*, replace every character that is not a
       word character, whitespace or ``'`` with a space. Apostrophes are
       kept, so ``don't`` stays one token, but so are quotation marks
       typed as apostrophes: ``'Yes,' she said`` gives ``'yes ' she
       said``, with a stray ``'`` token.
    7. With *remove_fillers*, drop the tokens in :data:`_FILLER_WORDS`.
    8. Collapse whitespace and strip.

    ``None`` returns the empty string.
    """
    if text is None:
        return ""
    if strip_header:
        text = _strip_transcript_header(text)
    # Remove diarisation speaker tags before any other rewriting so that
    # punctuation stripping does not splinter them into stray tokens.
    text = _SPEAKER_RE.sub(" ", text)
    # NFKC folds compatibility forms (ligatures, full-width letters, the
    # no-break space) into their plain equivalents and composes a letter
    # and a combining accent into one character, so both Unicode spellings
    # of an accented word score alike. It keeps accents, and it leaves the
    # curly quotation marks unchanged. The replace that follows maps the
    # single ones, U+2018 and U+2019, to "'", which punctuation stripping
    # keeps. U+2019 is also the typographic apostrophe, so a contraction
    # typed with it stays one token. The double ones, U+201C and U+201D,
    # are left to punctuation stripping.
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    if lowercase:
        text = text.lower()
    if strip_punctuation:
        text = _PUNCT_RE.sub(" ", text)
    if remove_fillers:
        tokens = [t for t in text.split() if t not in _FILLER_WORDS]
        text = " ".join(tokens)
    text = _WS_RE.sub(" ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

@dataclass
class PairResult:
    """Result of comparing a single hypothesis/reference pair."""

    name: str
    wer: float
    mer: float
    wil: float
    cer: float
    hits: int
    substitutions: int
    deletions: int
    insertions: int
    reference_words: int
    hypothesis_words: int


def compute_metrics(reference: str, hypothesis: str) -> dict:
    """Return WER/MER/WIL/CER plus alignment counts for one pair.

    Both strings are expected to be normalised already.

    Raises
    ------
    ValueError
        If *reference* is empty or whitespace.
    ImportError
        If jiwer is not installed.
    """
    if not reference.strip():
        raise ValueError("Reference text is empty after normalisation.")
    require_jiwer()
    out = jiwer.process_words(reference, hypothesis)
    cer = jiwer.cer(reference, hypothesis)
    return {
        "wer": float(out.wer),
        "mer": float(out.mer),
        "wil": float(out.wil),
        "cer": float(cer),
        "hits": int(out.hits),
        "substitutions": int(out.substitutions),
        "deletions": int(out.deletions),
        "insertions": int(out.insertions),
        "reference_words": int(out.hits + out.substitutions + out.deletions),
        "hypothesis_words": int(out.hits + out.substitutions + out.insertions),
    }


#: Transcript formats this module reads, in the order preferred when one
#: recording is present in several.
FORMAT_PREFERENCE = (".txt", ".json", ".vtt")

# A WebVTT cue timing line: "00:00:01.000 --> 00:00:02.500" (hours
# optional), possibly followed by cue settings. A comma before the
# milliseconds is accepted too, as SRT writes it.
_VTT_TIMING_RE = re.compile(
    r"^\s*(?:\d+:)?\d{1,2}:\d{2}[.,]\d{3}\s+-->\s+(?:\d+:)?\d{1,2}:\d{2}[.,]\d{3}")
# Cue markup: voice spans (<v SPEAKER_00>), classes, italics and inline
# timestamps (<00:00:01.000>).
_VTT_TAG_RE = re.compile(r"<[^>]*>")


def _vtt_text(raw: str) -> str:
    """Return the cue text of a WebVTT document, cues joined by spaces.

    Blocks are separated by blank lines. A block counts as a cue only if
    it holds a timing line; the lines after it are the cue text, from
    which markup is removed and HTML entities (``&amp;``) are decoded.
    Everything else, the ``WEBVTT`` header, ``NOTE``, ``STYLE`` and
    ``REGION`` blocks and cue identifiers, is dropped. Read as plain text,
    each cue used to add its two timestamps as eight numeric tokens plus
    ``webvtt``, each scored as a deletion (audit finding EWER-07).
    """
    texts = []
    for block in re.split(r"\n[ \t]*\n", raw.lstrip("\ufeff").replace("\r\n", "\n")):
        lines = block.split("\n")
        timing = next((i for i, line in enumerate(lines)
                       if _VTT_TIMING_RE.match(line)), None)
        if timing is None:
            continue
        cue = " ".join(html.unescape(_VTT_TAG_RE.sub("", line)).strip()
                       for line in lines[timing + 1:])
        if cue.strip():
            texts.append(cue.strip())
    return " ".join(texts)


def _read_text(path: Path) -> str:
    """Return the transcript text of *path*.

    A ``.json`` file yields its ``text`` field, or failing that its
    segments' texts joined by spaces (an empty string for any other JSON
    shape); a ``.vtt`` file yields its cue text (:func:`_vtt_text`); any
    other file is read whole as UTF-8.
    """
    suffix = path.suffix.lower()
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        # Prefer the raw `text` field written by `write_timestamped_outputs`,
        # falling back to a concatenation of segments.
        if isinstance(payload, dict):
            if payload.get("text"):
                return str(payload["text"])
            segs = payload.get("segments") or []
            return " ".join(s.get("text", "") for s in segs if isinstance(s, dict))
        return ""
    if suffix == ".vtt":
        return _vtt_text(path.read_text(encoding="utf-8"))
    return path.read_text(encoding="utf-8")


def evaluate_pair(
    reference_path: Path,
    hypothesis_path: Path,
    *,
    normaliser_kwargs: Mapping | None = None,
) -> PairResult:
    """Score a single reference/hypothesis pair.

    Returns a :class:`PairResult` named after the hypothesis stem. Raises
    ``ValueError`` when the reference is empty after normalisation.
    """
    kwargs = dict(normaliser_kwargs or {})
    ref = normalise_text(_read_text(reference_path), **kwargs)
    hyp = normalise_text(_read_text(hypothesis_path), **kwargs)
    metrics = compute_metrics(ref, hyp)
    return PairResult(name=hypothesis_path.stem, **metrics)


def _one_per_stem(directory: Path, formats: tuple[str, ...],
                  label: str) -> dict[str, Path]:
    """Return ``{stem: path}`` with one file per stem, in format preference.

    When a stem is present in several of *formats*, the earliest in
    *formats* is kept and the choice is printed to stderr, naming the files
    left out.
    """
    by_stem: dict[str, dict[str, Path]] = {}
    for path in sorted(directory.iterdir()):
        suffix = path.suffix.lower()
        if path.is_file() and suffix in formats:
            by_stem.setdefault(path.stem, {})[suffix] = path
    chosen: dict[str, Path] = {}
    for stem, versions in by_stem.items():
        keep = next(versions[s] for s in formats if s in versions)
        if len(versions) > 1:
            dropped = sorted(p.name for p in versions.values() if p != keep)
            print(f"  {label} {stem!r} is present as {keep.name} and "
                  f"{', '.join(dropped)}; scoring {keep.name} only",
                  file=sys.stderr)
        chosen[stem] = keep
    return chosen


def _match_files(ref_dir: Path, hyp_dir: Path,
                 hypothesis_format: str | None = None) -> list[tuple[Path, Path]]:
    """Pair reference and hypothesis files by stem, one pair per reference.

    A hypothesis stem ``foo_transcript`` is matched to a reference stem
    ``foo`` or ``foo_transcript``. Each recording is scored once: of the
    formats present for one stem (``transcription.py`` writes ``.txt``,
    ``.json`` and ``.vtt`` side by side) only the preferred is used,
    ``.txt`` first, or only *hypothesis_format* (``"txt"``, ``"json"`` or
    ``"vtt"``) when given; and when two hypothesis stems resolve to the same
    reference (``foo`` and ``foo_transcript``), only the first in sorted
    order is paired. Both choices are announced on stderr. Scoring every
    format used to count such a recording two or three times in the corpus
    WER (audit finding NEW-01).
    """
    hyp_formats = (FORMAT_PREFERENCE if hypothesis_format is None
                   else ("." + hypothesis_format.lower().lstrip("."),))
    refs = _one_per_stem(ref_dir, FORMAT_PREFERENCE, "reference")
    hyps = _one_per_stem(hyp_dir, hyp_formats, "hypothesis")
    pairs: list[tuple[Path, Path]] = []
    paired: dict[Path, Path] = {}
    for stem in sorted(hyps):
        hyp = hyps[stem]
        candidates = [stem, stem.replace("_transcript", ""),
                      stem.removesuffix("_transcript")]
        ref_path = next((refs[c] for c in candidates if c in refs), None)
        if ref_path is None:
            continue
        if ref_path in paired:
            print(f"  hypothesis {hyp.name} would also pair with "
                  f"{ref_path.name}, already paired with "
                  f"{paired[ref_path].name}; not scored", file=sys.stderr)
            continue
        paired[ref_path] = hyp
        pairs.append((ref_path, hyp))
    return pairs


def evaluate_directory(
    reference_dir: Path,
    hypothesis_dir: Path,
    *,
    normaliser_kwargs: Mapping | None = None,
    hypothesis_format: str | None = None,
) -> list[PairResult]:
    """Pair files in two directories by stem and score each pair.

    See :func:`_match_files` for the pairing, including which of several
    formats of one recording is scored (*hypothesis_format*). A pair that
    fails to score is skipped with a message on stderr.

    Raises
    ------
    FileNotFoundError
        When no reference and hypothesis share a stem.
    """
    pairs = _match_files(reference_dir, hypothesis_dir, hypothesis_format)
    if not pairs:
        raise FileNotFoundError(
            f"No matching reference/hypothesis pairs found in "
            f"{reference_dir} vs {hypothesis_dir}."
        )
    results: list[PairResult] = []
    for ref, hyp in pairs:
        try:
            results.append(evaluate_pair(ref, hyp,
                                         normaliser_kwargs=normaliser_kwargs))
        except Exception as e:  # pragma: no cover
            print(f"  ⚠️  Skipping {hyp.name}: {e}", file=sys.stderr)
    return results


def aggregate(results: Iterable[PairResult]) -> dict:
    """Return a corpus-level summary across pair results.

    Macro-averaged metrics are the unweighted mean of the per-pair values
    and are reported for all four metrics (WER, MER, WIL, CER).  Micro
    (pooled) WER and MER are computed here from the pooled alignment
    counts.  Pooled WIL is not computed, although the stored totals
    determine it: ``1 - (H / N_ref) * (H / N_hyp)`` with ``H =
    total_hits``, ``N_ref = total_reference_words`` and ``N_hyp =
    total_hypothesis_words``.  Pooled CER cannot be derived, because
    per-pair character counts are not stored.

    Returns an empty dict for no results; otherwise the keys ``files``,
    ``macro_wer``, ``micro_wer``, ``macro_mer``, ``micro_mer``,
    ``macro_wil``, ``macro_cer`` and the ``total_*`` counts.  Micro
    values are NaN when their denominator is zero.
    """
    rs = list(results)
    if not rs:
        return {}
    total_hit = sum(r.hits for r in rs)
    total_sub = sum(r.substitutions for r in rs)
    total_del = sum(r.deletions for r in rs)
    total_ins = sum(r.insertions for r in rs)
    total_ref = sum(r.reference_words for r in rs)
    total_hyp = sum(r.hypothesis_words for r in rs)
    total_err = total_sub + total_del + total_ins
    micro_wer = total_err / total_ref if total_ref else float("nan")
    micro_mer = (
        total_err / (total_err + total_hit)
        if (total_err + total_hit)
        else float("nan")
    )
    n = len(rs)
    return {
        "files": n,
        "macro_wer": sum(r.wer for r in rs) / n,
        "micro_wer": micro_wer,
        "macro_mer": sum(r.mer for r in rs) / n,
        "micro_mer": micro_mer,
        "macro_wil": sum(r.wil for r in rs) / n,
        "macro_cer": sum(r.cer for r in rs) / n,
        "total_reference_words": total_ref,
        "total_hypothesis_words": total_hyp,
        "total_hits": total_hit,
        "total_substitutions": total_sub,
        "total_deletions": total_del,
        "total_insertions": total_ins,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def write_csv(results: Iterable[PairResult], path: Path) -> None:
    """Write one row per pair result to *path*.

    The columns are the :class:`PairResult` fields in declaration order
    (``name, wer`` only when *results* is empty). Creates the parent
    directory and overwrites *path*.
    """
    rs = list(results)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(asdict(rs[0]).keys()) if rs else ["name", "wer"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in rs:
            writer.writerow(asdict(r))


def write_summary_json(results: Iterable[PairResult], path: Path,
                       evaluation: Mapping | None = None,
                       run_meta: Mapping | None = None) -> None:
    """Write ``{"summary": aggregate(results), "per_file": [...]}`` to *path*.

    *evaluation*, when given, is written as an ``evaluation`` block (what
    was compared and how it was normalised) and *run_meta* as
    ``run_metadata`` (:func:`provenance.run_metadata`). The block is named
    ``evaluation`` and not ``benchmark``, so this summary cannot be taken
    for a corpus benchmark's. Creates the parent directory and overwrites
    *path*.
    """
    rs = list(results)
    payload: dict = {}
    if evaluation is not None:
        payload["evaluation"] = dict(evaluation)
    payload["summary"] = aggregate(rs)
    payload["per_file"] = [asdict(r) for r in rs]
    if run_meta is not None:
        payload["run_metadata"] = dict(run_meta)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="evaluation.wer",
        description="Compute Word Error Rate (WER) against ground-truth transcripts.",
    )
    p.add_argument("--hypothesis", required=True,
                   help="Hypothesis transcript file or directory.")
    p.add_argument("--reference", required=True,
                   help="Reference transcript file or directory.")
    # Not wer_report.csv / wer_summary.json: those names hold the
    # manuscript's headline pair, the sweep's raw Large v3 test-clean cell.
    # The manuscript's load-wer-ci chunk checks the summary's benchmark
    # block and stops the render when it does not describe that run, so a
    # summary from this module, which has no benchmark block, is refused
    # there. A run written under those names would still replace the
    # committed pair (audit finding EWER-11).
    p.add_argument("--report",
                   default="output/evaluation/wer_report_transcripts.csv",
                   help="Path for the per-file CSV report "
                        "(default: %(default)s).")
    p.add_argument("--summary",
                   default="output/evaluation/wer_summary_transcripts.json",
                   help="Path for the JSON corpus-level summary "
                        "(default: %(default)s).")
    p.add_argument("--hypothesis-format", choices=("txt", "json", "vtt"),
                   default=None,
                   help="Score only hypothesis files of this format.  By "
                        "default one file per recording is scored, .txt "
                        "first, then .json, then .vtt.")
    p.add_argument("--keep-case", action="store_true",
                   help="Do not lowercase before comparison.")
    p.add_argument("--keep-punctuation", action="store_true",
                   help="Do not strip punctuation before comparison.")
    p.add_argument("--remove-fillers", action="store_true",
                   help="Discard the filler tokens in _FILLER_WORDS "
                        "(uh, um, erm, ah, eh, mm, hmm).")
    return p


def main(argv: list[str] | None = None) -> int:
    """Run the command-line interface.

    Scores one file pair or two directories paired by stem, writes the
    ``--report`` CSV and ``--summary`` JSON (overwriting them; the summary
    records what was compared, the normaliser settings and
    :func:`provenance.run_metadata`) and prints the corpus summary.
    Returns ``0``; raises ``SystemExit`` when the two paths are not both
    files or both directories, and ``FileNotFoundError`` when two
    directories share no stem. Runs ``git`` to record the commit.
    """
    args = _build_parser().parse_args(argv)
    normaliser_kwargs = {
        "lowercase": not args.keep_case,
        "strip_punctuation": not args.keep_punctuation,
        "remove_fillers": args.remove_fillers,
    }
    hyp = Path(args.hypothesis)
    ref = Path(args.reference)

    if hyp.is_file() and ref.is_file():
        results = [evaluate_pair(ref, hyp, normaliser_kwargs=normaliser_kwargs)]
    elif hyp.is_dir() and ref.is_dir():
        results = evaluate_directory(ref, hyp, normaliser_kwargs=normaliser_kwargs,
                                     hypothesis_format=args.hypothesis_format)
    else:
        raise SystemExit(
            "Both --hypothesis and --reference must be either files or directories."
        )

    from provenance import run_metadata  # noqa: PLC0415

    report_path, summary_path = Path(args.report), Path(args.summary)
    # The git state is read before either file is written and leaves both
    # out, as provenance.write_sidecar does for the CSV-only writers. It
    # used to be read after the report had been written, so a regeneration
    # in place of a tracked pair counted either file as a change to the tree
    # whenever it differed from its committed copy.
    run_meta = run_metadata(ignore=(report_path, summary_path))
    write_csv(results, report_path)
    write_summary_json(
        results, summary_path,
        evaluation={"tool": "evaluation.wer",
                    "reference": str(ref), "hypothesis": str(hyp),
                    "hypothesis_format": args.hypothesis_format,
                    "normaliser": normaliser_kwargs},
        run_meta=run_meta,
    )

    summary = aggregate(results)
    print("WER evaluation")
    print("--------------")
    print(f"  Files scored:       {summary.get('files', 0)}")
    print(f"  Macro-averaged WER: {summary.get('macro_wer', float('nan')):.4f}")
    print(f"  Micro-averaged WER: {summary.get('micro_wer', float('nan')):.4f}")
    print(f"  Macro-averaged MER: {summary.get('macro_mer', float('nan')):.4f}")
    print(f"  Macro-averaged WIL: {summary.get('macro_wil', float('nan')):.4f}")
    print(f"  Macro-averaged CER: {summary.get('macro_cer', float('nan')):.4f}")
    print(f"  Reference words:    {summary.get('total_reference_words', 0)}")
    print(f"  Per-file report:    {args.report}")
    print(f"  Summary JSON:       {args.summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
