#!/usr/bin/env python3
"""
Load audio of any common format, without the usual dependency archaeology.

Reading audio in Python fails in a way that wastes a great deal of time for
a reason that is never stated in the error. ``libsndfile``, which backs
``soundfile``, handles WAV, FLAC, OGG and MP3 but not AAC in an MP4
container, which is what ``.m4a`` is and what most podcasts and phone
recorders produce. ``librosa`` falls back to ``audioread``, which shells out
to an ``ffmpeg`` binary it looks for on ``PATH``. On a cluster there is
usually no system ffmpeg, so the fallback finds nothing and the caller sees
"Format not recognised", which names neither the missing decoder nor the
format that needed it.

The environment usually does have a working ffmpeg, because
``imageio_ffmpeg`` ships one, but it is installed under a versioned name
such as ``ffmpeg-linux-x86_64-v7.0.2`` and setting ``IMAGEIO_FFMPEG_EXE``
does not help: that variable is read by imageio, not by audioread, librosa
or pydub, which all want a binary called ``ffmpeg`` on the path.

This module resolves that once. :func:`ensure_ffmpeg_on_path` finds whatever
ffmpeg exists and makes it discoverable under the name the other libraries
expect, and :func:`load_audio` decodes through soundfile where it can and
through ffmpeg where it must, so a caller gets samples back without needing
to know which case applied.

Usage::

    from audio_io import load_audio
    samples, sample_rate = load_audio("interview.m4a", sr=16000)

    python -m audio_io                 # report what this environment can read
    python -m audio_io recording.m4a   # probe one file
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import numpy as np
except ImportError as exc:  # pragma: no cover - numpy is a core dependency
    # ImportError, not SystemExit: a library must not terminate its importer.
    # preflight imports this module to diagnose a broken environment and must
    # be able to report the failure instead of exiting (audit finding CORE-02).
    raise ImportError("numpy is required for audio_io.") from exc

try:
    import soundfile as _sf
    _HAS_SOUNDFILE = True
except ImportError:
    _HAS_SOUNDFILE = False

# Formats libsndfile decodes natively. Anything else needs ffmpeg.
_NATIVE_SUFFIXES = {".wav", ".flac", ".ogg", ".oga", ".aiff", ".aif", ".au", ".w64"}
_FFMPEG_TIMEOUT_S = 600
_cached_ffmpeg: str | None = None


def find_ffmpeg() -> str | None:
    """Return a path to a usable ffmpeg, or ``None``.

    A system ffmpeg is preferred because it is the one the user can also
    invoke themselves; the binary bundled with ``imageio_ffmpeg`` is the
    fallback, and is what makes this work on a cluster with no system
    install. The result is cached, since resolution touches the filesystem.
    """
    global _cached_ffmpeg
    if _cached_ffmpeg is not None:
        return _cached_ffmpeg or None

    found = shutil.which("ffmpeg")
    if not found:
        try:
            import imageio_ffmpeg
            candidate = imageio_ffmpeg.get_ffmpeg_exe()
            if candidate and Path(candidate).exists():
                found = candidate
        except Exception:
            found = None
    _cached_ffmpeg = found or ""
    return found


def ensure_ffmpeg_on_path() -> str | None:
    """Make ffmpeg discoverable to libraries that shell out to it.

    ``audioread``, ``librosa`` and ``pydub`` all invoke a binary named
    ``ffmpeg`` found on ``PATH``. A bundled binary carries a versioned name
    and so is invisible to them. This creates a small shim directory holding
    an ``ffmpeg`` that points at whatever was found, prepends it to ``PATH``,
    and also sets ``IMAGEIO_FFMPEG_EXE`` for anything that reads it.

    Returns the resolved ffmpeg path, or ``None`` when there is none to
    resolve. Safe to call repeatedly.

    Side effects: may create a per-user directory under the system temp
    directory (mode 0700 on POSIX) and prepends it to ``os.environ["PATH"]``;
    sets ``IMAGEIO_FFMPEG_EXE`` if unset.

    The shim directory is per user and per binary (audit findings CORE-23,
    TESTS-04). A single fixed ``/tmp`` directory could be pre-created by
    another user on a shared login node, who would then control an
    ``ffmpeg`` placed first on PATH; and a shim written once was never
    refreshed, so it kept pointing at a binary from another environment, or
    at one that had since been deleted.
    """
    exe = find_ffmpeg()
    if not exe:
        return None
    os.environ.setdefault("IMAGEIO_FFMPEG_EXE", exe)

    # Already reachable under the plain name: nothing to do.
    if shutil.which("ffmpeg"):
        return exe

    # On Windows, CreateProcess resolves a bare "ffmpeg" only to ffmpeg.exe
    # (a .bat is never found for a list argv), so when the binary already has
    # that name its own directory is the right thing to expose.
    if os.name == "nt" and Path(exe).name.lower() == "ffmpeg.exe":
        _prepend_path(Path(exe).parent)
        return exe

    try:
        shim_dir = _private_shim_dir(exe)
        if shim_dir is None:
            return exe
        if os.name == "nt":
            _write_windows_shim(shim_dir, exe)
        else:
            _write_posix_shim(shim_dir / "ffmpeg", exe)
        _prepend_path(shim_dir)
    except OSError:
        # A read-only or full temp directory is not fatal: decoding through
        # load_audio still works, only third-party fallbacks stay blind.
        pass
    return exe


def _prepend_path(directory: Path) -> None:
    """Put *directory* first on ``PATH`` (once)."""
    current = os.environ.get("PATH", "")
    entry = str(directory)
    if current.split(os.pathsep)[:1] != [entry]:
        os.environ["PATH"] = f"{entry}{os.pathsep}{current}"


def _private_shim_dir(exe: str) -> Path | None:
    """Return a shim directory only the current user can write, or ``None``.

    The directory name carries the user and a digest of *exe*, so two
    environments never share a shim. On POSIX it is created with mode 0700
    and rejected if another user owns it or it is group/world writable.
    """
    import hashlib

    user = str(os.getuid()) if hasattr(os, "getuid") else (
        os.environ.get("USERNAME") or os.environ.get("USER") or "user")
    tag = hashlib.sha1(exe.encode("utf-8")).hexdigest()[:12]
    parent = Path(tempfile.gettempdir()) / f"transcription_ffmpeg_shim-{user}"
    shim_dir = parent / tag
    for d in (parent, shim_dir):
        d.mkdir(mode=0o700, exist_ok=True)
        if hasattr(os, "getuid"):
            st = d.lstat()
            if d.is_symlink() or st.st_uid != os.getuid() or st.st_mode & 0o022:
                # Someone else controls this path: do not put it on PATH.
                return None
    return shim_dir


def _write_posix_shim(shim: Path, exe: str) -> None:
    """Point *shim* at *exe*, replacing a stale or dangling shim."""
    if shim.is_symlink():
        if os.readlink(shim) == exe:
            return
        shim.unlink()
    elif shim.exists():
        if shim.read_text(encoding="utf-8", errors="replace") == _posix_wrapper(exe):
            return
        shim.unlink()
    try:
        shim.symlink_to(exe)
    except OSError:
        # Filesystems without symlink support get a wrapper.
        shim.write_text(_posix_wrapper(exe), encoding="utf-8")
        shim.chmod(0o700)


def _posix_wrapper(exe: str) -> str:
    return f'#!/bin/sh\nexec "{exe}" "$@"\n'


def _write_windows_shim(shim_dir: Path, exe: str) -> None:
    """Expose *exe* as ``ffmpeg.exe`` in *shim_dir*, refreshing a stale one.

    A hard link is tried first because CreateProcess only resolves ``.exe``.
    When linking fails (for example across volumes), a ``.bat`` wrapper is
    written; that only helps callers that go through the shell.
    """
    shim = shim_dir / "ffmpeg.exe"
    if shim.exists():
        try:
            if os.path.samefile(shim, exe):
                return
        except OSError:
            pass
        shim.unlink()
    try:
        os.link(exe, shim)
        return
    except OSError:
        pass
    bat = shim_dir / "ffmpeg.bat"
    bat.write_text(f'@echo off\r\n"{exe}" %*\r\n', encoding="utf-8")


def _to_mono(data: np.ndarray) -> np.ndarray:
    """Average any channel dimension away."""
    if data.ndim > 1:
        return data.mean(axis=1)
    return data


def _resample(data: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    """Resample *data* from *src_sr* to *dst_sr*.

    Uses librosa when it is installed, since its filtering is better than
    linear interpolation, and falls back to interpolation otherwise so that
    the absence of librosa never blocks a transcription.

    Multichannel input is ``(frames, channels)``, as soundfile returns it,
    and is resampled along the frame axis, one channel at a time. The 1-D
    path is unchanged, so mono output is identical to before (CORE-06).
    """
    if src_sr == dst_sr:
        return data
    if data.ndim > 1:
        # librosa's default axis=-1 would resample the channel axis of a
        # (frames, channels) array, and np.interp needs 1-D input.
        return np.stack(
            [_resample(np.ascontiguousarray(data[:, c]), src_sr, dst_sr)
             for c in range(data.shape[1])], axis=1)
    try:
        import librosa
        return librosa.resample(data, orig_sr=src_sr, target_sr=dst_sr)
    except ImportError:
        n_out = int(round(len(data) * dst_sr / float(src_sr)))
        if n_out <= 0:
            return data.astype(np.float32)
        return np.interp(
            np.linspace(0, len(data) - 1, n_out),
            np.arange(len(data)),
            data,
        ).astype(np.float32)


def decode_with_ffmpeg(path, sr: int = 16000, mono: bool = True):
    """Decode *path* to float32 samples using ffmpeg, at *sr*.

    ffmpeg writes a WAV stream to stdout, which soundfile then reads, so no
    temporary file is involved and the resampling is done by ffmpeg itself.

    Raises
    ------
    RuntimeError
        If no ffmpeg is available, or if it fails on this input. The message
        names the format and the remedy rather than only the failure.
    """
    exe = find_ffmpeg()
    if not exe:
        raise RuntimeError(
            f"Cannot decode {Path(path).suffix or 'this file'}: no ffmpeg found. "
            "Install it with `pip install imageio-ffmpeg`, or convert the "
            "recording to WAV or FLAC first."
        )
    if not _HAS_SOUNDFILE:
        raise RuntimeError("soundfile is required to read decoded audio.")

    # With mono=False the source channel layout is kept; forcing "-ac 2"
    # upmixed mono files and dropped channels from surround ones (CORE-06).
    channel_args = ["-ac", "1"] if mono else []
    command = [exe, "-nostdin", "-loglevel", "error", "-i", str(path),
               *channel_args, "-ar", str(sr), "-f", "wav", "pipe:1"]
    try:
        completed = subprocess.run(
            command, capture_output=True, timeout=_FFMPEG_TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"ffmpeg failed on {path}: {exc}") from exc
    if completed.returncode != 0 or not completed.stdout:
        detail = (completed.stderr or b"").decode("utf-8", "replace").strip()
        raise RuntimeError(
            f"ffmpeg could not decode {path}: {detail[:300] or 'no output'}")

    data, native_sr = _sf.read(io.BytesIO(completed.stdout), dtype="float32",
                               always_2d=False)
    return (_to_mono(data) if mono else data), int(native_sr)


def load_audio(path, sr: int = 16000, mono: bool = True):
    """Return ``(samples, sample_rate)`` for *path*, whatever its format.

    soundfile is tried first because it is fast and needs no subprocess.
    When it cannot read the file, which is the usual outcome for ``.m4a``
    and other compressed formats, the file is decoded with ffmpeg instead.

    Parameters
    ----------
    path:
        The recording.
    sr:
        Target sample rate.
    mono:
        When true (the default, and what every pipeline caller uses) the
        result is 1-D. When false it is ``(frames, channels)`` for
        multichannel input and 1-D for mono input.

    Returns ``(samples, sr)`` with float32 samples.

    Raises
    ------
    FileNotFoundError
        If *path* is not a file.
    RuntimeError
        If neither soundfile nor ffmpeg can decode it. When soundfile failed
        first, its error is named in the message and chained, so a corrupt
        WAV is not reported only as a missing ffmpeg (CORE-07).
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Audio file not found: {path}")

    native_error: Exception | None = None
    if _HAS_SOUNDFILE:
        # Every suffix is tried natively: an unexpected suffix may still be
        # readable, and trying costs less than spawning ffmpeg. Only decode
        # failures fall through; an error raised while resampling is a real
        # fault and must not silently switch the waveform to ffmpeg's
        # resampler (CORE-07).
        try:
            data, native_sr = _sf.read(str(path), dtype="float32",
                                       always_2d=False)
        except (RuntimeError, OSError, ValueError) as exc:
            native_error = exc
        else:
            if mono:
                data = _to_mono(data)
            return _resample(data, int(native_sr), sr), sr
    try:
        return decode_with_ffmpeg(path, sr=sr, mono=mono)
    except RuntimeError as ffmpeg_error:
        if native_error is None:
            raise
        raise RuntimeError(
            f"Cannot decode {path}: soundfile failed ({native_error}); "
            f"ffmpeg fallback failed ({ffmpeg_error})") from native_error


def audio_support() -> dict:
    """Describe what this environment can decode, and how."""
    exe = find_ffmpeg()
    formats = []
    if _HAS_SOUNDFILE:
        try:
            formats = sorted(_sf.available_formats())
        except Exception:
            formats = []
    return {
        "soundfile": _HAS_SOUNDFILE,
        "soundfile_formats": formats,
        "ffmpeg": exe,
        "ffmpeg_source": ("system" if exe and shutil.which("ffmpeg") == exe
                          else ("bundled" if exe else None)),
        "compressed_formats_readable": bool(exe),
    }


def main(argv=None) -> int:
    """Report decoding support, and optionally probe one file."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    ensure_ffmpeg_on_path()
    info = audio_support()
    print("\nAudio decoding support")
    print(f"  soundfile:  {'yes' if info['soundfile'] else 'NO'}")
    print(f"  ffmpeg:     {info['ffmpeg'] or 'NOT FOUND'}"
          f"{'  (' + info['ffmpeg_source'] + ')' if info['ffmpeg_source'] else ''}")
    if info["soundfile_formats"]:
        print(f"  native:     {', '.join(info['soundfile_formats'][:12])}"
              f"{' ...' if len(info['soundfile_formats']) > 12 else ''}")
    if info["compressed_formats_readable"]:
        print("  m4a/aac:    readable through ffmpeg")
    else:
        print("  m4a/aac:    NOT readable. Fix with:  pip install imageio-ffmpeg")

    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        target = argv[0]
        print(f"\nProbing {target}")
        try:
            samples, rate = load_audio(target)
            seconds = len(samples) / rate if rate else 0.0
            print(f"  decoded {len(samples):,} samples at {rate} Hz "
                  f"({seconds / 60:.1f} min)")
        except Exception as exc:
            print(f"  FAILED: {exc}")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
