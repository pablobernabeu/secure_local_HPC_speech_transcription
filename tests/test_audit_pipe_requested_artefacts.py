"""A run that cannot produce a requested artefact does not report success.

Audit findings T3-07, XREF-15 and T2-08: failures of the timestamped
outputs, the review, diarisation, the Word document and the manifest were
printed as warnings (or, for the .docx, followed by a success line) and the
job still exited 0; an unreadable --exclude-names-file only warned.
"""

from __future__ import annotations

import contextlib
import io
import sys

import pytest


def _fake_result(*_args, **_kwargs):
    return {
        'text': 'hello there. goodbye now.',
        'chunks': [
            {'text': 'hello', 'timestamp': (0.0, 0.4)},
            {'text': 'there.', 'timestamp': (0.5, 0.9)},
            {'text': 'goodbye', 'timestamp': (2.0, 2.4)},
            {'text': 'now.', 'timestamp': (2.5, 2.9)},
        ],
    }


@pytest.fixture()
def run(transcription_module, tmp_path, monkeypatch):
    m = transcription_module
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(m, "AUDIO_LIBS_AVAILABLE", True)
    monkeypatch.setattr(m, "TRANSFORMERS_AVAILABLE", True)
    monkeypatch.setattr(m, "transcribe_audio_only", _fake_result)
    (tmp_path / "rec.wav").write_bytes(b"RIFF0000WAVE")

    def _run(**kwargs):
        kwargs.setdefault("language", "english")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ok = m.process_audio_file(str(tmp_path / "rec.wav"), **kwargs)
        return ok, out.getvalue()

    return _run


def test_clean_run_succeeds(run, tmp_path):
    ok, log = run(timestamps=True)
    assert ok is True
    assert "SUCCESS" in log


def test_timestamped_output_failure_fails_the_run(run, transcription_module,
                                                  monkeypatch, tmp_path):
    def boom(*_a, **_k):
        raise OSError("disk quota exceeded")

    monkeypatch.setattr(transcription_module, "write_timestamped_outputs", boom)
    ok, log = run(timestamps=True)
    assert ok is False
    assert "timestamped JSON/VTT (disk quota exceeded)" in log
    # The other outputs are still written.
    assert (tmp_path / "output" / "transcripts" / "rec_transcript.txt").exists()


def test_unavailable_diarisation_fails_the_run(run, transcription_module,
                                               monkeypatch):
    monkeypatch.setattr(
        transcription_module, "perform_speaker_diarization",
        lambda *_a, **_k: (None, {'source': 'unavailable',
                                  'error': 'no token'}))
    ok, log = run(speaker_attribution=True)
    assert ok is False
    assert "speaker attribution (no token)" in log


def test_failed_word_document_is_not_reported_as_saved(
        run, transcription_module, monkeypatch):
    monkeypatch.setattr(transcription_module, "create_word_document",
                        lambda *_a, **_k: False)
    ok, log = run()
    assert ok is False
    assert "Word document saved" not in log
    assert "Word document not saved" in log


def test_word_document_without_python_docx_returns_false(
        transcription_module, monkeypatch, tmp_path):
    monkeypatch.setattr(transcription_module, "DOCX_AVAILABLE", False)
    with contextlib.redirect_stdout(io.StringIO()):
        assert transcription_module.create_word_document(
            "text", str(tmp_path / "x.docx"), "x.wav") is False


def test_manifest_failure_fails_the_run(run, monkeypatch):
    import provenance

    def boom(*_a, **_k):
        raise OSError("read-only file system")

    monkeypatch.setattr(provenance, "write_manifest", boom)
    ok, log = run()
    assert ok is False
    assert "run manifest (read-only file system)" in log


def test_unreadable_exclusion_file_is_a_usage_error(transcription_module,
                                                    monkeypatch, tmp_path):
    m = transcription_module
    called = []
    monkeypatch.setattr(m, "process_audio_file",
                        lambda *a, **k: called.append(1) or True)
    monkeypatch.setattr(sys, "argv", [
        "transcription.py", "rec.wav", "--mask-personal-names",
        "--exclude-names-file", str(tmp_path / "keep.txt")])
    with contextlib.redirect_stdout(io.StringIO()), \
            contextlib.redirect_stderr(io.StringIO()):
        with pytest.raises(SystemExit) as exc:
            m.main()
    assert exc.value.code == 2
    assert called == []
