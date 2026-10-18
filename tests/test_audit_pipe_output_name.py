"""Every artefact of a run, the saved enhanced recording included, shares
one base name.

Audit finding T3-20: base_name was derived three times and the enhanced
recording's copy ignored --output-name.
"""

from __future__ import annotations

import contextlib
import io
from pathlib import Path


def _fake_result(*_args, **_kwargs):
    return {'text': 'hello there.',
            'chunks': [{'text': 'hello', 'timestamp': (0.0, 0.4)},
                       {'text': 'there.', 'timestamp': (0.5, 0.9)}]}


def test_enhanced_audio_uses_the_output_name(transcription_module, tmp_path,
                                             monkeypatch):
    m = transcription_module
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(m, "AUDIO_LIBS_AVAILABLE", True)
    monkeypatch.setattr(m, "TRANSFORMERS_AVAILABLE", True)
    monkeypatch.setattr(m, "transcribe_audio_only", _fake_result)
    monkeypatch.setattr(m, "enhance_audio",
                        lambda _src, dst: Path(dst).write_bytes(b"x"))
    (tmp_path / "rec.wav").write_bytes(b"RIFF0000WAVE")
    with contextlib.redirect_stdout(io.StringIO()):
        assert m.process_audio_file(
            str(tmp_path / "rec.wav"), language="english",
            output_name="client_call", enhance_audio_enabled=True,
            save_enhanced_audios=True)
    assert (tmp_path / "output" / "enhanced_audio"
            / "client_call_enhanced.wav").exists()
    assert (tmp_path / "output" / "transcripts"
            / "client_call_transcript.txt").exists()
    assert not (tmp_path / "output" / "enhanced_audio"
                / "rec_enhanced.wav").exists()
