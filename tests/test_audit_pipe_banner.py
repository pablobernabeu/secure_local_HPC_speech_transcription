"""The start-up banner describes the run that was actually requested.

Audit finding T3-19: it printed 'No line wrapping, no timestamps' and
'requires HuggingFace token' whatever the flags were.
"""

from __future__ import annotations

import contextlib
import io
import sys

import pytest


def _banner(m, monkeypatch, argv):
    monkeypatch.setattr(m, "process_audio_file", lambda *a, **k: True)
    monkeypatch.setattr(sys, "argv", ["transcription.py", "rec.wav", *argv])
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        with pytest.raises(SystemExit):
            m.main()
    return out.getvalue()


def test_timestamps_and_local_diarisation(transcription_module, monkeypatch):
    text = _banner(transcription_module, monkeypatch, [
        "--timestamps", "--speaker-attribution",
        "--diarization-config", "cfg.yaml"])
    assert "no timestamps" not in text
    assert "word timestamps" in text
    assert "Enabled (local pipeline)" in text
    assert "requires HuggingFace token" not in text


def test_plain_run(transcription_module, monkeypatch):
    text = _banner(transcription_module, monkeypatch, [])
    assert "Features: plain transcript" in text
    assert "spelling corrections" not in text
