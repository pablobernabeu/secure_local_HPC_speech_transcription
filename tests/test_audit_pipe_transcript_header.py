"""The .txt and .docx headers come from one list of metadata lines.

Audit finding T2-09: the header was written twice, line for line, by
save_transcript_file and create_word_document, called positionally with
their parameters in different orders. The .txt layout must be unchanged,
since evaluation/wer.py strips it.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import io

import pytest


class _FixedDatetime(_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 9, 25, 12, 0, 0)


@pytest.fixture()
def fixed(transcription_module, monkeypatch):
    m = transcription_module
    monkeypatch.setattr(m, "datetime", _FixedDatetime)
    monkeypatch.setattr(m, "get_latest_version", lambda: "9.9.9")
    return m


SETTINGS = dict(original_filename="Team_meeting.m4a", model="whisper-x",
                language="english", mask_names=True, fix_repetitions=True,
                use_facebook_names=False, use_facebook_surnames=False,
                enhance_audio_enabled=True)

EXPECTED_TXT = (
    "Team:meeting\n"
    "============\n\n"
    "Input file: Team_meeting.m4a\n"
    "Processed: 2026-09-25 12:00:00\n"
    "Transcription system version: 9.9.9\n"
    "Model: whisper-x\n"
    "Audio enhanced before transcription\n"
    "Language: English\n"
    "Edited to remove likely spurious repetitions.\n"
    "Privacy: Personal names masked using internal list (review recommended)\n"
    "Speaker attribution: Enabled (accuracy depends on recording quality, "
    "speaker count, and speaker similarity)\n"
    "============\n\n"
    "Body text.\n\n"
)


def test_txt_layout_is_unchanged(fixed, tmp_path):
    out = tmp_path / "t.txt"
    fixed.save_transcript_file(str(out), "Body text.", "base", "tmp123.wav",
                               speaker_attribution=True, **SETTINGS)
    assert out.read_text(encoding="utf-8") == EXPECTED_TXT


def test_docx_carries_the_same_lines(fixed, tmp_path):
    docx = pytest.importorskip("docx")
    path = tmp_path / "t.docx"
    settings = dict(SETTINGS)
    settings["model_name"] = settings.pop("model")
    with contextlib.redirect_stdout(io.StringIO()):
        assert fixed.create_word_document("Body text.", str(path),
                                          "tmp123.wav",
                                          speaker_attribution=True, **settings)
    paragraphs = [p.text for p in docx.Document(str(path)).paragraphs]
    header = EXPECTED_TXT.split("============\n\n")[1].strip().split("\n")
    assert paragraphs[0] == "Team:meeting"
    assert paragraphs[2:2 + len(header)] == header
    assert paragraphs[-1] == "Body text."


def test_settings_are_keyword_only(transcription_module):
    import inspect
    m = transcription_module
    for fn, first_kw in ((m.save_transcript_file, "original_filename"),
                         (m.create_word_document, "mask_names")):
        param = inspect.signature(fn).parameters[first_kw]
        assert param.kind is inspect.Parameter.KEYWORD_ONLY
