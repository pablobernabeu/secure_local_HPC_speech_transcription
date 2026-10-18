#!/usr/bin/env python3
"""
Flag transcript segments that warrant a human look.

Whisper-family models fail in characteristic ways rather than at random.
On silence, music, or badly degraded audio they do not fall silent; they
emit fluent, well-formed text that was never spoken, and they loop short
phrases. Such a segment reads no differently from a correct one, so a
researcher scanning a long transcript has nothing to draw their attention
to it. This module supplies that: a review layer that marks the segments
whose shape is characteristic of those failures.

On the confidence signal actually available
-------------------------------------------
Whisper computes an average log probability and a no-speech probability
per segment, and uses them internally to decide whether to retry decoding
at a higher temperature. They are not, however, surfaced by the
``transformers`` automatic-speech-recognition pipeline that this workflow
uses: its post-processing step returns the text and the timestamped
chunks and discards the rest. Reading them would mean bypassing the
pipeline and calling ``model.generate`` with ``return_segments=True``,
which is a larger change to the transcription path than this layer
warrants.

The flags below are therefore computed from what the pipeline does
return, the text and its timings, and they are heuristics rather than
model confidence. They are deliberately shaped to have few false
negatives on the failure they target and are offered as an aid to review,
not as a measurement of correctness. Where a true confidence value is
wanted, ``return_segments=True`` is the route, and this module's interface
would not need to change to accommodate it.

Usage::

    python -m confidence output/transcripts/interview_transcript.json
    python -m confidence transcript.json --min-duration 3.0 --json review.json
    python -m confidence transcript.json --flag-zero-duration \
        --repeated-passage-words 8 --repeated-passage-window 60 --json review_new.json

The two checks in the last example are optional. They address the unflagged
repeated passages described in ``output/case_study/README.md`` (NEW-12), but
their precision has not been measured on annotated recordings. They leave
the words and timings alone; listen to the audio before treating a repeated
passage as a recognition error. Existing reviews use neither check.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import unicodedata
from collections import defaultdict, deque
from pathlib import Path

# A segment lasting at least this long while carrying almost no words is the
# signature of decoding over silence or music.
_LONG_SEGMENT_S = 2.5
# Words per second. Ordinary speech sits around 2 to 4; the bounds are set
# wide so that only implausible values are flagged.
_MIN_RATE = 0.5
_MAX_RATE = 7.0
# Han characters and kana per second, the upper bound for text in scripts
# written without spaces between words. Each such character is about one
# syllable or mora, and ordinary speech runs at roughly five syllables per
# second in Mandarin and eight morae per second in Japanese (Pellegrino,
# Coupé & Marsico, 2011, Language 87(3), 539-558). The bound keeps the
# word bound's margin over ordinary speech (7 against 4, a factor of 1.75)
# above the faster of the two: 1.75 x 8 = 14. Not validated on a Chinese
# or Japanese corpus.
_MAX_CHAR_RATE = 14.0
# A token repeated at least this many times in a row is a decoding loop
# rather than emphasis.
_REPEAT_RUN = 3
# A minute is a provisional review window, not a fitted error threshold.
# Both the passage length and this window remain opt-in (NEW-12).
_PASSAGE_WINDOW_S = 60.0

# Han ideographs (unified, extensions and compatibility) and kana, the
# characters counted one by one for the speech rate: in Chinese and
# Japanese a run of them is a whole clause, not a word, so counting runs
# made ordinary speech look like near-silence (audit finding CORE-09).
_SYLLABIC_CHARS = (
    "\U00003040-\U000030FF"  # hiragana and katakana
    "\U000031F0-\U000031FF"  # katakana phonetic extensions
    "\U00003400-\U00004DBF"  # CJK unified ideographs extension A
    "\U00004E00-\U00009FFF"  # CJK unified ideographs
    "\U0000F900-\U0000FAFF"  # CJK compatibility ideographs
    "\U0000FF66-\U0000FF9D"  # halfwidth katakana
    "\U00020000-\U0003134F"  # CJK unified ideographs extensions B to G
)
_SYLLABIC_RE = re.compile(f"[{_SYLLABIC_CHARS}]")

# Scripts also written without spaces between words, for which no rate unit
# has been validated: a character is well below a syllable, and a run is a
# phrase. The rate flags are not raised for a segment in these scripts, and
# the summary counts how many segments were skipped.
_UNSPACED_SCRIPTS_RE = re.compile(
    "["
    "\U00000E00-\U00000E7F"  # Thai
    "\U00000E80-\U00000EFF"  # Lao
    "\U00001000-\U0000109F"  # Myanmar
    "\U00001780-\U000017FF"  # Khmer
    "\U000019E0-\U000019FF"  # Khmer symbols
    "]")


def _is_word_char(ch: str) -> bool:
    """Return whether *ch* is a letter as ``[^\\W\\d_]`` defines it."""
    return ch.isalnum() and not ch.isdecimal()


def _tokens(text: str) -> list[str]:
    """Return lower-cased word tokens, ignoring punctuation and digits.

    A token is a run of letters (``[^\\W\\d_]``), and a combining mark
    continues the token it follows. Marks are not word characters to
    Python's ``re``, so the plain ``[^\\W\\d_]+`` pattern this replaced cut
    Devanagari, Thai and every other script that writes vowels as marks
    into fragments at each vowel sign (the two words "नमस्ते दुनिया" became
    five tokens), which inflated the speech rate. Text without combining
    marks, English and NFC-composed Latin among it, is tokenised exactly
    as before.
    """
    tokens: list[str] = []
    current: list[str] = []
    for ch in text or "":
        if _is_word_char(ch) or (current and unicodedata.category(ch)[0] == "M"):
            current.append(ch)
        elif current:
            tokens.append("".join(current).lower())
            current = []
    if current:
        tokens.append("".join(current).lower())
    return tokens


def _rate_units(tokens: list[str]) -> tuple[int, int, bool]:
    """Return ``(words, characters, unvalidated)`` for the speech rate.

    Han characters and kana are counted one by one (*characters*); every
    other stretch of a token counts as one word, so an English segment's
    words equal its tokens. *unvalidated* is true when a token is in a
    script listed in :data:`_UNSPACED_SCRIPTS_RE`, for which neither unit
    measures speech.
    """
    words = chars = 0
    unvalidated = False
    for token in tokens:
        n_syllabic = len(_SYLLABIC_RE.findall(token))
        chars += n_syllabic
        words += len(_SYLLABIC_RE.sub(" ", token).split()) if n_syllabic else 1
        if _UNSPACED_SCRIPTS_RE.search(token):
            unvalidated = True
    return words, chars, unvalidated


def _max_immediate_repeat(tokens: list[str]) -> int:
    """Return the length of the longest run of one repeated token."""
    best = run = 1 if tokens else 0
    for i in range(1, len(tokens)):
        if tokens[i] == tokens[i - 1]:
            run += 1
            best = max(best, run)
        else:
            run = 1
    return best


def _max_phrase_repeat(tokens: list[str], max_n: int = 4) -> int:
    """Return the longest run of one repeated phrase, counted in repetitions.

    A single-token check misses the commoner loop, where a short phrase
    rather than one word is repeated: "and then and then and then". Every
    phrase length from two up to *max_n* is tried, and the longest run of
    consecutive identical phrases is reported. A run of one means no
    repetition, matching :func:`_max_immediate_repeat`.
    """
    best = 1 if tokens else 0
    for n in range(2, max_n + 1):
        if len(tokens) < 2 * n:
            break
        i = 0
        while i + n <= len(tokens):
            phrase = tokens[i:i + n]
            run = 1
            j = i + n
            while tokens[j:j + n] == phrase:
                run += 1
                j += n
            best = max(best, run)
            i = j if run > 1 else i + 1
    return best


def _normalised(text: str) -> str:
    return " ".join(_tokens(text))


def _finite_time(value) -> float | None:
    """Read a finite cue time without accepting booleans as timestamps."""
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def _usable_span(segment: dict) -> tuple[float, float] | None:
    """Return finite, ordered cue times, or None when they cannot be used."""
    start, end = _finite_time(segment.get("start")), _finite_time(segment.get("end"))
    if start is None or end is None or end < start:
        return None
    return start, end


def _passage_tokens(text: str) -> list[str]:
    """Use the existing letter/mark tokenizer, retaining numerical differences.

    The older text flags omit digits. A long passage about 10 participants
    followed by one about 20 should not be labelled a repeated passage on
    that account. Signed numbers, leading-dot decimals and simple scientific
    notation therefore remain tokens here, including a Unicode minus sign;
    punctuation and case elsewhere are still ignored. Numeric spellings
    are preserved, so this does not equate mathematically equivalent forms.
    """
    tokens = []
    previous = 0
    for match in re.finditer(
            r"[+\-\u2212]?(?:\d+(?:[.,:]\d+)*|\.\d+)(?:[eE][+\-\u2212]?\d+)?",
            text or ""):
        tokens.extend(_tokens(text[previous:match.start()]))
        tokens.append(match.group())
        previous = match.end()
    tokens.extend(_tokens((text or "")[previous:]))
    return tokens


def _repeated_passage_links(segments, width: int, window_s: float) -> dict[int, tuple[int, ...]]:
    """Find non-overlapping repeated token runs across usable timed cues.

    The window compares the start times of the cues containing each run's
    first token. Missing, invalid or decreasing cue starts break the stream:
    text across those gaps is never assembled into a putative passage.
    Each flagged cue links to the first partner run found, not every match.

    A sliding index expires old runs once, and tests only the earliest
    remaining occurrence of each token tuple. For a fixed *width* this is
    linear in the token count, including on long runs of identical words;
    it does not compare every pair of cues. Memory holds the active window,
    the rolling token run and one partner tuple per flagged cue. When many
    cues share one timestamp the active window can contain the whole text.
    """
    links: dict[int, tuple[int, ...]] = {}
    rolling = deque(maxlen=width)
    active = deque()
    occurrences = defaultdict(deque)
    position = 0
    previous_start = None
    for index, segment in enumerate(segments):
        span = _usable_span(segment)
        if span is None or (previous_start is not None and span[0] < previous_start):
            rolling.clear()
            active.clear()
            occurrences.clear()
            previous_start = None
            if span is None:
                continue
        previous_start = span[0]
        for token in _passage_tokens(segment.get("text") or ""):
            rolling.append((token, index, span[0]))
            position += 1
            if len(rolling) < width:
                continue
            key = tuple(item[0] for item in rolling)
            owners = tuple(dict.fromkeys(item[1] for item in rolling))
            first_start = rolling[0][2]
            first_position = position - width
            while active and active[0][1] < first_start - window_s:
                old_key, _, _ = active.popleft()
                occurrences[old_key].popleft()
                if not occurrences[old_key]:
                    del occurrences[old_key]
            previous = occurrences.get(key)
            # Overlapping windows in one occurrence cannot be two copies.
            if previous and previous[0][0] + width <= first_position:
                partner_owners = previous[0][1]
                for owner in owners:
                    links.setdefault(owner, partner_owners)
                for owner in partner_owners:
                    links.setdefault(owner, owners)
            occurrences[key].append((first_position, owners))
            active.append((key, first_start, first_position))
    return links


def flag_segments(segments, long_segment_s: float = _LONG_SEGMENT_S,
                  min_rate: float = _MIN_RATE, max_rate: float = _MAX_RATE,
                  repeat_run: int = _REPEAT_RUN,
                  max_char_rate: float = _MAX_CHAR_RATE,
                  flag_zero_duration: bool = False,
                  repeated_passage_words: int | None = None,
                  repeated_passage_window_s: float = _PASSAGE_WINDOW_S) -> list[dict]:
    """Return one record per segment that earned at least one flag.

    Each record carries the segment's index, span and text, the flags it
    raised, and the speech rate that produced them. The two rate flags need
    a usable start and end and are not raised for a segment without one,
    rather than guessed at. The text flags (``empty``,
    ``duplicate_of_previous``, ``internal_repetition``) do not depend on
    timing and are raised regardless, so a flagged record may have ``None``
    for ``start``, ``end`` and ``speech_rate``.

    The speech rate counts words, except that Han characters and kana
    count one unit each (see :func:`_rate_units`), so it is units per
    second; for text without those characters it is words per second, as
    before. Such characters are held to *max_char_rate* rather than
    *max_rate*: a segment is too fast when its words at *max_rate* and its
    characters at *max_char_rate* would need longer than it lasts. The
    rate flags are not raised for a segment in a script with no validated
    unit (Thai, Lao, Khmer, Myanmar); :func:`summarise` counts those.
    Counting a run of Chinese or Japanese characters as one word, as this
    once did, flagged ordinary speech as ``low_speech_rate`` (audit
    finding CORE-09).

    The flags are:

    ``empty``
        No word characters at all, so there is nothing to review but also
        nothing the model should have emitted.
    ``duplicate_of_previous``
        The same words as the preceding segment. Whisper repeats a segment
        when it loses its place, and a duplicated sentence in a transcript
        is rarely something the speaker said twice verbatim.
    ``internal_repetition``
        One token, or one phrase of two to four tokens, repeated
        *repeat_run* times or more in a row, the signature of a decoding
        loop.
    ``low_speech_rate``
        A long segment carrying almost no words, which is what decoding
        over silence or music looks like once the text is stripped away.
    ``high_speech_rate``
        More words than could have been spoken in the time, which usually
        means the segment's timing is wrong rather than its text.
    ``zero_duration`` (optional)
        A non-empty cue with finite, equal start and end times. Enabled
        with *flag_zero_duration*; missing or reversed times do not qualify.
    ``repeated_passage`` (optional)
        At least *repeated_passage_words* matching tokens in two distinct,
        non-overlapping runs, within *repeated_passage_window_s* seconds.
        Matching crosses cue boundaries and marks both copies. Tokens use
        the existing letter/combining-mark rules with numbers retained;
        case and punctuation are ignored. An apostrophe splits a word, so
        a contraction such as "don't" counts as two tokens and a clause
        of six or seven words with contractions can reach eight tokens.
        ``repeated_passage_with`` lists
        the partner cue indices of the first matching run for that cue.
        Missing, invalid or decreasing times break passage matching.

    Both optional checks are disabled by default, preserving historical
    reviews. The token threshold must be an integer of at least two and
    the window finite and positive. The suggested eight-token, 60-second
    setting is a review aid, not a validated classifier: genuine restated
    clauses can qualify, and altered or more distant copies can be missed.
    """
    if repeated_passage_words is not None and (
            isinstance(repeated_passage_words, bool)
            or not isinstance(repeated_passage_words, int)
            or repeated_passage_words < 2):
        raise ValueError("repeated_passage_words must be an integer of at least two")
    try:
        window_s = float(repeated_passage_window_s)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("repeated_passage_window_s must be finite and positive") from exc
    if isinstance(repeated_passage_window_s, bool) or not math.isfinite(window_s) or window_s <= 0:
        raise ValueError("repeated_passage_window_s must be finite and positive")
    segments = list(segments or [])
    passage_links = (_repeated_passage_links(segments, repeated_passage_words, window_s)
                     if repeated_passage_words is not None else {})
    flagged = []
    previous_norm = None
    for index, seg in enumerate(segments or []):
        start, end = seg.get("start"), seg.get("end")
        text = seg.get("text") or ""
        tokens = _tokens(text)
        norm = _normalised(text)

        flags = []
        if not tokens:
            flags.append("empty")
        if norm and norm == previous_norm:
            flags.append("duplicate_of_previous")
        if (_max_immediate_repeat(tokens) >= repeat_run
                or _max_phrase_repeat(tokens) >= repeat_run):
            flags.append("internal_repetition")
        span = _usable_span(seg) if flag_zero_duration else None
        if span is not None and span[0] == span[1] and _passage_tokens(text):
            flags.append("zero_duration")
        if index in passage_links:
            flags.append("repeated_passage")

        rate = None
        n_words, n_chars, unvalidated = _rate_units(tokens)
        if start is not None and end is not None and not unvalidated:
            usable = _usable_span(seg)
            duration = usable[1] - usable[0] if usable is not None else 0.0
            if duration > 0:
                rate = (n_words + n_chars) / duration
                if n_chars:
                    too_fast = n_words / max_rate + n_chars / max_char_rate > duration
                else:
                    # Words only: the original comparison, kept exactly so
                    # that no borderline segment changes its flag.
                    too_fast = rate > max_rate
                if duration >= long_segment_s and rate < min_rate:
                    flags.append("low_speech_rate")
                elif too_fast:
                    flags.append("high_speech_rate")

        previous_norm = norm or previous_norm
        if flags:
            record = {
                "index": index,
                "start": _finite_time(start),
                "end": _finite_time(end),
                "words": len(tokens),
                "speech_rate": round(rate, 2) if rate is not None else None,
                "flags": flags,
                "text": text.strip(),
            }
            if index in passage_links:
                record["repeated_passage_with"] = list(passage_links[index])
            flagged.append(record)
    return flagged


def summarise(segments, flagged) -> dict:
    """Return counts of each flag and the proportion of segments flagged.

    ``rate_flags_skipped`` counts the segments whose speech rate was not
    judged because they are in a script with no validated rate unit (see
    :func:`flag_segments`), so a reader can tell "not flagged" from "not
    checked".
    """
    counts: dict[str, int] = {}
    for record in flagged:
        for flag in record["flags"]:
            counts[flag] = counts.get(flag, 0) + 1
    total = len(segments or [])
    skipped = sum(1 for seg in segments or []
                  if _rate_units(_tokens(seg.get("text") or ""))[2])
    return {
        "segments": total,
        "flagged": len(flagged),
        "flag_rate": round(len(flagged) / total, 4) if total else 0.0,
        "counts_by_flag": dict(sorted(counts.items())),
        "rate_flags_skipped": skipped,
        "signal": "heuristic (pipeline does not expose model log-probabilities)",
    }


# A transcript whose last segment ends this far short of the recording,
# as a fraction of its duration, has almost certainly stopped early rather
# than merely ended on a pause.
_TRUNCATION_SHORTFALL = 0.10


def truncation_check(segments, audio_duration_s=None) -> dict:
    """Report whether the transcript stops well before the recording does.

    The timestamp benchmark identified early truncation as the dominant
    boundary failure on AMI: every gross end-boundary error was the model
    ceasing to transcribe part-way through, in the worst cases after less
    than a fifth of the segment, and none was a run-on past the true end.
    Post-processing cannot repair that, because the words were never
    emitted; what the workflow can do is notice, so that a short
    transcript is not mistaken for a complete one.

    The check is whole-transcript rather than per segment, since that is
    the scale at which the failure shows: the final cue simply arrives
    early and nothing follows it. Returns ``checked: False`` when the
    recording's duration is unknown, because a shortfall cannot be
    measured against an unknown total and guessing would be worse than
    declining.
    """
    spans = [(s.get("start"), s.get("end")) for s in segments or []]
    ends = [value for _, end in spans if (value := _finite_time(end)) is not None]
    duration = _finite_time(audio_duration_s)
    if not ends or duration is None or duration <= 0:
        return {"checked": False}
    last_end = max(ends)
    shortfall = max(0.0, duration - last_end)
    return {
        "checked": True,
        "audio_duration_s": round(duration, 2),
        "last_segment_end_s": round(last_end, 2),
        "shortfall_s": round(shortfall, 2),
        "shortfall_fraction": round(shortfall / duration, 4),
        "truncated": shortfall / duration > _TRUNCATION_SHORTFALL,
    }


def review_transcript(transcript: dict, audio_duration_s=None,
                      **kwargs) -> dict:
    """Flag the segments of a loaded transcript and summarise the result.

    When *audio_duration_s* is known the report also carries a
    whole-transcript truncation check, which catches the failure the
    per-segment flags cannot see: a transcript that simply stops early.
    """
    segments = transcript.get("segments") or []
    flagged = flag_segments(segments, **kwargs)
    report = {
        "summary": summarise(segments, flagged),
        "truncation": truncation_check(segments, audio_duration_s),
        "flagged": flagged,
    }
    if kwargs.get("flag_zero_duration") or kwargs.get("repeated_passage_words") is not None:
        report["optional_checks"] = {
            "flag_zero_duration": bool(kwargs.get("flag_zero_duration", False)),
            "repeated_passage_words": kwargs.get("repeated_passage_words"),
            "repeated_passage_window_s": float(kwargs.get(
                "repeated_passage_window_s", _PASSAGE_WINDOW_S)),
        }
    return report


def print_report(report: dict, limit: int = 20) -> None:
    """Print a readable summary of the flagged segments."""
    s = report["summary"]
    print(f"\n  Segments:     {s['segments']}")
    print(f"  Flagged:      {s['flagged']}  ({s['flag_rate'] * 100:.1f}%)")
    for flag, count in s["counts_by_flag"].items():
        print(f"      {flag:<24} {count}")
    if s.get("rate_flags_skipped"):
        print(f"  Speech rate not checked on {s['rate_flags_skipped']} "
              f"segment(s): no validated rate unit for their script.")
    if not report["flagged"]:
        print("  Nothing flagged for review.")
        return
    print(f"\n  {'Span':<18}  {'Flags':<38}  Text")
    print("  " + "-" * 88)
    for record in report["flagged"][:limit]:
        # An external report may carry numeric strings or unusable times;
        # format validated values without modifying its recorded fields.
        times = _usable_span(record)
        span = f"{times[0]:.1f}-{times[1]:.1f}s" if times is not None else "n/a"
        text = record["text"][:44] + ("..." if len(record["text"]) > 44 else "")
        print(f"  {span:<18}  {','.join(record['flags']):<38}  {text}")
    if len(report["flagged"]) > limit:
        print(f"  ... and {len(report['flagged']) - limit} more")
    print("\n  These are heuristics, not model confidence: review the audio "
          "before acting on them.")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="confidence",
        description="Flag transcript segments whose shape is characteristic "
                    "of Whisper hallucination or decoding loops.")
    p.add_argument("transcript", type=Path,
                   help="a transcript .json written by the workflow")
    p.add_argument("--json", type=Path, default=None, dest="json_out",
                   help="also write the full report to this path")
    p.add_argument("--min-duration", type=float, default=_LONG_SEGMENT_S,
                   dest="long_segment_s",
                   help="seconds above which a near-wordless segment is "
                        "flagged (default: %(default)s)")
    p.add_argument("--min-rate", type=float, default=_MIN_RATE,
                   help="words per second below which a long segment is "
                        "flagged (default: %(default)s)")
    p.add_argument("--max-rate", type=float, default=_MAX_RATE,
                   help="words per second above which a segment is flagged "
                        "(default: %(default)s)")
    p.add_argument("--max-char-rate", type=float, default=_MAX_CHAR_RATE,
                   help="Han characters and kana per second above which a "
                        "Chinese or Japanese segment is flagged "
                        "(default: %(default)s)")
    p.add_argument("--flag-zero-duration", action="store_true",
                   help="also flag non-empty cues with equal finite start/end times")
    p.add_argument("--repeated-passage-words", type=int, default=None, metavar="N",
                   help="also flag both copies of repeated runs of N tokens across cues; "
                        "an apostrophe splits a word, so a contraction counts as two "
                        "tokens (suggested: 8; disabled by default)")
    # None marks the option as unset, so that a window given without the
    # passage check is refused instead of silently ignored.
    p.add_argument("--repeated-passage-window", type=float, default=None,
                   dest="repeated_passage_window_s", metavar="SECONDS",
                   help="maximum gap between the starting cues of repeated runs "
                        f"(default: {_PASSAGE_WINDOW_S:g}; needs --repeated-passage-words)")
    return p


def main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.repeated_passage_window_s is None:
        args.repeated_passage_window_s = _PASSAGE_WINDOW_S
    elif args.repeated_passage_words is None:
        parser.error("--repeated-passage-window needs --repeated-passage-words")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    try:
        transcript = json.loads(args.transcript.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  Error: cannot read {args.transcript}: {exc}", file=sys.stderr)
        return 2

    try:
        report = review_transcript(
            transcript, long_segment_s=args.long_segment_s,
            min_rate=args.min_rate, max_rate=args.max_rate,
            max_char_rate=args.max_char_rate,
            flag_zero_duration=args.flag_zero_duration,
            repeated_passage_words=args.repeated_passage_words,
            repeated_passage_window_s=args.repeated_passage_window_s)
    except ValueError as exc:
        print(f"  Error: {exc}", file=sys.stderr)
        return 2
    print(f"Transcript: {args.transcript}")
    print_report(report)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  report: {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
