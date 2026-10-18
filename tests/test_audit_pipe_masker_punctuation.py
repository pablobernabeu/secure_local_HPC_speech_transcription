"""Names next to quotes, brackets and closing punctuation are masked.

Audit findings T1-03 and EPRIV-10: the capitalisation gate read the raw
token's first character, so a name opening a quotation or parenthesis was
never masked, and a possessive followed by punctuation ("Sarah's.") missed
the dictionary. Bare tokens, and the title template, come out exactly as
before. A possessive now keeps its clitic after the placeholder
("[NAME]'s", where it used to lose the "s" and give "[NAME]'"), which the
masking benchmark's scorer must strip before matching a placeholder.
"""

from __future__ import annotations

import contextlib
import io

import pytest


@pytest.fixture(scope="module")
def mask(transcription_module):
    with contextlib.redirect_stdout(io.StringIO()):
        fn, _ = transcription_module.create_enhanced_name_masker()
    return fn


@pytest.mark.parametrize("text, expected", [
    ("I told (Sarah) about it.", "I told ([NAME]) about it."),
    ('He said "Sarah, come here".', 'He said "[NAME], come here".'),
    ("She said, 'Sarah was there' and (John) agreed.",
     "She said, '[NAME] was there' and ([NAME]) agreed."),
    ("It was Sarah's.", "It was [NAME]'s."),
    ("(Dr Smith) signed it.", "([TITLE] [SURNAME]) signed it."),
    ('Ask "Dr Smith" today.', 'Ask "[TITLE] [SURNAME]" today.'),
])
def test_punctuated_names_are_masked(mask, text, expected):
    assert mask(text) == expected


@pytest.mark.parametrize("text", [
    'I told (sarah) about it.',          # lower case still passes the gate
    'He said "will you" twice.',         # common word, not a name
])
def test_gate_is_otherwise_unchanged(mask, text):
    assert mask(text) == text


@pytest.mark.parametrize("text, expected", [
    # The benchmark's own shapes: bare, possessive, title template.
    ("Sarah arrived at the clinic before the appointment.",
     "[NAME] arrived at the clinic before the appointment."),
    ("Yesterday the patient told Sarah's about the results.",
     "Yesterday the patient told [NAME]'s about the results."),
    ("The referral was signed by Dr Smith this morning.",
     "The referral was signed by [TITLE] [SURNAME] this morning."),
    ("The referral was signed by Dr smith this morning.",
     "The referral was signed by Dr smith this morning."),
])
def test_benchmark_shaped_tokens_unchanged(mask, text, expected):
    assert mask(text) == expected


@pytest.mark.parametrize("token", [
    "Sarah", "sarah", "Sarah's", "Sarah,", "_x", "9am", "O'Brien", "É",
])
def test_capitalisation_matches_old_rule_without_leading_punctuation(
        transcription_module, token):
    m = transcription_module
    assert m._token_is_capitalised(token) == token[0].isupper()


@pytest.mark.parametrize("token, expected", [
    ("Sarah", "[NAME]"), ("Sarah,", "[NAME],"), ("Sarah's", "[NAME]'s"),
    ('"Sarah,', '"[NAME],'), ("(Sarah)", "([NAME])"),
])
def test_wrap_placeholder(transcription_module, token, expected):
    assert transcription_module._wrap_placeholder(token, "[NAME]") == expected
