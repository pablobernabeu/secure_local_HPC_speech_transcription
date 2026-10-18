"""Stage-1 fix to _filler_bracket (audit findings T1-18 and EWER-03).

Hyphenated backchannels were bracketed element by element
("[mm]-[hmm]", "[uh]-huh"), and a filler after an apostrophe was
bracketed inside a word ("o'[er]").
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# T1-18 and EWER-03: _filler_bracket
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("uh-huh mm-hmm", "[uh-huh] [mm-hmm]"),
    ("Mm-hmm, Uh-huh.", "[Mm-hmm], [Uh-huh]."),
    ("uh-uh mm-mm", "[uh-uh] [mm-mm]"),
    ("uh-oh", "uh-oh"),                     # a compound, not a filler
    ("um the cat", "[um] the cat"),
    ("um um uh", "[um] [um] [uh]"),
    ("I, uh- I think", "I, [uh]- I think"),  # a cut-off, not a compound
    ("O'er the hills, e'er so", "O'er the hills, e'er so"),
    ("o’er", "o’er"),
])
def test_filler_bracket(transcription_module, text, expected):
    assert transcription_module._filler_bracket(text) == expected


def test_filler_bracket_is_idempotent(transcription_module):
    f = transcription_module._filler_bracket
    for s in ("uh-huh mm-hmm um", "[mm-hmm] [uh-uh] [um]", "O'er uh-oh um"):
        assert f(f(s)) == f(s)


def test_disfluency_counts_a_bracketed_backchannel_once(transcription_module):
    """evaluation/disfluency.py must count '[mm-hmm]' as one filler."""
    from evaluation.disfluency import count_fillers
    raw = "mm-hmm yes uh-huh"
    assert count_fillers(transcription_module._filler_bracket(raw)) == \
        count_fillers(raw)
    assert sum(count_fillers(raw).values()) == 2
