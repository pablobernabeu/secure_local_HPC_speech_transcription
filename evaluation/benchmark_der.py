#!/usr/bin/env python3
"""
Diarisation error rate (DER) benchmark on the AMI Meeting Corpus.

The benchmark reconstructs AMI meetings from the utterance-level
``edinburghcstr/ami`` release, runs ``pyannote/speaker-diarization-3.1``
over each reconstruction, and scores the output against the corpus
speaker labels.  Per-meeting and corpus-level results are written to
``der_report.csv`` and ``der_summary.json``.

Reconstruction mode
-------------------
``--mix-mode timeline`` (the default) places every utterance at its true
position in the meeting and sums the headset channels, so speech that
overlapped in the original meeting overlaps here too.  That is the
condition diarisation systems are normally reported under on AMI, and
the resulting signal approximates the corpus's own headset mix.

``--mix-mode concat`` reproduces the arrangement this benchmark used
first: utterances laid end to end with a half-second silent gap.  It is
kept for reproducibility of the earlier figures only.  Because
concatenation removes all overlapping speech and switches microphone
channel at every utterance boundary, DER measured that way is not
comparable with published AMI results.  See :mod:`evaluation.ami_meetings`.

Tuning and reporting
--------------------
``--split validation`` scores the AMI development set, which is where
hyperparameters should be chosen. ``--split test`` is the held-out set
that the headline figure should come from.  Tuning and reporting on the
same split would make the reported DER an optimistic in-sample estimate.

Caching
-------
Reconstruction streams and decodes several hours of audio, which is slow
and does not need a GPU.  ``--cache-dir`` writes each reconstruction to
disk so that a sweep re-reads it instead of re-downloading it, and
``--build-cache-only`` performs the download on a CPU node without
holding a GPU idle.

Usage::

    # Build the reconstruction cache once, on CPU
    python -m evaluation.benchmark_der --split validation \\
        --cache-dir "$DATA/ami_cache" --build-cache-only

    # Score from the cache, on GPU
    python -m evaluation.benchmark_der --split test \\
        --cache-dir "$DATA/ami_cache" --output-dir output/evaluation

Privacy note
------------
Audio is streamed from the HuggingFace Hub and decoded locally.  Model
weights are downloaded to the local cache, an outbound-only operation
carrying no user data, and inference runs entirely on the local machine.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
from pathlib import Path

# No blanket warnings filter here. pyannote reports TF32 toggles
# (ReproducibilityWarning) and checkpoint or version mismatches through
# warnings, and those are exactly what explains a DER that differs
# between two jobs. Importing this module used to silence them for the
# whole process, the sweep and the anonymisation benchmark included.

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from evaluation.ami_meetings import (  # noqa: E402
    AMI_CONFIG,
    AMI_DATASET,
    CONCAT_GAP_S,
    DEFAULT_UTTERANCES_PER_MEETING,
    RECONSTRUCTION_VERSION,
    SAMPLE_RATE,
    concat_meeting,
    group_rows_by_meeting,
    mix_meeting,
)
# Re-exported under their historical private names: benchmark_anonymisation
# imports them from here, and tests replace ``_stream_ami`` on this module.
from evaluation.ami_meetings import decode_audio_bytes as _decode_audio_bytes  # noqa: E402
from evaluation.ami_meetings import load_hf_token as _load_hf_token  # noqa: E402
from evaluation.ami_meetings import stream_ami as _stream_ami  # noqa: E402
from evaluation.der_metrics import COLLAR_CONVENTION, DEFAULT_COLLAR_S  # noqa: E402

_DEFAULT_OUTPUT_DIR = _ROOT / "output" / "evaluation"
_AMI_DATASET = AMI_DATASET
_AMI_CONFIG = AMI_CONFIG
_COLLAR = DEFAULT_COLLAR_S
_DEFAULT_UTT_PER_MEETING = DEFAULT_UTTERANCES_PER_MEETING
_DEFAULT_MODEL = "pyannote/speaker-diarization-3.1"
#: The models the default pipeline's config.yaml names.
_DEFAULT_SUB_MODELS = ("pyannote/segmentation-3.0",
                       "pyannote/wespeaker-voxceleb-resnet34-LM")

#: Hyperparameters ``pyannote/speaker-diarization-3.1`` actually exposes,
#: mapped from command-line name to their position in the pipeline's
#: parameter tree.  Verified against the instantiated pipeline at runtime
#: rather than assumed, because a parameter that silently fails to apply
#: turns a sweep into an expensive way of re-measuring the default.
_TUNABLE = {
    "clustering_threshold": ("clustering", "threshold"),
    "min_cluster_size": ("clustering", "min_cluster_size"),
    "min_duration_off": ("segmentation", "min_duration_off"),
}


# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------

def _cache_paths(cache_dir: Path, split: str, mode: str, max_minutes,
                 utterances_per_meeting=None):
    """Return the directory for one reconstruction configuration.

    Whatever limits the meeting's extent goes into the directory name, so
    that two reconstructions of the same split can never be mistaken for
    one another: a ten-minute cache is not a full-length one, and a
    twenty-five-utterance concatenation is not a fifty-utterance one.
    Reading the wrong cache would silently score the wrong corpus.
    """
    if mode == "concat":
        cap = f"{int(utterances_per_meeting)}utt" if utterances_per_meeting else "all"
    else:
        cap = "full" if not max_minutes else f"{max_minutes:g}min"
    return cache_dir / f"{split}_{mode}_{cap}"


#: Manifest of a finished, unlimited build. Only this file is ever read.
_MANIFEST = "manifest.json"
#: Manifest of a build stopped by --limit-meetings. Written for the record
#: but never read, so a smoke test cannot pass itself off as the corpus.
_PARTIAL_MANIFEST = "manifest.partial.json"


def _manifest_record(split: str, mix_mode: str, max_minutes,
                     utterances_per_meeting, meetings: list[str],
                     limit_meetings: int | None) -> dict:
    """Describe a cache build, including what makes it complete.

    The first five keys are the ones every existing cache already carries;
    the rest were added so that a cache can be checked against the request
    and against the reconstruction code that built it.
    """
    return {
        "split": split, "mix_mode": mix_mode,
        # Only a timeline build is truncated, and 0 means no cap there, as
        # in _cache_paths; recording anything else would describe a cap the
        # audio never had.
        "max_minutes": (max_minutes or None) if mix_mode == "timeline" else None,
        "sample_rate": SAMPLE_RATE,
        "meetings": meetings,
        "complete": limit_meetings is None,
        "limit_meetings": limit_meetings,
        "reconstruction_version": RECONSTRUCTION_VERSION,
        "utterances_per_meeting": (utterances_per_meeting
                                   if mix_mode == "concat" else None),
        "concat_gap_s": CONCAT_GAP_S if mix_mode == "concat" else None,
        "normalise": mix_mode == "timeline",
    }


def _same_cap(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return float(a) == float(b)


def _check_manifest(manifest: dict, cache: Path, split: str, mix_mode: str,
                    max_minutes, utterances_per_meeting) -> None:
    """Refuse a cache that was not built for this request.

    The directory name already encodes split, mode and cap, so a mismatch
    here means the cache was copied, renamed or built by older code; in
    each case scoring it would report a different corpus under this
    request's label. Manifests written before the completeness and version
    fields existed are accepted: the two timeline caches behind the
    committed results, built by ARC job 8534741 on 2026-08-10, are of that
    kind and were checked complete when they were used. The concatenation
    cache behind ``der_concat/`` was built by the run that scored it, job
    8976357 at 9cb43e3, and carries the fields.

    Raises
    ------
    SystemExit
        On any mismatch, naming the field and the cache directory.
    """
    def refuse(what: str) -> None:
        raise SystemExit(
            f"cache {cache} does not match this request ({what}). Rebuild it "
            f"by removing that directory, or point --cache-dir elsewhere.")

    if manifest.get("split") != split:
        refuse(f"split {manifest.get('split')!r}, requested {split!r}")
    if manifest.get("mix_mode") != mix_mode:
        refuse(f"mix_mode {manifest.get('mix_mode')!r}, requested {mix_mode!r}")
    # The cap shapes only a timeline reconstruction, where 0 and None both
    # mean whole meetings (_cache_paths, build_corpus). A concat cache is
    # named by its utterance cap alone and concat_meeting never sees a
    # duration, so an older concat manifest that recorded one describes
    # the same audio as one that did not.
    if mix_mode == "timeline" and not _same_cap(
            manifest.get("max_minutes") or None, max_minutes or None):
        refuse(f"max_minutes {manifest.get('max_minutes')!r}, "
               f"requested {max_minutes!r}")
    if manifest.get("sample_rate") != SAMPLE_RATE:
        refuse(f"sample_rate {manifest.get('sample_rate')!r}, "
               f"expected {SAMPLE_RATE}")
    if manifest.get("complete") is False or manifest.get("limit_meetings") is not None:
        refuse("it was built with --limit-meetings "
               f"{manifest.get('limit_meetings')!r} and is incomplete")
    if "reconstruction_version" in manifest:
        if manifest["reconstruction_version"] != RECONSTRUCTION_VERSION:
            refuse(f"built by reconstruction version "
                   f"{manifest['reconstruction_version']!r}, the code is "
                   f"version {RECONSTRUCTION_VERSION}")
    else:
        print(f"  note: {cache / _MANIFEST} predates reconstruction "
              "versioning; accepted as complete", flush=True)
    if mix_mode == "concat":
        if (manifest.get("utterances_per_meeting") is not None
                and manifest["utterances_per_meeting"] != utterances_per_meeting):
            refuse(f"utterances_per_meeting {manifest['utterances_per_meeting']!r}, "
                   f"requested {utterances_per_meeting!r}")
        if (manifest.get("concat_gap_s") is not None
                and float(manifest["concat_gap_s"]) != CONCAT_GAP_S):
            refuse(f"concat_gap_s {manifest['concat_gap_s']!r}, "
                   f"the code uses {CONCAT_GAP_S}")


def refuse_cap_in_concat(mix_mode: str, max_minutes) -> None:
    """Refuse a meeting-length cap in concat mode, where nothing applies it.

    concat_meeting is bounded by the utterance cap and is never given a
    duration, so ``--max-minutes`` there would change no audio and only
    put a cap that was never applied into ``der_summary.json``. The
    variable behind it, MAX_MINUTES, is also one sbatch passes through from
    the submitting shell (hpc/submit_ami_cache.sh), so it can reach a
    concat job by accident.

    Raises
    ------
    SystemExit
        When *mix_mode* is ``"concat"`` and *max_minutes* is set and not 0.
    """
    if mix_mode == "concat" and max_minutes:
        raise SystemExit(
            f"--max-minutes {max_minutes:g} applies to --mix-mode timeline "
            "only; concat meetings are bounded by --utterances-per-meeting. "
            "Drop it (or unset MAX_MINUTES) for a concat run.")


def _partial(path: Path) -> Path:
    """Where *path* is written until the run that produces it has finished."""
    return path.with_name(path.name + ".partial")


def _require_scored(n: int, what: str, partial: Path | None = None) -> None:
    """Stop a run that scored nothing instead of reporting a DER of zero.

    Raises
    ------
    SystemExit
        When *n* is zero. The committed outputs are left untouched; the
        in-progress file, if any, is named so it can be inspected.
    """
    if n == 0:
        where = f"  The in-progress file is {partial}." if partial else ""
        raise SystemExit(
            f"no {what} was scored, so there is no DER to report.  Check "
            f"the split, the cache and the reconstruction log.{where}")


def _write_json_atomically(path: Path, payload: dict) -> None:
    """Write JSON through a temporary file, so a killed job leaves no half file."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)


#: The one signal every scoring path hands the pipeline: the reconstruction
#: as the cache stores it, a 16-bit PCM WAV read back as float32. Recorded
#: in der_summary.json as ``audio_signal``.
AUDIO_SIGNAL = "PCM_16 WAV read back as float32 (the cache format)"


def _as_cached(audio):
    """Return *audio* exactly as a PCM_16 cache file would give it back.

    A meeting read from the cache has been quantised to 16 bits by
    ``sf.write(..., subtype="PCM_16")``; a meeting built from the stream
    had not, so the first run into a new cache directory, and every run
    without ``--cache-dir``, scored different audio from every later run
    (EDER-06). The same soundfile write and read, done in memory, gives
    the no-cache path the identical signal.

    Parameters
    ----------
    audio:
        Mono float samples at ``SAMPLE_RATE``.

    Returns
    -------
    numpy.ndarray
        float32 samples after the 16-bit round trip; an empty input is
        returned unchanged.
    """
    import numpy as np
    import soundfile as sf

    audio = np.asarray(audio, dtype=np.float32)
    if audio.size == 0:
        return audio
    buffer = io.BytesIO()
    sf.write(buffer, audio, SAMPLE_RATE, subtype="PCM_16", format="WAV")
    buffer.seek(0)
    quantised, _ = sf.read(buffer, dtype="float32")
    return np.asarray(quantised, dtype=np.float32)


def build_corpus(
    split: str,
    mix_mode: str = "timeline",
    limit_meetings: int | None = None,
    max_minutes: float | None = None,
    utterances_per_meeting: int = _DEFAULT_UTT_PER_MEETING,
    cache_dir: Path | None = None,
    hf_token: str | None = None,
):
    """Yield ``(meeting_id, audio, reference, statistics)`` per meeting.

    When *cache_dir* holds a complete manifest for this configuration the
    reconstructions are read from disk and the dataset is never touched.
    The manifest is checked against the request first (see
    :func:`_check_manifest`), and every WAV must be at ``SAMPLE_RATE``.

    Otherwise the meetings are built from the stream and each is written
    to the cache as it is produced. The manifest that makes the cache
    readable is written only after the stream is exhausted, and only when
    no ``limit_meetings`` was given; a limited build writes
    ``manifest.partial.json``, which is never read. An interrupted build
    therefore leaves no manifest and the next run starts again from the
    stream, re-downloading every meeting.

    Parameters
    ----------
    split:
        AMI split to reconstruct.
    mix_mode:
        ``"timeline"`` (:func:`evaluation.ami_meetings.mix_meeting`) or
        ``"concat"`` (:func:`evaluation.ami_meetings.concat_meeting`).
    limit_meetings:
        Stop after this many meetings. A limited build is never read back
        as the cache for an unlimited request.
    max_minutes:
        Timeline mode only: truncate each meeting to its first *M* minutes.
        Concat mode refuses it (see :func:`refuse_cap_in_concat`);
        *utterances_per_meeting* bounds those meetings.
    utterances_per_meeting:
        Concat mode only: utterances per mini-meeting.
    cache_dir:
        Root of the reconstruction cache, or ``None`` to build in memory.
    hf_token:
        HuggingFace token for the stream.

    Yields
    ------
    (meeting_id, audio, reference, statistics)
        *audio* is float32 at ``SAMPLE_RATE`` and has always been through
        the cache's 16-bit PCM round trip (:data:`AUDIO_SIGNAL`), whether
        it was read from the cache, written to it on this call, or built
        without one, so the same request scores the same signal on every
        run. A meeting with nothing decodable is yielded with an empty
        *reference* and is not cached.

    Side effects
    ------------
    Streams from the HuggingFace Hub when the cache cannot serve the
    request; creates ``<cache_dir>/<split>_<mode>_<cap>/`` and writes one
    ``.wav`` and ``.json`` per meeting plus the manifest.

    Raises
    ------
    SystemExit
        When a cached manifest does not match the request, a cached WAV is
        at the wrong rate, *mix_mode* is unknown, or a concat request
        carries *max_minutes*.
    """
    import numpy as np
    import soundfile as sf

    refuse_cap_in_concat(mix_mode, max_minutes)
    cache = (_cache_paths(cache_dir, split, mix_mode, max_minutes,
                          utterances_per_meeting) if cache_dir else None)
    manifest_path = cache / _MANIFEST if cache else None

    if manifest_path is not None and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        _check_manifest(manifest, cache, split, mix_mode, max_minutes,
                        utterances_per_meeting)
        ids = manifest["meetings"][:limit_meetings] if limit_meetings else manifest["meetings"]
        print(f"  reading {len(ids)} reconstructed meetings from {cache}", flush=True)
        for mid in ids:
            audio, sr = sf.read(cache / f"{mid}.wav", dtype="float32")
            if sr != SAMPLE_RATE:
                # diarise() is told SAMPLE_RATE, so any other rate would
                # rescale every boundary the pipeline reports.
                raise SystemExit(f"{cache / (mid + '.wav')} is at {sr} Hz, "
                                 f"expected {SAMPLE_RATE} Hz")
            payload = json.loads((cache / f"{mid}.json").read_text(encoding="utf-8"))
            yield (mid, np.asarray(audio, dtype=np.float32), payload["reference"],
                   payload["statistics"])
        return

    if cache is not None:
        cache.mkdir(parents=True, exist_ok=True)

    def _decode(row):
        return _decode_audio_bytes(row["audio"])

    built: list[str] = []
    max_duration_s = max_minutes * 60 if max_minutes else None
    for mid, rows in group_rows_by_meeting(_stream_ami(split, hf_token),
                                           limit_meetings=limit_meetings):
        if mix_mode == "timeline":
            audio, reference, stats = mix_meeting(
                rows, _decode, sample_rate=SAMPLE_RATE,
                max_duration_s=max_duration_s)
        elif mix_mode == "concat":
            audio, reference, stats = concat_meeting(
                rows, _decode, sample_rate=SAMPLE_RATE,
                max_utterances=utterances_per_meeting)
        else:
            raise SystemExit(f"unknown --mix-mode {mix_mode!r}")

        if cache is not None and reference:
            wav_path = cache / f"{mid}.wav"
            sf.write(wav_path, audio, SAMPLE_RATE, subtype="PCM_16")
            (cache / f"{mid}.json").write_text(
                json.dumps({"reference": reference, "statistics": stats},
                           indent=2), encoding="utf-8")
            built.append(mid)
            # Score what was written, as every later run will (EDER-06).
            audio, _ = sf.read(wav_path, dtype="float32")
            audio = np.asarray(audio, dtype=np.float32)
        else:
            audio = _as_cached(audio)
        yield mid, audio, reference, stats

    if cache is not None and built:
        record = _manifest_record(split, mix_mode, max_minutes,
                                  utterances_per_meeting, built, limit_meetings)
        target = manifest_path if record["complete"] else cache / _PARTIAL_MANIFEST
        _write_json_atomically(target, record)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def load_pipeline(model_id: str = _DEFAULT_MODEL,
                  hf_token: str | None = None,
                  segmentation_model: str | None = None):
    """Load the diarisation pipeline once and move it to the best device.

    Loading is deliberately separated from scoring.  The earlier version
    of this benchmark rebuilt the pipeline for every meeting, which put a
    Hub round trip and a full model initialisation in front of each
    sixty-second recording and made a hyperparameter sweep unaffordable.

    Parameters
    ----------
    model_id:
        Hub id of the diarisation pipeline, loaded at the revision
        :mod:`evaluation.revisions` pins for it (audit finding DEPS-04), or
        a local path. The segmentation and embedding models the pipeline's
        config.yaml names are loaded by pyannote without a revision.
    hf_token:
        HuggingFace token; the default pipeline is gated.
    segmentation_model:
        Path to a Lightning checkpoint file of a segmentation model that
        replaces the pipeline's own (see
        :func:`_use_segmentation_checkpoint`), or ``None``.

    Returns
    -------
    pyannote.audio.Pipeline
        On CUDA when available, otherwise on CPU.

    Side effects
    ------------
    Downloads the pipeline to the HuggingFace cache when absent.

    Security
    --------
    pyannote.audio 3.x loads checkpoints with full pickle deserialisation
    (on torch 2.5 ``torch.load`` defaults to ``weights_only=False``), so
    loading one runs whatever code it carries. Load only trusted
    checkpoints: the pinned Hub pipeline, or a *segmentation_model* you
    trained yourself.

    Raises
    ------
    SystemExit
        When *segmentation_model* is not a file, the pipeline cannot be
        loaded, or the checkpoint cannot be put in place of its
        segmentation model.
    """
    # Checked before anything is downloaded. Model.from_pretrained treats
    # anything that is not an existing file as a Hub repository id, so a
    # mistyped path would otherwise surface as a confusing download error.
    if segmentation_model is not None and not Path(segmentation_model).is_file():
        raise SystemExit(f"--segmentation-model {segmentation_model!r} is "
                         "not a checkpoint file.")

    from pyannote.audio import Pipeline
    import torch

    from evaluation.hub_loading import pinned_checkpoint, token_kwargs

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    checkpoint, pin = pinned_checkpoint(Pipeline.from_pretrained, model_id)
    pipe = Pipeline.from_pretrained(
        checkpoint, **pin, **token_kwargs(Pipeline.from_pretrained, hf_token))
    if pipe is None:
        raise SystemExit(
            f"could not load {model_id!r}.  It is a gated model: accept its "
            "conditions on the Hub and provide HF_TOKEN or hf_token.txt.")
    pipe.to(device)
    print(f"  pipeline {model_id} loaded on {device}", flush=True)

    if segmentation_model is not None:
        _use_segmentation_checkpoint(pipe, segmentation_model, device)

    return pipe


def _use_segmentation_checkpoint(pipe, checkpoint: str, device) -> None:
    """Make *pipe* segment with the model saved in *checkpoint*.

    In pyannote.audio 3.4.0, ``SpeakerDiarization`` keeps two things under
    similar names. ``segmentation_model`` holds the specification it was
    built from, the string ``"pyannote/segmentation-3.0"``, and nothing
    reads it again (pipelines/speaker_diarization.py:129). Segmentation
    runs through ``_segmentation``, an ``Inference`` built once from the
    released model (lines 143-149, called at 221 and 224). Assigning a
    model to ``segmentation_model``, as this function's predecessor did,
    only files it in the pipeline's model registry (core/pipeline.py,
    ``__setattr__``) and leaves the released weights in use, so the
    benchmark reported the released model's DER under the checkpoint's
    name.

    The ``Inference`` also fixes its chunk duration, step and powerset
    conversion from the model it is given, so the model is not swapped into
    the existing one: a new ``Inference`` is built the way the pipeline's
    constructor builds it (chunk duration from the checkpoint's
    specifications, step ``segmentation_step`` times that duration,
    ``skip_aggregation=True``, the same batch size). The result is the
    pipeline pyannote would have built had it been given the checkpoint.

    Parameters
    ----------
    pipe:
        A loaded pyannote.audio 3.x ``SpeakerDiarization`` pipeline.
    checkpoint:
        Path to a Lightning checkpoint of a pyannote segmentation model.
    device:
        The ``torch.device`` the pipeline runs on.

    Raises
    ------
    SystemExit
        When the pipeline has no segmentation ``Inference``, the checkpoint
        does not load, its output is not the same kind as the released
        model's (powerset or multi-label, and frame resolution), or the new
        model is not the one the pipeline then holds. The kind must match
        because the pipeline's hyperparameters were instantiated for it: a
        powerset model has no ``segmentation.threshold`` to apply.

    Side effects
    ------------
    Unpickles *checkpoint* (see :func:`load_pipeline`), moves the model to
    *device* and replaces ``pipe._segmentation``.
    """
    from pyannote.audio import Inference, Model

    released_inference = getattr(pipe, "_segmentation", None)
    released = getattr(released_inference, "model", None)
    step_ratio = getattr(pipe, "segmentation_step", None)
    if released is None or step_ratio is None:
        raise SystemExit(
            "could not locate the pipeline's segmentation inference; the "
            "fine-tuned weights would have been ignored.")

    fine_tuned = Model.from_pretrained(checkpoint, map_location=device)
    if fine_tuned is None:
        raise SystemExit(f"could not load {checkpoint!r} as a pyannote.audio "
                         "segmentation model.")

    old_spec, new_spec = released.specifications, fine_tuned.specifications
    if isinstance(old_spec, tuple) or isinstance(new_spec, tuple):
        raise SystemExit(f"{checkpoint!r} or the pipeline's segmentation model "
                         "has several outputs; the pipeline expects one.")
    if (bool(new_spec.powerset) != bool(old_spec.powerset)
            or new_spec.resolution != old_spec.resolution):
        raise SystemExit(
            f"{checkpoint!r} does not produce the kind of output the "
            f"pipeline was configured for (powerset {new_spec.powerset}, "
            f"resolution {new_spec.resolution}; the pipeline's model has "
            f"powerset {old_spec.powerset}, resolution {old_spec.resolution}).")

    duration = new_spec.duration
    inference = Inference(
        fine_tuned,
        duration=duration,
        step=step_ratio * duration,
        skip_aggregation=True,
        batch_size=released_inference.batch_size,
        device=device,
    )
    pipe._segmentation = inference
    if pipe._segmentation is not inference or pipe._segmentation.model is not fine_tuned:
        raise SystemExit(
            "the fine-tuned segmentation model did not take effect; "
            "refusing to report the released model's DER under its name.")
    print(f"  segmentation model replaced from {checkpoint} "
          f"({duration:g} s chunks, step {step_ratio * duration:g} s)",
          flush=True)


def uses_powerset(pipe) -> bool:
    """Whether the segmentation head emits powerset rather than binary scores.

    pyannote 3.x segmentation predicts one class per *combination* of
    simultaneously active speakers, so there is no binary onset or offset
    threshold to move.  Callers use this to reject the older VAD
    threshold options outright instead of accepting and ignoring them.
    """
    try:
        return bool(pipe._segmentation.model.specifications.powerset)
    except AttributeError:
        return False


def apply_hyperparameters(pipe, **overrides) -> dict:
    """Set pipeline hyperparameters and confirm they took effect.

    Values are written through ``Pipeline.instantiate`` and then read back
    from the instantiated parameter tree, which is the copy consulted at
    inference time.  A mismatch raises rather than warning: an override
    that quietly fails to apply would make a sweep report that the
    parameter does not matter, which is a far more damaging outcome than
    a stopped job.

    Returns the full instantiated parameter set, for the run record.
    """
    requested = {k: v for k, v in overrides.items() if v is not None}
    params = pipe.parameters(instantiated=True)

    unknown = set(requested) - set(_TUNABLE)
    if unknown:
        raise SystemExit(f"not tunable on this pipeline: {sorted(unknown)}")

    for name, value in requested.items():
        group, key = _TUNABLE[name]
        if group not in params or key not in params[group]:
            raise SystemExit(
                f"{name} maps to {group}.{key}, which this pipeline does not "
                f"expose (it has {dict(params)}).")
        params[group][key] = value

    if requested:
        pipe.instantiate(params)

    applied = pipe.parameters(instantiated=True)
    for name, value in requested.items():
        group, key = _TUNABLE[name]
        got = applied[group][key]
        if isinstance(value, float) and abs(float(got) - value) > 1e-9:
            raise SystemExit(f"{name} did not take effect: asked {value}, "
                             f"pipeline reports {got}")
        if isinstance(value, int) and int(got) != value:
            raise SystemExit(f"{name} did not take effect: asked {value}, "
                             f"pipeline reports {got}")

    record = {group: dict(values) for group, values in applied.items()}
    print(f"  hyperparameters: {json.dumps(record)}", flush=True)
    return record


def diarise(pipe, audio, sample_rate: int = SAMPLE_RATE,
            num_speakers: int | None = None) -> list[dict]:
    """Run the pipeline over one reconstruction.

    The waveform is handed over already decoded.  Given a path, pyannote
    reads the file itself through libsndfile, which is the route that
    fails on compressed containers elsewhere in this workflow.

    Parameters
    ----------
    pipe:
        A loaded pipeline (:func:`load_pipeline`).
    audio:
        Mono samples at *sample_rate*.
    sample_rate:
        Rate of *audio*; every reported boundary scales with it.
    num_speakers:
        Oracle speaker count, or ``None`` to let the pipeline infer it.

    Returns
    -------
    list of dict
        ``{'start', 'end', 'speaker'}`` turns in seconds.
    """
    import numpy as np
    import torch

    waveform = torch.from_numpy(np.asarray(audio, dtype=np.float32)).unsqueeze(0)
    kwargs = {}
    if num_speakers is not None:
        kwargs["num_speakers"] = int(num_speakers)
    result = pipe({"waveform": waveform, "sample_rate": sample_rate}, **kwargs)
    return [{"start": turn.start, "end": turn.end, "speaker": speaker}
            for turn, _, speaker in result.itertracks(yield_label=True)]


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------

_FIELDNAMES = [
    "meeting_id", "n_utterances", "n_speakers", "duration_s", "speech_s",
    "overlap_fraction", "silence_fraction",
    "der", "missed_speech", "false_alarm", "speaker_confusion",
    "hyp_n_speakers",
]


def run_benchmark(
    output_dir: Path,
    split: str = "test",
    mix_mode: str = "timeline",
    limit_meetings: int | None = None,
    max_minutes: float | None = None,
    utterances_per_meeting: int = _DEFAULT_UTT_PER_MEETING,
    cache_dir: Path | None = None,
    build_cache_only: bool = False,
    model_id: str = _DEFAULT_MODEL,
    segmentation_model: str | None = None,
    oracle_num_speakers: bool = False,
    collar: float = _COLLAR,
    vad_onset: float | None = None,
    vad_offset: float | None = None,
    **hyperparameters,
) -> dict:
    """Score one configuration and write the report and summary.

    Parameters
    ----------
    output_dir:
        Directory for ``der_report.csv`` and ``der_summary.json``. The
        default command-line value is the committed ``output/evaluation``,
        whose files a finished run replaces.
    split, mix_mode, limit_meetings, max_minutes, utterances_per_meeting, cache_dir:
        Passed to :func:`build_corpus`.
    build_cache_only:
        Build the reconstruction cache, print its size and return without
        loading a model. Requires *cache_dir*.
    model_id, segmentation_model:
        Passed to :func:`load_pipeline`.
    oracle_num_speakers:
        Give the pipeline each meeting's true speaker count (an upper
        bound, reported separately).
    collar:
        Scoring collar in seconds (``DEFAULT_COLLAR_S`` by default), the
        total width centred on each reference boundary in the
        pyannote.metrics convention, so 0.25 leaves ±0.125 s unscored
        (see :mod:`evaluation.der_metrics`).
    vad_onset, vad_offset:
        Refused: pyannote 3.x has no binary VAD threshold.
    **hyperparameters:
        ``clustering_threshold``, ``min_cluster_size``,
        ``min_duration_off``; ``None`` leaves the pipeline default.

    Returns
    -------
    dict
        The summary written to ``der_summary.json``: the keys of
        :func:`evaluation.der_metrics.aggregate_der` plus ``collar_s``,
        ``collar_convention``, ``audio_signal``, ``dataset``, ``split``,
        ``mix_mode``, ``model``,
        ``hyperparameters``, ``oracle_num_speakers``, ``max_minutes``,
        ``corpus`` and, when known, ``segmentation_model`` and
        ``pyannote_audio_version``. With *build_cache_only*, only
        ``{'cached_hours': ...}``.

    Side effects
    ------------
    Creates *output_dir*, reads ``HF_TOKEN``/``HUGGINGFACE_TOKEN`` or
    ``hf_token.txt`` and downloads the pipeline when it is not cached (see
    :func:`load_pipeline`). Then runs ``git`` for
    :func:`provenance.run_metadata`, before any of the run's own files is
    written. Streams the corpus or reads the cache meeting by meeting (see
    :func:`build_corpus`, which writes the cache when it builds one),
    writes ``der_report.csv.partial`` row by row and, once every meeting
    is scored, replaces ``der_report.csv`` and ``der_summary.json``
    together. With *build_cache_only* it builds or reads the cache and
    returns before the pipeline is loaded or ``git`` is run.

    Raises
    ------
    SystemExit
        On refused options, a cache mismatch, or when no meeting was
        scored.
    """
    from evaluation.der_metrics import (
        aggregate_der, annotation_from_segments, compute_der)

    # build_corpus checks this too, but it is a generator and would only
    # do so once the pipeline had loaded.
    refuse_cap_in_concat(mix_mode, max_minutes)
    output_dir.mkdir(parents=True, exist_ok=True)
    hf_token = _load_hf_token()

    corpus = build_corpus(
        split=split, mix_mode=mix_mode, limit_meetings=limit_meetings,
        max_minutes=max_minutes,
        utterances_per_meeting=utterances_per_meeting,
        cache_dir=cache_dir, hf_token=hf_token)

    if build_cache_only:
        if cache_dir is None:
            raise SystemExit("--build-cache-only requires --cache-dir")
        total = 0.0
        n_cached = 0
        for mid, _audio, reference, stats in corpus:
            n_cached += bool(reference)
            total += stats["duration_s"]
            print(f"  cached {mid}: {stats['duration_s'] / 60:.1f} min, "
                  f"{stats['n_speakers']} speakers, "
                  f"overlap {stats['overlap_fraction']:.1%}", flush=True)
        _require_scored(n_cached, "meeting with a usable reference")
        print(f"\nCache built: {total / 3600:.2f} h of reconstructed audio.")
        return {"cached_hours": total / 3600}

    pipe = load_pipeline(model_id, hf_token, segmentation_model)
    if vad_onset is not None or vad_offset is not None:
        # Refused rather than warned about.  A benchmark that accepts a
        # swept parameter and ignores it reports that the parameter does
        # not matter, which is worse than not running at all.
        raise SystemExit(
            "--vad-onset/--vad-offset are not applicable here.  "
            + ("This pipeline uses powerset segmentation, which predicts "
               "speaker combinations directly and has no binary onset or "
               "offset threshold." if uses_powerset(pipe) else
               "This benchmark does not implement binary VAD thresholds.")
            + "  Tune --min-duration-off and --clustering-threshold instead.")
    applied = apply_hyperparameters(pipe, **hyperparameters)

    report_path = output_dir / "der_report.csv"
    summary_path = output_dir / "der_summary.json"
    # The code and packages behind the figures (audit finding OUTPUTS-12),
    # read before any of this run's files is written, and leaving out the
    # two it replaces, as provenance.write_sidecar does for the CSV-only
    # writers. Read at the end without that list, as it was, a second run
    # in place counted the first one's report and summary as uncommitted
    # code.
    from provenance import run_metadata
    run_meta = run_metadata(repo_dir=_ROOT, ignore=(report_path, summary_path))
    # Both files are written under a .partial name and moved into place
    # together at the end. A job killed part-way (walltime, OOM) then
    # leaves the previous run's report and summary as a matching pair,
    # instead of a new partial report beside the old summary.
    report_partial = _partial(report_path)
    summary_partial = _partial(summary_path)

    results: list[dict] = []
    corpus_stats: list[dict] = []
    with report_partial.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_FIELDNAMES)
        writer.writeheader()

        for index, (mid, audio, reference, stats) in enumerate(corpus, 1):
            if not reference:
                print(f"  [{index}] {mid}: skipped (nothing decodable)")
                continue
            print(f"  [{index}] {mid}: {stats['duration_s'] / 60:.1f} min, "
                  f"{stats['n_utterances']} utterances, "
                  f"{stats['n_speakers']} speakers, "
                  f"overlap {stats['overlap_fraction']:.1%}", flush=True)

            hypothesis = diarise(
                pipe, audio, SAMPLE_RATE,
                num_speakers=stats["n_speakers"] if oracle_num_speakers else None)

            result = compute_der(
                annotation_from_segments(reference, uri=mid),
                annotation_from_segments(hypothesis, uri=mid),
                collar=collar)
            result["meeting_id"] = mid
            results.append(result)
            corpus_stats.append(stats)

            row = {k: stats.get(k) for k in
                   ("n_utterances", "n_speakers", "duration_s",
                    "speech_s", "overlap_fraction", "silence_fraction")}
            row.update({
                "meeting_id": mid,
                "der": round(result["der"], 6),
                "missed_speech": round(result["missed_speech"], 6),
                "false_alarm": round(result["false_alarm"], 6),
                "speaker_confusion": round(result["speaker_confusion"], 6),
                "hyp_n_speakers": len({s["speaker"] for s in hypothesis}),
            })
            writer.writerow(row)
            fh.flush()

            print(f"      DER={result['der']:.4f}  "
                  f"miss={result['missed_speech']:.4f}  "
                  f"FA={result['false_alarm']:.4f}  "
                  f"conf={result['speaker_confusion']:.4f}", flush=True)

    # aggregate_der([]) returns zeros, which would read as a perfect score.
    _require_scored(len(results), "meeting", report_partial)
    summary = aggregate_der(results)
    summary.update({
        "collar_s": collar,
        "collar_convention": COLLAR_CONVENTION,
        "audio_signal": AUDIO_SIGNAL,
        "dataset": f"{_AMI_DATASET}/{_AMI_CONFIG}/{split}",
        "split": split,
        "mix_mode": mix_mode,
        "model": model_id,
        "hyperparameters": applied,
        "oracle_num_speakers": oracle_num_speakers,
        "max_minutes": max_minutes,
        "corpus": _corpus_summary(corpus_stats),
    })
    if segmentation_model is not None:
        summary["segmentation_model"] = str(segmentation_model)
    try:
        import pyannote.audio as _pa
        summary["pyannote_audio_version"] = _pa.__version__
    except Exception:  # provenance only; the key is then absent
        pass
    # Which snapshots produced the figures, and the code and packages
    # (audit findings DEPS-04, OUTPUTS-12). The pipeline and AMI are loaded
    # at the revisions recorded; the two models the default pipeline's
    # config.yaml names are loaded by pyannote without a revision, so they
    # resolve to the cache's main and are listed as not enforced.
    from evaluation.revisions import revisions_used

    sub_models = list(_DEFAULT_SUB_MODELS) if model_id == _DEFAULT_MODEL else []
    summary["revisions"] = revisions_used(model_id, _AMI_DATASET, *sub_models)
    summary["revisions_not_enforced"] = sub_models
    summary["run_metadata"] = run_meta
    summary_partial.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    os.replace(report_partial, report_path)
    os.replace(summary_partial, summary_path)

    print(f"\n{split} DER  macro={summary['macro_der']:.4f}  "
          f"micro={summary['micro_der']:.4f}  "
          f"({summary['n_meetings']} meetings, "
          f"{summary['total_ref_duration'] / 60:.1f} min scored reference "
          f"time, speaker-weighted and collar-excluded)")
    print(f"Report:  {report_path}")
    print(f"Summary: {summary_path}")
    return summary


def _corpus_summary(stats: list[dict]) -> dict:
    """Describe the reconstruction the scores were obtained on.

    Recorded alongside the scores because DER is only interpretable
    against the corpus it was measured on, and the overlap fraction in
    particular separates a faithful reconstruction from a concatenation.
    """
    if not stats:
        return {}
    audio_s = sum(s["duration_s"] for s in stats)
    speech_s = sum(s["speech_s"] for s in stats)
    overlap_s = sum(s["overlap_s"] for s in stats)
    return {
        "audio_hours": round(audio_s / 3600, 3),
        "speech_hours": round(speech_s / 3600, 3),
        "overlap_fraction": round(overlap_s / speech_s, 4) if speech_s else 0.0,
        "silence_fraction": round(max(0.0, audio_s - speech_s) / audio_s, 4) if audio_s else 0.0,
        "mean_speakers_per_meeting": round(
            sum(s["n_speakers"] for s in stats) / len(stats), 2),
    }


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="DER benchmark on AMI using pyannote diarisation.")
    p.add_argument("--output-dir", type=Path, default=_DEFAULT_OUTPUT_DIR,
                   help="directory for der_report.csv and der_summary.json")
    p.add_argument("--split", default="test",
                   choices=["train", "validation", "test"],
                   help="AMI split.  Tune on validation, report on test "
                        "(default: %(default)s)")
    p.add_argument("--mix-mode", default="timeline",
                   choices=["timeline", "concat"],
                   help="timeline sums headset channels at their true offsets "
                        "and preserves overlapping speech.  concat reproduces "
                        "the earlier utterance concatenation "
                        "(default: %(default)s)")
    p.add_argument("--limit-meetings", type=int, default=None, metavar="N",
                   help="stop after scoring this many meetings")
    p.add_argument("--max-minutes", type=float, default=None, metavar="M",
                   help="timeline mode only: truncate each meeting to its "
                        "first M minutes")
    p.add_argument("--utterances-per-meeting", type=int,
                   default=_DEFAULT_UTT_PER_MEETING, metavar="N",
                   help="concat mode only: utterances per mini-meeting "
                        "(default: %(default)s)")
    p.add_argument("--cache-dir", type=Path, default=None, metavar="DIR",
                   help="read and write reconstructed meetings here, so a "
                        "sweep does not re-download the corpus")
    p.add_argument("--build-cache-only", action="store_true",
                   help="build the reconstruction cache and exit.  Needs no GPU")
    p.add_argument("--model", dest="model_id", default=_DEFAULT_MODEL,
                   help="diarisation pipeline to load (default: %(default)s)")
    p.add_argument("--segmentation-model", default=None, metavar="PATH",
                   help="replace the pipeline's segmentation weights with a "
                        "fine-tuned Lightning checkpoint file (.ckpt), such "
                        "as the one finetune_pyannote_segmentation exports. "
                        "It is unpickled, so pass only a trusted file")
    p.add_argument("--oracle-num-speakers", action="store_true",
                   help="tell the pipeline how many speakers each meeting "
                        "has.  Reported separately: it is an upper bound "
                        "that assumes knowledge a real recording lacks.")
    p.add_argument("--collar", type=float, default=_COLLAR, metavar="S",
                   help="scoring collar in seconds, the total width centred "
                        "on each reference boundary (pyannote.metrics), so "
                        "0.25 leaves 0.125 s either side unscored; the NIST "
                        "md-eval -c 0.25 collar is 0.5 here "
                        "(default: %(default)s)")

    tuning = p.add_argument_group("hyperparameters")
    tuning.add_argument("--clustering-threshold", type=float, default=None,
                        metavar="T",
                        help="agglomerative clustering threshold; higher "
                             "merges speakers more readily (default ~0.705)")
    tuning.add_argument("--min-cluster-size", type=int, default=None,
                        metavar="N",
                        help="smallest admissible speaker cluster (default 12)")
    tuning.add_argument("--min-duration-off", type=float, default=None,
                        metavar="S",
                        help="pauses shorter than this do not split a turn "
                             "(default 0.0)")
    tuning.add_argument("--vad-onset", type=float, default=None,
                        help="binary VAD onset threshold.  Rejected on "
                             "pyannote 3.x, which has no such threshold.")
    tuning.add_argument("--vad-offset", type=float, default=None,
                        help="binary VAD offset threshold.  Rejected on "
                             "pyannote 3.x, which has no such threshold.")
    return p.parse_args(argv)


def exit_without_finalising(code: int) -> None:
    """Terminate immediately, skipping interpreter finalisation.

    Streaming the corpus leaves a native worker thread behind that calls
    back into Python while the interpreter is shutting down.  The process
    then aborts with ``PyGILState_Release: thread state ... must be
    current when releasing`` and exit status 134, *after* every result has
    been computed, written and flushed.  A job that finished its work
    would otherwise be reported as failed, and under ``set -e`` would stop
    the rest of the pipeline.

    Buffers are flushed first and the status is passed through unchanged,
    so a real failure still exits non-zero.

    ``os._exit`` also skips ``atexit`` handlers and the finalisers of
    anything still open. Nothing in this module or the sweep registers
    one today; code that does (a training logger, a buffered file left
    open) must flush or close it before returning from ``main``.

    The abort was observed on ARC in the reconstruction smoke test (commit
    9de2c7d) with the job environment's ``datasets`` streaming stack. The
    upstream issue and the exact library versions were not recorded.
    TODO: justify (source unknown): link the upstream report once found.
    Removal condition: once a streaming run such as
    ``python -m evaluation.benchmark_der --split validation
    --limit-meetings 1 --build-cache-only --cache-dir /tmp/x`` with this
    call replaced by ``sys.exit`` exits 0 on the job environment, delete
    this function and call ``sys.exit`` directly.
    """
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def main(argv: list[str] | None = None) -> int:
    """Run :func:`run_benchmark` with the command-line arguments.

    *argv* replaces ``sys.argv[1:]`` (see :func:`_parse_args`). Returns 0
    once the run is complete. A refused option or a failed step raises
    ``SystemExit`` with its message; run as a script, the module prints
    that message and exits with its status through
    :func:`exit_without_finalising`. Side effects are those of
    :func:`run_benchmark`, whose default ``--output-dir`` is the committed
    ``output/evaluation``.
    """
    args = _parse_args(argv)
    run_benchmark(
        output_dir=args.output_dir,
        split=args.split,
        mix_mode=args.mix_mode,
        limit_meetings=args.limit_meetings,
        max_minutes=args.max_minutes,
        utterances_per_meeting=args.utterances_per_meeting,
        cache_dir=args.cache_dir,
        build_cache_only=args.build_cache_only,
        model_id=args.model_id,
        segmentation_model=args.segmentation_model,
        oracle_num_speakers=args.oracle_num_speakers,
        collar=args.collar,
        clustering_threshold=args.clustering_threshold,
        min_cluster_size=args.min_cluster_size,
        min_duration_off=args.min_duration_off,
        vad_onset=args.vad_onset,
        vad_offset=args.vad_offset,
    )
    return 0


if __name__ == "__main__":
    try:
        _status = main()
    except SystemExit as _exc:          # the explicit failures raised above
        if _exc.code not in (0, None):
            print(f"error: {_exc}", file=sys.stderr)
        _status = _exc.code if isinstance(_exc.code, int) else 1
    exit_without_finalising(_status or 0)
