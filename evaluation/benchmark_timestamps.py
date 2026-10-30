#!/usr/bin/env python3
"""
Segment-level timestamp alignment benchmark on the AMI Meeting Corpus.

Streams the AMI IHM test split and, for each utterance, runs Whisper Large
v3 with segment-level ``return_timestamps=True``.  The reference boundaries
for each utterance are 0.0 s (start) and the audio duration (end), since
each AMI IHM row is cut at its annotated segment.  The annotated end can
include trailing non-speech, so the benchmark measures how far Whisper's
first and last timestamps lie from the clip's boundaries, not from a
measured onset and offset of speech.

What it scores is Whisper's segment-level timestamp tokens. The workflow
asks for word-level timestamps instead whenever timestamps or speaker
attribution are requested (``effective_timestamps`` in
``transcription.process_audio_file``), and those word timings are what its JSON,
WebVTT and review outputs carry, so this benchmark does not measure them.

Metrics reported per utterance and in aggregate:

``start_error``
    ``predicted_start - 0.0``.  Positive means Whisper's first timestamp
    is after the clip start.
``end_error``
    ``ref_duration - predicted_end``.  Positive means Whisper's last
    timestamp ends before the clip does, which need not mean words were
    left out; the summary's ``truncation_rate`` counts the ends more than
    0.5 s early (see :func:`evaluation.timestamp_metrics.aggregate_boundary_errors`
    for what that rate measures and why its name is historical).
``MAE_start``, ``MAE_end``, ``MAE_total``
    Mean absolute errors in seconds.
``RMSE_start``, ``RMSE_end``
    Root mean squared errors in seconds.

Output is written to ``output/evaluation/timestamp_report.csv`` (one row
per scored utterance), ``timestamp_skipped.csv`` (one row per utterance
that could not be scored, with the reason) and ``timestamp_summary.json``.

Sampling
--------
By default the first ``--limit`` rows of the streamed split are used, in
the release's order. The release stores each meeting's rows together, so
the committed 500-row sample is the first rows of one meeting (EN2002a,
four speakers). ``--per-meeting N`` instead takes at most *N* rows from each
meeting in turn, spreading the same budget across the split's meetings.
It is off by default so the committed result stays reproducible. The
summary records which sampling ran and the meetings it covered.

Usage::

    python -m evaluation.benchmark_timestamps
    python -m evaluation.benchmark_timestamps --limit 500
    python -m evaluation.benchmark_timestamps --limit 500 --per-meeting 32
    python -m evaluation.benchmark_timestamps \\
        --model openai/whisper-large-v3 \\
        --limit 200 \\
        --output-dir output/evaluation

Privacy note
------------
Audio is streamed from the HuggingFace Hub, decoded locally, and never
written to disk.  No audio or transcript leaves the local machine.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import warnings
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # For the annotations only: importing numpy at run time would register
    # warning filters on import, and this module promises not to.
    import numpy as np

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_OUTPUT_DIR = _ROOT / "output" / "evaluation"
_AMI_DATASET = "edinburghcstr/ami"
_AMI_CONFIG = "ihm"
_AMI_SPLIT = "test"
_SR = 16_000
_DEFAULT_MODEL = "openai/whisper-large-v3"
_DEFAULT_LIMIT = 500
# ``pipeline(..., dtype=...)`` in _load_whisper is accepted from this
# transformers release onwards; older releases reject the keyword.
_TRANSFORMERS_DTYPE_FLOOR = (4, 56)
# Long-form chunking of the ASR pipeline. Every AMI IHM utterance is far
# shorter than one chunk, so these govern only an unusually long clip;
# they are recorded in the summary because they shape the decode.
# TODO: justify (source unknown): 30 s is Whisper's input window; no
# record says why the 5 s stride was chosen.
_CHUNK_LENGTH_S = 30
_STRIDE_LENGTH_S = 5

#: Silero VAD release loaded through torch.hub, pinned to a tag
#: (DEPS-06, TESTS-10). The first committed evaluation_vad_refine run
#: (job 7746221, 31 May 2026) named no tag and loaded the repository head,
#: commit 980b17e (26 March 2026). The snapshot it loaded is still in the
#: project's hub cache on ARC ($DATA/speech_transcription_env/.torch_cache/
#: hub/snakers4_silero-vad_master), a shallow clone made at 14:47 that
#: day, before the job started. That commit differs from v6.2.1 (7e30209,
#: 24 February 2026) only in save_audio, _seconds_to_samples_tss, the
#: README and a Rust example, none of which this benchmark calls, and its
#: model files have the same SHA-256 as the tag's (both checked on ARC on
#: 2026-10-04). Job 8917981 loaded this tag and reproduced that run's
#: report in every row.
SILERO_VAD_REPO = "snakers4/silero-vad:v6.2.1"

#: Why an utterance was not scored, as written to timestamp_skipped.csv
#: and counted in the summary's ``skip_reasons``.
SKIP_REASONS = (
    "decode_error",          # the audio bytes could not be decoded
    "resample_error",        # a non-16 kHz clip could not be resampled
    "asr_error",             # the pipeline raised
    "no_chunks",             # the pipeline returned no timestamped chunks
    "untimed_tail",          # the final chunk has no end timestamp
    "no_start_timestamp",    # no chunk carries both timestamps
)


class TimestampBenchmarkError(RuntimeError):
    """A run that cannot produce a trustworthy summary.

    Raised by the library functions of this module and turned into an exit
    status by :func:`main` (ESTATS-14), so a caller that imports
    :func:`run_benchmark` can catch it like any other exception.
    """


# The token lookup and the AMI audio decoder are shared with the DER
# benchmark and the fine-tuning script (audit findings EDER-15, XREF-07);
# this module used to carry its own copies. The decoder is the same code
# path (array if present, otherwise soundfile on the encoded bytes), so the
# committed timestamp results are unaffected. Both are imported on first
# use: importing ami_meetings loads numpy, which would register warning
# filters at import time, and this module promises not to.
def _load_hf_token() -> str | None:
    """Return the shared HuggingFace token; see ``ami_meetings.load_hf_token``."""
    from evaluation.ami_meetings import load_hf_token

    return load_hf_token()


def _decode_audio_bytes(audio_dict: dict):
    """Decode one AMI audio field; see ``ami_meetings.decode_audio_bytes``."""
    from evaluation.ami_meetings import decode_audio_bytes

    return decode_audio_bytes(audio_dict)


def _load_silero_vad():
    """Load the Silero VAD model from :data:`SILERO_VAD_REPO` (torch.hub).

    Silero VAD is a small offline model (its hub entry loads a 2.3 MB
    TorchScript file) that detects voice activity with frame-level
    resolution.  It is used here solely to refine
    Whisper's predicted end boundary: the refined end is the later of the
    VAD's last-voiced-frame end and Whisper's own end, so the boundary is
    extended where speech continues past Whisper's final timestamp and is
    never pulled earlier (see :func:`_refine_end_with_vad`).

    Returns
    -------
    (model, utils)
        ``utils`` is Silero's tuple ``(get_speech_timestamps, save_audio,
        read_audio, VADIterator, collect_chunks)`` (hubconf.py at v6.2.1).

    Side effects
    ------------
    Downloads the tagged release into the torch hub cache on first use and
    runs its ``hubconf.py`` (``trust_repo=True``: the tag, not a moving
    branch, is what is trusted). A job without network access needs the
    cache warmed with the same tag beforehand.
    """
    import torch
    model, utils = torch.hub.load(
        repo_or_dir=SILERO_VAD_REPO,
        model="silero_vad",
        force_reload=False,
        trust_repo=True,
        verbose=False,
    )
    model.eval()
    return model, utils


def _refine_end_with_vad(
    audio_array: np.ndarray,
    whisper_end: float,
    vad_model,
    get_speech_timestamps,
    stats: dict | None = None,
) -> float:
    """Return a refined end timestamp using Silero VAD.

    If the VAD finds voiced speech in *audio_array*, the refined end is the
    end of the last voiced segment.  If the VAD finds no speech at all, the
    Whisper end is returned unchanged (the clip may be near-silence).

    The refined end is the later of the VAD endpoint and Whisper's own
    prediction, so a clip on which Whisper's last timestamp falls before the
    last voiced frame (for example on a soft trailing syllable) is extended
    to that frame. The VAD never pulls the end earlier than Whisper already
    predicted.

    Parameters
    ----------
    stats:
        Optional counter dict. When given, ``n_vad_exception`` or
        ``n_vad_no_speech`` is incremented for a clip on which the VAD
        raised or found no speech, so a run can report how many ends were
        left unrefined. The returned value does not depend on it.
    """
    import torch

    waveform = torch.tensor(audio_array).unsqueeze(0)   # (1, T)
    try:
        timestamps = get_speech_timestamps(
            waveform,
            vad_model,
            sampling_rate=_SR,
            return_seconds=True,
        )
    except Exception:
        if stats is not None:
            stats["n_vad_exception"] = stats.get("n_vad_exception", 0) + 1
        return whisper_end

    if not timestamps:
        if stats is not None:
            stats["n_vad_no_speech"] = stats.get("n_vad_no_speech", 0) + 1
        return whisper_end

    vad_end = float(timestamps[-1]["end"])
    # Extend Whisper's end to the last voiced frame when the VAD detects
    # speech continuing beyond Whisper's final chunk, as on a soft trailing
    # syllable. Where the clip ends in non-speech after the last word, the
    # VAD's end is no later than Whisper's and the end is left as it was.
    return max(vad_end, whisper_end)


def _transformers_version_ok(version: str) -> bool:
    """Whether *version* is at least :data:`_TRANSFORMERS_DTYPE_FLOOR`.

    Compares the leading ``major.minor`` numbers only, so pre-release and
    local suffixes do not matter.
    """
    parts = []
    for piece in version.split(".")[:2]:
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 2:
        parts.append(0)
    return tuple(parts) >= _TRANSFORMERS_DTYPE_FLOOR


def _load_whisper(model_id: str):
    """Load the Whisper ASR pipeline at its pinned revision.

    Builds a new pipeline on every call, on the first CUDA device when one
    is available (float16) and on the CPU otherwise (float32). The model is
    loaded at :func:`evaluation.revisions.revision_for` of *model_id*, the
    snapshot the committed runs used; an unlisted model loads ``main``.

    Returns
    -------
    (pipeline, settings)
        *settings* records what shapes the decode: ``device``, ``dtype``,
        ``chunk_length_s``, ``stride_length_s`` and ``model_revision``
        (ESTATS-12). A CPU re-run decodes in float32 and can move timestamp
        tokens, so the summary must say which ran.

    Raises
    ------
    TimestampBenchmarkError
        If torch or transformers is missing, or if transformers is older
        than :data:`_TRANSFORMERS_DTYPE_FLOOR`, whose ASR pipeline rejects
        the ``dtype`` keyword used below. Failing here, before the corpus
        is streamed, costs less than a TypeError inside a queued GPU job.
    """
    try:
        import torch
        import transformers
        from transformers import pipeline as hf_pipeline
    except ImportError as exc:
        raise TimestampBenchmarkError("transformers and torch are required.") from exc
    if not _transformers_version_ok(transformers.__version__):
        raise TimestampBenchmarkError(
            f"transformers {transformers.__version__} is too old for this "
            "benchmark: it passes dtype= to pipeline(), which needs "
            f"transformers>={'.'.join(map(str, _TRANSFORMERS_DTYPE_FLOOR))}."
        )
    from evaluation.revisions import revision_for

    device = 0 if torch.cuda.is_available() else -1
    dtype = torch.float16 if device >= 0 else torch.float32
    revision = revision_for(model_id)
    pipe = hf_pipeline(
        "automatic-speech-recognition",
        model=model_id,
        revision=revision,
        dtype=dtype,
        device=device,
        return_timestamps=True,
        chunk_length_s=_CHUNK_LENGTH_S,
        stride_length_s=_STRIDE_LENGTH_S,
    )
    settings = {
        "device": "cuda:0" if device >= 0 else "cpu",
        "gpu": torch.cuda.get_device_name(0) if device >= 0 else None,
        "dtype": str(dtype).replace("torch.", ""),
        "chunk_length_s": _CHUNK_LENGTH_S,
        "stride_length_s": _STRIDE_LENGTH_S,
        "model_revision": revision,
    }
    return pipe, settings


def _predict_boundaries(
    asr_pipe,
    audio_array: np.ndarray,
    vad_model=None,
    get_speech_timestamps=None,
    vad_stats: dict | None = None,
    info: dict | None = None,
) -> tuple[float, float] | None:
    """Return (predicted_start, predicted_end) from Whisper chunk timestamps.

    The start is that of the first chunk carrying both timestamps; the end
    is that of the final chunk. When *vad_model* and
    *get_speech_timestamps* are supplied, the predicted end boundary is
    refined using Silero VAD: the refined end is the later of the VAD's
    last-voiced-frame end and Whisper's own end, so an end Whisper placed
    before the last voiced frame is extended and none is pulled earlier.
    *vad_stats* is passed through to :func:`_refine_end_with_vad`.

    A final chunk without an end timestamp is an untimed tail: the
    tokenizer logs "Whisper did not predict an ending timestamp" and still
    returns the chunk, with its text, and an end of ``None``. The end of
    speech is then unknown. Taking the previous chunk's end instead, as
    this function used to, reported the utterance as ending early and
    counted it in ``truncation_rate`` although the model had transcribed
    the tail (ESTATS-02). Such an utterance is not scored.

    Parameters
    ----------
    info:
        Optional dict, filled with ``n_chunks``, ``text`` (the
        hypothesis), ``untimed_tail`` and ``skip_reason`` (one of
        :data:`SKIP_REASONS`, or ``None`` when the utterance is scored).

    Returns
    -------
    tuple or None
        ``None`` when the utterance cannot be scored; *info* says why.
    """
    if info is None:
        info = {}
    info.update({"n_chunks": 0, "text": "", "untimed_tail": False,
                 "skip_reason": None})
    try:
        result = asr_pipe(audio_array.copy())
    except Exception as exc:
        print(f"    ASR failed: {exc}", file=sys.stderr)
        info["skip_reason"] = "asr_error"
        return None

    chunks = result.get("chunks") or []
    info["n_chunks"] = len(chunks)
    info["text"] = str(result.get("text") or "").strip()
    if not chunks:
        info["skip_reason"] = "no_chunks"
        return None

    final = chunks[-1].get("timestamp") or (None, None)
    if len(final) < 2 or final[1] is None:
        info["untimed_tail"] = True
        info["skip_reason"] = "untimed_tail"
        return None

    timed = [c for c in chunks if c.get("timestamp") and None not in c["timestamp"]]
    if not timed:
        info["skip_reason"] = "no_start_timestamp"
        return None

    pred_start = float(timed[0]["timestamp"][0])
    pred_end = float(final[1])

    if vad_model is not None and get_speech_timestamps is not None:
        pred_end = _refine_end_with_vad(
            audio_array, pred_end, vad_model, get_speech_timestamps,
            stats=vad_stats,
        )

    return pred_start, pred_end


def _meeting_of(row: dict) -> str:
    """Return the AMI meeting id of *row* (``meeting_id``, else from ``audio_id``).

    AMI audio ids read ``AMI_<meeting>_<headset>_<speaker>_<begin>_<end>``.
    """
    if row.get("meeting_id"):
        return str(row["meeting_id"])
    parts = str(row.get("audio_id", "")).split("_")
    return parts[1] if len(parts) > 1 else ""


def select_rows(rows, limit: int | None, per_meeting: int | None = None):
    """Yield the utterance rows to score, in order.

    With *per_meeting* unset the first *limit* rows of the stream are
    yielded, which is what produced the committed results. With it set, at
    most *per_meeting* rows of each meeting are taken (earliest first, as
    :func:`evaluation.ami_meetings.group_rows_by_meeting` sorts them), until
    *limit* rows have been yielded, so the same budget covers more meetings
    and speakers (ESTATS-12; the anonymisation benchmark's ``--per-meeting``
    does the same).

    Parameters
    ----------
    rows:
        Iterable of AMI rows in stream order.
    limit:
        Rows to yield at most; ``None`` for no cap. Rows that later fail to
        decode or score still count toward it.
    per_meeting:
        Cap per meeting, or ``None``.

    Raises
    ------
    ValueError
        When *per_meeting* is not positive, or (from the grouping) when a
        meeting's rows are not contiguous in the stream.
    """
    if per_meeting is None:
        for i, row in enumerate(rows):
            if limit is not None and i >= limit:
                return
            yield row
        return
    if per_meeting < 1:
        raise ValueError(f"per_meeting must be at least 1, got {per_meeting}")
    from evaluation.ami_meetings import group_rows_by_meeting

    taken = 0
    for _mid, meeting_rows in group_rows_by_meeting(rows):
        for row in meeting_rows[:per_meeting]:
            if limit is not None and taken >= limit:
                return
            yield row
            taken += 1


def run_benchmark(
    output_dir: Path,
    model_id: str,
    limit: int | None,
    vad_refine: bool = False,
    per_meeting: int | None = None,
) -> dict:
    """Run the timestamp alignment benchmark and write results to *output_dir*.

    Parameters
    ----------
    output_dir:
        Directory for ``timestamp_report.csv``, ``timestamp_skipped.csv``
        and ``timestamp_summary.json``. Created if absent; the files are
        overwritten.
    model_id:
        HuggingFace model identifier for the Whisper pipeline.
    limit:
        Cap on the number of utterances streamed (``None`` streams all).
        Utterances that fail to decode or yield no timestamps count toward
        the cap and are reported as ``n_skipped``, by reason.
    vad_refine:
        When ``True``, load Silero VAD (:data:`SILERO_VAD_REPO`) and refine
        Whisper's predicted end boundary on each utterance to the later of
        the VAD's last-voiced end and Whisper's own end, extending ends
        where speech continues past Whisper's final timestamp and never
        pulling one earlier.  Requires an internet connection on the first
        call, when torch.hub fetches the tag's repository (about 35 MB
        unpacked); later calls use the local torch hub cache.
    per_meeting:
        Take at most this many utterances per meeting (see
        :func:`select_rows`); ``None``, the default, reads the stream from
        the front as the committed run did.

    Returns
    -------
    dict
        The summary written to ``timestamp_summary.json``.

    Raises
    ------
    TimestampBenchmarkError
        If a dependency is missing, if *vad_refine* was requested but the
        VAD could not be loaded (a run labelled as refined must have been
        refined), or if no utterance was scored (every error would then be
        undefined). In the last case the files are still written.

    Side effects
    ------------
    Streams the AMI corpus from the Hugging Face Hub at its pinned
    revision, loads the Whisper model (and the VAD from torch hub), reads
    the Hugging Face token (see :func:`_load_hf_token`) and prints
    progress. Python warnings raised while it runs are suppressed; the
    suppression is scoped to this call.
    """
    # TODO: justify (source unknown). The benchmark has silenced every
    # warning since it was added (4e7813e) without saying which ones. The
    # filter is scoped to the run, so a process that merely imports this
    # module keeps its own warnings.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return _run_benchmark(output_dir, model_id, limit, vad_refine,
                              per_meeting)


_REPORT_FIELDS = [
    "audio_id", "ref_duration_s",
    "pred_start_s", "pred_end_s",
    "start_error_s", "end_error_s",
    "abs_start_error_s", "abs_end_error_s",
    "n_chunks", "hypothesis",
]
_SKIPPED_FIELDS = ["audio_id", "meeting_id", "reason", "n_chunks", "hypothesis"]


def _run_benchmark(
    output_dir: Path,
    model_id: str,
    limit: int | None,
    vad_refine: bool,
    per_meeting: int | None = None,
) -> dict:
    """Body of :func:`run_benchmark`, run inside its warnings scope."""
    from evaluation.revisions import revision_for, revisions_used
    from evaluation.timestamp_metrics import aggregate_boundary_errors, boundary_error
    from provenance import run_metadata

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "timestamp_report.csv"
    skipped_path = output_dir / "timestamp_skipped.csv"
    summary_path = output_dir / "timestamp_summary.json"
    # The git state the summary records is read before anything is written
    # and leaves out the three files this run rewrites, as
    # provenance.write_sidecar does for the CSV-only writers. It used to be
    # read after the report and skipped files had been written, so a
    # regeneration in place, which a run into the default output directory
    # (the repository's output/evaluation) is, counted any of the three that
    # differed from its committed copy as a change to the tree.
    run_meta = run_metadata(ignore=(report_path, skipped_path, summary_path))
    hf_token = _load_hf_token()

    try:
        import datasets as hf_datasets
        from datasets import Audio as _HFAudio
    except ImportError as exc:
        raise TimestampBenchmarkError("datasets>=2.14.0 is required.") from exc

    load_kwargs: dict = {
        "path": _AMI_DATASET,
        "name": _AMI_CONFIG,
        "split": _AMI_SPLIT,
        "streaming": True,
        "revision": revision_for(_AMI_DATASET),
    }
    if hf_token:
        load_kwargs["token"] = hf_token

    print(f"Loading Whisper model {model_id}...", flush=True)
    asr_pipe, whisper_settings = _load_whisper(model_id)

    vad_model = None
    get_speech_timestamps = None
    if vad_refine:
        print(f"Loading Silero VAD ({SILERO_VAD_REPO}) for end-boundary "
              "refinement...", flush=True)
        try:
            vad_model, vad_utils = _load_silero_vad()
            get_speech_timestamps = vad_utils[0]  # silero returns a namedtuple
            print("  Silero VAD loaded.", flush=True)
        except Exception as exc:
            # A run asked to refine and quietly not refining would still
            # write vad_refine: true into its summary, so stop instead.
            raise TimestampBenchmarkError(
                f"Could not load Silero VAD ({exc}); --vad-refine was "
                "requested, so the run stops rather than write unrefined "
                "boundaries under a refined label."
            ) from exc
    vad_stats: dict = {"n_vad_exception": 0, "n_vad_no_speech": 0}

    print("Streaming AMI IHM test utterances...", flush=True)
    ds = hf_datasets.load_dataset(**load_kwargs)
    # Disable the datasets 3.x automatic audio decoding (torchcodec / FFmpeg)
    # and decode the raw bytes ourselves using soundfile.
    ds = ds.cast_column("audio", _HFAudio(decode=False))

    error_records: list[dict] = []
    skip_counts = dict.fromkeys(SKIP_REASONS, 0)
    meetings: dict[str, int] = {}
    n_streamed = 0

    with report_path.open("w", newline="", encoding="utf-8") as fh, \
            skipped_path.open("w", newline="", encoding="utf-8") as skipped_fh:
        writer = csv.DictWriter(fh, fieldnames=_REPORT_FIELDS)
        writer.writeheader()
        skipped_writer = csv.DictWriter(skipped_fh, fieldnames=_SKIPPED_FIELDS)
        skipped_writer.writeheader()

        def skip(audio_id, meeting, reason, info=None):
            info = info or {}
            skip_counts[reason] += 1
            skipped_writer.writerow({
                "audio_id": audio_id, "meeting_id": meeting, "reason": reason,
                "n_chunks": info.get("n_chunks", ""),
                "hypothesis": info.get("text", ""),
            })
            skipped_fh.flush()

        for i, row in enumerate(select_rows(ds, limit, per_meeting)):
            n_streamed += 1
            audio_id = row["audio_id"]
            meeting = _meeting_of(row)
            meetings[meeting] = meetings.get(meeting, 0) + 1
            if (i + 1) % 50 == 0:
                print(f"  processed {i + 1} utterances "
                      f"(skipped {sum(skip_counts.values())})...", flush=True)

            try:
                arr, sr = _decode_audio_bytes(row["audio"])
            except Exception as exc:
                print(f"  ⚠  {audio_id}: audio decode failed: {exc}", file=sys.stderr)
                skip(audio_id, meeting, "decode_error")
                continue

            if sr != _SR:
                try:
                    import librosa
                    arr = librosa.resample(arr, orig_sr=sr, target_sr=_SR)
                except Exception as exc:
                    print(f"  ⚠  {audio_id}: resample from {sr} Hz failed: "
                          f"{exc}", file=sys.stderr)
                    skip(audio_id, meeting, "resample_error")
                    continue

            ref_duration = len(arr) / _SR

            info: dict = {}
            boundaries = _predict_boundaries(
                asr_pipe, arr,
                vad_model=vad_model,
                get_speech_timestamps=get_speech_timestamps,
                vad_stats=vad_stats,
                info=info,
            )
            if boundaries is None:
                skip(audio_id, meeting, info["skip_reason"], info)
                continue

            pred_start, pred_end = boundaries
            errs = boundary_error(pred_start, pred_end, ref_duration)
            errs["audio_id"] = audio_id
            error_records.append(errs)

            writer.writerow({
                "audio_id":            audio_id,
                "ref_duration_s":      round(ref_duration, 4),
                "pred_start_s":        round(pred_start, 4),
                "pred_end_s":          round(pred_end, 4),
                "start_error_s":       round(errs["start_error"], 4),
                "end_error_s":         round(errs["end_error"], 4),
                "abs_start_error_s":   round(errs["abs_start_error"], 4),
                "abs_end_error_s":     round(errs["abs_end_error"], 4),
                "n_chunks":            info["n_chunks"],
                "hypothesis":          info["text"],
            })
            fh.flush()

    n_skipped = sum(skip_counts.values())
    summary = aggregate_boundary_errors(error_records)
    summary["n_skipped"] = n_skipped
    summary["skip_reasons"] = skip_counts
    # Named on its own because it is the case that used to be counted in
    # truncation_rate (ESTATS-02).
    summary["n_missing_end_timestamp"] = skip_counts["untimed_tail"]
    summary["dataset"] = f"{_AMI_DATASET}/{_AMI_CONFIG}/{_AMI_SPLIT}"
    summary["model"] = model_id
    # What the sample is, so the artefact does not read as the whole split
    # (ESTATS-12): the committed default is the first rows of one meeting.
    summary["sampling"] = {
        "limit": limit,
        "per_meeting": per_meeting,
        "order": ("spread across meetings" if per_meeting is not None
                  else "stream order, first rows of the split"),
        "n_streamed": n_streamed,
        "n_meetings": len(meetings),
        "utterances_per_meeting": dict(sorted(meetings.items())),
    }
    summary["whisper"] = whisper_settings
    summary["revisions"] = revisions_used(model_id, _AMI_DATASET)
    summary["vad_refine"] = vad_refine
    # What was applied, beside what was asked for: vad_refine records the
    # request, and the counts say on how many clips the VAD left Whisper's
    # end untouched because it raised or heard no speech.
    summary["vad_applied"] = get_speech_timestamps is not None
    if summary["vad_applied"]:
        summary["vad_source"] = SILERO_VAD_REPO
        summary.update(vad_stats)
    summary["run"] = run_meta
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    n = summary["n"]
    if n == 0:
        # Every error is undefined (None) at n == 0. Leave the files for
        # inspection but fail the job.
        reasons = {k: v for k, v in skip_counts.items() if v}
        raise TimestampBenchmarkError(
            f"No utterance was scored ({n_skipped} skipped: {reasons}). "
            f"See {summary_path} and {skipped_path}."
        )
    print(f"\nTimestamp summary ({n} utterances, {n_skipped} skipped, "
          f"{len(meetings)} meeting(s)):")
    print(f"  MAE start : {summary['mae_start']:.4f} s")
    print(f"  MAE end   : {summary['mae_end']:.4f} s")
    print(f"  MAE total : {summary['mae_total']:.4f} s")
    print(f"  RMSE start: {summary['rmse_start']:.4f} s")
    print(f"  RMSE end  : {summary['rmse_end']:.4f} s")
    if skip_counts["untimed_tail"]:
        print(f"  {skip_counts['untimed_tail']} utterance(s) had no end "
              "timestamp on their final chunk and were not scored.")
    print(f"Report written to {report_path}")
    print(f"Skipped utterances written to {skipped_path}")
    print(f"Summary written to {summary_path}")
    return summary


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Whisper timestamp alignment benchmark on AMI IHM.",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=_DEFAULT_OUTPUT_DIR,
    )
    p.add_argument(
        "--model",
        default=_DEFAULT_MODEL,
        help="HuggingFace model ID (default: openai/whisper-large-v3).",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=_DEFAULT_LIMIT,
        metavar="N",
        help=f"Number of utterances to score (default: {_DEFAULT_LIMIT}).",
    )
    p.add_argument(
        "--per-meeting",
        type=int,
        default=None,
        metavar="N",
        dest="per_meeting",
        help=(
            "Take at most N utterances from each meeting, so the --limit "
            "budget covers more meetings and speakers.  Off by default: "
            "the committed run read the first rows of the stream, which "
            "are one meeting."
        ),
    )
    p.add_argument(
        "--vad-refine",
        action="store_true",
        default=False,
        help=(
            "Refine Whisper end boundaries using Silero VAD "
            f"({SILERO_VAD_REPO}).  The refined end is the later of the "
            "VAD's last voiced frame and Whisper's own end, so ends are "
            "extended where speech continues past Whisper's final timestamp "
            "and never pulled earlier.  Requires a one-time torch.hub "
            "download of that release (about 35 MB unpacked); the run stops "
            "if the VAD cannot be loaded."
        ),
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the benchmark from the command line.

    Returns
    -------
    int
        0 on success; 1 when the run raised
        :class:`TimestampBenchmarkError` (message on stderr).
    """
    args = _parse_args(argv)
    try:
        run_benchmark(
            output_dir=args.output_dir,
            model_id=args.model,
            limit=args.limit,
            vad_refine=args.vad_refine,
            per_meeting=args.per_meeting,
        )
    except TimestampBenchmarkError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
