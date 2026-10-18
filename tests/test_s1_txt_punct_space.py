"""Stage-1 fix to _punct_space_fix (audit findings T1-04, T2-01, T1-03).

The stage split decimals, thousands separators and clock times
("3. 5", "1, 000", "10: 30"), collapsed an ellipsis to a full stop,
and removed the space before an opening quote, which hid the quoted
name from the masker.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# T1-04 / T2-01 / T1-03: _punct_space_fix
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("It rose 3.5 percent to $1,000 at 10:30.",
     "It rose 3.5 percent to $1,000 at 10:30."),
    ("il est 3,5 fois plus grand.", "il est 3,5 fois plus grand."),
    ("usually 0.05.", "usually 0.05."),
    ("over 1,200,000 people", "over 1,200,000 people"),
    ("at 10:30:45 exactly", "at 10:30:45 exactly"),
])
def test_punct_space_fix_keeps_numbers_whole(transcription_module, text,
                                             expected):
    assert transcription_module._punct_space_fix(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("hello , world .", "hello, world."),
    ("hello ,world", "hello, world"),
    ("hi .there", "hi. there"),
    ("end.Next one", "end. Next one"),
    ("chapter 3.Then", "chapter 3. Then"),       # digit then a letter
    ("a.5", "a. 5"),                             # letter then a digit
    ("hi !! there", "hi! there"),
])
def test_punct_space_fix_still_spaces_punctuation(transcription_module, text,
                                                  expected):
    assert transcription_module._punct_space_fix(text) == expected


@pytest.mark.parametrize("text, expected", [
    ('he said "Sarah" to me.', 'he said "Sarah" to me.'),
    ('He said "hello " to me.', 'He said "hello" to me.'),
    ('They said "hello." Then left.', 'They said "hello." Then left.'),
    ('"Yes," she said.', '"Yes," she said.'),
])
def test_punct_space_fix_keeps_space_before_opening_quote(
        transcription_module, text, expected):
    assert transcription_module._punct_space_fix(text) == expected


def test_punct_space_fix_keeps_an_ellipsis(transcription_module):
    f = transcription_module._punct_space_fix
    assert f("wait...so") == "wait... so"
    assert f("and then...") == "and then..."
    assert f("stop.. now") == "stop. now"


def test_punct_space_fix_is_idempotent(transcription_module):
    f = transcription_module._punct_space_fix
    for s in ('It rose 3.5 percent to $1,000 at 10:30.',
              'he said "Sarah" to me.', "wait...so", "(hello.) there"):
        assert f(f(s)) == f(s)


def test_clean_text_leaves_the_name_after_a_quote_visible(transcription_module):
    """The whole English chain, whose output the masker then reads."""
    out = transcription_module.clean_transcription_text(
        'he said "Sarah" to me.', "english")
    assert out == 'He said "Sarah" to me.'

# ---------------------------------------------------------------------------
# T2-01 (remaining part): dotted abbreviations and hostnames stay whole
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("we use it, i.e. often, and e.g. this",
     "We use it, i.e. often, and e.g. this"),
    ("the U.S. army", "The U.S. Army"),     # see the p.m. case below
    ("see example.com or ox.ac.uk for more.",
     "See example.com or ox.ac.uk for more."),
    ("mail me@example.com.then go", "Mail me@example.com. Then go"),
    ("so i think i.e. yes", "So I think i.e. yes"),
    # Sentences glued at a chunk join are still separated, including a
    # lower-case one whose second word is not a listed domain.
    ("It ended.Next one started", "It ended. Next one started"),
    ("he left.it was late", "He left. It was late"),
    # The last stop of "U.S." or "p.m." may end a sentence, so the word
    # after it is capitalised as before; only "i.e." and "e.g." never end one.
    ("at 5 p.m. then left", "At 5 p.m. Then left"),
])
def test_clean_text_keeps_abbreviations_and_hostnames_whole(
        transcription_module, text, expected):
    assert transcription_module.clean_transcription_text(text, "english") == expected


@pytest.mark.parametrize("stage, text, expected", [
    ("_punct_space_fix", "e.g.this and i.e.that", "e.g. this and i.e. that"),
    ("_punct_space_fix", "visit bbc.co.uk,then", "visit bbc.co.uk, then"),
    ("_whitespace_normalise", "the  U.S. army", "the U.S. army"),
    ("_sentence_capitalise", "we saw it, e.g. there", "We saw it, e.g. there"),
    ("_pronoun_i_fix", "i said i.e. no", "I said i.e. no"),
])
def test_each_stage_keeps_abbreviations_whole(transcription_module, stage,
                                              text, expected):
    """Each stage is also scored alone as a WER condition, so each protects
    the dots itself."""
    assert getattr(transcription_module, stage)(text) == expected


def test_a_stand_in_character_in_the_input_is_left_alone(transcription_module):
    m = transcription_module
    # The protection is skipped, so the stand-in is never turned into a
    # full stop; the abbreviation is then spaced as before the fix.
    out = m._punct_space_fix("odd\ue000char i.e. here")
    assert "\ue000" in out and "odd.char" not in out
