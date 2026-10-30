#!/usr/bin/env python3
"""
Check that this environment can actually run the workflow, before it tries.

The expensive failures in this project have not been in the science but in
the plumbing: a GPU job that dies because the module stack shadowed the
CUDA build of torch, a recording that will not open because the only ffmpeg
on the machine carries a versioned filename, a language-detection path that
silently returns nothing on transformers 4.48 through 5.6. Each of those
costs a queue wait and a failed job to discover, and none of them names its
own cause when it fails.

This module makes the same discoveries in seconds on the login node or the
laptop. Every check prints one line, ``[ OK ]``, ``[WARN]`` or ``[FAIL]``,
and every failure names its remedy, because a diagnostic that only restates
the symptom is how "Format not recognised" happens.

WARN means a feature is degraded but transcription can proceed: no ffmpeg
(compressed formats unreadable), no pyannote (no diarisation), no GPU when
none was demanded. FAIL means the workflow cannot do its job: no torch, no
transformers or one older than the floor in ``requirements.txt``, no CUDA
when ``--gpu-required`` says the caller is about to spend GPU time, an
activated environment whose torch, transformers or pyannote is loaded from
somewhere else, or (with ``--lock``) an installed version that differs from
the lock file. With ``--diarisation-required`` the diarisation problems
fail too, among them a damaged cached pipeline config, or a cached blob
of the pipeline that no longer matches its name, which no token repairs.

Usage::

    python -m preflight                  # report; exit 1 on any FAIL
    python -m preflight --gpu-required   # a missing GPU becomes a FAIL
    python -m preflight --lock requirements-lock.txt   # exact versions
    python -m preflight --json report.json

The HPC job scripts run it through ``hpc/common/arc_common.sh`` after
activating the environment: the GPU jobs with ``--gpu-required``, the CPU
jobs without, and ``hpc/run_tests.sh`` with ``--lock``. A failure stops the
job in seconds rather than after a queue wait, and nothing is installed or
repaired from inside a job.
"""

from __future__ import annotations

import argparse
import codecs
import hashlib
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

# The lowest transformers this workflow supports. Two features set it:
# WhisperGenerationMixin.detect_language, which the language gate relies on
# (added in 4.45), and the `dtype=` keyword that
# evaluation/benchmark_timestamps.py passes to pipeline() (accepted from
# 4.56; that module's _TRANSFORMERS_DTYPE_FLOOR), so the higher one wins.
# With the old 4.45 floor, a 4.45-4.55 environment passed this check and
# then failed inside the GPU job (audit finding DEPS-10). Kept in step with
# requirements.txt; tests/test_audit_core_fixes.py asserts the two agree.
_TRANSFORMERS_FLOOR = (4, 56)
# The interpreter floor, kept in step with setup.py's python_requires (the
# same test asserts they agree).
_PYTHON_FLOOR = (3, 11)
# Every Hub repository pyannote/speaker-diarization-3.1 loads: the pipeline
# config, its segmentation model and its speaker-embedding model. The
# embedding repo is named in the pipeline's config.yaml, and the repo loads
# it directly in evaluation/benchmark_anonymisation.py. setup/
# cache_pyannote_arc.py pre-caches exactly this list (audit finding CORE-15).
# The pipeline itself comes first.
PYANNOTE_PIPELINE_REPOS = (
    "pyannote/speaker-diarization-3.1",
    "pyannote/segmentation-3.0",
    "pyannote/wespeaker-voxceleb-resnet34-LM",
)
_PIPELINE_REPO = PYANNOTE_PIPELINE_REPOS[0]
# A git blob id: the Hub's cache names the blob of a file kept in git (not
# LFS), such as the pipeline's config.yaml, after it.
_GIT_BLOB_ID = re.compile(r"[0-9a-f]{40}")
# A SHA-256: the name of the blob of a file kept in LFS, the X-Linked-Etag
# huggingface_hub reads. On ARC both LFS blobs in pyannote's cache, the
# weights of segmentation-3.0 and wespeaker-voxceleb-resnet34-LM, are named
# after the SHA-256 of their content (checked with sha256sum, 2026-10-04).
_LFS_BLOB_ID = re.compile(r"[0-9a-f]{64}")
_REPO_ROOT = Path(__file__).resolve().parent
# The range in which the ASR pipeline's return_language reporting is empty
# (generation strips the language token before the tokenizer sees it). The
# workflow detects language another way, so this is informational, but it is
# exactly the kind of silent trap a reader of the report should know about.
# Pre-release builds of the fixed boundary ("5.7.0.dev0", "5.7.0rc1") parse
# to (5, 7, 0) and are optimistically treated as fixed, though PEP 440
# orders them before the release that carries the fix.
_RETURN_LANGUAGE_BROKEN = ((4, 48), (5, 7))

OK, WARN, FAIL = "OK", "WARN", "FAIL"


@dataclass
class CheckResult:
    """Outcome of one environment check.

    ``status`` is one of ``OK``, ``WARN`` or ``FAIL``; ``detail`` is the
    one-line finding; ``remedy`` names the fix and is set exactly when the
    status is not ``OK``, because a warning without a remedy is homework.
    """

    name: str
    status: str
    detail: str
    remedy: str | None = None


def _parse_version(text: str) -> tuple:
    """Return the leading numeric components of a version string.

    ``"4.57.1"`` becomes ``(4, 57, 1)``; a suffix such as ``"2.5.0+cu121"``
    stops the parse cleanly at the first non-numeric component. An
    unparseable string yields an empty tuple, which compares smaller than
    any real version and therefore fails floors loudly rather than passing
    them silently.
    """
    parts: list[int] = []
    for token in text.split("."):
        digits = ""
        for ch in token:
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def check_python() -> CheckResult:
    """The interpreter itself: version floor from setup.py."""
    version = sys.version_info
    detail = f"{version.major}.{version.minor}.{version.micro}"
    if (version.major, version.minor) < _PYTHON_FLOOR:
        floor = ".".join(str(part) for part in _PYTHON_FLOOR)
        return CheckResult("python", FAIL, detail,
                           f"the workflow requires Python {floor} or newer")
    return CheckResult("python", OK, detail)


def check_numpy() -> CheckResult:
    """numpy underlies every audio buffer; without it nothing runs."""
    try:
        import numpy
        return CheckResult("numpy", OK, numpy.__version__)
    except ImportError:
        return CheckResult("numpy", FAIL, "not importable",
                           "pip install numpy")


def check_audio() -> CheckResult:
    """Audio decoding: soundfile for open formats, ffmpeg for compressed.

    Delegates to :func:`audio_io.audio_support`, which is the module that
    actually does the decoding, so this report cannot drift from the
    behaviour it describes.
    """
    try:
        from audio_io import audio_support
    except (Exception, SystemExit) as exc:
        # SystemExit too: an import-time exit in any module this check
        # imports must become a FAIL, not end the report (CORE-02).
        return CheckResult("audio", FAIL, f"audio_io unavailable: {exc}",
                           "pip install soundfile numpy")
    info = audio_support()
    if not info["soundfile"]:
        return CheckResult("audio", FAIL, "soundfile not importable",
                           "pip install soundfile")
    if not info["ffmpeg"]:
        return CheckResult(
            "audio", WARN,
            "soundfile present; no ffmpeg, so compressed formats "
            "(.m4a, .mp4, .aac) will not open",
            "pip install imageio-ffmpeg")
    return CheckResult(
        "audio", OK,
        f"soundfile + ffmpeg ({info['ffmpeg_source']}); "
        "compressed formats readable")


_PYTORCH_INDEX = "https://download.pytorch.org/whl/"
# CUDA wheel index that publishes each torch minor series. From PyTorch's
# "previous versions" install matrix: cu121 carries torch 2.1-2.5, cu126
# carries 2.6-2.9. The old fixed cu121 remedy served nothing newer than
# 2.5.1, so following it against a torch 2.8 (the CPU build in the ARC
# account's ~/.local, which shadows the job environment's 2.5.1+cu121 when
# the user site is on) installed a torch that no longer matched torchaudio
# (audit finding CORE-21).
_CUDA_INDEX_BY_MINOR = {**{(2, m): "cu121" for m in range(1, 6)},
                        **{(2, m): "cu126" for m in range(6, 10)}}


def cuda_reinstall_remedy(torch_version: str) -> str:
    """Return the reinstall advice that matches the installed torch.

    torch, torchaudio and torchvision must be reinstalled together at
    matching versions: torchaudio 2.x.y pairs with torch 2.x.y, and
    torchvision 0.(x+15).y with torch 2.x.y. torchvision is named only when
    it is installed, since the ARC environment does not have it.

    Parameters
    ----------
    torch_version:
        ``torch.__version__``; any ``+local`` suffix is ignored.

    Returns a runnable ``pip install`` command when the CUDA index for this
    torch series is known, otherwise a description of the constraint.
    """
    import importlib.util

    base = torch_version.split("+", 1)[0]
    parts = _parse_version(base)
    if len(parts) < 3 or parts[0] != 2:
        return ("reinstall torch and torchaudio together, at matching "
                "versions, from the CUDA wheel index at " + _PYTORCH_INDEX)
    major, minor, patch = parts[:3]
    pins = [f"torch=={major}.{minor}.{patch}",
            f"torchaudio=={major}.{minor}.{patch}"]
    try:
        has_vision = importlib.util.find_spec("torchvision") is not None
    except (ImportError, ValueError):
        has_vision = False
    if has_vision:
        pins.append(f"torchvision==0.{minor + 15}.{patch}")
    index = _CUDA_INDEX_BY_MINOR.get((major, minor))
    if index is None:
        return (f"reinstall {', '.join(pins)} together from the CUDA wheel "
                f"index under {_PYTORCH_INDEX} that publishes torch {base}")
    return (f"reinstall with CUDA wheels: pip install --force-reinstall "
            f"{' '.join(pins)} --index-url {_PYTORCH_INDEX}{index}")


def check_torch(gpu_required: bool = False) -> CheckResult:
    """torch and CUDA: the check the GPU job scripts exist to make early.

    A missing GPU is a WARN on a login node or laptop, where it is
    expected, and a FAIL when the caller declares it is about to spend GPU
    time, where discovering it after a queue wait is the failure mode this
    module exists to prevent.
    """
    try:
        import torch
    except ImportError:
        return CheckResult("torch", FAIL, "not importable",
                           "pip install torch  (transcription cannot run)")
    except Exception as exc:
        # A CUDA build can fail to import with OSError when a shared
        # library will not load, which is a different problem from the
        # package being absent and needs saying so.
        return CheckResult("torch", FAIL, f"import raised {type(exc).__name__}: {exc}",
                           "the installed torch cannot load on this node; "
                           "reinstall, or run on a node with the libraries "
                           "it links against")
    detail = torch.__version__
    try:
        available = torch.cuda.is_available()
    except Exception as exc:
        return CheckResult("torch", FAIL, f"{detail}; CUDA probe raised: {exc}",
                           cuda_reinstall_remedy(detail))
    if available:
        try:
            name = torch.cuda.get_device_name(0)
            memory_gb = (torch.cuda.get_device_properties(0).total_memory
                         / (1 << 30))
            detail += f"; CUDA {torch.version.cuda}; {name} ({memory_gb:.0f} GB)"
        except Exception:
            detail += f"; CUDA {torch.version.cuda}"
        return CheckResult("torch", OK, detail)
    if gpu_required:
        # A CUDA build that sees no device is a node or allocation problem,
        # and reinstalling torch cannot fix it; only a CPU-only build needs
        # the reinstall. Telling the two apart keeps a job log from sending
        # someone to modify a working environment (CORE-21).
        cuda_build = getattr(getattr(torch, "version", None), "cuda", None)
        if cuda_build:
            return CheckResult(
                "torch", FAIL,
                f"{detail}; CUDA {cuda_build} build, but no CUDA device is visible",
                "the torch build is not the problem: check that the job asked "
                "for a GPU (--gres=gpu:1), that CUDA_VISIBLE_DEVICES is not "
                "empty and that nvidia-smi works on the node; do not "
                "reinstall torch")
        return CheckResult(
            "torch", FAIL, f"{detail}; CPU-only build, CUDA not available",
            "on the cluster: the environment's torch lacks CUDA wheels; "
            + cuda_reinstall_remedy(detail)
            + " (from a login node, never from inside a job); locally: run "
            "without --gpu-required")
    return CheckResult("torch", WARN, f"{detail}; CUDA not available",
                       "fine on a login node or laptop; GPU jobs must FAIL "
                       "this, so they pass --gpu-required")


def check_transformers() -> CheckResult:
    """transformers: import, version floor, and the return_language trap."""
    try:
        import transformers
    except ImportError:
        floor = ".".join(str(part) for part in _TRANSFORMERS_FLOOR)
        return CheckResult("transformers", FAIL, "not importable",
                           f"pip install 'transformers[torch]>={floor}.0'")
    except Exception as exc:
        return CheckResult("transformers", FAIL,
                           f"import raised {type(exc).__name__}: {exc}",
                           "the installed transformers cannot load here; "
                           "reinstall it, or run on a node where its "
                           "dependencies (usually torch) can load")
    raw = transformers.__version__
    version = _parse_version(raw)
    if version < _TRANSFORMERS_FLOOR:
        floor = ".".join(str(part) for part in _TRANSFORMERS_FLOOR)
        return CheckResult(
            "transformers", FAIL, raw,
            f"the workflow needs transformers {floor} or newer (the language "
            "gate's detect_language, and pipeline(dtype=) in the timestamp "
            f"benchmark): pip install 'transformers>={floor}'")
    low, high = _RETURN_LANGUAGE_BROKEN
    detail = raw
    if low <= version < high:
        detail += ("; pipeline return_language is empty on this version "
                   "(workflow unaffected: it uses detect_language)")
    return CheckResult("transformers", OK, detail)


_TOKEN_ENV_VARS = ("HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGING_FACE_HUB_TOKEN")


def _hf_home() -> Path | None:
    """Return the HuggingFace home directory as huggingface_hub computes it.

    ``$HF_HOME``, else ``$XDG_CACHE_HOME/huggingface``, else
    ``~/.cache/huggingface``. ``None`` when no home directory resolves.
    """
    if (os.environ.get("HF_HOME") or "").strip():
        return Path(os.environ["HF_HOME"]).expanduser()
    if (os.environ.get("XDG_CACHE_HOME") or "").strip():
        return Path(os.environ["XDG_CACHE_HOME"]).expanduser() / "huggingface"
    try:
        return Path.home() / ".cache" / "huggingface"
    except (OSError, RuntimeError):
        return None


def _token_file_candidates() -> list[tuple[Path, str]]:
    """Token files in lookup order, each with the label reported for it."""
    candidates = [(_REPO_ROOT / "hf_token.txt", str(_REPO_ROOT / "hf_token.txt"))]
    # The current directory is still consulted, after the repository root,
    # because transcription.py reads a cwd-relative hf_token.txt; dropping it
    # here would let preflight and the pipeline disagree.
    cwd_file = Path("hf_token.txt")
    try:
        if cwd_file.resolve() != candidates[0][0]:
            candidates.append((cwd_file, str(cwd_file)))
    except OSError:
        pass
    if (os.environ.get("HF_TOKEN_PATH") or "").strip():
        p = Path(os.environ["HF_TOKEN_PATH"]).expanduser()
        candidates.append((p, str(p)))
    home = _hf_home()
    if home is not None:
        candidates.append((home / "token", str(home / "token")))
    try:
        legacy = Path.home() / ".huggingface" / "token"
        candidates.append((legacy, str(legacy)))
    except (OSError, RuntimeError):
        pass
    return candidates


def _read_token_file(path: Path) -> str:
    """Return the text of a token file, without a byte-order mark or blanks.

    A token saved by a Windows editor can begin with a byte-order mark.
    UTF-8's, read as UTF-8, is the character U+FEFF, which ``str.strip``
    keeps because it is not whitespace, so it was returned as part of the
    token. UTF-16's made the UTF-8 decode fail, and the file was skipped as
    if it held no token. A file that starts with a UTF-16 mark is decoded as
    UTF-16, and any other as UTF-8 with a leading mark dropped. Raises
    ``UnicodeDecodeError`` for a file that is neither.
    """
    raw = path.read_bytes()
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        text = raw.decode("utf-16")
    else:
        text = raw.decode("utf-8-sig")
    return text.lstrip("﻿").strip()


def resolve_hf_token() -> tuple[str | None, str | None]:
    """Return ``(token, source)`` for the HuggingFace token, or ``(None, None)``.

    This is the single token lookup the workflow's components should share
    (audit findings CORE-13, XREF-04); seven modules previously carried
    their own copy, each with a different source list. The order is:

    1. the ``HF_TOKEN``, ``HUGGINGFACE_TOKEN`` and ``HUGGING_FACE_HUB_TOKEN``
       environment variables;
    2. ``hf_token.txt`` at the repository root, located from this file and
       not from the current directory, then ``./hf_token.txt``;
    3. ``$HF_TOKEN_PATH``, then ``<HF_HOME>/token``, which is where
       ``huggingface-cli login`` and setup/cache_pyannote_arc.py store it
       (CORE-11), then the legacy ``~/.huggingface/token``.

    Step 3 mirrors ``huggingface_hub.get_token()``'s file lookup instead of
    calling it, because the hub fixes its paths when it is first imported
    and cannot then be pointed at a different HF_HOME. Reading the same
    locations gives the same answer and keeps the lookup testable.

    No side effects: nothing is written, printed or exported. The token is
    never logged; ``source`` names only where it came from.
    """
    for variable in _TOKEN_ENV_VARS:
        value = (os.environ.get(variable) or "").strip()
        if value:
            return value, f"{variable} environment variable"
    for path, label in _token_file_candidates():
        try:
            if path.is_file():
                value = _read_token_file(path)
                if value:
                    return value, label
        except (OSError, UnicodeDecodeError):
            continue
    return None, None


def _find_hf_token() -> str | None:
    """Return where a HuggingFace token was found, or ``None``.

    Kept for existing callers; see :func:`resolve_hf_token`.
    """
    return resolve_hf_token()[1]


def pyannote_cache_dir() -> Path | None:
    """Return the directory pyannote.audio 3.x loads pretrained weights from.

    pyannote.audio 3.x does not use the HuggingFace hub cache
    (``<HF_HOME>/hub``). ``Pipeline.from_pretrained`` and
    ``Model.from_pretrained`` default ``cache_dir`` to
    ``pyannote.audio.core.model.CACHE_DIR``, which is ``$PYANNOTE_CACHE`` or
    ``~/.cache/torch/pyannote``, and hand it to ``hf_hub_download``; nothing
    in this repository passes another ``cache_dir`` (audit finding CORE-R3).
    requirements.txt caps pyannote.audio below 4.

    The constant is read from an already imported pyannote module when there
    is one, since that is the value from_pretrained will use; otherwise the
    same rule is applied to the environment. Nothing is imported here.

    Returns ``None`` when no home directory resolves.
    """
    model_module = sys.modules.get("pyannote.audio.core.model")
    configured = getattr(model_module, "CACHE_DIR", None)
    if configured:
        return Path(configured).expanduser()
    if (os.environ.get("PYANNOTE_CACHE") or "").strip():
        return Path(os.environ["PYANNOTE_CACHE"]).expanduser()
    try:
        return Path.home() / ".cache" / "torch" / "pyannote"
    except (OSError, RuntimeError):
        return None


def _repo_folder(repo: str) -> str:
    """The directory ``hf_hub_download`` keeps *repo* in, inside a cache."""
    return "models--" + repo.replace("/", "--")


def _hf_hub_cache() -> Path | None:
    """Return the Hugging Face hub cache as huggingface_hub computes it.

    ``$HF_HUB_CACHE``, else the older ``$HUGGINGFACE_HUB_CACHE``, else
    ``<HF_HOME>/hub``; ``None`` when no home directory resolves. pyannote
    3.x does not load from it, but an earlier setup/cache_pyannote_arc.py
    downloaded there (REV-01), so it may hold an intact copy of a file
    damaged in pyannote's own cache.
    """
    for variable in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
        if (os.environ.get(variable) or "").strip():
            return Path(os.environ[variable]).expanduser()
    home = _hf_home()
    return home / "hub" if home is not None else None


def _git_blob_id(data: bytes) -> str:
    """Return the id ``git hash-object`` prints for a file holding *data*."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data,
                        usedforsecurity=False).hexdigest()


def _blob_digest(blob: Path) -> tuple[str, str] | None:
    """Return ``(command, digest)`` for the cache blob *blob*, or ``None``.

    ``hf_hub_download`` names a blob after the file's ETag (huggingface_hub
    0.35.3): the git blob id, 40 hex digits, for a file kept in git, and
    the SHA-256 of the content, 64, for one kept in LFS. *digest* is the
    one the name should equal and *command* the program that prints it
    (``git hash-object`` or ``sha256sum``). Any other name, such as the
    ``.incomplete`` file an interrupted download leaves, gives ``None``.
    The file is read in blocks, since an LFS blob can be large. Raises
    OSError when it cannot be read.
    """
    if _GIT_BLOB_ID.fullmatch(blob.name):
        command, digest = "git hash-object", hashlib.sha1(usedforsecurity=False)
    elif _LFS_BLOB_ID.fullmatch(blob.name):
        command, digest = "sha256sum", hashlib.sha256()
    else:
        return None
    with open(blob, "rb") as handle:
        if command == "git hash-object":
            digest.update(b"blob %d\0" % os.fstat(handle.fileno()).st_size)
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return command, digest.hexdigest()


def _differs_from_name(command: str, actual: str, name: str) -> str:
    """The phrase for a cached file whose content no longer hashes to its blob's name."""
    return (f"differs from the file the Hub served ({command} gives {actual[:8]}, "
            f"not the blob's name {name[:8]})")


def _linked_blob(path: Path) -> Path | None:
    """The cache blob *path* is a symlink to, or ``None`` if it is not one.

    ``hf_hub_download`` stores each file once under ``blobs/`` and links
    the snapshot's copy to it, except where symlinks are unavailable
    (Windows without the privilege), where the snapshot holds the file.
    """
    try:
        if not path.is_symlink():
            return None
        target = path.resolve()
    except (OSError, RuntimeError):
        return None
    return target if target.parent.name == "blobs" else None


def _pipeline_name_without_yaml(text: str) -> str | None:
    """Return ``pipeline.name`` from a config's text, without a YAML parser.

    Reads only the block layout pyannote's own configs use: a top-level
    ``pipeline:`` line, then ``name:`` among the keys at the first
    indentation under it. Anything else gives ``None``, so a config this
    cannot read is reported as damaged instead of passing unread. Only used
    when PyYAML is missing, which pyannote.audio itself requires.
    """
    in_pipeline = False
    child_indent = None
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.lstrip(" ")
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(stripped)
        if indent == 0:
            in_pipeline = stripped.split(" #", 1)[0].rstrip() == "pipeline:"
            child_indent = None
            continue
        if not in_pipeline:
            continue
        if child_indent is None:
            child_indent = indent
        if indent != child_indent:
            continue
        key, sep, value = stripped.partition(":")
        if sep and key.strip().strip("\"'") == "name":
            value = value.split(" #", 1)[0].strip().strip("\"'")
            return value or None
    return None


def _load_problem(text: str) -> str | None:
    """Say why ``Pipeline.from_pretrained`` could not load a config with *text*.

    pyannote.audio 3.x parses the config with ``yaml.SafeLoader`` and then
    reads ``config["pipeline"]["name"]`` to choose the pipeline class
    (core/pipeline.py in 3.4.0). PyYAML does the parsing here too when it
    is importable; otherwise :func:`_pipeline_name_without_yaml` looks for
    the name. Returns ``None`` when the config would load.
    """
    try:
        import yaml
    except ImportError:
        if _pipeline_name_without_yaml(text):
            return None
        return "has no pipeline.name, so Pipeline.from_pretrained cannot load it"
    try:
        config = yaml.safe_load(text)
    except Exception as exc:
        # Whatever stops the parser stops pyannote's load too. PyYAML's
        # own errors carry the problem and its position; anything else is
        # reported as it prints.
        mark = getattr(exc, "problem_mark", None)
        where = f" at line {mark.line + 1}" if mark is not None else ""
        reason = getattr(exc, "problem", None) or " ".join(str(exc).split())[:160]
        return f"does not parse as YAML ({reason}{where})"
    if not isinstance(config, dict):
        return "is not a YAML mapping, so Pipeline.from_pretrained cannot load it"
    pipeline = config.get("pipeline")
    if not isinstance(pipeline, dict):
        return "has no pipeline mapping, so Pipeline.from_pretrained cannot load it"
    name = pipeline.get("name")
    if isinstance(name, str) and name.strip():
        return None
    # The incident's stub lacked the key, which is what fails with KeyError.
    symptom = " (KeyError: 'name')" if "name" not in pipeline else ""
    return "has no pipeline.name, so Pipeline.from_pretrained cannot load it" + symptom


def _config_problem(data: bytes, blob_name: str | None = None) -> str | None:
    """Say what is wrong with this cached pipeline config, if anything.

    A config that does not parse, or parses without ``pipeline.name``,
    fails every load (:func:`_load_problem`); the stub that the test suite
    wrote over the cached config on ARC, in jobs 8913985 and 8917186, made
    each one fail with KeyError: 'name' (NEW-INC-01). A config whose
    content no longer matches the blob it was downloaded as is damaged
    too, although it may still load, with parameters nobody chose.

    Parameters
    ----------
    data:
        The bytes of a cached ``config.yaml``.
    blob_name:
        The cache blob the bytes were read from, when the snapshot's file
        links to one. The cache names that blob after the file's git blob
        id, so content that no longer hashes to the name was changed after
        the download, even when it still parses.

    Returns ``None`` when the config would load unchanged, else the
    problems as one phrase, to follow the file's path in a report.
    """
    problems = []
    try:
        problem = _load_problem(data.decode("utf-8"))
    except UnicodeDecodeError:
        problem = "is not UTF-8 text, so Pipeline.from_pretrained cannot load it"
    if problem:
        problems.append(problem)
    if blob_name and _GIT_BLOB_ID.fullmatch(blob_name):
        actual = _git_blob_id(data)
        if actual != blob_name:
            problems.append(_differs_from_name("git hash-object", actual, blob_name))
    return ", and ".join(problems) or None


def pipeline_config_problem(path: Path) -> str | None:
    """Say what is wrong with the cached pipeline config at *path*, if anything.

    Returns ``None`` when it is intact; see :func:`_config_problem`.
    """
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        return f"cannot be read ({exc.strerror or exc})"
    blob = _linked_blob(Path(path))
    return _config_problem(data, blob.name if blob is not None else None)


def _pipeline_config_files(cache: Path) -> list[Path]:
    """The ``config.yaml`` of every snapshot of the pipeline in *cache*.

    A snapshot without one is what an interrupted download leaves
    (``hf_hub_download`` creates the snapshot directory before it fetches
    the file), and a link to a missing blob is what deleting the blob
    leaves. A later download completes either, so neither is returned:
    such a snapshot is not damaged, though it does not count as cached.
    """
    snapshots = cache / _repo_folder(_PIPELINE_REPO) / "snapshots"
    try:
        configs = sorted(snapshot / "config.yaml" for snapshot in snapshots.iterdir())
    except OSError:
        return []
    return [config for config in configs if config.is_file()]


def _pipeline_blobs(cache: Path) -> list[Path]:
    """Every file in the ``blobs`` directory of the pipeline in *cache*."""
    blobs = cache / _repo_folder(_PIPELINE_REPO) / "blobs"
    try:
        return sorted(blob for blob in blobs.iterdir() if blob.is_file())
    except OSError:
        return []


def _resolved(path: Path) -> Path:
    """*path* with every link followed, or as given when that fails."""
    try:
        return path.resolve()
    except (OSError, RuntimeError):
        return path


def _blob_problem(blob: Path) -> str | None:
    """Say how the cache blob *blob* differs from its name, if it does.

    A blob whose content no longer hashes to its name (:func:`_blob_digest`)
    was changed after the download. ``None`` when it matches, or when its
    name is not a digest.
    """
    try:
        found = _blob_digest(blob)
    except OSError as exc:
        return f"cannot be read ({exc.strerror or exc})"
    if found is None or found[1] == blob.name:
        return None
    return _differs_from_name(found[0], found[1], blob.name)


def damaged_pipeline_configs(cache: Path | None = None) -> list[tuple[Path, str]]:
    """Return ``(path, problem)`` for each damaged file in the pipeline's cache.

    These are the damaged cached pipeline configs, those that cannot load
    or no longer match the blob they were downloaded as
    (:func:`_config_problem`), and then every other blob of the pipeline
    whose content no longer hashes to its name (:func:`_blob_problem`).
    Every snapshot of pyannote/speaker-diarization-3.1 in *cache*
    (:func:`pyannote_cache_dir` by default) is checked: the loaders ask for
    the pinned revision, a download for ``main`` can leave another, and a
    damaged blob is shared by every snapshot that links to it. A token does
    not repair one, because ``hf_hub_download`` returns a file already in
    the cache without fetching it again (huggingface_hub 0.35.3), so every
    load fails until the file is replaced (NEW-INC-01).

    The blobs are checked whether or not a snapshot links to them, because
    a download links a blob the cache already holds instead of fetching
    the file. Deleting a damaged config's link but not its blob leaves no
    config to check. Before the blobs were checked, the pipeline then
    counted as not cached, a job with a token passed, and the next download
    linked the damaged blob again. A blob a damaged config links to is
    reported once, with the config.

    Empty when nothing cached is damaged, including when nothing is cached.
    No side effects: files are only read.
    """
    if cache is None:
        cache = pyannote_cache_dir()
    if cache is None:
        return []
    damaged = []
    reported = set()
    for config in _pipeline_config_files(cache):
        problem = pipeline_config_problem(config)
        if problem:
            damaged.append((config, problem))
            blob = _linked_blob(config)
            if blob is not None:
                reported.add(blob)
    for blob in _pipeline_blobs(cache):
        if _resolved(blob) in reported:
            continue
        problem = _blob_problem(blob)
        if problem:
            damaged.append((blob, problem + ", and a download keeps it, since it "
                                  "finds the blob already cached"))
    return damaged


def _is_cache_blob(path: Path) -> bool:
    """True for a file in a ``blobs`` directory itself, not a snapshot's link."""
    return path.parent.name == "blobs" and not path.is_symlink()


def pipeline_damage_heading(damaged: list[tuple[Path, str]]) -> str:
    """Name what :func:`damaged_pipeline_configs` found, to head its report.

    A blob no config links to may hold any file of the repository, so with
    one among *damaged* the heading names the pipeline's cache, not its
    config.
    """
    if any(_is_cache_blob(path) for path, _problem in damaged):
        return "the pipeline's cache is damaged"
    return "the cached pipeline config is damaged"


def _intact_hub_copy(blob_name: str) -> Path | None:
    """A copy of the pipeline's blob *blob_name* in the hub cache, if intact.

    Intact means its content still hashes to its name, the check the
    remedy asks for with ``git hash-object`` (or ``sha256sum`` for an LFS
    blob, :func:`_blob_digest`).
    """
    hub = _hf_hub_cache()
    if hub is None:
        return None
    copy = hub / _repo_folder(_PIPELINE_REPO) / "blobs" / blob_name
    try:
        found = _blob_digest(copy)
    except OSError:
        return None
    return copy if found is not None and found[1] == blob_name else None


def _restore_from_hub(blob: Path) -> str:
    """The offline alternative to deleting the damaged cache blob *blob*.

    Names an intact copy of the same name in the hub cache when there is
    one; otherwise says where it would be and how to check it first.
    """
    command = "sha256sum" if _LFS_BLOB_ID.fullmatch(blob.name) else "git hash-object"
    copy = _intact_hub_copy(blob.name)
    if copy is not None:
        return (f"Or copy {copy} over {blob}: that copy in the Hugging Face hub "
                f"cache still matches its name under {command}")
    hub = _hf_hub_cache()
    where = (f" ({hub / _repo_folder(_PIPELINE_REPO) / 'blobs' / blob.name})"
             if hub is not None else "")
    return (f"Or restore {blob} from the Hugging Face hub cache blob of the same "
            f"name{where}, after checking that {command} on that copy prints "
            f"{blob.name}")


def _intact_hub_snapshot_copy(config: Path) -> Path | None:
    """The hub cache's copy of *config*, from the same commit, if verifiably intact.

    A damaged config that is a file of its own (a cache written where
    symlinks are unavailable, or copied without them) has no blob name to
    check a replacement against. The hub cache's snapshot of the same
    commit qualifies when its config.yaml links to a blob whose content
    still hashes to the blob's name; a copy that cannot be checked that way
    is not offered.
    """
    hub = _hf_hub_cache()
    if hub is None:
        return None
    copy = (hub / _repo_folder(_PIPELINE_REPO) / "snapshots" / config.parent.name
            / config.name)
    blob = _linked_blob(copy)
    if blob is None or not _GIT_BLOB_ID.fullmatch(blob.name):
        return None
    try:
        data = copy.read_bytes()
    except OSError:
        return None
    return copy if _config_problem(data, blob.name) is None else None


def pipeline_config_remedy(damaged: list[tuple[Path, str]]) -> str:
    """Say how to replace each file :func:`damaged_pipeline_configs` found.

    A new download skips a file the cache already holds, so the damaged
    file is deleted first: a config's blob as well as the snapshot's link
    to it, and a blob no config links to on its own. Restoring it from an
    intact copy in the hub cache is the offline alternative.
    """
    download = ("then fetch it again with python setup/cache_pyannote_arc.py "
                "where there is network access (on ARC, a login node)")
    fixes = []
    for path, _problem in damaged:
        if _is_cache_blob(path):
            fixes.append(f"delete {path}, {download}; until it is deleted, a "
                         "download links this blob instead of fetching the file. "
                         f"{_restore_from_hub(path)}")
            continue
        blob = _linked_blob(path)
        if blob is None:
            fix = f"delete {path}, {download}"
            copy = _intact_hub_snapshot_copy(path)
            if copy is not None:
                fix += (f". Or copy {copy} over {path}: that copy in the Hugging "
                        "Face hub cache, from the same commit, links to a blob "
                        "that still matches its name under git hash-object")
            fixes.append(fix)
            continue
        fixes.append(f"delete {blob} and the link {path} to it, {download}; a "
                     "download skips a file already in the cache, so it cannot "
                     f"replace the damaged one in place. {_restore_from_hub(blob)}")
    return ". Also: ".join(fixes)


def pyannote_pipeline_cached() -> bool:
    """True when every repo in PYANNOTE_PIPELINE_REPOS has a cached snapshot.

    Used to downgrade a missing token to a warning: a fully cached gated
    model loads without one. The snapshots are looked for in
    :func:`pyannote_cache_dir`, in the ``models--<org>--<name>/snapshots``
    layout ``hf_hub_download`` writes there. An earlier version looked in
    the hub cache, which pyannote 3.x never reads, so a
    ``--diarisation-required`` job without a token could pass this check
    and then fail inside its GPU allocation (CORE-R3). The pipeline counts
    as cached only when a snapshot holds a config.yaml pyannote can load
    and nothing in the pipeline's cache is damaged
    (:func:`damaged_pipeline_configs`).
    """
    cache = pyannote_cache_dir()
    if cache is None:
        return False
    for repo in PYANNOTE_PIPELINE_REPOS:
        snapshots = cache / _repo_folder(repo) / "snapshots"
        try:
            if not any(snapshots.iterdir()):
                return False
        except OSError:
            return False
    return bool(_pipeline_config_files(cache)) and not damaged_pipeline_configs(cache)


def check_diarisation(diarisation_required: bool = False) -> CheckResult:
    """pyannote, its cached pipeline config, and the token its gated model needs.

    The import is genuinely attempted rather than probed with ``find_spec``,
    because an installed-but-unimportable pyannote (a torch mismatch is the
    usual cause) would otherwise be affirmed here and then silently skipped
    at runtime. When *diarisation_required* is set, a job that exists to
    demonstrate speaker attribution escalates the degraded outcomes to
    failures rather than running without its own point.

    A damaged cached pipeline config.yaml is one of those outcomes, whether
    or not a token is found, and so is a damaged blob of the pipeline that
    no config links to (:func:`damaged_pipeline_configs`). On ARC the test
    suite wrote a stub over the cached config (jobs 8913985 and 8917186,
    NEW-INC-01). This check, which then never read the cache when a token
    was found, returned OK, and the four workflow jobs that loaded the
    pipeline before the blob was restored either failed with KeyError:
    'name' (the case study) or fell back to loading the pipeline's
    embedding model directly (the anonymisation benchmark).
    """
    degraded = FAIL if diarisation_required else WARN
    try:
        import pyannote.audio  # noqa: F401
    except ImportError:
        return CheckResult(
            "diarisation", degraded, "pyannote.audio not installed",
            "pip install pyannote.audio  (transcription works without it; "
            "there is just no speaker attribution)")
    except Exception as exc:
        return CheckResult(
            "diarisation", degraded,
            f"pyannote.audio installed but not importable: "
            f"{type(exc).__name__}: {exc}",
            "reinstall pyannote.audio against the installed torch")
    damaged = damaged_pipeline_configs()
    if damaged:
        return CheckResult(
            "diarisation", degraded,
            f"pyannote.audio importable, but {pipeline_damage_heading(damaged)}: "
            + "; ".join(f"{path} {problem}" for path, problem in damaged),
            pipeline_config_remedy(damaged))
    token = _find_hf_token()
    if token is None:
        # A fully cached pipeline loads without a token, as the remedy says,
        # so failing a --diarisation-required job here would abort a run that
        # works (CORE-11).
        cached = pyannote_pipeline_cached()
        return CheckResult(
            "diarisation", WARN if cached else degraded,
            "pyannote.audio importable; no HuggingFace token found"
            + ("; pipeline weights are cached" if cached else ""),
            "the gated model downloads only with a token (hf_token.txt in "
            "the repository root, HF_TOKEN, or <HF_HOME>/token); an "
            "already-cached model still works")
    return CheckResult("diarisation", OK,
                       f"pyannote.audio importable; token: {token}")


def check_optional() -> list[CheckResult]:
    """Optional dependencies that degrade specific features when absent."""
    import importlib.util
    wanted = (
        ("librosa", "librosa", "higher-quality resampling",
         "pip install librosa"),
        ("word documents", "docx", ".docx output",
         "pip install python-docx"),
        ("evaluation", "jiwer", "WER scoring",
         "pip install jiwer datasets"),
    )
    results = []
    for name, module, feature, remedy in wanted:
        if importlib.util.find_spec(module) is not None:
            results.append(CheckResult(name, OK, f"{module} importable"))
        else:
            results.append(CheckResult(
                name, WARN, f"{module} not installed; no {feature}", remedy))
    return results


# The packages whose build decides the numbers: a copy of any of them loaded
# from outside the environment changes what a job computes while the
# environment's own metadata still reports the expected version.
_ISOLATED_PACKAGES = ("torch", "transformers", "pyannote.audio")


def _module_origin(name: str) -> str | None:
    """Return the file *name* is (or would be) imported from, or ``None``.

    An already imported module answers from its ``__file__``; otherwise the
    import system is asked with ``find_spec``, which locates the package
    without running it. ``None`` when the package is absent or its origin
    cannot be determined (a stand-in object in ``sys.modules``, say).
    """
    import importlib.util

    module = sys.modules.get(name)
    origin = getattr(module, "__file__", None) if module is not None else None
    if origin:
        return str(origin)
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError, AttributeError):
        return None
    return spec.origin if spec is not None and spec.origin else None


def _within(path: str, root: str) -> bool:
    """True when *path* lies inside directory *root* (symlinks resolved)."""
    try:
        return Path(path).resolve().is_relative_to(Path(root).resolve())
    except (OSError, ValueError):
        return False


def _activated_environment() -> bool:
    """True when the caller activated the environment this Python runs in.

    ``activate_project_env_arc.sh`` and venv's ``activate`` both set
    ``VIRTUAL_ENV`` to the environment root, which is ``sys.prefix``; conda
    sets ``CONDA_PREFIX``. A bare interpreter on a laptop sets neither.
    """
    for variable in ("VIRTUAL_ENV", "CONDA_PREFIX"):
        value = (os.environ.get(variable) or "").strip()
        if value and _within(value, sys.prefix) and _within(sys.prefix, value):
            return True
    return False


def check_isolation() -> CheckResult:
    """torch, transformers and pyannote must come from the environment itself.

    On ARC the account's ``~/.local`` user site holds torch 2.8.0+cpu and
    transformers 4.56.2; whenever the user site is on, those shadow the job
    environment's 2.5.1+cu121 and 4.57.1 while ``pip freeze`` of the
    environment still lists the right versions (audit finding DEPS-02).
    ``activate_project_env_arc.sh`` now sets ``PYTHONNOUSERSITE=1``; this
    check catches any other route to the same mix-up.

    A package outside ``sys.prefix`` is a FAIL when an environment has been
    activated (``VIRTUAL_ENV`` or ``CONDA_PREFIX`` names ``sys.prefix``),
    because the caller then expects that environment to supply it, and a
    WARN otherwise: a laptop's interpreter can legitimately use its user
    site. Absent packages are left to the checks that own them.
    """
    stray = []
    for name in _ISOLATED_PACKAGES:
        origin = _module_origin(name)
        if origin and not _within(origin, sys.prefix):
            stray.append(f"{name} from {origin}")
    if not stray:
        return CheckResult("isolation", OK,
                           f"torch, transformers, pyannote load from {sys.prefix}")
    status = FAIL if _activated_environment() else WARN
    return CheckResult(
        "isolation", status,
        f"outside {sys.prefix}: " + "; ".join(stray),
        "another copy shadows the environment's own, usually the user site "
        "(~/.local): export PYTHONNOUSERSITE=1, which "
        "activate_project_env_arc.sh sets, or remove that copy")


def _read_lock(lock_path: Path) -> tuple[dict[str, str], list[str]]:
    """Parse a ``pip freeze`` file into ``{name: version}`` and skipped lines.

    Only ``name==version`` entries are pins; comments and blank lines are
    ignored, and anything else (a URL requirement, an editable install) is
    returned in the second list so the caller can say it was not checked.
    """
    pins: dict[str, str] = {}
    skipped: list[str] = []
    for raw in lock_path.read_text(encoding="utf-8").splitlines():
        entry = raw.split("#", 1)[0].split(";", 1)[0].strip()
        if not entry:
            continue
        name, sep, version = entry.partition("==")
        if sep and name.strip() and version.strip():
            pins[name.strip()] = version.strip()
        else:
            skipped.append(entry)
    return pins, skipped


def check_lock(lock_path: Path) -> CheckResult:
    """Every pin in *lock_path* must be installed at exactly that version.

    Used by ``hpc/run_tests.sh``, which used to ``pip install`` whatever was
    missing into the shared results environment (audit findings TESTS-02,
    SHELL-06). A test run against a drifted environment now stops and says
    which versions differ, and the environment stays as it is.

    Parameters
    ----------
    lock_path:
        A ``pip freeze`` file, normally ``requirements-lock.txt``.

    Returns a FAIL listing the first mismatches when any pin differs or is
    missing, or when the file cannot be read or holds no pins.
    """
    from importlib import metadata

    try:
        pins, skipped = _read_lock(lock_path)
    except (OSError, UnicodeDecodeError) as exc:
        return CheckResult("lock", FAIL, f"cannot read {lock_path}: {exc}",
                           "pass the path of requirements-lock.txt")
    if not pins:
        return CheckResult("lock", FAIL, f"no name==version pins in {lock_path}",
                           "pass a pip freeze file such as requirements-lock.txt")
    mismatches = []
    for name, wanted in sorted(pins.items(), key=lambda item: item[0].lower()):
        try:
            installed = metadata.version(name)
        except metadata.PackageNotFoundError:
            installed = None
        if installed != wanted:
            mismatches.append(f"{name} {installed or 'missing'} (lock {wanted})")
    note = f"; {len(skipped)} non-pin line(s) not checked" if skipped else ""
    if mismatches:
        shown = "; ".join(mismatches[:8])
        more = f"; and {len(mismatches) - 8} more" if len(mismatches) > 8 else ""
        return CheckResult(
            "lock", FAIL,
            f"{len(mismatches)} of {len(pins)} pins differ: {shown}{more}{note}",
            "the environment has drifted from the lock. Rebuild it from a "
            "login node (pip install -r requirements-lock.txt "
            "--extra-index-url https://download.pytorch.org/whl/cu121), or "
            "take and commit a new lock on purpose; never install from a job")
    return CheckResult("lock", OK,
                       f"all {len(pins)} pins in {lock_path.name} match{note}")


def run_checks(gpu_required: bool = False,
               diarisation_required: bool = False,
               lock: Path | None = None) -> list[CheckResult]:
    """Run every check and return the results in report order.

    Parameters
    ----------
    gpu_required:
        Make a missing CUDA device a FAIL instead of a WARN.
    diarisation_required:
        Make a missing or unimportable pyannote, or a missing token, a FAIL.
    lock:
        When given, also compare every installed version with this
        ``pip freeze`` file (:func:`check_lock`).

    The never-crash contract is enforced structurally: a check that raises
    is itself converted into a FAIL naming the exception, because a doctor
    that dies mid-diagnosis is worse than none.
    """
    planned = [
        ("python", check_python),
        ("numpy", check_numpy),
        ("audio", check_audio),
        ("torch", lambda: check_torch(gpu_required=gpu_required)),
        ("transformers", check_transformers),
        ("diarisation",
         lambda: check_diarisation(diarisation_required=diarisation_required)),
        ("isolation", check_isolation),
    ]
    if lock is not None:
        planned.append(("lock", lambda: check_lock(lock)))
    results: list[CheckResult] = []
    for name, check in planned:
        try:
            results.append(check())
        except (Exception, SystemExit) as exc:
            # SystemExit is a BaseException, so `except Exception` let an
            # import-time exit escape and end the whole report (CORE-02).
            results.append(CheckResult(
                name, FAIL,
                f"the check itself crashed: {type(exc).__name__}: {exc}",
                "this is a preflight bug; the feature's real state is "
                "unknown, so treat it as broken and report the crash"))
    try:
        results.extend(check_optional())
    except (Exception, SystemExit) as exc:
        results.append(CheckResult(
            "optional", FAIL,
            f"the check itself crashed: {type(exc).__name__}: {exc}",
            "this is a preflight bug; report it"))
    return results


def print_report(results: list[CheckResult]) -> None:
    """Print one aligned line per check, remedies under their failures."""
    print("\nPreflight")
    for result in results:
        print(f"  [{result.status:^4}] {result.name:<14} {result.detail}")
        if result.remedy and result.status != OK:
            print(f"         {'':<14} fix: {result.remedy}")
    failures = sum(1 for result in results if result.status == FAIL)
    warnings = sum(1 for result in results if result.status == WARN)
    verdict = "NOT USABLE" if failures else "usable"
    print(f"  -> {verdict}: {failures} failure(s), {warnings} warning(s)")


def main(argv=None) -> int:
    """Run the preflight command line and return its exit code.

    Parameters
    ----------
    argv:
        Argument list, or ``None`` to read ``sys.argv``.

    Returns
    -------
    int
        1 when any check FAILs, else 0 (warnings alone exit 0). The HPC job
        scripts gate on this with ``python -m preflight ... || exit``.

    Side effects: reconfigures stdout to UTF-8, prints the report, and with
    ``--json`` writes the results to that path.
    """
    parser = argparse.ArgumentParser(
        prog="preflight",
        description="Check this environment can run the transcription "
                    "workflow, and say what to fix if it cannot.")
    parser.add_argument("--gpu-required", action="store_true",
                        dest="gpu_required",
                        help="treat a missing GPU as a failure rather than "
                             "a warning (job scripts pass this)")
    # Both spellings, as transcription.py accepts for its diarisation flags
    # (XREF-16).
    parser.add_argument("--diarisation-required", "--diarization-required",
                        action="store_true",
                        dest="diarisation_required",
                        help="treat missing or unimportable pyannote, or a "
                             "missing HuggingFace token, as a failure; for "
                             "jobs whose point is speaker attribution")
    parser.add_argument("--lock", type=Path, default=None, dest="lock",
                        help="also require every name==version pin in this "
                             "pip freeze file (requirements-lock.txt) to be "
                             "installed at exactly that version")
    parser.add_argument("--json", type=Path, default=None, dest="json_out",
                        help="also write the results to this path as JSON")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    results = run_checks(gpu_required=args.gpu_required,
                         diarisation_required=args.diarisation_required,
                         lock=args.lock)
    print_report(results)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps([asdict(result) for result in results], indent=2,
                       ensure_ascii=False),
            encoding="utf-8")
        print(f"  report: {args.json_out}")
    return 1 if any(result.status == FAIL for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
