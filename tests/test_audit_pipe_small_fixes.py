"""VTT cue times, redacted-copy independence and .docx naming.

Audit findings T3-18 (a cue time of '60.000' seconds), T3-22 (a redacted
segment shared its empty words list with the raw one) and T3-21 (the
.docx path came from str.replace over the whole path).
"""

from __future__ import annotations

import contextlib
import io
import json

import pytest


@pytest.mark.parametrize("seconds, expected", [
    (0.0, "00:00:00.000"),
    (None, "00:00:00.000"),
    (-1.0, "00:00:00.000"),
    (1.02, "00:00:01.020"),
    (59.9996, "00:01:00.000"),
    (119.99999999999999, "00:02:00.000"),
    (3599.9996, "01:00:00.000"),
    (3661.5, "01:01:01.500"),
])
def test_vtt_timestamp(transcription_module, seconds, expected):
    assert transcription_module._format_vtt_timestamp(seconds) == expected


def test_whisper_grid_is_formatted_as_before(transcription_module):
    fmt = transcription_module._format_vtt_timestamp

    def old(s):
        h = int(s // 3600)
        m = int((s % 3600) // 60)
        return f"{h:02d}:{m:02d}:{s - h * 3600 - m * 60:06.3f}"

    for k in range(0, 200000, 7):
        assert fmt(k * 0.02) == old(k * 0.02)


def test_redacted_words_list_is_independent(transcription_module):
    segs = [{'text': 'Hi', 'words': []}, {'text': 'Yo'}]
    red = transcription_module._redact_segments(segs, str.upper)
    assert red[0]['words'] == [] and red[0]['words'] is not segs[0]['words']
    red[0]['words'].append({'word': 'x'})
    assert segs[0]['words'] == []
    assert 'words' not in red[1]


def _fake_result(*_args, **_kwargs):
    return {'text': 'hello there.',
            'chunks': [{'text': 'hello', 'timestamp': (0.0, 0.4)},
                       {'text': 'there.', 'timestamp': (0.5, 0.9)}]}


def test_docx_named_from_the_suffix_only(transcription_module, tmp_path,
                                         monkeypatch):
    m = transcription_module
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(m, "AUDIO_LIBS_AVAILABLE", True)
    monkeypatch.setattr(m, "TRANSFORMERS_AVAILABLE", True)
    monkeypatch.setattr(m, "transcribe_audio_only", _fake_result)
    (tmp_path / "notes.txt.wav").write_bytes(b"RIFF0000WAVE")
    with contextlib.redirect_stdout(io.StringIO()):
        assert m.process_audio_file(str(tmp_path / "notes.txt.wav"),
                                    language="english")
    out = tmp_path / "output" / "transcripts"
    assert (out / "notes.txt_transcript.docx").exists()
    assert not (out / "notes.docx_transcript.docx").exists()
    listed = [e['path'] for e in json.loads(
        (out / "notes.txt_manifest.json").read_text("utf-8"))['artefacts']]
    assert "notes.txt_transcript.docx" in listed
