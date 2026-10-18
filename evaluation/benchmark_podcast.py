#!/usr/bin/env python3
"""
Reference-free structural evaluation of transcription outputs.

The *Codex Mentis* corpus (see ``evaluation/fetch_codex_mentis.py``) has no
gold transcript, so it cannot yield word error rate. It can, however,
support several rigorous checks that need no reference at all --- the ones
that catch the failure modes corpus WER hides on long-form audio. This
module scores a transcript JSON (as written by the pipeline, with
segment- and word-level timestamps and optional speaker labels) on four
structural axes:

* **Timestamp integrity** --- monotonicity of word times, the voiced time
  the words cover (and the looser segment span) against the recording,
  and inter-segment gap and overlap statistics. A backward-jumping or
  uncovered timeline is an unambiguous defect.
* **Diarisation plausibility** --- the number of speakers found against the
  number expected (two, for a NotebookLM dialogue), the number of speaker
  turns, and the talk-time balance. A wrong speaker count is a
  reference-free error.
* **Masking behaviour** --- the redaction rate on natural technical prose.
  With no injected gold this is an upper bound on the false-positive rate,
  complementing the injection benchmark (which measures recall on a known
  set but cannot estimate precision on real content).
* **Repetition** --- the longest run of identical consecutive tokens, a
  proxy for the repetition-loop hallucination Whisper produces near
  segment boundaries.

The masking function is injected, so the same masker used for the text
drives the redaction-rate measurement and the tests can substitute a stub.

Usage::

    python -m evaluation.benchmark_podcast --transcript out/ep05.json
    python -m evaluation.benchmark_podcast --transcript out/ --manifest \\
        data/codex_mentis/manifest.json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
from pathlib import Path

_DEFAULT_OUTPUT_DIR = Path("output/evaluation")
_EXPECTED_SPEAKERS = 2  # NotebookLM produces a two-voice dialogue.
# Only the masker's own placeholders count as redactions. The earlier
# pattern, any bracketed all-caps token, also counted tags Whisper writes
# itself ([MUSIC], [BLANK_AUDIO]) and so inflated the false-positive upper
# bound. The list is retyped from transcription.create_enhanced_name_masker,
# which keeps it inside the function.
_PLACEHOLDER_RE = re.compile(r"\[(?:NAME|SURNAME|TITLE)\]")


def load_transcript(path: Path) -> dict:
    """Load a transcript JSON file into a dict."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _iter_words(transcript: dict) -> list[dict]:
    """Return all word dicts across segments, in document order."""
    words: list[dict] = []
    for seg in transcript.get("segments", []):
        words.extend(seg.get("words", []) or [])
    return words


def _union_length(intervals) -> float:
    """Total length of the union of ``(start, end)`` intervals.

    Overlapping or touching intervals are merged first, so no stretch of
    time is counted twice; an interval with ``end <= start`` adds nothing.
    """
    total = 0.0
    current_start = current_end = None
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if current_end is None or start > current_end:
            if current_end is not None:
                total += current_end - current_start
            current_start, current_end = start, end
        else:
            current_end = max(current_end, end)
    if current_end is not None:
        total += current_end - current_start
    return total


def timestamp_metrics(transcript: dict, audio_duration_s: float | None = None) -> dict:
    """Structural checks on the word and segment timelines.

    Reports the word and segment counts, the number of monotonicity
    violations (a word starting before the previous word, or ending before
    it starts), inter-segment gap and overlap statistics, and two measures
    of how much of the timeline carries speech:

    ``speech_s``
        The union of the timed words' intervals, overlaps merged. Pauses
        between words are not speech, so this is the voiced time the
        transcript accounts for.
    ``segment_span_s``
        The union of the segment spans. Segments are caption-sized groups
        of words that may hold pauses of up to a second, so this is larger
        than ``speech_s``. It used to be reported as ``speech_s``, summed
        without merging, so overlapping segments counted twice (EPRIV-32).

    When the recording's duration is known, ``coverage_ratio`` is
    ``speech_s`` over it and ``segment_coverage_ratio`` the segment
    measure over it, with ``end_drift_s`` the time after the last segment.
    ``median_gap_s`` is the median of the gaps between consecutive
    segments (the mean of the middle two for an even count).
    """
    segments = transcript.get("segments", [])
    words = _iter_words(transcript)

    timed = [w for w in words if w.get("start") is not None and w.get("end") is not None]
    violations = 0
    prev_start = None
    for w in timed:
        s, e = float(w["start"]), float(w["end"])
        if e < s:
            violations += 1
        if prev_start is not None and s < prev_start - 1e-6:
            violations += 1
        prev_start = s

    seg_spans = [(float(s["start"]), float(s["end"]))
                 for s in segments
                 if s.get("start") is not None and s.get("end") is not None]
    speech_s = _union_length((float(w["start"]), float(w["end"])) for w in timed)
    segment_span_s = _union_length(seg_spans)
    gaps = [seg_spans[i + 1][0] - seg_spans[i][1] for i in range(len(seg_spans) - 1)]
    overlaps = sum(1 for g in gaps if g < -1e-6)
    span_end = max((e for _, e in seg_spans), default=0.0)

    metrics = {
        "n_segments": len(segments),
        "n_words": len(words),
        "n_words_timed": len(timed),
        "monotonicity_violations": violations,
        "n_overlaps": overlaps,
        "max_gap_s": round(max(gaps), 3) if gaps else 0.0,
        "median_gap_s": round(statistics.median(gaps), 3) if gaps else 0.0,
        "speech_s": round(speech_s, 2),
        "segment_span_s": round(segment_span_s, 2),
        "span_end_s": round(span_end, 2),
    }
    if audio_duration_s:
        duration = float(audio_duration_s)
        metrics["audio_duration_s"] = round(duration, 2)
        metrics["coverage_ratio"] = round(speech_s / duration, 4)
        metrics["segment_coverage_ratio"] = round(segment_span_s / duration, 4)
        metrics["end_drift_s"] = round(duration - span_end, 2)
    return metrics


def diarisation_metrics(transcript: dict,
                        expected_speakers: int = _EXPECTED_SPEAKERS) -> dict:
    """Speaker-count and turn statistics from segment speaker labels."""
    segments = transcript.get("segments", [])
    labelled = [s for s in segments if s.get("speaker")]
    if not labelled:
        return {"has_speakers": False}

    speakers = sorted({s["speaker"] for s in labelled})
    turns = 1
    for i in range(1, len(labelled)):
        if labelled[i]["speaker"] != labelled[i - 1]["speaker"]:
            turns += 1

    per_speaker: dict[str, float] = {}
    for s in labelled:
        if s.get("start") is not None and s.get("end") is not None:
            per_speaker[s["speaker"]] = per_speaker.get(s["speaker"], 0.0) + \
                (float(s["end"]) - float(s["start"]))

    return {
        "has_speakers": True,
        "n_speakers": len(speakers),
        "expected_speakers": expected_speakers,
        "speaker_count_error": abs(len(speakers) - expected_speakers),
        "n_turns": turns,
        "talk_time_s": {k: round(v, 1) for k, v in sorted(per_speaker.items())},
    }


def masking_metrics(transcript: dict, mask_fn) -> dict:
    """Redaction rate when the masker is run over the full transcript text.

    On natural prose with no injected names this is an upper bound on the
    false-positive rate: some redactions may be genuine names, but a high
    rate on technical content signals over-masking of capitalised terms.

    Parameters
    ----------
    transcript:
        A transcript payload.
    mask_fn:
        The masking function, or ``None`` when no masker could be loaded.

    Returns
    -------
    dict
        ``n_tokens``, ``n_redacted`` and ``redaction_rate``. When there is
        no masker, or it raised, the last two are ``None`` and
        ``masking_error`` says why: scoring the unmasked text would report
        a rate of 0.0, which reads as a measurement of zero false
        positives.
    """
    text = transcript.get("text") or " ".join(
        seg.get("text", "") for seg in transcript.get("segments", []))
    n_tokens = len(text.split())
    if mask_fn is None:
        return {"n_tokens": n_tokens, "n_redacted": None,
                "redaction_rate": None, "masking_error": "masker unavailable"}
    if n_tokens == 0:
        return {"n_tokens": 0, "n_redacted": 0, "redaction_rate": 0.0}
    try:
        masked = mask_fn(text)
    except Exception as exc:
        return {"n_tokens": n_tokens, "n_redacted": None,
                "redaction_rate": None,
                "masking_error": f"{type(exc).__name__}: {exc}"}
    n_redacted = len(_PLACEHOLDER_RE.findall(masked))
    return {
        "n_tokens": n_tokens,
        "n_redacted": n_redacted,
        "redaction_rate": round(n_redacted / n_tokens, 5),
    }


def repetition_metrics(transcript: dict) -> dict:
    """Longest run of identical consecutive tokens (a hallucination proxy)."""
    text = transcript.get("text") or " ".join(
        seg.get("text", "") for seg in transcript.get("segments", []))
    tokens = [re.sub(r"[^\w]", "", t.lower()) for t in text.split()]
    tokens = [t for t in tokens if t]
    best = cur = 1 if tokens else 0
    for i in range(1, len(tokens)):
        if tokens[i] == tokens[i - 1]:
            cur += 1
            best = max(best, cur)
        else:
            cur = 1
    return {"max_immediate_repeat": best, "n_tokens": len(tokens)}


def analyse(transcript: dict, mask_fn, audio_duration_s: float | None = None,
            expected_speakers: int = _EXPECTED_SPEAKERS) -> dict:
    """Run all four structural analyses on one transcript."""
    return {
        "timestamps": timestamp_metrics(transcript, audio_duration_s),
        "diarisation": diarisation_metrics(transcript, expected_speakers),
        "masking": masking_metrics(transcript, mask_fn),
        "repetition": repetition_metrics(transcript),
    }


def _duration_lookup(manifest_path: Path | None) -> dict[str, float]:
    """Map episode audio basenames to durations from a fetch manifest.

    Returns ``{}`` when no manifest is named.

    Raises
    ------
    FileNotFoundError
        When *manifest_path* is given but does not exist. It used to return
        ``{}`` without a word, which dropped every coverage figure from the
        committed case-study summary unnoticed (EPRIV-23).
    """
    if not manifest_path:
        return {}
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    out: dict[str, float] = {}
    for ep in manifest.get("episodes", []):
        stem = Path(ep.get("filename", "")).stem
        if stem and ep.get("duration_s"):
            out[stem] = float(ep["duration_s"])
    return out


_EPISODE_RE = re.compile(r"(?<![a-z0-9])(ep\d+)(?!\d)", re.IGNORECASE)


def _match_duration(transcript: dict, durations: dict[str, float]
                    ) -> tuple[float | None, str]:
    """Match a transcript to its episode's duration by the audio file name.

    The transcript's ``audio_file`` stem is looked up exactly first, then
    by its episode number (``ep05``), which must pick out one manifest
    entry: the case study transcribes ``ep05_..._16k.wav``, derived from
    the manifest's ``ep05_....m4a``.

    Returns
    -------
    (duration, source)
        *source* is ``"exact"``, ``"episode"``, ``"no_audio_file"``,
        ``"ambiguous"`` or ``"unmatched"``; the duration is ``None`` for
        the last three. An empty ``audio_file`` used to match the first
        episode, because ``"" in stem`` is always true (EPRIV-23).
    """
    audio = Path(transcript.get("audio_file") or "").stem
    if not audio:
        return None, "no_audio_file"
    if audio in durations:
        return durations[audio], "exact"
    episode = _EPISODE_RE.search(audio)
    if episode:
        wanted = episode.group(1).lower()
        hits = [stem for stem in durations
                if (m := _EPISODE_RE.search(stem)) and m.group(1).lower() == wanted]
        if len(hits) == 1:
            return durations[hits[0]], "episode"
        if len(hits) > 1:
            return None, "ambiguous"
    return None, "unmatched"


def _flatten(rec: dict) -> dict:
    """Flatten the nested analysis into a single CSV row of scalars."""
    row: dict[str, object] = {}
    for group, metrics in rec.items():
        if group == "file":
            row["file"] = metrics
            continue
        for k, v in metrics.items():
            if isinstance(v, dict):
                continue  # talk_time_s stays in the JSON only
            row[f"{group}.{k}"] = v
    return row


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="evaluation.benchmark_podcast",
        description="Reference-free structural evaluation of transcription "
                    "outputs (timestamps, diarisation, masking, repetition).",
    )
    p.add_argument("--transcript", type=Path, required=True,
                   help="A transcript JSON file or a directory of them.")
    p.add_argument("--manifest", type=Path, default=None,
                   help="fetch_codex_mentis manifest, for audio durations.")
    p.add_argument("--output-dir", type=Path, default=_DEFAULT_OUTPUT_DIR,
                   help="Destination for the report/summary (default: %(default)s).")
    p.add_argument("--expected-speakers", type=int, default=_EXPECTED_SPEAKERS,
                   dest="expected_speakers",
                   help="Expected speaker count (default: %(default)s).")
    p.add_argument("--allow-no-masker", action="store_true",
                   dest="allow_no_masker",
                   help="Carry on when the name masker cannot be loaded or "
                        "fails, recording the redaction rate as null. "
                        "Without it that is an error.")
    return p


def main(argv: list[str] | None = None) -> int:
    """Score each transcript and write the report and summary.

    Returns 0 on success; 2 when there is no transcript or ``--manifest``
    names a file that does not exist or lists no episode duration; 3 when
    the masker could not be
    loaded or raised on a transcript and ``--allow-no-masker`` was not
    given (nothing is written in those cases). A transcript the manifest
    has no duration for is scored without coverage figures, with a
    warning and its ``duration_source`` recorded. Side effects: reads
    the transcripts and manifest, builds the masker (which prints its
    database report), writes (overwriting) ``podcast_eval_summary.json``
    and ``podcast_eval_report.csv`` in ``--output-dir``.
    """
    args = _build_parser().parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    if args.transcript.is_dir():
        files = sorted(args.transcript.glob("*.json"))
    else:
        files = [args.transcript]
    if not files:
        print(f"  Error: no transcript JSON at {args.transcript}", file=sys.stderr)
        return 2

    # Checked before the masker is built, which is the slow step.
    try:
        durations = _duration_lookup(args.manifest)
    except FileNotFoundError as exc:
        # Asked for durations and given none: carrying on would drop every
        # coverage figure without a word (EPRIV-23).
        print(f"  Error: {exc}", file=sys.stderr)
        return 2
    if args.manifest and not durations:
        # The same loss by another route: a manifest that names no episode
        # with a duration would leave every transcript without coverage
        # figures, and with no warning, since there is nothing to match.
        print(f"  Error: manifest lists no episode duration: {args.manifest}",
              file=sys.stderr)
        return 2

    try:
        from transcription import create_enhanced_name_masker  # noqa: PLC0415
        mask_fn, _ = create_enhanced_name_masker()
    except Exception as exc:
        if not args.allow_no_masker:
            print(f"  Error: masker unavailable ({exc}); pass "
                  "--allow-no-masker to score without it.", file=sys.stderr)
            return 3
        print(f"  Warning: masker unavailable ({exc}); redaction rate "
              "recorded as null.", file=sys.stderr)
        mask_fn = None

    records = []
    for f in files:
        transcript = load_transcript(f)
        duration, source = _match_duration(transcript, durations)
        if durations and duration is None:
            print(f"  Warning: {f.name}: no episode duration "
                  f"({source}: audio_file {transcript.get('audio_file')!r}); "
                  "coverage not computed.", file=sys.stderr)
        rec = analyse(transcript, mask_fn, duration, args.expected_speakers)
        rec["file"] = f.name
        # Where the duration came from, or why there is none; recorded only
        # when a manifest was given, so a run without one is unchanged.
        if durations:
            rec["timestamps"]["duration_source"] = source
        records.append(rec)
        ts, di, ma = rec["timestamps"], rec["diarisation"], rec["masking"]
        if ma.get("masking_error") and not args.allow_no_masker:
            print(f"  Error: masking failed on {f.name} "
                  f"({ma['masking_error']}); pass --allow-no-masker to "
                  "record it as null.", file=sys.stderr)
            return 3
        spk = di.get("n_speakers", "-") if di.get("has_speakers") else "-"
        rate = ma["redaction_rate"]
        rate_text = "n/a" if rate is None else f"{rate:.3f}"
        print(f"  {f.name[:44]:<44}  words={ts['n_words']:<5} "
              f"mono_viol={ts['monotonicity_violations']:<3} "
              f"speakers={spk} redact={rate_text}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary = {"n_transcripts": len(records), "per_file": records}
    (args.output_dir / "podcast_eval_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    rows = [_flatten(r) for r in records]
    fields = sorted({k for r in rows for k in r})
    with open(args.output_dir / "podcast_eval_report.csv", "w",
              encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  report:  {args.output_dir / 'podcast_eval_report.csv'}")
    print(f"  summary: {args.output_dir / 'podcast_eval_summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
