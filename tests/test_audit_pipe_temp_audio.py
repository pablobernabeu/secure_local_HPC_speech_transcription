"""The temporary enhanced recording is removed on every exit path.

Audit finding T3-11: the temporary copy of the enhanced participant audio
was deleted only on success and when transcription failed, so any
exception raised later left the whole recording in the temp directory.
"""

from __future__ import annotations

import contextlib
import io
from pathlib import Path

import pytest


def _fake_result(*_args, **_kwargs):
    return {'text': 'hello there.',
            'chunks': [{'text': 'hello', 'timestamp': (0.0, 0.4)},
                       {'text': 'there.', 'timestamp': (0.5, 0.9)}]}


@pytest.fixture()
def setup(transcription_module, tmp_path, monkeypatch):
    m = transcription_module
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(m, "AUDIO_LIBS_AVAILABLE", True)
    monkeypatch.setattr(m, "TRANSFORMERS_AVAILABLE", True)
    monkeypatch.setattr(m, "transcribe_audio_only", _fake_result)
    written = []

    def fake_enhance(_src, dst):
        Path(dst).write_bytes(b"enhanced participant audio")
        written.append(Path(dst))

    monkeypatch.setattr(m, "enhance_audio", fake_enhance)
    (tmp_path / "rec.wav").write_bytes(b"RIFF0000WAVE")

    def run(**kwargs):
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            return m.process_audio_file(str(tmp_path / "rec.wav"),
                                        language="english",
                                        enhance_audio_enabled=True, **kwargs)

    return m, run, written


def test_removed_after_a_later_exception(setup, monkeypatch):
    m, run, written = setup

    def boom(*_a, **_k):
        raise OSError("quota exceeded")

    monkeypatch.setattr(m, "save_transcript_file", boom)
    assert run() is False
    assert len(written) == 1 and not written[0].exists()


def test_removed_after_success(setup):
    _m, run, written = setup
    assert run() is True
    assert len(written) == 1 and not written[0].exists()


def test_kept_when_saving_was_requested(setup, tmp_path):
    _m, run, written = setup
    assert run(save_enhanced_audios=True) is True
    assert written[0].exists()
    assert written[0].resolve().parent == tmp_path / "output" / "enhanced_audio"
