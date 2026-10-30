#!/usr/bin/env python3
"""
Fine-tune pyannote/segmentation-3.0 on AMI training data.

Background
----------
On the AMI IHM test split, reconstructed on the original meeting
timeline, ``pyannote/speaker-diarization-3.1`` has missed speech as the
largest DER component, and it is concentrated where meetings are spoken
over: the overlapped proportion of reference speech correlates strongly
with per-meeting error, and more strongly with missed speech alone.
The figures are in ``output/evaluation/der_summary.json`` and
``der_report.csv``; they are not repeated here because a re-score would
leave copies stale.

That points at the segmentation model rather than at clustering.
Clustering cannot recover speech that segmentation never emitted, which
is consistent with the finding that the clustering threshold leaves
missed speech identical to six decimal places across an entire sweep.

What this script tests is domain adaptation within the released model's
output space.  ``pyannote/segmentation-3.0`` assigns each frame to one of
an enumerated (powerset) set of speaker combinations, built for at most
three speakers per chunk and two active in any frame, and the task here
keeps that configuration, because it is what lets training start from
the released weights.  Fine-tuning on in-domain meeting audio can
therefore reduce misses where two people overlap, but it cannot
represent a third simultaneous voice.  Testing that would need a larger
powerset and a newly initialised output layer, which is a different
experiment.

Two cautions before spending GPU time on it.  Nothing here has been run
for any reported result, so the improvement is a hypothesis, not a
measurement.  And an earlier version of this file diagnosed the problem
as speaker confusion on "far-field" recordings, which was wrong twice
over: the individual headset microphone release is close-talking, not
far-field, and confusion is not the dominant component.  That diagnosis
came from a benchmark that concatenated single-speaker clips and so
contained no overlapping speech at all.

Workflow
--------
The script executes in three phases.

Phase 1 — data preparation.  The AMI IHM train split is streamed from
HuggingFace and each meeting is rebuilt with
:func:`evaluation.ami_meetings.mix_meeting`, the same reconstruction the
benchmark scores, so that training and evaluation see the same kind of
signal.  Using the older concatenation here would train the model on
audio with no overlapping speech and then evaluate it on audio that has
plenty, which is the one mismatch this task cannot afford.  Each meeting
is saved as a WAV file and an RTTM annotation file, so later epochs read
from disk without re-downloading, and ``data_manifest.json`` records the
cap they were built with so a pilot's truncated meetings are never
reused by a full run.  Whole AMI series are held out as the development
set, so no participant is in both sets.

Phase 2 — fine-tuning.  A pyannote.database protocol wraps the saved
files and serves them to the ``pyannote.audio.tasks.SpeakerDiarization``
task.  ``pyannote/segmentation-3.0`` is loaded from the HuggingFace Hub
(or from the local cache if already present) and fine-tuned using
PyTorch Lightning, seeded by ``--seed``.  The best checkpoint (lowest
validation DER) is copied to
``output_dir/segmentation_model/segmentation-ami-best.ckpt`` with
``finetune_provenance.json`` beside it.

Run a CPU smoke test (``--limit-meetings 8 --epochs 1 --max-minutes 1
--skip-eval --output-dir <scratch>``, enough meetings for at least two
series) in the job environment before any
full submission: the pyannote calls were checked against the 3.4.0
source but have not yet been executed.

Phase 3 — evaluation.  The full benchmark is re-run on the AMI IHM test set
with the fine-tuned segmentation model substituted into the
``pyannote/speaker-diarization-3.1`` pipeline, and the results are written to
``output_dir/evaluation``.  Compare them against the released model scored
the same way, which is ``output/evaluation/der_summary.json``.

Usage::

    python -m evaluation.finetune_pyannote_segmentation

    # Limit data and epochs for a quick pilot
    python -m evaluation.finetune_pyannote_segmentation \\
        --limit-meetings 20 \\
        --epochs 3 \\
        --output-dir output/finetune_pilot

    # Skip Phase 1 if WAV/RTTM files are already on disk
    python -m evaluation.finetune_pyannote_segmentation \\
        --skip-data-prep \\
        --epochs 5

    # Skip Phase 3 evaluation
    python -m evaluation.finetune_pyannote_segmentation \\
        --skip-eval

Privacy note
------------
Audio is streamed from the HuggingFace Hub, decoded locally, and written to
the output directory only.  No audio, transcript, or model output leaves the
local machine or the ARC cluster.  Downloading model weights is an
outbound-only operation carrying no user data; see the project privacy
contract in the repository's ``copilot-instructions.md``.

Requirements
------------
In addition to the standard project dependencies, this script requires
``pytorch-lightning>=2.0``::

    pip install "pytorch-lightning>=2.0"
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import sys
from pathlib import Path

import soundfile as sf

# No blanket warnings filter: pyannote's reproducibility and
# checkpoint-version warnings are part of a training run's record.

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# The AMI helpers are the benchmark's own, so training audio is decoded,
# grouped and reconstructed exactly as the scored audio is.
from evaluation.ami_meetings import (  # noqa: E402
    AMI_CONFIG,
    AMI_DATASET,
    RECONSTRUCTION_VERSION,
    SAMPLE_RATE,
    decode_audio_bytes,
    group_rows_by_meeting,
    load_hf_token,
    mix_meeting,
    stream_ami,
)
from evaluation.benchmark_der import exit_without_finalising  # noqa: E402

_DEFAULT_OUTPUT_DIR = _ROOT / "output" / "finetune"
_AMI_TRAIN_SPLIT = "train"
_SR = SAMPLE_RATE
_BASE_MODEL = "pyannote/segmentation-3.0"
_DEFAULT_LIMIT_MEETINGS = 80
_DEFAULT_DEV_FRACTION = 0.10
_DEFAULT_EPOCHS = 10
_DEFAULT_DURATION = 10.0   # seconds per training chunk
_DEFAULT_SEED = 42
#: The released segmentation-3.0 powerset: at most three speakers in a
#: chunk, at most two active in any frame. Kept, because fine-tuning
#: starts from the released weights and a different powerset would need
#: a newly initialised output layer (a different experiment).
_MAX_SPEAKERS_PER_CHUNK = 3
_MAX_SPEAKERS_PER_FRAME = 2
_DATA_MANIFEST = "data_manifest.json"
_BEST_CHECKPOINT_NAME = "segmentation-ami-best.ckpt"


def _gpu_available() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# RTTM read / write
# ---------------------------------------------------------------------------

def _write_rttm(segments: list[dict], uri: str, path: Path) -> None:
    """Write speaker segments to RTTM format."""
    with path.open("w", encoding="utf-8") as fh:
        for seg in segments:
            duration = seg["end"] - seg["start"]
            fh.write(
                f"SPEAKER {uri} 1 {seg['start']:.6f} {duration:.6f} "
                f"<NA> <NA> {seg['speaker']} <NA> <NA>\n"
            )


def _read_annotation_from_rttm(path: Path):
    """Return a ``pyannote.core.Annotation`` loaded from an RTTM file.

    Each ``SPEAKER`` line becomes its own track, as in
    :func:`evaluation.der_metrics.annotation_from_segments`: on pyannote's
    default track a second speaker whose turn has exactly the same span
    would replace the first, and AMI has such pairs (EDER-02). An exact
    repeat of a line by the same speaker is kept once, since on separate
    tracks it would count that speaker twice.

    Parameters
    ----------
    path:
        RTTM file as written by :func:`_write_rttm`; its stem is the URI.

    Returns
    -------
    pyannote.core.Annotation
    """
    from pyannote.core import Annotation, Segment

    ann = Annotation(uri=path.stem)
    seen: set[tuple[float, float, str]] = set()
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            parts = line.strip().split()
            if not parts or parts[0] != "SPEAKER":
                continue
            start = float(parts[3])
            end = start + float(parts[4])
            speaker = parts[7]
            if (start, end, speaker) in seen:
                continue
            ann[Segment(start, end), len(seen)] = speaker
            seen.add((start, end, speaker))
    return ann


# ---------------------------------------------------------------------------
# Phase 1 — data preparation
# ---------------------------------------------------------------------------

def _series_of(meeting_id: str) -> str:
    """Return the AMI series a meeting belongs to.

    AMI meeting ids are a series plus a session letter (``ES2002a`` to
    ``ES2002d``), and the sessions of one series share their participants
    and room. They need not share headset channels: some EN2002 speakers
    change channel between meetings (evaluation/benchmark_anonymisation.py).
    """
    return re.sub(r"[a-z]$", "", meeting_id)


def _split_by_series(
    protocol_files: list[dict], dev_fraction: float,
) -> tuple[list[dict], list[dict]]:
    """Hold out whole AMI series as the development set.

    Taking the first tenth of sorted meeting ids used to cut through a
    series whenever the boundary fell inside one, putting the same
    speakers in training and in the set ``ModelCheckpoint`` selects the
    best epoch on, which favours memorising them. Whole series are taken
    in sorted order until at least ``dev_fraction`` of the meetings are
    held out, so the development set can exceed the fraction by up to one
    series.

    Parameters
    ----------
    protocol_files:
        Protocol file dicts carrying ``uri``.
    dev_fraction:
        Minimum share of meetings to hold out (at least one meeting).

    Returns
    -------
    (train_files, dev_files)
        Both sorted by ``uri``, with no series in both.

    Raises
    ------
    SystemExit
        When holding out whole series would leave nothing to train on.
    """
    files = sorted(protocol_files, key=lambda f: f["uri"])
    target = max(1, int(len(files) * dev_fraction))
    dev_series: set[str] = set()
    n_dev = 0
    for series in sorted({_series_of(f["uri"]) for f in files}):
        if n_dev >= target:
            break
        dev_series.add(series)
        n_dev += sum(_series_of(f["uri"]) == series for f in files)

    dev = [f for f in files if _series_of(f["uri"]) in dev_series]
    train = [f for f in files if _series_of(f["uri"]) not in dev_series]
    if not train:
        raise SystemExit(
            f"holding out whole AMI series for development left no training "
            f"meetings ({len(files)} meeting(s) in {len(dev_series)} series); "
            "raise --limit-meetings.")
    assert not ({_series_of(f["uri"]) for f in train} & dev_series)
    return train, dev


def _data_manifest_path(output_dir: Path) -> Path:
    return output_dir / _DATA_MANIFEST


def _read_data_manifest(output_dir: Path, max_minutes: float | None) -> dict | None:
    """Return the data manifest, refusing one built with other settings.

    The manifest records what the WAV and RTTM files on disk were built
    with. Without it an earlier pilot's truncated meetings would be reused
    by a full run and trained on under the full run's provenance.

    Returns
    -------
    dict or None
        ``None`` when the directory has no manifest and no audio yet.

    Raises
    ------
    SystemExit
        When audio exists without a manifest, or the manifest's cap,
        sample rate or reconstruction version differs from this run's.
    """
    path = _data_manifest_path(output_dir)
    audio_dir = output_dir / "audio" / _AMI_TRAIN_SPLIT
    if not path.exists():
        if audio_dir.exists() and any(audio_dir.glob("*.wav")):
            raise SystemExit(
                f"{audio_dir} holds reconstructed meetings but {path} is "
                "missing, so the cap they were built with is unknown.  Use a "
                "fresh --output-dir, or delete the audio and rttm directories.")
        return None

    manifest = json.loads(path.read_text(encoding="utf-8"))
    recorded = manifest.get("max_minutes")
    same_cap = (recorded is None and max_minutes is None) or (
        recorded is not None and max_minutes is not None
        and float(recorded) == float(max_minutes))
    problems = []
    if not same_cap:
        problems.append(f"max_minutes {recorded!r}, requested {max_minutes!r}")
    if manifest.get("sample_rate") != _SR:
        problems.append(f"sample_rate {manifest.get('sample_rate')!r}, "
                        f"expected {_SR}")
    if manifest.get("reconstruction_version") != RECONSTRUCTION_VERSION:
        problems.append(f"reconstruction version "
                        f"{manifest.get('reconstruction_version')!r}, the code "
                        f"is version {RECONSTRUCTION_VERSION}")
    if problems:
        raise SystemExit(
            f"the meetings in {output_dir} were built with "
            f"{'; '.join(problems)}.  Use a separate --output-dir for each "
            "setting.")
    return manifest


def _write_data_manifest(output_dir: Path, max_minutes: float | None,
                         meetings: list[str]) -> None:
    """Record the meetings on disk and the settings that built them."""
    path = _data_manifest_path(output_dir)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({
        "dataset": f"{AMI_DATASET}/{AMI_CONFIG}/{_AMI_TRAIN_SPLIT}",
        "max_minutes": max_minutes,
        "sample_rate": _SR,
        "reconstruction_version": RECONSTRUCTION_VERSION,
        "meetings": meetings,
    }, indent=2), encoding="utf-8")
    tmp.replace(path)


def _build_and_save_ami(
    output_dir: Path,
    hf_token: str | None,
    limit_meetings: int | None,
    max_minutes: float | None,
    dev_fraction: float,
) -> tuple[list[dict], list[dict]]:
    """Stream the AMI IHM train split and save reconstructed meetings.

    Each meeting is rebuilt by :func:`evaluation.ami_meetings.mix_meeting`,
    which places every utterance at its true onset and sums the headset
    channels.  This is the same reconstruction the benchmark scores, and
    using it here is what keeps the model from being trained on audio
    without overlapping speech and then evaluated on audio with plenty of
    it.  Meetings are streamed and grouped one at a time with
    :func:`evaluation.ami_meetings.group_rows_by_meeting`, so only one
    meeting's encoded audio is held in memory.

    Parameters
    ----------
    output_dir:
        Root for ``audio/train/*.wav``, ``rttm/train/*.rttm`` and
        ``data_manifest.json``.
    hf_token:
        HuggingFace token, or ``None``.
    limit_meetings:
        Use the first *limit_meetings* meetings of the stream.
    max_minutes:
        Truncate each meeting, for a cheaper pilot; ``None`` keeps it
        whole. Must match the cap of any meetings already on disk.
    dev_fraction:
        Passed to :func:`_split_by_series`.

    Returns
    -------
    (train_files, dev_files)
        Protocol file dicts for the meetings of this run.

    Side effects
    ------------
    Streams from the HuggingFace Hub; writes WAV and RTTM files and the
    data manifest. Meetings already on disk and listed in a manifest with
    the same settings are reused rather than rebuilt.
    """
    manifest = _read_data_manifest(output_dir, max_minutes)
    on_disk = list(manifest["meetings"]) if manifest else []

    audio_dir = output_dir / "audio" / _AMI_TRAIN_SPLIT
    rttm_dir = output_dir / "rttm" / _AMI_TRAIN_SPLIT
    audio_dir.mkdir(parents=True, exist_ok=True)
    rttm_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n--- Phase 1: streaming AMI IHM {_AMI_TRAIN_SPLIT} split ---")

    def _decode(row):
        return decode_audio_bytes(row["audio"])

    protocol_files: list[dict] = []
    stream = stream_ami(_AMI_TRAIN_SPLIT, hf_token)
    for mid, rows in group_rows_by_meeting(stream, limit_meetings=limit_meetings):
        wav_path = audio_dir / f"{mid}.wav"
        rttm_path = rttm_dir / f"{mid}.rttm"

        reusable = mid in on_disk and wav_path.exists() and rttm_path.exists()
        if not reusable:
            audio_array, segments, stats = mix_meeting(
                rows, _decode, sample_rate=_SR,
                max_duration_s=max_minutes * 60 if max_minutes else None)

            if not segments:
                continue
            if stats["skipped_utterances"]:
                print(f"  ⚠  {mid}: {stats['skipped_utterances']} "
                      f"utterance(s) could not be decoded", file=sys.stderr)

            sf.write(str(wav_path), audio_array, _SR)
            _write_rttm(segments, mid, rttm_path)
            if mid not in on_disk:
                on_disk.append(mid)
            # Recorded after every meeting, so an interrupted run's files
            # are still known to have been built with this cap.
            _write_data_manifest(output_dir, max_minutes, on_disk)

        pf = _make_protocol_file(mid, wav_path, rttm_path)
        if pf is not None:
            protocol_files.append(pf)
            print(f"  ✓ {mid}  ({len(protocol_files)})", end="\r", flush=True)

    print(f"\n  {len(protocol_files)} meetings ready in {output_dir}", flush=True)
    if not protocol_files:
        raise SystemExit("no usable training meeting was reconstructed.")

    train_files, dev_files = _split_by_series(protocol_files, dev_fraction)
    print(f"  Train: {len(train_files)}  Dev: {len(dev_files)}", flush=True)
    return train_files, dev_files


def _make_protocol_file(
    uri: str, wav_path: Path, rttm_path: Path
) -> dict | None:
    """Build a protocol file dict from saved WAV and RTTM paths.

    ``scope`` and ``database`` are required by pyannote.audio 3.4's
    ``Task.prepare_data``. ``scope`` is ``"file"``: speaker labels are
    only compared within a meeting, which is all a diarisation task needs.
    """
    from pyannote.core import Timeline, Segment

    try:
        ann = _read_annotation_from_rttm(rttm_path)
        info = sf.info(str(wav_path))
        annotated = Timeline([Segment(0.0, info.duration)], uri=uri)
        return {
            "uri":        uri,
            "database":   "AMIFinetune",
            "scope":      "file",
            "audio":      str(wav_path),
            "annotation": ann,
            "annotated":  annotated,
        }
    except Exception as exc:
        print(f"  ⚠  could not build protocol file for {uri}: {exc}", file=sys.stderr)
        return None


def _reload_from_disk(
    output_dir: Path,
    dev_fraction: float,
    limit_meetings: int | None = None,
    max_minutes: float | None = None,
) -> tuple[list[dict], list[dict]]:
    """Reload protocol file dicts from previously saved WAV and RTTM files.

    Only the meetings the data manifest lists are used, in stream order and
    limited to *limit_meetings*, so ``--skip-data-prep`` with a limit
    trains on the same meetings as a fresh run with that limit would.

    Raises
    ------
    SystemExit
        When there is no manifest, its settings differ from this run's
        (see :func:`_read_data_manifest`), or no listed meeting is on disk.
    """
    audio_dir = output_dir / "audio" / _AMI_TRAIN_SPLIT
    rttm_dir = output_dir / "rttm" / _AMI_TRAIN_SPLIT

    manifest = _read_data_manifest(output_dir, max_minutes)
    if manifest is None:
        raise SystemExit(
            f"no prepared meetings under {output_dir}.  "
            "Run without --skip-data-prep first.")

    meetings = manifest["meetings"]
    if limit_meetings is not None:
        meetings = meetings[:limit_meetings]

    protocol_files: list[dict] = []
    for mid in meetings:
        wav_path = audio_dir / f"{mid}.wav"
        rttm_path = rttm_dir / f"{mid}.rttm"
        if not (wav_path.exists() and rttm_path.exists()):
            raise SystemExit(f"{mid} is listed in the data manifest but its "
                             f"WAV or RTTM file is missing from {output_dir}.")
        pf = _make_protocol_file(mid, wav_path, rttm_path)
        if pf is not None:
            protocol_files.append(pf)

    if not protocol_files:
        raise SystemExit(
            f"No WAV/RTTM pairs found under {output_dir}. "
            "Run without --skip-data-prep first."
        )

    print(f"  Reloaded {len(protocol_files)} meetings from disk.", flush=True)
    return _split_by_series(protocol_files, dev_fraction)


# ---------------------------------------------------------------------------
# Phase 2 — fine-tuning
# ---------------------------------------------------------------------------

_PROTOCOL_NAME = "AMIFinetune.SpeakerDiarization.Custom"


def _make_protocol(train_files: list[dict], dev_files: list[dict]):
    """Wrap the prepared files in a pyannote.database protocol.

    pyannote.audio 3.4's ``check_protocol`` registers preprocessors (for
    ``torchaudio.info``, for instance) on ``protocol.preprocessors``, and
    only a real :class:`pyannote.database.Protocol` applies them to the
    files it serves; ``Task.prepare_data`` also records
    ``protocol.name``. A bare object with ``train()`` and
    ``development()`` has neither, and failed there.
    """
    from pyannote.database.protocol import SpeakerDiarizationProtocol

    class _AMIProtocol(SpeakerDiarizationProtocol):
        def __init__(self) -> None:
            super().__init__()
            self.name = _PROTOCOL_NAME
            self._train = list(train_files)
            self._dev = list(dev_files)

        def train_iter(self):
            yield from (dict(f) for f in self._train)

        def development_iter(self):
            yield from (dict(f) for f in self._dev)

    return _AMIProtocol()


def _library_versions() -> dict:
    """Versions of the libraries a training run depends on, for provenance."""
    versions = {}
    for label, module in (("torch", "torch"),
                          ("pytorch_lightning", "pytorch_lightning"),
                          ("pyannote_audio", "pyannote.audio")):
        try:
            versions[label] = __import__(module, fromlist=["__version__"]).__version__
        except Exception:  # provenance only
            versions[label] = None
    return versions


def _provenance(
    train_files: list[dict],
    dev_files: list[dict],
    epochs: int,
    duration: float,
    seed: int,
    max_minutes: float | None,
    limit_meetings: int | None,
    best_checkpoint: str,
    exported_checkpoint: str,
) -> dict:
    """The record written beside the exported checkpoint.

    Holds enough to rebuild the training corpus and repeat the run: the
    meeting ids of each set, the cap and limit the audio was built with,
    the powerset the task was configured with, the seed and the library
    versions.
    """
    return {
        "base_model": _BASE_MODEL,
        "fine_tuned_on": f"{AMI_DATASET}/{AMI_CONFIG}/{_AMI_TRAIN_SPLIT}",
        "reconstruction_version": RECONSTRUCTION_VERSION,
        "max_minutes": max_minutes,
        "limit_meetings": limit_meetings,
        "n_train_meetings": len(train_files),
        "n_dev_meetings": len(dev_files),
        "train_meetings": [f["uri"] for f in train_files],
        "dev_meetings": [f["uri"] for f in dev_files],
        "dev_split": "whole AMI series, see _split_by_series",
        "max_speakers_per_chunk": _MAX_SPEAKERS_PER_CHUNK,
        "max_speakers_per_frame": _MAX_SPEAKERS_PER_FRAME,
        "epochs": epochs,
        "chunk_duration_s": duration,
        "seed": seed,
        "versions": _library_versions(),
        "best_checkpoint": best_checkpoint,
        "exported_checkpoint": exported_checkpoint,
    }


def _finetune(
    train_files: list[dict],
    dev_files: list[dict],
    output_dir: Path,
    hf_token: str | None,
    epochs: int,
    duration: float,
    seed: int = _DEFAULT_SEED,
    max_minutes: float | None = None,
    limit_meetings: int | None = None,
) -> Path:
    """Fine-tune ``pyannote/segmentation-3.0`` and return the best checkpoint.

    Parameters
    ----------
    train_files, dev_files:
        Protocol file dicts from Phase 1; the development set selects the
        best epoch by validation DER.
    output_dir:
        Root for ``checkpoints/``, ``lightning_logs/`` and
        ``segmentation_model/``.
    hf_token:
        HuggingFace token for the gated base model.
    epochs, duration:
        Training epochs and chunk length in seconds.
    seed:
        Passed to ``pl.seed_everything(seed, workers=True)``, which seeds
        Python, NumPy and torch and sets ``PL_GLOBAL_SEED``, from which
        pyannote derives each worker's chunk sampler.
    max_minutes, limit_meetings:
        Recorded in the provenance only.

    Returns
    -------
    Path
        ``output_dir/segmentation_model/segmentation-ami-best.ckpt``, a
        Lightning checkpoint that ``pyannote.audio.Model.from_pretrained``
        (and so ``benchmark_der --segmentation-model``) loads from a path.

    Side effects
    ------------
    Downloads the base model, trains on the GPU when one is available,
    and writes checkpoints, logs, the exported checkpoint and
    ``finetune_provenance.json``. Seeds the global RNGs.
    """
    print("\n--- Phase 2: fine-tuning segmentation model ---", flush=True)

    try:
        from pyannote.audio import Model
        from pyannote.audio.tasks import SpeakerDiarization
    except ImportError as exc:
        raise SystemExit(
            "pyannote.audio is required.  "
            "Install with:  pip install 'pyannote.audio>=3.1'"
        ) from exc

    try:
        # pyannote.audio 3.4 builds Model on pytorch_lightning, not on the
        # 'lightning' namespace, so the Trainer must come from here too.
        import pytorch_lightning as pl
    except ImportError as exc:
        raise SystemExit(
            "pytorch-lightning is required.  "
            "Install with:  pip install 'pytorch-lightning>=2.0'"
        ) from exc

    # Before the task and model exist, so that everything they draw from
    # the RNGs, and the worker chunk samplers, follow the seed.
    pl.seed_everything(seed, workers=True)

    protocol = _make_protocol(train_files, dev_files)

    # The released model's powerset (see _MAX_SPEAKERS_PER_CHUNK): up to
    # three speakers per chunk, two per frame. Fine-tuning within it can
    # reduce missed two-speaker overlap but cannot represent a third
    # simultaneous voice.
    task = SpeakerDiarization(
        protocol,
        duration=duration,
        max_speakers_per_chunk=_MAX_SPEAKERS_PER_CHUNK,
        max_speakers_per_frame=_MAX_SPEAKERS_PER_FRAME,
    )

    print(f"  Loading {_BASE_MODEL} ...", flush=True)
    # At the revision evaluation/revisions.py pins (spelt "<repo>@<sha>" for
    # pyannote 3.x), with the token keyword this pyannote takes (audit
    # findings DEPS-04, DEPS-10).
    from evaluation.hub_loading import pinned_checkpoint, token_kwargs

    checkpoint, pin = pinned_checkpoint(Model.from_pretrained, _BASE_MODEL)
    model = Model.from_pretrained(
        checkpoint, **pin, **token_kwargs(Model.from_pretrained, hf_token))
    if model is None:
        raise SystemExit(f"could not load {_BASE_MODEL}: accept its conditions "
                         "on the Hub and provide HF_TOKEN or hf_token.txt.")

    model.task = task

    ckpt_dir = output_dir / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    checkpoint_cb = pl.callbacks.ModelCheckpoint(
        dirpath=str(ckpt_dir),
        filename="segmentation-ami-{epoch:02d}-{DiarizationErrorRate:.4f}",
        monitor="DiarizationErrorRate",
        mode="min",
        save_top_k=3,
    )
    lr_monitor = pl.callbacks.LearningRateMonitor(logging_interval="step")

    accelerator = "gpu" if _gpu_available() else "cpu"
    print(
        f"  Accelerator: {accelerator}  |  Epochs: {epochs}  "
        f"|  Chunk duration: {duration} s  |  Seed: {seed}",
        flush=True,
    )

    trainer = pl.Trainer(
        max_epochs=epochs,
        accelerator=accelerator,
        devices=1,
        gradient_clip_val=0.5,
        callbacks=[checkpoint_cb, lr_monitor],
        log_every_n_steps=1,
        default_root_dir=str(output_dir / "lightning_logs"),
        # "warn" rather than True: the cuDNN LSTM backward pass has no
        # deterministic implementation, and True would stop the run.
        deterministic="warn",
    )

    trainer.fit(model)

    best_ckpt = Path(checkpoint_cb.best_model_path)
    if not best_ckpt.is_file():
        raise SystemExit("training produced no checkpoint to export "
                         f"(best_model_path={checkpoint_cb.best_model_path!r}).")
    print(f"  Best checkpoint: {best_ckpt}", flush=True)

    # pyannote.audio 3.4's Model has no save_pretrained. Its
    # from_pretrained loads a Lightning checkpoint given as a file path,
    # so the best checkpoint itself is the exported model.
    export_dir = output_dir / "segmentation_model"
    export_dir.mkdir(parents=True, exist_ok=True)
    exported = export_dir / _BEST_CHECKPOINT_NAME
    shutil.copy2(best_ckpt, exported)

    provenance = _provenance(
        train_files, dev_files, epochs, duration, seed, max_minutes,
        limit_meetings, str(best_ckpt), str(exported))
    (export_dir / "finetune_provenance.json").write_text(
        json.dumps(provenance, indent=2), encoding="utf-8"
    )

    print(f"  Fine-tuned model saved to {exported}", flush=True)
    return exported


# ---------------------------------------------------------------------------
# Phase 3 — evaluation
# ---------------------------------------------------------------------------

def _evaluate(
    segmentation_model_path: Path,
    output_dir: Path,
    cache_dir: Path | None = None,
) -> None:
    """Re-run the DER benchmark with the fine-tuned segmentation model.

    Results are written to ``output_dir/evaluation`` so they sit alongside
    the training artefacts without overwriting the committed baseline results
    in ``output/evaluation``. The benchmark reads the HuggingFace token
    itself, from the same sources as :func:`load_hf_token`.

    Parameters
    ----------
    segmentation_model_path:
        The exported checkpoint.
    output_dir:
        The fine-tuning run's root directory.
    cache_dir:
        Reconstruction cache root to read the test split from, normally
        the one the baseline was scored from (``$DATA/ami_cache``);
        ``None`` streams and rebuilds the split. Either way the benchmark
        scores the cache's 16-bit signal (EDER-06), so the comparison with
        the baseline is like for like; the cache only saves the download.

    Side effects
    ------------
    Streams the test split or reads *cache_dir*, loads the pipeline, writes
    ``der_report.csv`` and ``der_summary.json`` under
    ``output_dir/evaluation`` and prints the change against
    ``output/evaluation/der_summary.json``.
    """
    print("\n--- Phase 3: evaluating fine-tuned model on AMI IHM test set ---",
          flush=True)

    eval_output = output_dir / "evaluation"
    eval_output.mkdir(parents=True, exist_ok=True)

    from evaluation.benchmark_der import run_benchmark

    # Scored the same way as the released model, on the timeline
    # reconstruction of the held-out test split and on the same 16-bit
    # signal, so the two numbers are directly comparable with
    # output/evaluation/der_summary.json.
    run_benchmark(
        output_dir=eval_output,
        split="test",
        mix_mode="timeline",
        limit_meetings=None,
        cache_dir=cache_dir,
        segmentation_model=str(segmentation_model_path),
    )

    summary_path = eval_output / "der_summary.json"
    if summary_path.exists():
        with summary_path.open(encoding="utf-8") as fh:
            s = json.load(fh)
        baseline_path = _ROOT / "output" / "evaluation" / "der_summary.json"
        print(f"\n  Fine-tuned results (saved to {eval_output}):")
        print(f"    macro-DER = {s['macro_der']:.4f}")
        print(f"    micro-DER = {s['micro_der']:.4f}")
        if baseline_path.exists():
            with baseline_path.open(encoding="utf-8") as fh:
                b = json.load(fh)
            print("\n  Baseline (pyannote/speaker-diarization-3.1):")
            print(f"    macro-DER = {b['macro_der']:.4f}")
            print(f"    micro-DER = {b['micro_der']:.4f}")
            delta_macro = s["macro_der"] - b["macro_der"]
            delta_micro = s["micro_der"] - b["micro_der"]
            # The "+" format flag signs positive changes and zero, as the
            # sign() lambda it replaces did (ruff E731).
            print(
                f"\n  Change:  macro {delta_macro:+.4f}  "
                f"micro {delta_micro:+.4f}"
            )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Fine-tune pyannote/segmentation-3.0 on AMI IHM training data, "
            "close-talking headset meeting audio with overlapping speech."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=_DEFAULT_OUTPUT_DIR,
        help="Root directory for WAV files, RTTM files, checkpoints, and model.",
    )
    p.add_argument(
        "--limit-meetings",
        type=int,
        default=_DEFAULT_LIMIT_MEETINGS,
        metavar="N",
        help=(
            "Maximum number of AMI train meetings to include.  "
            "The AMI IHM train split contains approximately 130 meetings; "
            "the default of 80 balances coverage against compute time."
        ),
    )
    p.add_argument(
        "--max-minutes",
        type=float,
        default=None,
        metavar="M",
        help="Truncate each training meeting to its first M minutes, for a "
             "cheaper pilot.  The default keeps whole meetings, which is "
             "what the benchmark scores.",
    )
    p.add_argument(
        "--epochs",
        type=int,
        default=_DEFAULT_EPOCHS,
        help="Number of fine-tuning epochs.",
    )
    p.add_argument(
        "--duration",
        type=float,
        default=_DEFAULT_DURATION,
        help="Chunk duration in seconds fed to the SpeakerDiarization task.",
    )
    p.add_argument(
        "--dev-fraction",
        type=float,
        default=_DEFAULT_DEV_FRACTION,
        help=(
            "Minimum fraction of train meetings held out as validation set.  "
            "Whole AMI series are held out, in sorted order, so no "
            "participant is in both sets and the same meetings are always "
            "selected across runs."
        ),
    )
    p.add_argument(
        "--seed",
        type=int,
        default=_DEFAULT_SEED,
        help="Seed for pl.seed_everything (Python, NumPy, torch and the "
             "pyannote chunk samplers).",
    )
    p.add_argument(
        "--skip-data-prep",
        action="store_true",
        help=(
            "Skip Phase 1 and reload protocol files from previously saved "
            "WAV and RTTM files.  Requires that Phase 1 has been run at "
            "least once with the same --output-dir."
        ),
    )
    p.add_argument(
        "--skip-eval",
        action="store_true",
        help="Skip Phase 3 (DER evaluation on the AMI IHM test set).",
    )
    p.add_argument(
        "--eval-cache-dir",
        type=Path,
        default=None,
        metavar="DIR",
        help="Reconstruction cache root for Phase 3, normally the one the "
             "baseline was scored from ($DATA/ami_cache). Without it the "
             "test split is streamed again; the scored signal is the same.",
    )
    # No --hf-token option: a token on the command line is visible to other
    # users of a shared node through ps and /proc, and stays in shell
    # history. HF_TOKEN or hf_token.txt is read instead.
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Run the three phases from the command line.

    *argv* replaces ``sys.argv[1:]`` (see :func:`_parse_args`). Phase 1
    builds the AMI training and development meetings
    (:func:`_build_and_save_ami`), or reloads them with
    ``--skip-data-prep`` (:func:`_reload_from_disk`); phase 2 fine-tunes
    the segmentation model (:func:`_finetune`); phase 3, unless
    ``--skip-eval``, scores it with the DER benchmark (:func:`_evaluate`).
    A missing HuggingFace token is warned about on stderr, and the run
    carries on without one.

    Returns ``None``. A phase that refuses its input or setup raises
    ``SystemExit`` with its message; other errors propagate. Side
    effects: creates ``--output-dir`` (``output/finetune`` by default)
    and writes the meetings, checkpoints, logs and evaluation the phases
    document there; prints progress and the commands that use the
    checkpoint.
    """
    args = _parse_args(argv)
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    hf_token = load_hf_token()
    if not hf_token:
        print(
            "⚠  No HuggingFace token found.  "
            "Set the HF_TOKEN environment variable or create hf_token.txt.",
            file=sys.stderr,
        )

    # Phase 1
    if args.skip_data_prep:
        print("Reloading data from disk (--skip-data-prep).", flush=True)
        train_files, dev_files = _reload_from_disk(
            output_dir, args.dev_fraction,
            limit_meetings=args.limit_meetings, max_minutes=args.max_minutes)
    else:
        train_files, dev_files = _build_and_save_ami(
            output_dir=output_dir,
            hf_token=hf_token,
            limit_meetings=args.limit_meetings,
            max_minutes=args.max_minutes,
            dev_fraction=args.dev_fraction,
        )

    # Phase 2
    model_path = _finetune(
        train_files=train_files,
        dev_files=dev_files,
        output_dir=output_dir,
        hf_token=hf_token,
        epochs=args.epochs,
        duration=args.duration,
        seed=args.seed,
        max_minutes=args.max_minutes,
        limit_meetings=args.limit_meetings,
    )

    # Phase 3
    if not args.skip_eval:
        _evaluate(
            segmentation_model_path=model_path,
            output_dir=output_dir,
            cache_dir=args.eval_cache_dir,
        )

    print(f"\nFine-tuned segmentation checkpoint: {model_path}")
    model_argument = shlex.quote(model_path.as_posix())
    print(
        "\nTo re-run the DER benchmark with this model:\n"
        f"  python -m evaluation.benchmark_der "
        f"--segmentation-model {model_argument}\n"
        "\nTo use it in the main transcription pipeline, write a pyannote "
        "pipeline YAML whose\nsegmentation entry is this checkpoint and pass "
        "it with --diarization-config."
    )


if __name__ == "__main__":
    # Ended as benchmark_der and sweep_der end. Phase 1 streams the AMI
    # train split, and phase 3 the test split unless --eval-cache-dir is
    # given; the datasets streaming stack can leave a native thread that
    # aborts the interpreter at shutdown with status 134 after every file
    # is written, so a run that saved its checkpoint would be reported as
    # failed. exit_without_finalising skips atexit handlers: nothing here
    # registers one, and Lightning's Trainer.fit finalises its loggers
    # before it returns. A phase's SystemExit keeps its status and message;
    # any other exception still propagates with its traceback.
    try:
        main()
        _status = 0
    except SystemExit as _exc:
        if _exc.code not in (0, None):
            print(f"error: {_exc}", file=sys.stderr)
        _status = _exc.code if isinstance(_exc.code, int) else 1
    exit_without_finalising(_status or 0)
