"""Audit fix EPRIV-22: one WAV reader, with a catchable error contract.

voice_anonymisation held a verbatim copy of audio_redaction's WAV I/O whose
reader raised SystemExit from a library function, which bypasses
``except Exception`` and kills a batch caller. Both modules now share one
implementation that raises ValueError.
"""

from __future__ import annotations

import sys
import wave
from pathlib import Path

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import audio_redaction
import voice_anonymisation


def _write_24bit(path: Path) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(3)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00\x00" * 100)


def test_modules_share_one_implementation():
    assert voice_anonymisation.read_wav is audio_redaction.read_wav
    assert voice_anonymisation.write_wav is audio_redaction.write_wav


def test_unsupported_wav_raises_a_catchable_error(tmp_path):
    path = tmp_path / "deep.wav"
    _write_24bit(path)
    with pytest.raises(ValueError):
        voice_anonymisation.read_wav(path)


def test_cli_reports_an_unreadable_wav(tmp_path, capsys):
    path = tmp_path / "deep.wav"
    _write_24bit(path)
    rc = voice_anonymisation.main(["--audio", str(path),
                                   "--out", str(tmp_path / "out.wav")])
    assert rc == 2
    assert "16-bit" in capsys.readouterr().err
    assert not (tmp_path / "out.wav").exists()


def test_roundtrip_through_voice_anonymisation(tmp_path):
    audio = np.linspace(-0.5, 0.5, 1600, dtype=np.float32)
    voice_anonymisation.write_wav(tmp_path / "x.wav", audio, 16000)
    back, rate = voice_anonymisation.read_wav(tmp_path / "x.wav")
    assert rate == 16000 and np.max(np.abs(back - audio)) < 1e-3
