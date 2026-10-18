"""Stage-1 fixes to the name masker (audit findings T1-03 and EPRIV-10).

The possessive clitic is kept after the placeholder ("[NAME]'s"), a
name after an opening quote survives cleaning and is masked, and the
capitalisation gate reads the token's own first letter.
"""

from __future__ import annotations

import contextlib
import io
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_PLACEHOLDER_RE = re.compile(r"\[(?:NAME|SURNAME|TITLE)\]")


@pytest.fixture(scope="module")
def masker(transcription_module):
    with contextlib.redirect_stdout(io.StringIO()):
        return transcription_module.create_enhanced_name_masker()


@pytest.fixture(scope="module")
def mask(masker):
    return masker[0]


# ---------------------------------------------------------------------------
# T1-03: the possessive clitic is a suffix of the placeholder
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("token, expected", [
    ("Sarah", "[NAME]"),
    ("Sarah's", "[NAME]'s"),
    ("Sarah's.", "[NAME]'s."),
    ("Sarah’s,", "[NAME]’s,"),
    ("James'", "[NAME]'"),
    ('"Sarah,', '"[NAME],'),
    ("(Sarah)", "([NAME])"),
    ("O'Brien", "[NAME]"),          # the apostrophe belongs to the name
    ("O'Brien's", "[NAME]'s"),
    ("Mary-Jane.", "[NAME]."),
])
def test_wrap_placeholder_keeps_the_clitic(transcription_module, token,
                                           expected):
    assert transcription_module._wrap_placeholder(token, "[NAME]") == expected


@pytest.mark.parametrize("text, expected", [
    ("It was Sarah's idea.", "It was [NAME]'s idea."),
    ("It was Sarah's.", "It was [NAME]'s."),
    ("Yesterday the patient told Sarah's about the results.",
     "Yesterday the patient told [NAME]'s about the results."),
])
def test_masker_keeps_the_possessive(mask, text, expected):
    assert mask(text) == expected


def test_log_records_the_suffixed_placeholder(masker):
    mask, get_log = masker
    mask("It was Sarah's idea.")
    assert [(r["original"], r["replacement"]) for r in get_log()] == [
        ("Sarah's", "[NAME]'s")]


def test_name_after_an_opening_quote_survives_cleaning_and_is_masked(
        transcription_module, masker):
    """The cleaner no longer glues the quote onto the previous word."""
    mask, get_log = masker
    out, log = transcription_module.postprocess_transcript_text(
        'he said "Sarah" to me.', "english", mask_fn=mask, get_log=get_log)
    assert out == 'He said "[NAME]" to me.'
    assert [r["original"] for r in log] == ['"Sarah"']


# ---------------------------------------------------------------------------
# EPRIV-10: the gate reads the token's own first letter (confirmation)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ('She said, "Aaron, can you hear me?"',
     'She said, "[NAME], can you hear me?"'),
    ("(Aaron was late)", "([NAME] was late)"),
    ("Hi -Aaron here", "Hi -[NAME] here"),
    ("Then Aaron joined.", "Then [NAME] joined."),
])
def test_punctuation_before_a_name_does_not_hide_it(mask, text, expected):
    assert mask(text) == expected
