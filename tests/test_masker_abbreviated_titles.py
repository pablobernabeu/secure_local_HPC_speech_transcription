"""An honorific written with a full stop is masked with the name after it.

Audit finding NEW-09: the masker split its text after every full stop, so
"Dr." ended one sentence and the name began the next, and the honorific
rule, which looks for a name in the next word of the same sentence, left
"Dr." in the case study's closing credits before "[NAME] [SURNAME]". Only
the abbreviated titles are joined to the following text: a sentence that
ends on a full word such as "sir" must stay a sentence of its own.

The casing tests come from the second review of 29 October 2026: "Mr.",
"Mrs.", "Dr." and "Prof." are titles in any case, "Ms" and "Miss" only as
the honorific is spelt (the unit "ms", the disease "MS" and the verb "miss"
are not), and case_insensitive=True relaxes the gate on the name after a
title as it does for any other name.
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
    # A lower-case dotted title is still a title (it was at bd37445, and
    # 5033ad1's capital requirement had stopped it joining its name).
    ("Thanks to mr. Smith today.", "Thanks to [TITLE] [SURNAME] today."),
    ("Thanks to mrs. Smith today.", "Thanks to [TITLE] [SURNAME] today."),
    ("Thanks to dr. Smith today.", "Thanks to [TITLE] [SURNAME] today."),
    ("Thanks to prof. Garcia today.", "Thanks to [TITLE] [SURNAME] today."),
    ("Thanks to Ms. Smith today.", "Thanks to [TITLE] [SURNAME] today."),
    ("Thanks to Ms Smith today.", "Thanks to [TITLE] [SURNAME] today."),
    ("Thanks to Miss Smith today.", "Thanks to [TITLE] [SURNAME] today."),
    # A possessive name loses its title as well (review finding CR-02).
    ("It was Dr. Smith's idea.", "It was [TITLE] [SURNAME]'s idea."),
    ("It was Dr Smith's idea.", "It was [TITLE] [SURNAME]'s idea."),
    ("It was Dr. Smith’s idea.", "It was [TITLE] [SURNAME]’s idea."),
])
def test_an_abbreviated_title_is_masked_with_its_name(masker, text, expected):
    mask, _ = masker
    assert mask(text) == expected


@pytest.mark.parametrize("text, expected", [
    # "miss" the verb and "ms" the unit are not honorifics: only the name
    # after them is masked.
    ("I miss Sarah a lot.", "I miss [NAME] a lot."),
    ("It took 200 ms Sarah then left.", "It took 200 ms [NAME] then left."),
    # "MS" the disease is not "Ms" either, with or without a full stop.
    ("She was diagnosed with MS. Sarah cared for her.",
     "She was diagnosed with MS. [NAME] cared for her."),
    ("She was diagnosed with MS Sarah said.",
     "She was diagnosed with MS [NAME] said."),
])
def test_a_word_spelt_unlike_the_honorific_is_not_a_title(masker, text, expected):
    mask, _ = masker
    assert mask(text) == expected


@pytest.fixture(scope="module")
def masker_ci(transcription_module):
    with contextlib.redirect_stdout(io.StringIO()):
        return transcription_module.create_enhanced_name_masker(
            case_insensitive=True)


@pytest.mark.parametrize("text, expected", [
    # The option relaxes the gate on the name after the title as well.
    ("Dr. smith arrived.", "[TITLE] [SURNAME] arrived."),
    ("dr smith arrived.", "[TITLE] [SURNAME] arrived."),
    # It does not make a lower-case "miss" or "ms" a title.
    ("I miss sarah a lot.", "I miss [NAME] a lot."),
    ("It took 200 ms sarah then left.", "It took 200 ms [NAME] then left."),
])
def test_case_insensitive_masks_the_title_before_a_lower_case_name(
        masker_ci, text, expected):
    mask, _ = masker_ci
    assert mask(text) == expected


@pytest.mark.parametrize("text, expected", [
    # A full word ends its sentence, so the next one is not its name.
    ("Yes, sir. Smith will come.", "Yes, sir. [SURNAME] will come."),
    # A lower-case word after the title is not a name to the masker.
    ("It was Dr. smith's idea.", "It was Dr. smith's idea."),
    # A unit is not an honorific, so the sentence and its full stop stay.
    ("The response took 200 ms. Sarah then repeated it.",
     "The response took 200 ms. [NAME] then repeated it."),
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
    # A lower-case "ms." is the unit and ends its sentence.
    ("Each trial lasted 30 ms. John pressed it.",
     ["Each trial lasted 30 ms.", "John pressed it."]),
    # "Mr.", "Mrs.", "Dr." and "Prof." are titles in any case.
    ("Signed by DR. Smith.", ["Signed by DR. Smith."]),
    ("Signed by dr. Smith.", ["Signed by dr. Smith."]),
    ("Signed by mr. Smith.", ["Signed by mr. Smith."]),
    ("Signed by mrs. Smith.", ["Signed by mrs. Smith."]),
    ("Signed by prof. Garcia.", ["Signed by prof. Garcia."]),
    # "Ms." only as written: "ms." is the unit and "MS." the disease.
    ("Signed by Ms. Smith.", ["Signed by Ms. Smith."]),
    ("It took 200 ms. Sarah left.", ["It took 200 ms.", "Sarah left."]),
    ("Diagnosed with MS. Sarah cared.", ["Diagnosed with MS.", "Sarah cared."]),
])
def test_sentence_split(transcription_module, text, expected):
    assert transcription_module._split_sentences_for_masking(text) == expected
