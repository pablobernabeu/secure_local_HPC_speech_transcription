"""Tests for format-agnostic audio loading.

The failure this module exists to prevent is environmental: a recording in
a compressed container will not open, on a machine that in fact holds a
usable decoder, because the libraries that shell out to ffmpeg look for it
under a name the bundled copy does not have. Most of these tests therefore
exercise the resolution and error paths rather than the decoding, which is
the part that depends on what happens to be installed.

Decoding through ffmpeg is skipped where no ffmpeg exists, so the suite
passes on a machine with only soundfile.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import audio_io  # noqa: E402
from audio_io import (  # noqa: E402
    audio_support,
    ensure_ffmpeg_on_path,
    find_ffmpeg,
    load_audio,
    _resample,
    _to_mono,
)

sf = pytest.importorskip("soundfile")


def _write_wav(path, seconds=1.0, sr=44100, channels=1, freq=440.0):
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False, dtype=np.float32)
    tone = (0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    data = tone if channels == 1 else np.stack([tone] * channels, axis=1)
    sf.write(str(path), data, sr)
    return path


def test_load_audio_resamples_to_the_requested_rate(tmp_path):
    path = _write_wav(tmp_path / "tone.wav", seconds=1.0, sr=44100)
    data, sr = load_audio(path, sr=16000)
    assert sr == 16000
    assert data.dtype == np.float32
    assert abs(len(data) - 16000) <= 2      # one second at the target rate


def test_load_audio_downmixes_to_mono(tmp_path):
    path = _write_wav(tmp_path / "stereo.wav", channels=2)
    data, _ = load_audio(path, sr=16000)
    assert data.ndim == 1


def test_load_audio_passes_through_at_native_rate(tmp_path):
    path = _write_wav(tmp_path / "native.wav", sr=16000)
    data, sr = load_audio(path, sr=16000)
    assert sr == 16000 and abs(len(data) - 16000) <= 2


def test_load_audio_keeps_channels_when_asked(tmp_path, monkeypatch):
    """mono=False returns (frames, channels) at the requested rate (CORE-06).

    Checked with and without librosa: its default axis would otherwise
    resample the channel axis, and the interpolation fallback needs 1-D.
    """
    path = _write_wav(tmp_path / "stereo44.wav", seconds=1.0, sr=44100,
                      channels=2)
    data, sr = load_audio(path, sr=16000, mono=False)
    assert sr == 16000
    assert data.shape[1] == 2 and abs(data.shape[0] - 16000) <= 2

    monkeypatch.setitem(sys.modules, "librosa", None)   # force the fallback
    data, sr = load_audio(path, sr=16000, mono=False)
    assert data.shape[1] == 2 and abs(data.shape[0] - 16000) <= 2


def test_missing_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_audio(tmp_path / "absent.wav")


def test_decode_without_ffmpeg_explains_the_remedy(tmp_path, monkeypatch):
    """The error must name the fix, not only the failure.

    'Format not recognised' is what the underlying libraries say, and it
    tells a user neither which decoder was missing nor what to install.
    """
    monkeypatch.setattr(audio_io, "find_ffmpeg", lambda: None)
    path = tmp_path / "recording.m4a"
    path.write_bytes(b"not really audio")
    with pytest.raises(RuntimeError) as excinfo:
        audio_io.decode_with_ffmpeg(path)
    message = str(excinfo.value)
    assert "ffmpeg" in message
    assert "imageio-ffmpeg" in message      # the actual remedy
    assert "m4a" in message or "WAV" in message


def test_undecodable_file_surfaces_a_useful_error(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_io, "find_ffmpeg", lambda: None)
    path = tmp_path / "broken.m4a"
    path.write_bytes(b"\x00\x01\x02")
    with pytest.raises(RuntimeError):
        load_audio(path)


def test_ensure_ffmpeg_on_path_is_safe_without_ffmpeg(monkeypatch):
    monkeypatch.setattr(audio_io, "find_ffmpeg", lambda: None)
    assert ensure_ffmpeg_on_path() is None


def test_ensure_ffmpeg_on_path_exposes_a_versioned_binary(tmp_path, monkeypatch):
    """A bundled ffmpeg has a versioned name, so it must be shimmed.

    This is the whole point of the module: the binary exists, but the
    libraries that want it look for the plain name on PATH.
    """
    import os
    import shutil as _shutil
    import tempfile

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "ffmpeg-linux-x86_64-v7.0.2"
    fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    if os.name != "nt":
        fake.chmod(0o755)
    monkeypatch.setattr(audio_io, "find_ffmpeg", lambda: str(fake))
    # Keep the shim inside tmp_path: writing it to the real temp directory
    # left a persistent shim that later runs picked up (TESTS-04).
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    monkeypatch.setenv("PATH", str(bin_dir))       # plain 'ffmpeg' absent
    monkeypatch.delenv("IMAGEIO_FFMPEG_EXE", raising=False)

    resolved = ensure_ffmpeg_on_path()
    assert resolved == str(fake)
    # Recorded for anything that does read the variable.
    assert os.environ["IMAGEIO_FFMPEG_EXE"] == str(fake)
    # And now reachable under the name the other libraries use, pointing at
    # this binary and not a leftover from another run.
    found = _shutil.which("ffmpeg")
    assert found is not None
    # The shim itself lives under the redirected temp directory. Resolve its
    # directory, not the shim: on POSIX the shim is a symlink, and resolving
    # it lands on the target binary, which is deliberately elsewhere.
    assert Path(found).parent.resolve().is_relative_to((tmp_path / "tmp").resolve())
    if Path(found).suffix.lower() == ".bat":
        assert str(fake) in Path(found).read_text(encoding="utf-8")
    else:
        assert os.path.samefile(found, fake)


def test_find_ffmpeg_result_is_a_path_or_none():
    result = find_ffmpeg()
    assert result is None or Path(result).exists()


def test_audio_support_reports_the_state_of_the_environment():
    info = audio_support()
    assert set(info) >= {"soundfile", "ffmpeg", "compressed_formats_readable"}
    assert isinstance(info["soundfile"], bool)
    # The claim about compressed formats must follow from having a decoder.
    assert info["compressed_formats_readable"] == bool(info["ffmpeg"])


def test_helpers():
    assert _to_mono(np.ones((10, 2), dtype=np.float32)).shape == (10,)
    assert _to_mono(np.ones(10, dtype=np.float32)).shape == (10,)
    out = _resample(np.ones(100, dtype=np.float32), 100, 50)
    assert abs(len(out) - 50) <= 1
    same = np.ones(10, dtype=np.float32)
    assert _resample(same, 16000, 16000) is same       # no needless work


@pytest.mark.skipif(find_ffmpeg() is None, reason="no ffmpeg in this environment")
def test_ffmpeg_decode_round_trip(tmp_path):
    """Where ffmpeg exists, decoding must agree with the native reader."""
    path = _write_wav(tmp_path / "tone.wav", sr=16000)
    decoded, sr = audio_io.decode_with_ffmpeg(path, sr=16000)
    assert sr == 16000
    assert abs(len(decoded) - 16000) <= 160            # within 10 ms
