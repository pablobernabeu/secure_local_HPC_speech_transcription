"""Stage-1 fix to _sentence_capitalise (audit finding T1-16).

The stage capitalised ASCII a-z only, although it claims to be
language-general.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# T1-16: _sentence_capitalise
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("vale. élève arrive.", "Vale. Élève arrive."),
    ("über alles. ärger.", "Über alles. Ärger."),
    ("łódź jest duża.", "Łódź jest duża."),
    ("это так.", "Это так."),
    ("hello world", "Hello world"),
    ("[um] so", "[um] so"),              # a bracket is not a letter
    ('"quoted" start', '"quoted" start'),
    ("3 apples", "3 apples"),
    ("中文。", "中文。"),                   # no case: unchanged
])
def test_sentence_capitalise_any_script(transcription_module, text, expected):
    assert transcription_module._sentence_capitalise(text) == expected


def test_sentence_capitalise_does_not_use_georgian_capitals(
        transcription_module):
    """Georgian title case is the letter itself; upper case is Mtavruli."""
    assert transcription_module._sentence_capitalise("ა") == "ა"


def test_sentence_capitalise_keeps_the_space_after_a_full_stop(
        transcription_module):
    assert transcription_module._sentence_capitalise("hello. world") == \
        "Hello. World"


def test_french_pipeline_capitalises_accented_sentence_start(
        transcription_module):
    out = transcription_module.clean_transcription_text(
        "élève arrive. à demain.", "french")
    assert out == "Élève arrive. À demain."
