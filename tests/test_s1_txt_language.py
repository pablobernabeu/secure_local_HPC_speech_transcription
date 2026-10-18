"""Stage-1 fix to the language gate (audit finding T2-14).

_language_is_english did not reduce Whisper's special-token form, so
"<|en|>" skipped the English-only stages, and _detected_language
returned an ISO code from the chunks where every other path records the
full name.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# T2-14: the language gate and the detected language
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("<|en|>", True), ("<|EN|>", True), ("english", True), ("en-GB", True),
    (None, True), ("", True), ("   ", True), (123, True),
    ("<|de|>", False), ("german", False),
])
def test_language_is_english_normalises_special_tokens(transcription_module,
                                                       value, expected):
    assert transcription_module._language_is_english(value) is expected


def test_special_token_english_runs_the_english_stages(transcription_module):
    m = transcription_module
    assert m.clean_transcription_text("i think im here", "<|en|>") == \
        m.clean_transcription_text("i think im here", "english")


def test_detected_language_is_a_full_name(transcription_module, monkeypatch):
    m = transcription_module
    monkeypatch.setattr(m, "_whisper_language_table",
                        lambda: {"de": "german", "en": "english"})
    assert m._detected_language({"chunks": [{"language": "<|de|>"}]}) == "german"
    assert m._detected_language({"language": "de"}) == "german"
    assert m._detected_language({"language": "german"}) == "german"
    mixed = {"chunks": [{"language": "de"}, {"language": "german"},
                        {"language": "english"}]}
    assert m._detected_language(mixed) == "german"


def test_without_the_table_the_code_is_kept(transcription_module, monkeypatch):
    m = transcription_module
    monkeypatch.setattr(m, "_whisper_language_table", lambda: None)
    assert m._detected_language({"language": "<|de|>"}) == "de"


def test_the_real_table_names_german(transcription_module):
    pytest.importorskip("transformers")
    assert transcription_module._language_name("de") == "german"
