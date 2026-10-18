"""The run manifest lists exactly the files this run wrote.

Audit finding T3-03: the manifest collected artefacts with an unescaped
prefix glob, so interview1's manifest certified interview10's transcripts,
stale raw files from an earlier run were hashed under the new run's
settings, and a name with glob characters ('session[1]') left the run's own
files out.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

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
def pipeline(transcription_module, tmp_path, monkeypatch):
    m = transcription_module
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(m, "AUDIO_LIBS_AVAILABLE", True)
    monkeypatch.setattr(m, "TRANSFORMERS_AVAILABLE", True)
    monkeypatch.setattr(m, "transcribe_audio_only", _fake_result)
    (tmp_path / "rec.wav").write_bytes(b"RIFF0000WAVE")

    def run(**kwargs):
        kwargs.setdefault("language", "english")
        with contextlib.redirect_stdout(io.StringIO()):
            ok = m.process_audio_file(str(tmp_path / "rec.wav"), **kwargs)
        return ok

    return run


def _listed(manifest_path: Path):
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return sorted(entry["path"] for entry in data["artefacts"])


def test_prefix_and_stale_files_are_not_certified(pipeline, tmp_path):
    out = tmp_path / "output" / "transcripts"
    out.mkdir(parents=True)
    (out / "rec10_transcript.txt").write_text("another recording")
    (out / "rec_transcript.json").write_text('{"stale": "raw text"}')

    assert pipeline() is True
    listed = _listed(out / "rec_manifest.json")
    assert "rec10_transcript.txt" not in listed
    assert "rec_transcript.json" not in listed
    assert "rec_transcript.txt" in listed


def test_timestamped_run_lists_its_json_vtt_and_review(pipeline, tmp_path):
    assert pipeline(timestamps=True) is True
    out = tmp_path / "output" / "transcripts"
    listed = _listed(out / "rec_manifest.json")
    for name in ("rec_transcript.json", "rec_transcript.vtt",
                 "rec_review.json", "rec_transcript.txt"):
        assert name in listed


def test_glob_characters_in_the_name_do_not_drop_artefacts(pipeline,
                                                          tmp_path):
    out = tmp_path / "output" / "transcripts"
    out.mkdir(parents=True)
    (out / "session1_transcript.txt").write_text("a different session")

    assert pipeline(output_name="session[1]") is True
    listed = _listed(out / "session[1]_manifest.json")
    assert "session[1]_transcript.txt" in listed
    assert "session1_transcript.txt" not in listed
