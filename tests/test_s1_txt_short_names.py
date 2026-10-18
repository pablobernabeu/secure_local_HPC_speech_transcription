"""Stage-1 fix to the curated short names (audit finding T1-07).

Names shorter than three characters were dropped from the curated
dictionary by a filter meant for the scraped Facebook sets, so "Li",
"Wu", "Al" and "Ed" were never masked.
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
# T1-07: curated short names are masked; Facebook sets keep the filter
# ---------------------------------------------------------------------------

def test_curated_short_names_are_masked_by_default(mask):
    assert mask("I met Li and Wu and Al and Ed yesterday.") == \
        "I met [SURNAME] and [SURNAME] and [NAME] and [NAME] yesterday."


def test_every_curated_short_name_is_in_the_dictionary(transcription_module):
    import csv
    with open(PROJECT_ROOT / "data" / "curated_names.csv",
              encoding="utf-8") as f:
        short = {row["name"].strip().lower() for row in csv.DictReader(f)
                 if len(row["name"].strip()) < 3}
    assert short, "the curated CSV has no short names to test"
    with contextlib.redirect_stdout(io.StringIO()):
        first, last = transcription_module.create_multilingual_curated_names()
    # Only the two that are also ordinary English tokens are filtered.
    assert short - (first | last) == {"an", "ai"} & short


@pytest.mark.parametrize("text", [
    "An example follows.",
    "AI is changing research.",
    "We asked the AI to help.",
])
def test_english_tokens_that_are_curated_names_stay(mask, text):
    assert mask(text) == text


def test_facebook_sets_keep_the_length_filter(transcription_module):
    f = transcription_module.filter_problematic_names
    assert f({"li", "xu", "bob", "will"}) == {"bob"}
    assert f({"li", "xu", "bob", "will"}, drop_short=False) == {"li", "xu", "bob"}
    assert transcription_module.MIN_FACEBOOK_NAME_LENGTH == 3


def test_case_study_redaction_count_is_unchanged(mask):
    """Exempting the curated short names adds no redaction to ep05: its
    twelve "AI" stay unmasked. The text holds three dictionary redactions,
    "Jordan" and the name and surname of its closing credits, and since
    NEW-09 the "Dr." before that name is masked as [TITLE] as well."""
    text = (PROJECT_ROOT / "output" / "case_study" / "ep05_raw_text.txt"
            ).read_text(encoding="utf-8")
    assert sorted(_PLACEHOLDER_RE.findall(mask(text))) == [
        "[NAME]", "[NAME]", "[SURNAME]", "[TITLE]"]
