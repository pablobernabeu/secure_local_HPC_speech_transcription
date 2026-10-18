"""An honorific written with a full stop is masked with the name after it.

Audit finding NEW-09: the masker split its text after every full stop, so
"Dr." ended one sentence and the name began the next, and the honorific
rule, which looks for a name in the next word of the same sentence, left
"Dr." in the case study's closing credits before "[NAME] [SURNAME]". Only
the abbreviated titles are joined to the following text: a sentence that
ends on a full word such as "sir" must stay a sentence of its own.
"""

from __future__ import annotations

import contextlib
import io

import pytest


@pytest.fixture(scope="module")
def masker(transcription_module):
    with contextlib.redirect_stdout(io.StringIO()):
        return transcription_module.create_enhanced_name_masker()


@pytest.mark.parametrize("text, expected", [
    ("The talk was given by Dr. Smith today.",
     "The talk was given by [TITLE] [SURNAME] today."),
    ("Thanks to Mr. Smith.", "Thanks to [TITLE] [SURNAME]."),
    ("(Dr. Smith) signed it.", "([TITLE] [SURNAME]) signed it."),
    ("Produced by Dr. Pablo Bernabeu.", "Produced by [TITLE] [NAME] [SURNAME]."),
    # The form without a full stop was already masked, and still is.
    ("The referral was signed by Dr Smith this morning.",
     "The referral was signed by [TITLE] [SURNAME] this morning."),
])
def test_an_abbreviated_title_is_masked_with_its_name(masker, text, expected):
    mask, _ = masker
    assert mask(text) == expected


@pytest.mark.parametrize("text, expected", [
    # A full word ends its sentence, so the next one is not its name.
    ("Yes, sir. Smith will come.", "Yes, sir. [SURNAME] will come."),
    # A lower-case word after the title is not a name to the masker.
    ("It was Dr. smith's idea.", "It was Dr. smith's idea."),
])
def test_other_sentence_ends_are_unchanged(masker, text, expected):
    mask, _ = masker
    assert mask(text) == expected


def test_the_log_row_names_the_title_rule_and_the_whole_sentence(masker):
    mask, get_log = masker
    mask("Produced by Dr. Pablo Bernabeu. Thanks for listening.")
    rows = get_log()
    title = [row for row in rows if row['replacement'] == '[TITLE]']
    assert len(title) == 1
    assert title[0]['original'] == 'Dr.'
    assert title[0]['source'] == 'title'
    assert title[0]['context_sentence'] == "Produced by Dr. Pablo Bernabeu."


@pytest.mark.parametrize("text, expected", [
    ("By Dr. Smith. Next.", ["By Dr. Smith.", "Next."]),
    ('Ask "Prof. Smith" now.', ['Ask "Prof. Smith" now.']),
    ("Thank you, sir. Smith left.", ["Thank you, sir.", "Smith left."]),
    # "dr." closing a longer word is not the abbreviation.
    ("I met Sandr. Smith left.", ["I met Sandr.", "Smith left."]),
    ("Ends with Mrs.", ["Ends with Mrs."]),
])
def test_sentence_split(transcription_module, text, expected):
    assert transcription_module._split_sentences_for_masking(text) == expected
