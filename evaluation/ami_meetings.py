#!/usr/bin/env python3
"""
Reconstruct AMI meetings from the utterance-level IHM release.

Why this module exists
----------------------
The ``edinburghcstr/ami`` release distributes AMI as individual
utterances rather than whole recordings: one row per speaker turn,
carrying that speaker's close-talking headset audio together with the
turn's ``begin_time`` and ``end_time`` **in the original meeting
timeline**.  A diarisation benchmark needs a meeting, not a bag of
utterances, so the rows have to be reassembled first.

There are two ways to do that, and they measure different things.

``timeline`` (the default)
    Each utterance is placed at its true ``begin_time`` on a common
    timeline and the channels are summed.  Turns that overlap in the
    original meeting therefore overlap in the reconstruction, and the
    result approximates AMI's own ``Mix-Headset`` signal, which is
    likewise a sum of the individual headset channels.  This is the
    condition under which diarisation systems are normally reported on
    AMI, and it preserves the property that makes meeting diarisation
    hard in the first place.

``concat``
    Utterances are concatenated end to end with a fixed silent gap,
    which is how the first version of this benchmark was built.  It is
    retained so that earlier numbers remain reproducible, but it should
    not be read as a diarisation result. Concatenation removes every
    overlap, and overlap is what most of the error tracks: in the timeline
    results committed in ``output/evaluation/der_report.csv`` the
    overlapped proportion of speech correlates strongly with per-meeting
    diarisation error (recompute the figure from that file rather than
    quoting it from here). The microphone channel also changes
    at every utterance boundary, which hands the speaker-embedding model
    a channel cue that no real recording provides.

Caveat that applies to both modes
---------------------------------
Silence between annotated turns is digital silence, not room tone,
because the release ships only the annotated spans.  Voice activity
detection therefore faces an easier problem in the gaps than it would on
the original continuous recording, and false-alarm rates measured here
should be read as a lower bound.  :func:`meeting_statistics` reports the
silent fraction of each reconstruction so the size of that gap is
visible rather than assumed.

Nothing here imports ``pyannote``, and ``datasets`` and ``soundfile``
are imported only inside the I/O helpers that need them. The
reconstruction functions take audio decoding as an injected callable,
which keeps their arithmetic testable without a GPU, a network
connection, or a gated model.

The streaming, decoding and token helpers below are the single copy
used by the DER benchmark, the sweep and the fine-tuning script, so that
the audio a model is trained on and the audio it is scored on cannot
drift apart through a fix applied to only one copy.
"""

from __future__ import annotations

import io
import warnings
from pathlib import Path
from collections.abc import Callable, Iterable, Iterator, Sequence

import numpy as np

SAMPLE_RATE = 16_000
#: Silence inserted between utterances in ``concat`` mode, in seconds.
CONCAT_GAP_S = 0.5
#: Utterances per mini-meeting in ``concat`` mode. Shared with the
#: benchmark's command-line default so the two cannot disagree.
DEFAULT_UTTERANCES_PER_MEETING = 25

#: HuggingFace release and configuration every caller reconstructs from.
#: ``ihm`` is the individual headset microphone release, whose per-speaker
#: clips are mono.
AMI_DATASET = "edinburghcstr/ami"
AMI_CONFIG = "ihm"

#: Version of the reconstruction arithmetic, written into every cache and
#: data manifest. Bump it whenever a change to this module would alter the
#: audio or the reference a reconstruction produces (placement, truncation,
#: normalisation, resampling, the concatenation gap), so that a cache built
#: by the old code is refused instead of being scored as if it were new.
#: Documentation-only edits leave it unchanged.
RECONSTRUCTION_VERSION = 1

_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Corpus I/O
# ---------------------------------------------------------------------------

def load_hf_token() -> str | None:
    """Return the HuggingFace token, or ``None`` when none is configured.

    Delegates to :func:`preflight.resolve_hf_token`, the one lookup the
    workflow shares (audit findings CORE-13, XREF-04): the ``HF_TOKEN``,
    ``HUGGINGFACE_TOKEN`` and ``HUGGING_FACE_HUB_TOKEN`` variables, then
    ``hf_token.txt`` at the repository root and in the working directory,
    then ``$HF_TOKEN_PATH`` and ``<HF_HOME>/token``. The earlier copy here
    stopped after the repository file, so a token saved by
    ``huggingface-cli login`` was invisible to the benchmarks.

    Returns
    -------
    str or None
        The stripped token, or ``None`` when no source provides one.

    Side effects
    ------------
    Reads the environment and the candidate token files; writes nothing.
    """
    from preflight import resolve_hf_token

    return resolve_hf_token()[0]


def decode_audio_bytes(audio_dict: dict):
    """Decode one AMI audio field to ``(samples, sample_rate)``.

    The ``datasets`` Audio feature yields either a decoded array or a
    ``{'bytes': ..., 'path': ...}`` dict when decoding is deferred.  This
    workflow defers deliberately: automatic decoding in ``datasets`` 3.x
    and later pulls in torchcodec and its FFmpeg shared libraries, which
    are not reliably present on a cluster node, whereas ``soundfile``
    already is.

    Parameters
    ----------
    audio_dict:
        The row's ``audio`` field.

    Returns
    -------
    (samples, sample_rate)
        *samples* is float32. ``soundfile`` returns shape ``(frames,)``
        for mono and ``(frames, channels)`` otherwise.

    Raises
    ------
    ValueError
        When the dict carries neither an array nor encoded bytes.
    """
    import soundfile as sf

    if isinstance(audio_dict, dict):
        if audio_dict.get("array") is not None:
            return (np.asarray(audio_dict["array"], dtype=np.float32),
                    audio_dict.get("sampling_rate", SAMPLE_RATE))
        raw = audio_dict.get("bytes")
        if raw is not None:
            arr, sr = sf.read(io.BytesIO(raw), dtype="float32", always_2d=False)
            return arr, sr
    raise ValueError(f"cannot decode audio from keys {list(audio_dict)}")


def stream_ami(split: str, hf_token: str | None,
               dataset: str = AMI_DATASET, config: str = AMI_CONFIG):
    """Return a streaming iterator over AMI rows for *split*.

    Nothing is written to disk: rows arrive over the network with their
    audio still encoded (``decode=False``, see :func:`decode_audio_bytes`).
    The dataset is loaded at :func:`evaluation.revisions.revision_for` of
    *dataset*, the snapshot every committed AMI run used; an unlisted
    dataset loads ``main``.

    Parameters
    ----------
    split:
        ``"train"``, ``"validation"`` or ``"test"``.
    hf_token:
        HuggingFace token, or ``None`` for anonymous access.
    dataset, config:
        HuggingFace dataset id and configuration.

    Raises
    ------
    SystemExit
        When the ``datasets`` package is not installed.
    """
    try:
        import datasets as hf_datasets
        from datasets import Audio as _HFAudio
    except ImportError as exc:
        raise SystemExit("The 'datasets' package is required.  "
                         "Install with:  pip install datasets>=2.14.0") from exc

    from evaluation.revisions import revision_for

    kwargs = {"path": dataset, "name": config, "split": split,
              "streaming": True, "revision": revision_for(dataset)}
    if hf_token:
        kwargs["token"] = hf_token
    ds = hf_datasets.load_dataset(**kwargs)
    return ds.cast_column("audio", _HFAudio(decode=False))


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------

def group_rows_by_meeting(
    rows: Iterable[dict],
    limit_meetings: int | None = None,
) -> Iterator[tuple[str, list[dict]]]:
    """Yield ``(meeting_id, rows)`` pairs from a stream of utterance rows.

    The release stores each meeting's rows contiguously, which lets a
    meeting be emitted as soon as the next one begins instead of holding
    the whole split, audio included, in memory.  That assumption is
    checked rather than trusted: if a meeting reappears after it has been
    emitted the grouping would silently split it in two, so a
    :class:`ValueError` is raised instead.

    Rows within each meeting are returned sorted by ``begin_time``.
    """
    current_id: str | None = None
    buffer: list[dict] = []
    emitted: set[str] = set()

    def _flush():
        buffer.sort(key=lambda r: float(r["begin_time"]))
        return current_id, list(buffer)

    for row in rows:
        mid = row["meeting_id"]
        if mid != current_id:
            if current_id is not None:
                emitted.add(current_id)
                yield _flush()
                if limit_meetings is not None and len(emitted) >= limit_meetings:
                    return
                buffer.clear()
            if mid in emitted:
                raise ValueError(
                    f"meeting {mid!r} reappeared after its rows were already "
                    "grouped. The split is not ordered by meeting, so this "
                    "grouping would silently split it in two.")
            current_id = mid
        buffer.append(row)

    if current_id is not None and buffer:
        yield _flush()


# ---------------------------------------------------------------------------
# Reconstruction
# ---------------------------------------------------------------------------

def _resample(audio: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    """Resample by linear interpolation.

    AMI is distributed at 16 kHz, so this is a safety net for an
    unexpected rate rather than a signal-processing component. Doing it
    here keeps ``scipy`` and ``librosa`` out of the reconstruction's
    dependencies.
    """
    if sr_in == sr_out or audio.size == 0:
        return audio.astype(np.float32, copy=False)
    # Linear interpolation has no anti-aliasing filter and differs from
    # the librosa resampler the WER harness uses, so a corpus that reaches
    # this line is no longer reconstructed the way the committed AMI
    # results were (every AMI clip is at 16 kHz). Said aloud, not silently.
    warnings.warn(
        f"resampling a clip from {sr_in} Hz to {sr_out} Hz by linear "
        "interpolation; AMI is distributed at 16 kHz, so this input is not "
        "the corpus the committed DER results were measured on",
        RuntimeWarning, stacklevel=2)
    n_out = int(round(audio.size * sr_out / sr_in))
    if n_out <= 0:
        return np.zeros(0, dtype=np.float32)
    source = np.arange(audio.size, dtype=np.float64)
    target = np.linspace(0.0, audio.size - 1, n_out)
    return np.interp(target, source, audio).astype(np.float32)


def _as_mono(audio) -> np.ndarray:
    """Return *audio* as a 1-D float32 array, refusing multi-channel input.

    Flattening a ``(frames, channels)`` array interleaves the channels
    (L0, R0, L1, R1, ...), which doubles the clip's length and garbles it
    without any error. The IHM clips every current caller reads are mono,
    so this never fires on them; it is here so that another configuration
    or corpus fails loudly instead of being summed as noise. Shapes with a
    single non-trivial axis, such as ``(frames, 1)``, are mono and pass.

    Raises
    ------
    ValueError
        When more than one axis has a length greater than one.
    """
    arr = np.asarray(audio, dtype=np.float32)
    if sum(d > 1 for d in arr.shape) > 1:
        raise ValueError(
            f"expected mono audio, got an array of shape {arr.shape}. "
            "Down-mix it explicitly before reconstruction.")
    return arr.reshape(-1)


def _usable_rows(rows: Sequence[dict], max_duration_s: float | None):
    """Return rows with a positive annotated span, truncated to the cap."""
    kept = []
    for row in rows:
        begin = float(row["begin_time"])
        end = float(row["end_time"])
        if max_duration_s is not None:
            if begin >= max_duration_s:
                continue
            end = min(end, max_duration_s)
        if end > begin:
            kept.append((begin, end, row))
    return kept


def mix_meeting(
    rows: Sequence[dict],
    decode: Callable[[dict], tuple[np.ndarray, int]],
    sample_rate: int = SAMPLE_RATE,
    max_duration_s: float | None = None,
    normalise: bool = True,
) -> tuple[np.ndarray, list[dict], dict]:
    """Rebuild one meeting by summing headset channels on a shared timeline.

    Each utterance is written at ``begin_time`` and added to whatever is
    already there, so simultaneous speakers reinforce exactly as they do
    in AMI's own headset mix.

    Audio is truncated to the annotated span whenever the distributed
    clip runs longer.  The alternative, writing the whole clip, would put
    speech outside the reference and charge the diarisation system a
    false alarm for a discrepancy in the corpus rather than an error of
    its own.  The size of that discrepancy is reported in the statistics
    as ``clip_annotation_mismatch_s`` rather than being silently absorbed.

    Parameters
    ----------
    rows:
        Utterance dicts carrying ``begin_time``, ``end_time`` and
        ``speaker_id``, plus whatever *decode* needs.
    decode:
        Callable returning ``(samples, sample_rate)`` for one row.  A row
        it cannot decode should raise, and is then skipped and counted.
        The samples must be mono; multi-channel audio raises
        :class:`ValueError` (see :func:`_as_mono`) and stops the meeting.
    max_duration_s:
        Truncate the meeting to its first *max_duration_s* seconds.
    normalise:
        Divide by the peak when summing pushes it above unity.  A single
        global gain leaves the relative levels of the speakers, and hence
        the diarisation problem, unchanged.

    Returns
    -------
    (audio, reference, statistics)
        *audio* is float32 at *sample_rate*. *reference* is a list of
        ``{'start', 'end', 'speaker'}`` dicts in the same timeline, and
        *statistics* describes the reconstruction.
    """
    usable = _usable_rows(rows, max_duration_s)
    if not usable:
        # The same keys as a non-empty meeting, so that a caller logging
        # n_speakers or skipped_utterances for every meeting does not fail
        # on exactly the meeting it most needs to report.
        stats = meeting_statistics([], duration_s=0.0)
        stats.update({"mode": "timeline", "skipped_utterances": 0,
                      "normalisation_gain": 1.0,
                      "clip_annotation_mismatch_s": 0.0})
        return np.zeros(0, dtype=np.float32), [], stats

    span_s = max(end for _, end, _ in usable)
    n_samples = int(round(span_s * sample_rate))
    mix = np.zeros(n_samples, dtype=np.float32)

    reference: list[dict] = []
    skipped = 0
    mismatch_total = 0.0
    for begin, end, row in usable:
        try:
            audio, sr_in = decode(row)
        except Exception:  # one bad clip must not lose a meeting
            skipped += 1
            continue
        audio = _resample(_as_mono(audio), int(sr_in), sample_rate)

        annotated = int(round((end - begin) * sample_rate))
        mismatch_total += abs(audio.size - annotated) / sample_rate
        if audio.size > annotated:
            audio = audio[:annotated]

        offset = int(round(begin * sample_rate))
        available = min(audio.size, n_samples - offset)
        if available > 0:
            mix[offset:offset + available] += audio[:available]

        reference.append({"start": begin, "end": end,
                          "speaker": str(row["speaker_id"])})

    gain = 1.0
    if normalise and mix.size:
        peak = float(np.max(np.abs(mix)))
        if peak > 1.0:
            gain = 1.0 / peak
            mix *= gain

    stats = meeting_statistics(reference, duration_s=span_s)
    stats.update({
        "mode": "timeline",
        "skipped_utterances": skipped,
        "normalisation_gain": round(gain, 6),
        "clip_annotation_mismatch_s": round(mismatch_total, 3),
    })
    return mix, reference, stats


def concat_meeting(
    rows: Sequence[dict],
    decode: Callable[[dict], tuple[np.ndarray, int]],
    sample_rate: int = SAMPLE_RATE,
    max_utterances: int | None = DEFAULT_UTTERANCES_PER_MEETING,
    gap_s: float = CONCAT_GAP_S,
) -> tuple[np.ndarray, list[dict], dict]:
    """Rebuild one meeting by concatenating utterances with silent gaps.

    Preserved so the benchmark's earlier results stay reproducible.  See
    the module docstring for why this arrangement understates the
    diarisation problem.

    Parameters
    ----------
    rows:
        Utterance dicts in the order they should be laid out, carrying
        ``speaker_id`` plus whatever *decode* needs.
    decode:
        Callable returning ``(samples, sample_rate)``; a row it cannot
        decode should raise, and is skipped and counted.
    sample_rate:
        Output rate.
    max_utterances:
        Use only the first *max_utterances* rows; ``None`` or 0 uses all.
    gap_s:
        Silence appended after every utterance, in seconds.

    Returns
    -------
    (audio, reference, statistics)
        *audio* is float32 at *sample_rate*; *reference* holds
        ``{'start', 'end', 'speaker'}`` turns on the concatenated
        timeline, each spanning its clip's decoded length; *statistics*
        is :func:`meeting_statistics` plus ``mode``,
        ``skipped_utterances`` and ``normalisation_gain``.
    """
    selected = list(rows)[:max_utterances] if max_utterances else list(rows)
    silence = np.zeros(int(round(gap_s * sample_rate)), dtype=np.float32)

    parts: list[np.ndarray] = []
    reference: list[dict] = []
    cursor = 0.0
    skipped = 0
    for row in selected:
        try:
            audio, sr_in = decode(row)
        except Exception:  # counted in skipped_utterances
            skipped += 1
            continue
        audio = _resample(_as_mono(audio), int(sr_in), sample_rate)
        duration = audio.size / sample_rate
        reference.append({"start": cursor, "end": cursor + duration,
                          "speaker": str(row["speaker_id"])})
        parts.append(audio)
        parts.append(silence)
        cursor += duration + gap_s

    if not parts:
        stats = meeting_statistics([], duration_s=0.0)
        stats.update({"mode": "concat", "skipped_utterances": skipped,
                      "normalisation_gain": 1.0})
        return np.zeros(0, dtype=np.float32), [], stats

    mixed = np.concatenate(parts)
    stats = meeting_statistics(reference, duration_s=mixed.size / sample_rate)
    stats.update({"mode": "concat", "skipped_utterances": skipped,
                  "normalisation_gain": 1.0})
    return mixed, reference, stats


# ---------------------------------------------------------------------------
# Description
# ---------------------------------------------------------------------------

def overlap_duration(reference: Sequence[dict]) -> tuple[float, float]:
    """Return ``(speech_s, overlap_s)`` for a reference annotation.

    *speech_s* is the union of all speaker turns and *overlap_s* the part
    of that union covered by two or more speakers at once.  A sweep line
    over turn boundaries gives both in one pass and handles turns that
    are nested inside one another, which a pairwise intersection does
    not.
    """
    events: list[tuple[float, int]] = []
    for seg in reference:
        start, end = float(seg["start"]), float(seg["end"])
        if end > start:
            events.append((start, 1))
            events.append((end, -1))
    if not events:
        return 0.0, 0.0

    events.sort()
    speech = overlap = 0.0
    depth = 0
    previous = events[0][0]
    for time, delta in events:
        if depth >= 1:
            speech += time - previous
            if depth >= 2:
                overlap += time - previous
        depth += delta
        previous = time
    return speech, overlap


def meeting_statistics(reference: Sequence[dict], duration_s: float) -> dict:
    """Describe a reconstructed meeting.

    ``silence_fraction`` records how much of the reconstruction carries no
    annotated speech, and therefore how much of it is digital silence
    rather than the room tone a continuous recording would contain.
    """
    speech, overlap = overlap_duration(reference)
    speakers = {seg["speaker"] for seg in reference}
    return {
        "n_utterances": len(reference),
        "n_speakers": len(speakers),
        "duration_s": round(float(duration_s), 3),
        "speech_s": round(speech, 3),
        "overlap_s": round(overlap, 3),
        "overlap_fraction": round(overlap / speech, 4) if speech else 0.0,
        "silence_fraction": (round(max(0.0, duration_s - speech) / duration_s, 4)
                             if duration_s else 0.0),
    }
