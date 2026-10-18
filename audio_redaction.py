#!/usr/bin/env python3
"""
Redact spoken personal names from an audio recording.

The workflow already masks names in the *text* it emits, and, when
timestamps are requested, it records a start and end time for every word.
Those two facts together support a stronger guarantee than either gives
alone: the same name-masking decision that redacts a token in the
transcript can silence the corresponding stretch of *audio*. This closes
the gap the artefact audit identified --- the transcript is
de-identified, but the recording still utters every name --- and it does
so using only the components the pipeline already produces.

The module has two pure parts and a thin I/O layer:

* :func:`find_name_spans` walks a transcript's word-level timestamps and
  returns the time spans of the name words. For a ``_redacted`` transcript
  written by the pipeline (``"redacted": true``) the placeholders already
  in the words *are* the run's own masking decisions, so they are used
  directly and the audio is redacted exactly where the text was. For a raw
  transcript a masking function is applied to each word instead. It is
  injected so the tests can substitute a stub.
* :func:`redact_spans` replaces those spans in a mono waveform with
  silence or a bleep tone, merging overlapping spans and applying a small
  pad so a slightly tight timestamp still covers the whole word.

Rebuilding a masker is the weaker route. The transcription run may have
used the Facebook lists, other languages, a different common-word filter
or an exclusion list, and a word masked on its own loses the sentence
context the masker sees. The command line therefore prefers the
``_redacted`` transcript, looks for it next to a raw one, and only falls
back to a rebuilt masker, taking the same masking options as
``transcription.py``, when no redacted set exists.

A run that finds nothing to redact refuses to write its output unless
``--allow-empty`` is given, because a file named ``*_redacted.wav`` that is
a sample-identical copy of the input is worse than no file.

The waveform I/O uses the standard-library :mod:`wave` module for PCM WAV,
so the core runs with no third-party audio dependency. Non-WAV inputs are
decoded with :mod:`librosa` when it is importable (as in the full
pipeline) and refused with a clear message otherwise.
:mod:`voice_anonymisation` reuses the same readers and writer.

Usage::

    python -m audio_redaction --audio talk.wav \\
        --transcript talk_transcript_redacted.json \\
        --out talk_redacted.wav --mode bleep
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import wave
from pathlib import Path

try:
    import numpy as np
except ImportError as exc:  # pragma: no cover - numpy is a core dependency
    raise SystemExit("numpy is required for audio_redaction.") from exc

# The placeholders transcription.create_enhanced_name_masker emits: [NAME]
# for a first name or a NER find, [SURNAME] for a surname and [TITLE] for an
# honorific before a name. Only these count. Whisper itself writes bracketed
# all-caps tags such as [MUSIC] or [BLANK_AUDIO], and a broader pattern would
# treat those as redactions. The list is retyped from transcription.py,
# which keeps it inside the masker where it cannot be imported; a new
# placeholder there has to be added here too.
_PLACEHOLDER_RE = re.compile(r"\[(?:NAME|SURNAME|TITLE)\]")
# Keys under which a word may carry its text, in the order
# transcription._TEXT_KEYS gives them. The pipeline's
# _build_segments_from_chunks writes ``word``; the shipped example
# artefacts use ``text``. Reading only one of them found no names at all in
# pipeline output (audit finding EPRIV-01).
_WORD_TEXT_KEYS = ("text", "word")
_DEFAULT_PAD_S = 0.05
_DEFAULT_BLEEP_HZ = 1000.0
_DEFAULT_BLEEP_AMP = 0.2

Span = tuple[float, float]


def word_is_name(word_text: str, mask_fn) -> bool:
    """Return ``True`` when *mask_fn* would redact *word_text* as a name.

    A word counts as a name when masking it introduces a bracketed
    placeholder ([NAME] or [SURNAME]) that
    :func:`transcription.create_enhanced_name_masker` emits and the word did
    not already contain one. Passing each word through the very masker used
    for the text keeps the audio redaction consistent with the transcript
    redaction.
    """
    if not word_text:
        return False
    try:
        masked = mask_fn(word_text)
    except Exception:
        return False
    return bool(_PLACEHOLDER_RE.search(masked)) and \
        _PLACEHOLDER_RE.search(word_text) is None


def word_text(word: dict) -> str:
    """Return the text of one word entry, whichever key carries it.

    Parameters
    ----------
    word:
        A word dict from a transcript's ``segments[*]["words"]``.

    Returns
    -------
    str
        The first non-empty value under :data:`_WORD_TEXT_KEYS`, or ``""``.
    """
    for key in _WORD_TEXT_KEYS:
        value = word.get(key)
        if value:
            return str(value)
    return ""


def is_redacted_transcript(transcript: dict) -> bool:
    """Return ``True`` for a transcript the pipeline wrote as its redacted set.

    ``transcription.write_timestamped_outputs`` stamps ``"redacted": true``
    on the ``_transcript_redacted.json`` payload and ``false`` on the raw
    one. Only an explicit ``True`` counts, so a transcript from elsewhere is
    treated as raw.
    """
    return transcript.get("redacted") is True


def _timed_words(transcript: dict):
    """Yield ``(start, end, word)`` for every word with both timestamps."""
    for segment in transcript.get("segments", []) or []:
        for word in segment.get("words", []) or []:
            start = word.get("start")
            end = word.get("end")
            if start is None or end is None:
                continue
            yield float(start), float(end), word


def find_name_spans(transcript: dict, mask_fn=None, pad_s: float = 0.0) -> list[Span]:
    """Return the ``(start, end)`` spans of name words in *transcript*.

    Walks ``transcript["segments"][*]["words"][*]``. Word text is read under
    either key the pipeline uses (see :func:`word_text`).

    Parameters
    ----------
    transcript:
        A transcript payload as written by ``transcription.py``.
    mask_fn:
        The masking function applied to each word of a *raw* transcript.
        It is ignored for a redacted transcript (see
        :func:`is_redacted_transcript`), whose placeholders already record
        the run's masking decisions; there a word carrying a placeholder is
        a span, so audio and text are redacted in exactly the same places.
    pad_s:
        Widens each returned span symmetrically, in seconds.

    Returns
    -------
    list of (start, end)
        Merged spans in seconds. Words without both a ``start`` and an
        ``end`` are skipped: audio redaction needs word-level times, so a
        segment transcribed without them contributes nothing.

    Raises
    ------
    ValueError
        If *transcript* is raw and *mask_fn* is ``None``.
    """
    redacted = is_redacted_transcript(transcript)
    if not redacted and mask_fn is None:
        raise ValueError("a raw transcript needs a masking function")
    spans: list[Span] = []
    for start, end, word in _timed_words(transcript):
        text = word_text(word)
        hit = (bool(_PLACEHOLDER_RE.search(text)) if redacted
               else word_is_name(text, mask_fn))
        if hit:
            spans.append((start - pad_s, end + pad_s))
    return _merge_spans(spans)


def transcript_diagnostics(transcript: dict) -> dict:
    """Count what a transcript offers for redaction, to explain an empty result.

    Returns
    -------
    dict
        ``timed_words``: words with both timestamps. ``timed_words_with_text``:
        those whose text is readable under :data:`_WORD_TEXT_KEYS`.
        ``placeholders_in_text``: masker placeholders anywhere in the
        top-level or segment text, which a redacted transcript whose names
        were masked must also show in its timed words.
    """
    timed = with_text = 0
    for _start, _end, word in _timed_words(transcript):
        timed += 1
        if word_text(word):
            with_text += 1
    texts = [str(transcript.get("text") or "")]
    texts += [str(seg.get("text") or "")
              for seg in transcript.get("segments", []) or []]
    placeholders = sum(len(_PLACEHOLDER_RE.findall(t)) for t in texts)
    return {"timed_words": timed, "timed_words_with_text": with_text,
            "placeholders_in_text": placeholders}


def redacted_sibling(transcript_path: Path) -> Path | None:
    """Return the ``_redacted`` JSON written beside a raw transcript, if any.

    The pipeline writes ``<base>_transcript.json`` and
    ``<base>_transcript_redacted.json`` side by side.
    """
    path = Path(transcript_path)
    if path.stem.endswith("_redacted"):
        return None
    candidate = path.with_name(f"{path.stem}_redacted{path.suffix}")
    return candidate if candidate.is_file() else None


def aligned_word_times(raw: dict, redacted: dict) -> bool:
    """Return ``True`` when two transcripts have the same timed words.

    ``transcription._redact_segments`` copies the segment and word lists
    one for one and changes only their text, so a raw transcript and its
    redacted sibling from the same run agree on every word's timing. A
    mismatch means the two files did not come from the same run, and the
    redacted decisions cannot be trusted to line up with the raw audio.
    """
    raw_times = [(s, e) for s, e, _ in _timed_words(raw)]
    red_times = [(s, e) for s, e, _ in _timed_words(redacted)]
    return raw_times == red_times


def _merge_spans(spans: list[Span]) -> list[Span]:
    """Merge overlapping or touching spans; clamp negative starts to zero."""
    if not spans:
        return []
    ordered = sorted((max(0.0, s), e) for s, e in spans if e > s)
    if not ordered:
        return []
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def redact_spans(
    audio: np.ndarray,
    sr: int,
    spans: list[Span],
    mode: str = "silence",
    pad_s: float = _DEFAULT_PAD_S,
    bleep_hz: float = _DEFAULT_BLEEP_HZ,
    bleep_amp: float = _DEFAULT_BLEEP_AMP,
) -> np.ndarray:
    """Return a copy of *audio* with *spans* silenced or bleeped.

    Parameters
    ----------
    audio:
        Mono float waveform in ``[-1, 1]``.
    sr:
        Sample rate in Hz.
    spans:
        ``(start_s, end_s)`` spans to redact; overlapping spans are merged
        and each is padded by *pad_s* before redaction.
    mode:
        ``"silence"`` zeroes the span; ``"bleep"`` replaces it with a
        fixed-frequency tone (a common, audible censor that makes the
        redaction obvious rather than ambiguous with a recording gap).
    """
    if mode not in ("silence", "bleep"):
        raise ValueError(f"mode must be 'silence' or 'bleep', got {mode!r}")
    out = np.array(audio, dtype=np.float32, copy=True)
    n = len(out)
    for start, end in padded_spans(spans, pad_s):
        i0 = max(0, int(round(start * sr)))
        i1 = min(n, int(round(end * sr)))
        if i1 <= i0:
            continue
        if mode == "silence":
            out[i0:i1] = 0.0
        else:
            t = np.arange(i1 - i0, dtype=np.float32) / sr
            out[i0:i1] = (bleep_amp * np.sin(2.0 * np.pi * bleep_hz * t)).astype(np.float32)
    return out


def padded_spans(spans: list[Span], pad_s: float,
                 duration_s: float | None = None) -> list[Span]:
    """Return *spans* widened by *pad_s* per side, merged and clamped.

    This is exactly the stretch :func:`redact_spans` overwrites, so a
    reported duration computed from it matches the audio removed. Starts
    are clamped at zero and, when *duration_s* is given, ends at the length
    of the recording.
    """
    merged = _merge_spans([(s - pad_s, e + pad_s) for s, e in spans])
    if duration_s is None:
        return merged
    clamped = [(s, min(e, float(duration_s))) for s, e in merged]
    return [(s, e) for s, e in clamped if e > s]


def redacted_duration(spans: list[Span]) -> float:
    """Return the total redacted time in seconds for *spans* (merged).

    Pass the output of :func:`padded_spans` to report the audio actually
    silenced; the raw word spans understate it by the padding.
    """
    return sum(e - s for s, e in _merge_spans(spans))


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    """Read a PCM WAV file into a mono float32 waveform and its sample rate.

    Multi-channel audio is down-mixed to mono by averaging.

    Raises
    ------
    ValueError
        If the file is not 16-bit PCM, the only encoding the
        standard-library reader handles. A library function raises a
        catchable error; the command-line entry points turn it into an exit
        message.
    """
    path = Path(path)
    with wave.open(str(path), "rb") as w:
        n_channels = w.getnchannels()
        sampwidth = w.getsampwidth()
        sr = w.getframerate()
        frames = w.readframes(w.getnframes())
    if sampwidth != 2:
        raise ValueError(f"only 16-bit PCM WAV is supported, got {sampwidth * 8}-bit")
    data = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if n_channels > 1:
        data = data.reshape(-1, n_channels).mean(axis=1)
    return data, sr


def write_wav(path: Path, audio: np.ndarray, sr: int) -> None:
    """Write a mono float32 waveform to a 16-bit PCM WAV file.

    Samples are clipped to ``[-1, 1]`` and scaled by 32767. Side effects:
    creates the parent directory if needed and overwrites *path*.
    """
    path = Path(path)
    clipped = np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def load_audio(path: Path) -> tuple[np.ndarray, int]:
    """Load *path* as mono float32 at its native sample rate.

    WAV is read with :func:`read_wav`; anything else is decoded with
    librosa.

    Raises
    ------
    ValueError
        For a WAV that is not 16-bit PCM.
    ImportError
        For a non-WAV input when librosa is not installed.
    """
    path = Path(path)
    if path.suffix.lower() == ".wav":
        return read_wav(path)
    try:
        import librosa  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            f"Reading {path.suffix} requires librosa; install it or supply WAV."
        ) from exc
    audio, sr = librosa.load(str(path), sr=None, mono=True)
    return np.asarray(audio, dtype=np.float32), int(sr)


# Kept for callers of the old private name.
_load_audio = load_audio


def _build_parser() -> argparse.ArgumentParser:
    """Return the command-line parser.

    The masking options mirror ``transcription.py``'s own, under the same
    names, so a raw transcript can be redacted with the masker the
    transcription run used when no ``_redacted`` set exists.
    """
    p = argparse.ArgumentParser(
        prog="audio_redaction",
        description="Silence or bleep spoken personal names in a recording, "
                    "using the transcript's word timestamps and the "
                    "pipeline's own masking decisions.",
    )
    p.add_argument("--audio", type=Path, required=True,
                   help="Input audio (WAV handled natively; others need librosa).")
    p.add_argument("--transcript", type=Path, required=True,
                   help="Transcript JSON with segment/word timestamps. The "
                        "_transcript_redacted.json from a --mask-personal-names "
                        "run is preferred; given the raw _transcript.json, its "
                        "redacted sibling is used when present.")
    p.add_argument("--out", type=Path, required=True,
                   help="Output WAV path for the redacted audio.")
    p.add_argument("--mode", choices=("silence", "bleep"), default="silence",
                   help="Redaction style (default: %(default)s).")
    p.add_argument("--pad", type=float, default=_DEFAULT_PAD_S,
                   help="Symmetric pad in seconds around each span "
                        "(default: %(default)s).")
    p.add_argument("--allow-empty", action="store_true", dest="allow_empty",
                   help="Write the output even when no name span is found. "
                        "Without it an empty result is an error, since the "
                        "output would be an unredacted copy.")
    masking = p.add_argument_group(
        "masker options",
        "Used only when no redacted transcript is available and the masker "
        "has to be rebuilt. Pass the values the transcription run used.")
    masking.add_argument("--use-facebook-names-for-masking", action="store_true",
                         dest="use_facebook_names")
    masking.add_argument("--use-facebook-surnames-for-masking",
                         action="store_true", dest="use_facebook_surnames")
    masking.add_argument("--languages-for-name-masking", nargs="*", default=None,
                         dest="languages",
                         help="Curated-list languages (default: all nine).")
    # BooleanOptionalAction as in transcription.py, so the --no- form that
    # switches the filter off for an English run can be mirrored too.
    masking.add_argument("--exclude-common-english-words-from-name-masking",
                         action=argparse.BooleanOptionalAction, default=None,
                         dest="exclude_common_words",
                         help="Default, as in transcription.py: on when the "
                              "transcript's language is English.")
    masking.add_argument("--exclude-names-from-masking", default=None,
                         dest="exclude_names",
                         help="Comma-separated names not to redact.")
    masking.add_argument("--exclude-names-file", type=Path, default=None,
                         dest="exclude_names_file",
                         help="File of names not to redact, one per line.")
    return p


def _excluded_names(args) -> set[str]:
    """Collect the lower-cased exclusion list from the CLI arguments."""
    names: set[str] = set()
    if args.exclude_names:
        names.update(n.strip().lower() for n in args.exclude_names.split(",")
                     if n.strip())
    if args.exclude_names_file:
        text = args.exclude_names_file.read_text(encoding="utf-8")
        names.update(line.strip().lower() for line in text.splitlines()
                     if line.strip())
    return names


def _rebuild_masker(args, transcript: dict):
    """Build the masker from the CLI's mirrored transcription options.

    Returns ``(mask_fn, description)``. The common-word filter follows
    ``transcription.process_audio_file`` when not given: on for an English
    transcript, off otherwise. Side effect: the masker prints its
    database-loading report to stdout.
    """
    from transcription import (  # noqa: PLC0415
        _language_is_english,
        create_enhanced_name_masker,
    )
    exclude_common = args.exclude_common_words
    if exclude_common is None:
        exclude_common = _language_is_english(transcript.get("language"))
    excluded = _excluded_names(args)
    mask_fn, _ = create_enhanced_name_masker(
        use_facebook_names=args.use_facebook_names,
        use_facebook_surnames=args.use_facebook_surnames,
        selected_languages=args.languages or None,
        exclude_common_words=exclude_common,
        excluded_names=excluded or None,
    )
    description = (
        f"rebuilt masker (facebook names={args.use_facebook_names}, "
        f"surnames={args.use_facebook_surnames}, "
        f"languages={args.languages or 'all'}, "
        f"exclude_common_words={exclude_common}, "
        f"excluded={len(excluded)} name(s)); words masked one at a time")
    return mask_fn, description


def main(argv: list[str] | None = None) -> int:
    """Redact spoken names in ``--audio`` and write ``--out``.

    Returns 0 on success, 2 when the transcript or masker cannot be loaded
    or the audio cannot be read, and 3 when there is nothing to redact
    (unless ``--allow-empty``) or the transcript's words carry no readable
    text. On any non-zero return no output file is written. Side effects:
    reads the transcript, a redacted sibling beside it and the audio;
    writes the output WAV; prints a report to stdout and errors to stderr.
    """
    args = _build_parser().parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    try:
        transcript = json.loads(args.transcript.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  Error: could not read the transcript: {exc}", file=sys.stderr)
        return 2

    # Prefer the run's own decisions: the redacted transcript, or the
    # redacted sibling of a raw one. Only rebuild a masker when neither
    # exists, since a rebuilt masker may not match the one the run used.
    source_path = args.transcript
    if not is_redacted_transcript(transcript):
        sibling = redacted_sibling(args.transcript)
        if sibling is not None:
            try:
                candidate = json.loads(sibling.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                print(f"  Error: could not read {sibling}: {exc}",
                      file=sys.stderr)
                return 2
            if is_redacted_transcript(candidate):
                if not aligned_word_times(transcript, candidate):
                    print(f"  Error: {sibling} does not have the same word "
                          f"timings as {args.transcript}; they are not from "
                          "the same run.", file=sys.stderr)
                    return 2
                transcript, source_path = candidate, sibling

    if is_redacted_transcript(transcript):
        mask_fn = None
        decision = f"the run's own redaction decisions in {source_path.name}"
    else:
        try:
            mask_fn, decision = _rebuild_masker(args, transcript)
        except Exception as exc:
            print(f"  Error: could not load the name masker: {exc}",
                  file=sys.stderr)
            return 2

    diagnostics = transcript_diagnostics(transcript)
    if diagnostics["timed_words"] and not diagnostics["timed_words_with_text"]:
        print(f"  Error: {diagnostics['timed_words']} timed word(s) but none "
              f"carries text under any of {_WORD_TEXT_KEYS}; the transcript "
              "format is not one this tool reads. Nothing written.",
              file=sys.stderr)
        return 3

    spans = find_name_spans(transcript, mask_fn)
    if not spans:
        if is_redacted_transcript(transcript) and diagnostics["placeholders_in_text"]:
            print(f"  Error: the transcript text holds "
                  f"{diagnostics['placeholders_in_text']} masked placeholder(s) "
                  "but no timed word carries one, so the names cannot be "
                  "located in the audio. Nothing written.", file=sys.stderr)
            return 3
        if not args.allow_empty:
            print("  Error: no name words with timestamps found, so the output "
                  "would be an unredacted copy of the input. Nothing written; "
                  "pass --allow-empty to write it anyway.", file=sys.stderr)
            return 3
        print("  No name words with timestamps found; writing an unredacted "
              "copy because --allow-empty was given.", file=sys.stderr)

    try:
        audio, sr = load_audio(args.audio)
    except (OSError, ValueError, ImportError, wave.Error) as exc:
        print(f"  Error: could not read {args.audio}: {exc}", file=sys.stderr)
        return 2
    redacted = redact_spans(audio, sr, spans, mode=args.mode, pad_s=args.pad)
    write_wav(args.out, redacted, sr)

    removed = padded_spans(spans, args.pad, len(audio) / sr if sr else None)
    print(f"Redacted {len(spans)} span(s), "
          f"{redacted_duration(removed):.2f}s of audio "
          f"(including {args.pad:.2f}s padding per side), mode={args.mode}")
    print(f"  decisions: {decision}")
    print(f"  wrote: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
