"""Stage-1 fix to the truncation check (audit finding T3-05).

The recording's length was measured only inside the speaker-attribution
block, so a --timestamps run without diarisation never checked whether
the transcript stops early.
"""

from __future__ import annotations

import contextlib
import io
import json

import pytest


def _result(duration=None):
    result = {
        'text': 'hello there. goodbye now.',
        'chunks': [
            {'text': 'hello', 'timestamp': (0.0, 0.4)},
            {'text': 'there.', 'timestamp': (0.5, 0.9)},
            {'text': 'goodbye', 'timestamp': (2.0, 2.4)},
            {'text': 'now.', 'timestamp': (2.5, 2.9)},
        ],
    }
    if duration is not None:
        result['audio_duration_s'] = duration
    return result


@pytest.fixture()
def run(transcription_module, tmp_path, monkeypatch):
    m = transcription_module
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(m, "AUDIO_LIBS_AVAILABLE", True)
    monkeypatch.setattr(m, "TRANSFORMERS_AVAILABLE", True)
    (tmp_path / "rec.wav").write_bytes(b"RIFF0000WAVE")

    def _run(result, **kwargs):
        monkeypatch.setattr(m, "transcribe_audio_only",
                            lambda *_a, **_k: result)
        kwargs.setdefault("language", "english")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ok = m.process_audio_file(str(tmp_path / "rec.wav"), **kwargs)
        return ok, out.getvalue(), tmp_path / "output" / "transcripts"

    return _run


# ---------------------------------------------------------------------------
# T3-05
# ---------------------------------------------------------------------------

def test_timestamps_only_run_checks_truncation(run):
    ok, log, out = run(_result(duration=10.0), timestamps=True)
    assert ok is True
    review = json.loads((out / "rec_review.json").read_text(encoding="utf-8"))
    assert review["truncation"]["checked"] is True
    assert review["truncation"]["truncated"] is True
    assert review["truncation"]["audio_duration_s"] == 10.0
    assert "before the recording does" in log


def test_a_complete_transcript_is_not_reported_truncated(run):
    ok, log, out = run(_result(duration=3.0), timestamps=True)
    review = json.loads((out / "rec_review.json").read_text(encoding="utf-8"))
    assert review["truncation"]["checked"] is True
    assert review["truncation"]["truncated"] is False
    assert "before the recording does" not in log


def test_unknown_duration_is_reported_not_silent(run):
    ok, log, out = run(_result(duration=None), timestamps=True)
    review = json.loads((out / "rec_review.json").read_text(encoding="utf-8"))
    assert review["truncation"] == {"checked": False}
    assert "duration is unknown" in log


def test_transcribe_audio_only_documents_the_duration_key(transcription_module):
    doc = transcription_module.transcribe_audio_only.__doc__
    assert "audio_duration_s" in doc
