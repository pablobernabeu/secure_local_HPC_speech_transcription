"""Stage-1 fix to _undefined_tag (audit finding T1-14).

The four whitespace-anchored substitutions missed occurrences at the
start or end of the text, before punctuation and the second of two in
a row.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# T1-14: _undefined_tag
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("undefined value", "[undefined] value"),                     # text start
    ("the value was undefined", "the value was [undefined]"),     # text end
    ("the value was undefin.", "the value was [undefined]."),     # sentence-final
    ("undefined undefined end", "[undefined] [undefined] end"),   # consecutive
    ("Undefining it", "[undefined] it"),
    ("the undefine thing", "the [undefined] thing"),
])
def test_undefined_tag_matches_everywhere(transcription_module, text,
                                          expected):
    assert transcription_module._undefined_tag(text) == expected


def test_undefined_tag_leaves_other_words_and_is_idempotent(
        transcription_module):
    f = transcription_module._undefined_tag
    assert f("an undefinable quantity") == "an undefinable quantity"
    assert f("[undefined] thing") == "[undefined] thing"
    once = f("undefined undefin undefined")
    assert f(once) == once
