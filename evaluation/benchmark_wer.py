#!/usr/bin/env python3
"""
Benchmark the transcription pipeline against a public ASR corpus.

By default, evaluates against the LibriSpeech ``test-clean`` split, which
is the standard reference used to compare ASR systems in the literature
(Radford et al., 2022; Wang et al., 2025). The headline files the Quarto
manuscript reads, ``output/evaluation/wer_report.csv`` and
``wer_summary.json``, are one cell of the condition sweep, which runs this
module through :func:`run_benchmark`. ``evaluation.sweep`` wrote the raw
Large v3 test-clean cell as ``wer_report_librispeech_whisper-large-v3.csv``
and ``wer_summary_librispeech_whisper-large-v3.json``, and those files were
copied under the headline names (audit finding OUTPUTS-03). Nothing writes
the headline names by default: ``evaluation.sweep`` writes them only when
given ``--legacy-primary-paths``, ``evaluation.wer`` writes
``*_transcripts`` names, and this module's own output paths are required
(below).

The corpus is streamed via HuggingFace ``datasets`` and is never stored
permanently; it is neither retained in the repository nor transmitted
anywhere beyond the local evaluation run. The dataset and the model are
loaded at the revisions pinned in :mod:`evaluation.revisions`, and every
summary records those revisions, the run's code commit and package
versions (:func:`provenance.run_metadata`), and the decoding device.

The model decodes on a GPU when torch sees one and on the processor
otherwise, in the checkpoint's own precision on a GPU and in float32 on a
processor. ``--device`` and ``--dtype`` override either choice, which is
how the determinism job's CPU arm runs the same decode on a processor
(``hpc/submit_determinism_cpu.sh``).

Usage::

    python -m evaluation.benchmark_wer --report R.csv --summary S.json
    python -m evaluation.benchmark_wer --limit 200 --report R.csv --summary S.json
    python -m evaluation.benchmark_wer --report R.csv --summary S.json \\
        --dataset LIUM/tedlium --config release3 --split test
    python -m evaluation.benchmark_wer --suite ami --limit 200 \\
        --device cpu --dtype float32 --report R.csv --summary S.json

``--report`` and ``--summary`` are required. They used to default to
``output/evaluation/wer_report.csv`` and ``wer_summary.json``, the
manuscript's headline files, so a bare run silently replaced them
(audit finding EWER-11).

Dependencies::

    pip install datasets>=2.14.0
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from collections.abc import Iterator

# ``datasets`` and ``transformers`` are imported lazily inside the functions
# that need them (_iter_samples and _build_asr_pipeline), so the CLI, the
# path/condition helpers, and the argument parser can be imported and tested
# without the heavy optional dependencies installed.

try:
    import io
    import soundfile as _sf
    _HAS_SOUNDFILE = True
except ImportError:
    _HAS_SOUNDFILE = False

try:
    import numpy as np
except ImportError as exc:  # pragma: no cover
    raise SystemExit("numpy is required.") from exc

try:
    import torch as _torch
    _HAS_TORCH = True
except ImportError:
    _HAS_TORCH = False

# evaluation.wer is imported lazily inside run_benchmark so the CLI and
# helpers load without the scoring stack; the name is needed here only for
# annotations.
if TYPE_CHECKING:  # pragma: no cover - type-checking aid only
    from evaluation.wer import PairResult

# Programming and environment errors that a per-utterance ``except`` must
# never swallow: they fail on every utterance alike, so skipping would
# drop a whole condition from the grid while the job still exits 0.
_FATAL_ERRORS = (ImportError, NameError, AttributeError)

_DEFAULT_DATASET    = "librispeech_asr"
_DEFAULT_CONFIG     = "clean"
_DEFAULT_SPLIT      = "test"
_DEFAULT_MODEL      = "openai/whisper-large-v3"
_SAMPLE_RATE        = 16_000
_DEFAULT_SEED       = 42

#: Accepted ``--device`` values. "auto" is the GPU when torch sees one.
_DEVICES = ("auto", "cpu", "cuda")
#: Accepted ``--dtype`` values. "auto" is the checkpoint's own dtype (its
#: config's ``torch_dtype``), which is what the transformers pipeline loads
#: when given no dtype from 4.56 on: float16 for Large v3 and
#: distil-large-v3, float32 for Whisper Medium.
_DTYPES = ("auto", "float32", "float16", "bfloat16")


@dataclass(frozen=True)
class _ConditionRun:
    """One scoring pass within a multi-condition benchmark invocation.

    The audio is iterated once and the ASR pipeline transcribes each
    utterance only once; each ``_ConditionRun`` then applies its own
    condition transform to the in-memory hypothesis (and, where the
    condition flags ``apply_to_reference``, to the reference) and writes a
    separate CSV / JSON pair.
    """

    condition_name: str       # registry key in evaluation.conditions
    report_path:    Path
    summary_path:   Path | None


def _derive_condition_paths(
    primary_report:  Path,
    primary_summary: Path | None,
    condition_name:  str,
    is_first:        bool,
) -> tuple[Path, Path | None]:
    """Return (report_path, summary_path) for the given condition.

    The first condition in a multi-condition run uses the caller's
    ``--report`` and ``--summary`` paths verbatim, preserving the canonical
    output contract (``output/evaluation/wer_report.csv`` /
    ``wer_summary.json``) consumed by the Quarto manuscript.  Subsequent
    conditions append ``_{condition_name}`` to the file stem of the primary
    paths.
    """
    if is_first:
        return primary_report, primary_summary
    report = primary_report.with_name(
        f"{primary_report.stem}_{condition_name}{primary_report.suffix}"
    )
    if primary_summary is None:
        return report, None
    summary = primary_summary.with_name(
        f"{primary_summary.stem}_{condition_name}{primary_summary.suffix}"
    )
    return report, summary


def _parse_conditions_arg(raw: str | None) -> list[str]:
    """Parse the ``--conditions`` CLI value into a list of names.

    Returns an empty list when *raw* is ``None`` or empty, signalling that
    the caller should score ``raw`` alone.  Names are stripped and
    de-duplicated while preserving first-seen order.
    """
    if not raw:
        return []
    seen: list[str] = []
    for tok in raw.split(","):
        name = tok.strip()
        if name and name not in seen:
            seen.append(name)
    return seen


def _apply_seed(seed: int) -> None:
    """Seed all relevant random-number generators and enable cuDNN determinism.

    CUBLAS_WORKSPACE_CONFIG must be set before the CUDA context is created;
    calling this function before ``_build_asr_pipeline`` ensures the env var
    is in place before any GPU memory is allocated.

    The same calls run when the model decodes on a processor, where the
    cuBLAS and cuDNN settings have nothing to act on, so a CPU decode is
    seeded exactly as a GPU one and the two can be compared.

    Side effects
    ------------
    Process-wide and not undone: sets ``os.environ['CUBLAS_WORKSPACE_CONFIG']``,
    seeds the global ``random``, ``numpy.random`` and (when installed) torch
    CPU and CUDA generators, and switches cuDNN to deterministic,
    non-benchmark mode.
    """
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    random.seed(seed)
    np.random.seed(seed)
    if _HAS_TORCH:
        _torch.manual_seed(seed)
        _torch.cuda.manual_seed_all(seed)
        _torch.backends.cudnn.deterministic = True
        _torch.backends.cudnn.benchmark = False


def _device() -> str:
    """Return ``"cuda"`` when torch sees a GPU, otherwise ``"cpu"``."""
    return "cuda" if (_HAS_TORCH and _torch.cuda.is_available()) else "cpu"


def _resolve_device(requested: str | None = None) -> str:
    """Return the device a run decodes on: ``"cuda"`` or ``"cpu"``.

    ``None`` and ``"auto"`` keep the choice every committed result was
    decoded under, :func:`_device`. ``"cpu"`` holds the model on the
    processor even where a GPU is visible: a CPU job that Slurm places on a
    GPU node would otherwise decode on that node's GPU and measure the
    wrong hardware. ``"cuda"`` refuses to fall back to the processor.

    Raises
    ------
    ValueError
        If *requested* is not one of :data:`_DEVICES`.
    SystemExit
        If ``"cuda"`` is requested and torch sees no GPU, before the model
        is loaded.
    """
    if requested is None or requested == "auto":
        return _device()
    if requested not in _DEVICES:
        raise ValueError(f"unknown device {requested!r}; expected one of {_DEVICES}")
    if requested == "cuda" and _device() != "cuda":
        raise SystemExit("--device cuda was requested, but torch sees no GPU.")
    return requested


def _resolve_dtype(requested: str | None, device: str) -> str:
    """Return the precision a run decodes in, as a :data:`_DTYPES` name.

    An explicit value wins. Without one a GPU decodes in ``"auto"``: no
    dtype is passed, as in every committed GPU run, and from transformers
    4.56 the pipeline then loads the dtype the checkpoint's config names,
    so the sweep's summaries record float16 for Large v3 and
    distil-large-v3 and float32 for Whisper Medium. A processor decodes in
    float32 instead, as ``transcription.py`` does on a machine without
    CUDA: the checkpoint's float16 would make a CPU run slow and would not
    be the desktop path it is meant to test.

    Raises
    ------
    ValueError
        If *requested* is not one of :data:`_DTYPES`.
    """
    if requested is not None:
        if requested not in _DTYPES:
            raise ValueError(f"unknown dtype {requested!r}; expected one of {_DTYPES}")
        return requested
    return "auto" if device == "cuda" else "float32"


def _build_asr_pipeline(model_id: str, language: str = "english",
                        device: str | None = None,
                        dtype: str | None = None) -> object:
    """Build the Hugging Face ASR pipeline for *model_id*.

    Parameters
    ----------
    model_id:
        Hugging Face model identifier (downloaded on first use), loaded at
        the revision :func:`evaluation.revisions.revision_for` pins (the
        repository's ``main`` when it pins none).
    language:
        Whisper decoding language, forced through ``generate_kwargs``.
    device:
        ``"cuda"`` or ``"cpu"``; ``None`` takes :func:`_device`.
    dtype:
        A :data:`_DTYPES` name. ``None`` and ``"auto"`` pass no dtype, so
        the call is the one every committed run made.

    Returns
    -------
    object
        A callable ``transformers`` pipeline.

    Raises
    ------
    SystemExit
        If ``transformers`` is not installed.
    """
    # Use return_timestamps=True to engage Whisper's native long-form
    # transcription mechanism rather than the experimental chunk_length_s path.
    # ``language`` is forwarded to Whisper's forced-decoder prompt; the default
    # keeps the English benchmarks bit-for-bit unchanged, and a non-English
    # value (e.g. "french") is what drives the multilingual FLEURS wave.
    try:
        from transformers import pipeline as hf_pipeline
    except ImportError as exc:
        raise SystemExit(
            "transformers is required.  Install with:  pip install transformers"
        ) from exc
    from evaluation.revisions import revision_for
    precision: dict = {}
    if dtype not in (None, "auto"):
        if dtype not in _DTYPES:
            raise ValueError(f"unknown dtype {dtype!r}; expected one of {_DTYPES}")
        if not _HAS_TORCH:
            raise SystemExit(f"--dtype {dtype} needs torch, which is not installed.")
        # The keyword needs transformers 4.56, the floor requirements.txt
        # and preflight already set for benchmark_timestamps' dtype=.
        precision["dtype"] = getattr(_torch, dtype)
    # A Hub repository is mutable; without a revision a later push to the
    # model repo (a generation_config update, say) would silently change
    # what a re-run decodes (audit findings EWER-10, DEPS-04).
    return hf_pipeline(
        "automatic-speech-recognition",
        model=model_id,
        revision=revision_for(model_id),
        device=device or _device(),
        return_timestamps=True,
        generate_kwargs={"language": language, "task": "transcribe"},
        **precision,
    )


def _processor_name() -> str | None:
    """Return the processor model, or ``None`` when it cannot be read.

    Recorded for GPU runs too: the pipeline computes the log-mel features
    on the host processor before the model sees them, so the host is part
    of the hardware a decode ran on. Never raises.
    """
    try:
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip() or None
    except OSError:
        pass
    try:
        import platform
        return platform.processor() or None
    except Exception:  # metadata must never fail a run
        return None


def _decode_environment(asr: object, device: str | None = None,
                        dtype_requested: str | None = None) -> dict:
    """Describe where and how *asr* decoded, for the summary.

    Returns the device (*device*, or :func:`_device` when not given), the
    precision asked for (*dtype_requested*, a :data:`_DTYPES` name) and
    the model's dtype as loaded, the model commit transformers resolved
    (``config._commit_hash``), the CUDA and cuDNN versions torch was built
    with, the GPU name when the decode ran on one, the host processor and
    torch's intra-op thread count, which can change a processor's
    reduction order. The committed raw LibriSpeech decodes from three
    environments disagree on a handful of utterances although repeat
    decodes in one environment are identical (audit finding EWER-10), so
    this is what a reader needs to attribute such drift. A field that
    cannot be read is ``None``; this never raises.
    """
    env: dict = {"device": device or _device(), "dtype": None,
                 "dtype_requested": dtype_requested, "model_commit": None,
                 "torch_cuda": None, "cudnn": None, "gpu": None,
                 "cpu": _processor_name(), "torch_threads": None}
    try:
        model = getattr(asr, "model", None)
        dtype = getattr(model, "dtype", None)
        env["dtype"] = str(dtype) if dtype is not None else None
        env["model_commit"] = getattr(getattr(model, "config", None),
                                      "_commit_hash", None)
        if _HAS_TORCH:
            env["torch_cuda"] = _torch.version.cuda
            env["torch_threads"] = _torch.get_num_threads()
            if _torch.backends.cudnn.is_available():
                env["cudnn"] = _torch.backends.cudnn.version()
            if env["device"] == "cuda" and _torch.cuda.is_available():
                env["gpu"] = _torch.cuda.get_device_name(0)
    except Exception:  # metadata must never fail a run
        pass
    return env


def _decode_audio(audio_dict: dict) -> tuple[np.ndarray, int]:
    """Decode a datasets audio dict to (float32 array, sampling_rate).

    Avoids the ``torchcodec`` dependency introduced in ``datasets`` 3.x by
    decoding directly with ``soundfile``.  The ``audio`` field in streaming
    mode is a dict with ``bytes`` (raw audio) and optionally ``path``.
    """
    if not _HAS_SOUNDFILE:
        raise SystemExit(
            "soundfile is required for audio decoding.  "
            "Install with:  pip install soundfile"
        )
    audio_bytes = audio_dict.get("bytes")
    if audio_bytes:
        arr, sr = _sf.read(io.BytesIO(audio_bytes), dtype="float32", always_2d=False)
        return arr, sr
    path = audio_dict.get("path")
    if path:
        arr, sr = _sf.read(path, dtype="float32", always_2d=False)
        return arr, sr
    # Already decoded (e.g. non-streaming mode)
    if audio_dict.get("array") is not None:
        return np.asarray(audio_dict["array"], dtype=np.float32), audio_dict["sampling_rate"]
    raise ValueError("Cannot decode audio: no bytes, path, or array in row.")


def _resample(arr: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    """Resample a mono signal from *orig_sr* to *target_sr*.

    Uses ``librosa.resample`` when librosa is installed. Otherwise falls
    back to linear interpolation with no anti-aliasing filter, which
    aliases on downsampling, and says so on stderr. Every corpus the
    committed runs used is already 16 kHz, so neither path ran for them.
    """
    if orig_sr == target_sr:
        return arr
    try:
        import librosa
        return librosa.resample(arr, orig_sr=orig_sr, target_sr=target_sr)
    except ImportError:
        pass
    print(
        f"  warning: librosa is not installed; resampling {orig_sr} Hz to "
        f"{target_sr} Hz by linear interpolation without anti-aliasing, "
        "which can raise WER on downsampled audio.",
        file=sys.stderr,
    )
    # Fallback: linear interpolation at any ratio, no low-pass filter.
    ratio = target_sr / orig_sr
    # Rounded, not truncated, so the length matches librosa's for the same
    # ratio (XREF-07); int() dropped a sample whenever the product was not whole.
    new_len = int(round(len(arr) * ratio))
    return np.interp(
        np.linspace(0, len(arr) - 1, new_len),
        np.arange(len(arr)),
        arr,
    ).astype(np.float32)


def _iter_samples(
    dataset_name: str,
    config: str,
    split: str,
    limit: int | None,
    ref_field: str | None = None,
    uid_field: str | None = None,
) -> Iterator[tuple[str, np.ndarray, int, str]]:
    """Yield ``(utterance_id, audio_array, sampling_rate, reference_text)``.

    Audio is decoded with ``soundfile`` directly from the raw bytes supplied
    by the streaming dataset, bypassing ``datasets``' ``Audio`` feature
    decoder and its optional ``torchcodec`` dependency.

    When *ref_field* is supplied, that column is used exclusively for the
    reference transcription.  Otherwise the function tries ``text``,
    ``sentence``, ``transcript``, ``transcription`` and ``normalized_text``
    in order, taking the first non-empty value.  The same explicit-or-fallback
    logic applies to *uid_field*, which defaults to probing ``id``,
    ``audio_id`` and ``path`` in order.

    The dataset is streamed at the revision
    :func:`evaluation.revisions.revision_for` pins for *dataset_name*
    (``main`` when it pins none).
    """
    try:
        import datasets as hf_datasets
        from datasets import Audio as _HFAudio
    except ImportError as exc:
        raise SystemExit(
            "The 'datasets' package is required.  "
            "Install with:  pip install datasets>=2.14.0"
        ) from exc
    from evaluation.revisions import revision_for
    ds = hf_datasets.load_dataset(
        dataset_name,
        config,
        split=split,
        streaming=True,
        trust_remote_code=False,
        # Hub datasets are re-sharded and converted to Parquet in place;
        # the pin keeps a re-run on the audio and references the committed
        # results scored (audit findings EWER-10, DEPS-04).
        revision=revision_for(dataset_name),
    )
    # Disable datasets 3.x automatic audio decoding (which requires torchcodec).
    # We decode the raw bytes ourselves using soundfile.
    ds = ds.cast_column("audio", _HFAudio(decode=False))

    for i, row in enumerate(ds):
        if limit is not None and i >= limit:
            break
        arr, sr = _decode_audio(row["audio"])
        if np.ndim(arr) != 1:
            # soundfile returns (frames, channels) for multi-channel audio,
            # which neither the resampler nor the ASR pipeline handles as
            # speech. Every committed corpus is mono.
            raise ValueError(
                f"row {i}: audio has shape {np.shape(arr)}; only mono audio "
                "is supported. Downmix the corpus first."
            )
        if sr != _SAMPLE_RATE:
            arr = _resample(arr, sr, _SAMPLE_RATE)
        if ref_field is not None:
            ref = str(row.get(ref_field) or "")
        else:
            ref = (row.get("text") or row.get("sentence")
                   or row.get("transcript") or row.get("transcription")
                   or row.get("normalized_text") or "")
        if uid_field is not None:
            _uid_val = row.get(uid_field)
            uid = str(_uid_val) if _uid_val is not None else f"utterance_{i:05d}"
        else:
            _uid_val = next(
                (row[k] for k in ("id", "audio_id", "path") if row.get(k) is not None),
                None,
            )
            uid = str(_uid_val) if _uid_val is not None else f"utterance_{i:05d}"
        yield Path(str(uid)).stem, arr, _SAMPLE_RATE, str(ref)


def _write_summary(
    results: list[PairResult],
    summary_data: dict,
    dataset_name: str,
    config: str,
    split: str,
    model_id: str,
    path: Path,
    seed: int = _DEFAULT_SEED,
    condition: str | None = None,
    language: str | None = None,
    extra: dict | None = None,
    run_meta: dict | None = None,
) -> None:
    """Write the JSON summary in the format expected by the Quarto manuscript.

    Parameters
    ----------
    results, summary_data:
        The scored pairs and their :func:`evaluation.wer.aggregate`.
    dataset_name, config, split, model_id, seed:
        Recorded in the ``benchmark`` block.
    path:
        Destination; its parent directory is created and the file
        overwritten.
    condition:
        Recorded as ``benchmark.condition`` so that downstream readers can
        disambiguate the condition outputs of one benchmark run.
    language:
        Recorded so a reader can tell an English run from a non-English
        FLEURS run.
    extra:
        Further ``benchmark`` keys: the requested limit, the skip counts, the renamed-id count,
        ``wer_invisible``, the revisions and the decoding environment.
    run_meta:
        :func:`provenance.run_metadata` for the run, written at the top
        level as ``run_metadata`` (code commit, dirty flag, Python and
        package versions).
    """
    benchmark_block: dict = {
        "dataset":    dataset_name,
        "config":     config,
        "split":      split,
        "model":      model_id,
        "utterances": len(results),
        "seed":       seed,
    }
    if condition is not None:
        benchmark_block["condition"] = condition
    if language is not None:
        benchmark_block["language"] = language
    if extra:
        benchmark_block.update(extra)
    payload = {
        "benchmark": benchmark_block,
        "summary":  summary_data,
        "per_file": [asdict(r) for r in results],
    }
    if run_meta is not None:
        payload["run_metadata"] = run_meta
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


class HypothesisDump:
    """Record the verbatim text behind every scored pair.

    The per-condition reports store metrics only, which is enough to say
    that a condition changed the word error rate and not enough to say
    what it did to the words. Answering a question such as "does
    ``pipeline_full`` keep the fillers it claims to keep" needs the
    hypothesis text itself, and re-transcribing a corpus to recover it
    costs the GPU time the run already spent.

    One row per scored (utterance, condition) pair, holding the reference
    as the corpus gives it, the reference the condition scored against
    (different only for conditions that also transform the reference, such
    as ``whisper_norm``), the model's untransformed output and the text the
    condition produced from it. Rows are flushed as they are written, so a
    job killed at the wall-clock limit still leaves usable data behind.

    Dumps written before audit finding EWER-22 have a single ``reference``
    column holding the *transformed* reference; ``evaluation.disfluency``
    reads both layouts.

    The file contains transcript text, so it inherits the privacy posture
    of a transcript: it stays wherever the run's other outputs go, and it
    is not written at all unless asked for.
    """

    FIELDNAMES = ("uid", "condition", "reference_raw", "reference_transformed",
                  "hypothesis_raw", "hypothesis_transformed", "wer")

    def __init__(self, path):
        """Create (or overwrite) the dump at *path* and write its header."""
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._fh, fieldnames=self.FIELDNAMES)
        self._writer.writeheader()
        self.rows = 0

    def write(self, uid, condition, reference_raw, hypothesis_raw,
              hypothesis_transformed, wer, reference_transformed=None):
        """Append one scored pair and flush it to disk.

        Parameters
        ----------
        uid, condition:
            The utterance and the condition name.
        reference_raw:
            The reference as the corpus gives it.
        hypothesis_raw, hypothesis_transformed:
            The model's output and the condition's output.
        wer:
            The pair's word error rate, written to six decimals.
        reference_transformed:
            The reference the pair was scored against; ``None`` means the
            condition left it unchanged, and *reference_raw* is written.
        """
        self._writer.writerow({
            "uid": uid,
            "condition": condition,
            "reference_raw": reference_raw,
            "reference_transformed": (reference_raw
                                      if reference_transformed is None
                                      else reference_transformed),
            "hypothesis_raw": hypothesis_raw,
            "hypothesis_transformed": hypothesis_transformed,
            "wer": f"{float(wer):.6f}",
        })
        self._fh.flush()
        self.rows += 1

    def close(self):
        """Close the file; safe to call more than once."""
        if not self._fh.closed:
            self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def run_benchmark(
    dataset_name: str,
    config: str,
    split: str,
    model_id: str,
    limit: int | None,
    runs: list[_ConditionRun],
    ref_field: str | None = None,
    uid_field: str | None = None,
    seed: int = _DEFAULT_SEED,
    language: str = "english",
    dump_hypotheses: Path | None = None,
    device: str | None = None,
    dtype: str | None = None,
    run_meta: dict | None = None,
) -> None:
    """Evaluate *model_id* on the given corpus split under one or more conditions.

    The audio is iterated once and each utterance is transcribed by the ASR
    pipeline only once.  Each entry in *runs* declares a registered condition
    (see :mod:`evaluation.conditions`) and a destination CSV / JSON pair;
    every entry produces its own scored output.  When the condition's
    ``apply_to_reference`` flag is set, the same transform is applied to the
    reference text before scoring.

    Parameters
    ----------
    dataset_name, config, split:
        The Hugging Face corpus to stream.
    model_id:
        Hugging Face ASR model identifier.
    limit:
        Cap on utterances streamed; ``None`` streams the whole split.
    runs:
        One :class:`_ConditionRun` per condition to score.
    ref_field, uid_field:
        Dataset columns for the reference text and the utterance id;
        ``None`` probes the usual names (see :func:`_iter_samples`).
    seed:
        Passed to :func:`_apply_seed` before the pipeline is built, on
        either device.
    language:
        Whisper decoding language, also forwarded to language-aware
        conditions.
    dump_hypotheses:
        When given, the verbatim text of every scored pair is written
        there (see :class:`HypothesisDump`).
    device, dtype:
        Where and in what precision the model decodes (see
        :func:`_resolve_device` and :func:`_resolve_dtype`). ``None``
        keeps the defaults: the GPU when there is one, in the checkpoint's
        own dtype, and otherwise the processor in float32.
    run_meta:
        The :func:`provenance.run_metadata` every summary records. A
        caller that writes other files of the same run before this call,
        as a sweep over several suites does, should read it once before
        the first of them, leaving all of them out of the dirty check, and
        pass it here. ``None`` reads it here, before anything is written,
        leaving out the reports, summaries and dump this call writes.

    Utterance ids that repeat within the corpus (FLEURS ids name the
    sentence, which several speakers read) are renamed ``<id>__2``,
    ``<id>__3`` and so on in streaming order, and the count is printed and
    recorded as ``benchmark.n_renamed_duplicate_uids``. Downstream tools
    pair reports by id, so a repeated id would silently merge different
    speakers' utterances.

    Per-utterance failures of a transform or of scoring are skipped and
    counted per condition, as is an utterance whose reference normalises to
    nothing under that condition (``whisper_norm`` empties filler-only
    references). Every summary records all three counts
    (``benchmark.n_skipped_transform``, ``n_skipped_empty_reference`` and
    ``n_skipped_scoring``) and the number of utterances streamed
    (``benchmark.n_streamed``), so conditions scored on different
    utterance sets can be told apart; compare them on the shared
    utterances with :func:`evaluation.condition_ci.normaliser_gain`.
    Import, name and attribute errors are not data problems and propagate.

    Each summary also records ``benchmark.wer_invisible`` (see
    :class:`evaluation.conditions.Condition`), the pinned revisions of the
    dataset and model (``benchmark.revisions``), the decoding environment
    (``benchmark.decode``), the normaliser's provenance for
    ``whisper_norm`` (``benchmark.normaliser``) and, at the top level,
    :func:`provenance.run_metadata`.

    Raises
    ------
    ValueError
        If *runs* is empty, *device* or *dtype* is not a known name, or a
        streamed row holds multi-channel audio.
    ImportError
        If jiwer, or a dependency of a requested condition (the Whisper
        normaliser's spelling map, say), is missing, before the model is
        loaded.
    SystemExit
        If *device* is ``"cuda"`` and torch sees no GPU, before anything
        else; if no utterance was scored at all; or if any requested
        condition scored none (after the other conditions' files are
        written), so an array task cannot exit 0 with a grid cell missing.

    Side effects
    ------------
    Calls :func:`_apply_seed`, which sets ``CUBLAS_WORKSPACE_CONFIG`` and
    seeds the global ``random``, NumPy and torch generators for the rest of
    the process. Downloads the model and streams the corpus. Writes each
    run's report CSV and summary JSON, overwriting them, and the optional
    dump. Runs ``git`` to record the commit. Prints progress to stdout and
    skips to stderr.
    """
    if not runs:
        raise ValueError("run_benchmark requires at least one _ConditionRun")
    decode_device = _resolve_device(device)
    decode_dtype = _resolve_dtype(dtype, decode_device)

    # Resolve registry objects up front so an unknown name fails before any
    # GPU work is done.
    from evaluation.conditions import (
        condition_provenance,
        get_condition,
    )
    from evaluation.revisions import revisions_used
    from evaluation.wer import (
        normalise_text, compute_metrics, aggregate, PairResult, write_csv,
        require_jiwer,
    )
    from provenance import run_metadata
    conditions = [(r, get_condition(r.condition_name)) for r in runs]
    # evaluation.wer imports without jiwer, so a missing scorer would
    # otherwise surface only after the model had loaded and decoded.
    require_jiwer()
    # The same holds for a condition's own dependencies: whisper_norm needs
    # openai-whisper's spelling map and loads it on first use. One call on a
    # short probe makes a missing one (an ImportError) fail here, before the
    # GPU work. Any other error on the probe is left to the per-utterance
    # loop, which counts it.
    for _run, cond in conditions:
        try:
            if cond.language_aware:
                cond.transform("probe", language)
            else:
                cond.transform("probe")
        except _FATAL_ERRORS:
            raise
        except Exception:  # counted per utterance below
            pass
    if run_meta is None:
        # Before anything is written, and leaving out what this call
        # rewrites, as provenance.write_sidecar does for the CSV-only
        # writers. Without the ignore list, a second run in place counted
        # the first one's rewritten reports and summaries as uncommitted
        # code (audit finding OUTPUTS-12).
        outputs = [p for r in runs for p in (r.report_path, r.summary_path)
                   if p is not None]
        if dump_hypotheses:
            outputs.append(dump_hypotheses)
        run_meta = run_metadata(ignore=tuple(outputs))

    print(f"ASR model:  {model_id}  ({decode_device}, dtype {decode_dtype})  "
          f"language={language}", flush=True)
    _apply_seed(seed)
    asr = _build_asr_pipeline(model_id, language, device=decode_device,
                              dtype=decode_dtype)
    decode_env = _decode_environment(asr, device=decode_device,
                                     dtype_requested=decode_dtype)

    desc = f"{dataset_name}/{config}  split={split}"
    if limit:
        desc += f"  (first {limit} utterances)"
    print(f"Corpus:     {desc}", flush=True)
    print(
        "Conditions: " + ", ".join(c.name for _, c in conditions),
        flush=True,
    )

    results_per_run: list[list[PairResult]] = [[] for _ in conditions]
    skips: list[dict[str, int]] = [
        {"n_skipped_transform": 0, "n_skipped_empty_reference": 0,
         "n_skipped_scoring": 0}
        for _ in conditions
    ]
    uid_counts: dict[str, int] = {}
    n_renamed = 0
    n_streamed = 0
    dump = HypothesisDump(dump_hypotheses) if dump_hypotheses else None
    if dump is not None:
        print(f"Hypotheses: {dump.path}", flush=True)

    for uid, array, sr, reference in _iter_samples(
        dataset_name, config, split, limit,
        ref_field=ref_field, uid_field=uid_field,
    ):
        n_streamed += 1
        seen = uid_counts.get(uid, 0) + 1
        uid_counts[uid] = seen
        if seen > 1:
            renamed = f"{uid}__{seen}"
            if renamed in uid_counts:
                raise ValueError(
                    f"utterance id {uid!r} repeats and its renamed form "
                    f"{renamed!r} is itself an id in the corpus; pick a "
                    "unique --uid-field."
                )
            uid_counts[renamed] = 1
            n_renamed += 1
            if n_renamed <= 5:
                print(f"  warning: utterance id {uid!r} repeats; scoring "
                      f"this occurrence as {renamed!r}", file=sys.stderr)
            uid = renamed
        raw_hyp  = asr({"array": np.asarray(array, dtype=float),
                        "sampling_rate": sr})
        hyp_text = (raw_hyp.get("text", "")
                    if isinstance(raw_hyp, dict) else str(raw_hyp))

        per_uid_wers: list[str] = []
        for idx, (_run, cond) in enumerate(conditions):
            try:
                # Language-aware conditions (the production composite) receive
                # the run's language so their English-only stages can be gated
                # on non-English corpora; ordinary conditions ignore it.
                if getattr(cond, "language_aware", False):
                    hyp_t = cond.transform(hyp_text, language)
                    ref_t = (cond.transform(reference, language)
                             if cond.apply_to_reference else reference)
                else:
                    hyp_t = cond.transform(hyp_text)
                    ref_t = cond.transform(reference) if cond.apply_to_reference else reference
            except _FATAL_ERRORS:
                raise
            except Exception as exc:
                print(
                    f"  skipping {uid} ({cond.name} transform): {exc}",
                    file=sys.stderr,
                )
                skips[idx]["n_skipped_transform"] += 1
                continue

            ref_norm = normalise_text(ref_t, strip_header=False)
            hyp_norm = normalise_text(hyp_t, strip_header=False)

            if not ref_norm.strip():
                # An empty reference has no word error rate, so the pair is
                # skipped, for this condition only. That breaks parity in
                # the utterance count: whisper_norm empties filler-only
                # references (990 AMI utterances in the post-fix grid) that
                # raw scores. The count is recorded per condition in the
                # summary, and normaliser_gain compares conditions on the
                # shared utterances (audit finding EWER-09). Printed once
                # per utterance, for the first condition, to keep the log
                # readable.
                if idx == 0:
                    print(
                        f"  skipping {uid}: empty reference after normalisation",
                        file=sys.stderr,
                    )
                skips[idx]["n_skipped_empty_reference"] += 1
                continue
            try:
                metrics = compute_metrics(ref_norm, hyp_norm)
            except _FATAL_ERRORS:
                raise
            except Exception as exc:
                print(
                    f"  skipping {uid} ({cond.name}): {exc}",
                    file=sys.stderr,
                )
                skips[idx]["n_skipped_scoring"] += 1
                continue

            results_per_run[idx].append(PairResult(name=uid, **metrics))
            per_uid_wers.append(f"{cond.name}={metrics['wer']:.3f}")
            if dump is not None:
                # Both references: a consumer that needs the transcriber's
                # own text (filler recall, a rescore under a revised
                # normaliser) must not receive the already-normalised one
                # (audit finding EWER-22).
                dump.write(uid, cond.name, reference, hyp_text, hyp_t,
                           metrics["wer"], reference_transformed=ref_t)

        if per_uid_wers:
            print(f"  {uid}  " + "  ".join(per_uid_wers), flush=True)

    if dump is not None:
        dump.close()
        print(f"  {dump.rows} hypothesis rows written to {dump.path}", flush=True)

    if n_renamed:
        print(f"  {n_renamed} repeated utterance id(s) were renamed with a "
              "'__<n>' suffix", file=sys.stderr)

    if not any(results_per_run):
        raise SystemExit("No utterances scored.  Check dataset name and split.")

    empty_conditions: list[str] = []
    revisions = revisions_used(dataset_name, model_id)
    print(f"\n{'─' * 50}")
    for (run, cond), results, skip in zip(conditions, results_per_run, skips,
                                          strict=True):
        if not results:
            print(f"  [{cond.name}] no utterances scored", file=sys.stderr)
            empty_conditions.append(cond.name)
            continue
        # Every count is recorded, zero included, so that a reader comparing
        # two conditions can see whether they scored the same utterances
        # without inferring it from a missing key (audit finding EWER-09).
        extra: dict = dict(skip)
        extra["limit"] = limit
        extra["n_streamed"] = n_streamed
        extra["n_renamed_duplicate_uids"] = n_renamed
        extra["wer_invisible"] = bool(cond.wer_invisible)
        extra["revisions"] = revisions
        extra["decode"] = decode_env
        normaliser = condition_provenance(cond.name)
        if normaliser is not None:
            extra["normaliser"] = normaliser
        if any(skip.values()):
            print(f"  [{cond.name}] skipped "
                  f"{skip['n_skipped_transform']} on transform, "
                  f"{skip['n_skipped_empty_reference']} with an empty "
                  f"reference and {skip['n_skipped_scoring']} on scoring",
                  file=sys.stderr)
        summary_data = aggregate(results)
        print(
            f"  [{cond.name}]  n={summary_data['files']}  "
            f"WER={summary_data['macro_wer']:.4f}  "
            f"MER={summary_data['macro_mer']:.4f}  "
            f"WIL={summary_data['macro_wil']:.4f}  "
            f"CER={summary_data['macro_cer']:.4f}  "
            f"ref_words={summary_data['total_reference_words']:,}"
        )
        write_csv(results, run.report_path)
        print(f"      report:   {run.report_path}")
        if run.summary_path is not None:
            _write_summary(
                results, summary_data, dataset_name, config,
                split, model_id, run.summary_path,
                seed=seed, condition=cond.name, language=language,
                extra=extra, run_meta=run_meta,
            )
            print(f"      summary:  {run.summary_path}")

    if empty_conditions:
        raise SystemExit(
            "No utterance was scored under condition(s) "
            f"{', '.join(empty_conditions)}; their report and summary were "
            "not written."
        )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="evaluation.benchmark_wer",
        description=(
            "Evaluate the transcription pipeline on a public ASR benchmark. "
            "Defaults to LibriSpeech test-clean."
        ),
    )
    p.add_argument("--dataset", default=_DEFAULT_DATASET,
                   help="HuggingFace dataset name  (default: %(default)s).")
    p.add_argument("--config",  default=_DEFAULT_CONFIG,
                   help="Dataset configuration  (default: %(default)s).")
    p.add_argument("--split",   default=_DEFAULT_SPLIT,
                   help="Dataset split  (default: %(default)s).")
    p.add_argument("--model",   default=_DEFAULT_MODEL,
                   help="Whisper model identifier  (default: %(default)s).")
    p.add_argument("--limit",   type=int, default=None,
                   help="Maximum utterances to score (omit for the full split).")
    # Required: the old defaults were the manuscript's headline files.
    p.add_argument("--report",  type=Path, required=True,
                   help="Output CSV path (required).")
    p.add_argument("--summary", type=Path, required=True,
                   help="Output JSON path (required).")
    p.add_argument(
        "--conditions", default=None, metavar="LIST",
        help=(
            "Comma-separated list of post-processing conditions to score in "
            "a single audio pass (e.g. 'raw,repetition_fix,whisper_norm'; "
            "default: raw alone).  See --list-conditions for available "
            "names.  The first condition writes to --report / --summary; "
            "subsequent conditions append '_<condition>' to the file stem."
        ),
    )
    p.add_argument(
        "--list-conditions", action="store_true", dest="list_conditions",
        help=(
            "Print all available post-processing conditions with their "
            "descriptions, then exit."
        ),
    )
    p.add_argument(
        "--dump-hypotheses", type=Path, default=None, metavar="PATH",
        help=(
            "Also write the verbatim reference and hypothesis text for every "
            "scored pair to this CSV.  The per-condition reports carry "
            "metrics only, so a question about what a condition did to the "
            "words, such as whether it keeps the fillers it claims to keep, "
            "otherwise needs the corpus transcribed again.  The file holds "
            "transcript text and is written only when asked for."
        ),
    )
    p.add_argument(
        "--seed", type=int, default=_DEFAULT_SEED,
        help=(
            "Random seed for Python, NumPy, and PyTorch; also enables cuDNN "
            "deterministic mode.  Fixes the tiny run-to-run variation that "
            "arises from non-deterministic GPU floating-point operations.  "
            "(default: %(default)s)."
        ),
    )
    p.add_argument(
        "--device", choices=_DEVICES, default="auto",
        help=(
            "Where the model decodes: 'cuda', 'cpu', or 'auto' for the GPU "
            "when torch sees one (default: %(default)s).  'cpu' keeps the "
            "model on the processor even on a GPU node; 'cuda' stops rather "
            "than fall back to the processor."
        ),
    )
    p.add_argument(
        "--dtype", choices=_DTYPES, default=None,
        help=(
            "Precision the model decodes in.  'auto' passes no dtype, so the "
            "checkpoint's own loads (float16 for Large v3 and "
            "distil-large-v3, float32 for Whisper Medium).  Default: 'auto' "
            "on a GPU, as every committed GPU run decoded, and float32 on a "
            "processor, as transcription.py decodes there."
        ),
    )
    p.add_argument(
        "--language", default=None, metavar="LANG",
        help=(
            "Whisper transcription language, forwarded to the decoder "
            "prompt (e.g. 'english', 'french', 'german').  Defaults to "
            "English, which leaves the existing benchmarks unchanged; set a "
            "non-English value to score a non-English corpus such as a "
            "FLEURS locale."
        ),
    )
    p.add_argument(
        "--ref-field", default=None, dest="ref_field", metavar="COLUMN",
        help=(
            "Dataset column holding the reference transcription.  Overrides "
            "the suite default and the automatic probe; use it with an "
            "explicit --dataset/--config (e.g. 'transcription' for FLEURS)."
        ),
    )
    p.add_argument(
        "--uid-field", default=None, dest="uid_field", metavar="COLUMN",
        help=(
            "Dataset column holding the utterance id (overrides the probe).  "
            "Ids that repeat are renamed '<id>__<n>' in streaming order."
        ),
    )
    p.add_argument(
        "--suite", default=None, metavar="NAME",
        help=(
            "Named challenge suite (see --list-suites).  When supplied, "
            "--dataset, --config and --split are ignored and the suite's "
            "own dataset, configuration, split, and reference-field settings "
            "are used instead."
        ),
    )
    p.add_argument(
        "--list-suites", action="store_true", dest="list_suites",
        help=(
            "Print all available challenge suites with their categories and "
            "descriptions, then exit."
        ),
    )
    return p


def _build_runs(
    conditions:   list[str],
    primary_report:  Path,
    primary_summary: Path | None,
) -> list[_ConditionRun]:
    """Construct the list of ``_ConditionRun`` specs from CLI arguments.

    Each named condition gets its own run; the first writes to
    *primary_report* / *primary_summary* and subsequent conditions append
    ``_<condition>`` to the file stem.  An empty *conditions* scores
    ``raw`` alone, on the primary paths.

    The pre-registry flags ``--report-postprocessed`` and
    ``--summary-postprocessed``, which added a ``repetition_fix`` run with
    its own naming rule, were removed (audit finding EWER-16): nothing
    used them, and that second naming rule once let the ``repetition_fix``
    report overwrite the raw one.  ``--conditions raw,repetition_fix``
    does the same job.
    """
    names = conditions or ["raw"]
    runs: list[_ConditionRun] = []
    for i, name in enumerate(names):
        report, summary = _derive_condition_paths(
            primary_report, primary_summary, name, is_first=(i == 0),
        )
        runs.append(_ConditionRun(
            condition_name=name,
            report_path=report,
            summary_path=summary,
        ))
    return runs


def _print_conditions() -> None:
    """Print every registered condition with its reference and WER flags.

    ``ref?`` says whether the transform is also applied to the reference;
    ``wer?`` is ``no`` for a condition the scoring normaliser makes score
    exactly as ``raw`` (``Condition.wer_invisible``).  Shared by the
    ``--list-conditions`` flags of this module and :mod:`evaluation.sweep`,
    so the two listings cannot diverge.
    """
    from evaluation.conditions import list_conditions
    print(f"  {'Condition':<20}  {'ref?':<5}  {'wer?':<5}  Description")
    print("  " + "─" * 98)
    for c in list_conditions():
        ref_flag = "yes" if c.apply_to_reference else "no"
        wer_flag = "no" if c.wer_invisible else "yes"
        print(f"  {c.name:<20}  {ref_flag:<5}  {wer_flag:<5}  "
              f"{c.description[:63]}")


def main(argv: list[str] | None = None) -> None:
    """Run the command-line interface.

    Lists suites or conditions and returns, or resolves the corpus (from
    ``--suite`` when given), builds the condition runs and calls
    :func:`run_benchmark`, whose side effects (global seeding, file
    writes) and exit behaviour apply.
    """
    args = _build_parser().parse_args(argv)

    if args.list_suites:
        from evaluation.challenge_suites import list_suites
        print(f"  {'Suite':<30}  {'Category':<20}  Description")
        print("  " + "─" * 98)
        for s in list_suites():
            print(f"  {s.name:<30}  {s.category:<20}  {s.description[:60]}")
        return

    if args.list_conditions:
        _print_conditions()
        return

    # Explicit CLI --ref-field/--uid-field take precedence; a suite fills any
    # field the caller left unset.
    ref_field: str | None = args.ref_field
    uid_field: str | None = args.uid_field
    dataset_name = args.dataset
    config       = args.config
    split        = args.split

    if args.suite is not None:
        from evaluation.challenge_suites import get_suite
        suite_obj    = get_suite(args.suite)
        dataset_name = suite_obj.dataset
        config       = suite_obj.config
        split        = suite_obj.split
        ref_field    = ref_field or suite_obj.ref_field
        uid_field    = uid_field or suite_obj.uid_field

    language = args.language or "english"

    runs = _build_runs(
        conditions=_parse_conditions_arg(args.conditions),
        primary_report=args.report,
        primary_summary=args.summary,
    )

    run_benchmark(
        dataset_name=dataset_name,
        config=config,
        split=split,
        model_id=args.model,
        limit=args.limit,
        runs=runs,
        ref_field=ref_field,
        uid_field=uid_field,
        seed=args.seed,
        language=language,
        dump_hypotheses=args.dump_hypotheses,
        device=args.device,
        dtype=args.dtype,
    )


if __name__ == "__main__":
    main()
