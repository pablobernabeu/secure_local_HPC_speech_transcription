"""Stage-1 fixes to the condition registry (EWER-03, EWER-05).

EWER-05: whisper_norm built the Whisper normaliser with an empty spelling
map, so "colour" and "color" scored as different words, under a docstring
saying the opposite. The map is now loaded explicitly, checked against a
pinned digest, and its absence is an error, never an empty map.

EWER-03: the scoring normaliser lowercases and strips punctuation on both
sides, so a condition that changes only case, punctuation, spacing or
brackets scores exactly as raw. Such conditions carry wer_invisible=True.
The flag is checked in both directions: a flagged condition must leave the
normalised tokens unchanged, and an unflagged one must have an input on
which it changes them. For punct_strip, the unflagged condition closest to
invisible, the cases in which it can score differently from raw are pinned
as well.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata

import pytest

from evaluation import conditions
from evaluation.wer import normalise_text


# ---------------------------------------------------------------------------
# EWER-05: the spelling map
# ---------------------------------------------------------------------------

def _fixture_map(tmp_path, mapping):
    path = tmp_path / "english.json"
    path.write_text(json.dumps(mapping), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_pinned_digest_is_enforced(tmp_path):
    path, digest = _fixture_map(tmp_path, {"colour": "color"})
    with pytest.raises(conditions.SpellingMapError, match="refuses"):
        conditions.load_whisper_spelling_map(path)          # default pin
    assert conditions.load_whisper_spelling_map(
        path, expected_sha256=digest) == {"colour": "color"}


def test_an_empty_or_malformed_map_is_refused(tmp_path):
    for bad in ({}, [], {"colour": 1}):
        path, digest = _fixture_map(tmp_path, bad)
        with pytest.raises(conditions.SpellingMapError, match="non-empty map"):
            conditions.load_whisper_spelling_map(path, expected_sha256=digest)


def test_a_missing_openai_whisper_is_an_error_not_an_empty_map(monkeypatch):
    monkeypatch.setattr(conditions.importlib.util, "find_spec",
                        lambda name: None)
    with pytest.raises(ImportError, match="openai-whisper"):
        conditions.whisper_spelling_map_path()
    # An ImportError, so the WER benchmark stops before loading a model
    # instead of skipping every utterance.
    assert issubclass(conditions.SpellingMapError, ImportError)


def test_whisper_norm_applies_the_map_to_both_sides(tmp_path, monkeypatch):
    pytest.importorskip("transformers")
    path, digest = _fixture_map(tmp_path, {"colour": "color",
                                           "honour": "honor"})
    monkeypatch.setattr(conditions, "whisper_spelling_map_path", lambda: path)
    monkeypatch.setattr(conditions, "_WHISPER_SPELLING_MAP_SHA256", digest)
    monkeypatch.setattr(conditions, "_WHISPER_NORM_SINGLETON", None)
    monkeypatch.setattr(conditions, "_WHISPER_NORM_PROVENANCE", None)
    cond = conditions.get_condition("whisper_norm")
    assert cond.apply_to_reference
    assert cond.transform("The Colour of honour.") == "the color of honor"
    assert cond.transform("the color of honor") == "the color of honor"
    prov = conditions.condition_provenance("whisper_norm")
    assert prov["spelling_map_entries"] == 2
    assert prov["spelling_map_sha256"] == digest
    assert conditions.condition_provenance("raw") is None


def test_the_description_no_longer_claims_the_opposite():
    cond = conditions.get_condition("whisper_norm")
    text = (cond.description + cond.notes).lower()
    assert "treated as equivalent" not in text
    assert "spelling map" in text


# ---------------------------------------------------------------------------
# EWER-03: which conditions normalised WER can see
# ---------------------------------------------------------------------------

_FLAGGED = {"case_fold", "common_phrase_fix", "sentence_capitalise",
            "pronoun_i_fix", "whitespace_normalise", "punct_space_fix",
            "filler_bracket"}

# Case, punctuation, quotes, brackets, spacing, numbers and fillers,
# including hyphenated backchannels. A filler inside an apostrophised word
# ("o'er") is left out: bracketing inside a word is a defect of the
# production stage, not a property of the scoring (see the module docstring).
_INVISIBILITY_FIXTURES = (
    "",
    "Um, hello uh there.",
    "I said er, no. i mean it!",
    "Uh-huh, mm-hmm. Mm-hmm? UH-HUH",
    'they said "hello" and (looked away) .',
    "It rose 3.5 percent to $1,000 at 10:30 , see e.g.this",
    "   many    spaces ,here .and there  ",
    "kind of you know i think i guess",
    "[um] the cat said hello",
    "Well...  what?! No; yes: maybe",
)

# One input per unflagged condition on which it changes the scored tokens,
# so the flag cannot be missing from a condition that deserves it.
_WITNESSES = {
    "repetition_fix": " ".join(["the cat sat on the mat"] * 12),
    "whisper_norm": "isn't it",
    "filler_strip": "so um yes",
    "dedup_window": "the the cat",
    "punct_strip": "don’t stop",
    # A symbol between two letters is deleted, not spaced, so two scored
    # tokens become one.
    "unicode_strip": "copy©right",
    "undefined_tag": "it was undefin now",
    "contraction_fix": "im here and dont know",
    "pipeline_full": "im here and dont know",
}


def _scored(cond, text):
    out = (cond.transform(text, "english") if cond.language_aware
           else cond.transform(text))
    return normalise_text(out, strip_header=False)


def test_the_flag_marks_exactly_the_expected_conditions():
    flagged = {c.name for c in conditions.list_conditions() if c.wer_invisible}
    assert flagged == _FLAGGED
    assert not conditions.get_condition("raw").wer_invisible


@pytest.mark.parametrize("name", sorted(_FLAGGED))
def test_a_flagged_condition_never_changes_the_scored_tokens(
        name, transcription_module):
    cond = conditions.get_condition(name)
    for text in _INVISIBILITY_FIXTURES:
        assert _scored(cond, text) == normalise_text(text, strip_header=False), (
            f"{name} changed the scored tokens of {text!r}")


@pytest.mark.parametrize("name", sorted(_WITNESSES))
def test_an_unflagged_condition_can_change_the_scored_tokens(
        name, transcription_module):
    if name == "whisper_norm":
        try:
            pytest.importorskip("transformers")
            conditions.whisper_spelling_map_path()
        except ImportError:
            pytest.skip("whisper_norm needs openai-whisper's spelling map")
    cond = conditions.get_condition(name)
    assert not cond.wer_invisible
    text = _WITNESSES[name]
    assert _scored(cond, text) != normalise_text(text, strip_header=False)


def test_every_unflagged_condition_has_a_witness():
    unflagged = {c.name for c in conditions.list_conditions()
                 if not c.wer_invisible} - {"raw"}
    assert unflagged == set(_WITNESSES)


# punct_strip runs before the scoring normaliser, so it can score
# differently from raw only on a character that the normaliser would have
# rewritten or removed before its own punctuation strip (the module
# docstring of evaluation.conditions). One input per case it names; the
# second is the FLEURS reference sentence behind the only punct_strip cells
# of the committed grid that differ from raw.
_PUNCT_STRIP_MOVES = (
    "don’t stop",                    # U+2019, the typographic apostrophe
    "a cave known as Hira‘” on",     # U+2018, written as a closing mark
    "Brand™ name",                   # NFKC folds U+2122 into TM
    "café au lait",            # NFKC joins U+0301 to its letter
    "SPEAKER-01 hello",              # the normaliser drops the whole tag
)
# Near misses: punctuation the normaliser strips itself, ASCII marks,
# speaker tags without a hyphen, and characters NFKC changes that are
# word characters already, so the strip leaves them for it.
_PUNCT_STRIP_AS_RAW = (
    "\"'Now what,' he said.\"",      # the marks Whisper writes
    "“Yes,” she said (twice)… fine!",
    "don't stop at o'clock",
    "[SPEAKER_00]: hello SPEAKER_01: hi",
    "x² and ﬁne",
)


@pytest.mark.parametrize("text", _PUNCT_STRIP_MOVES)
def test_punct_strip_differs_from_raw_where_the_normaliser_rewrites_first(text):
    cond = conditions.get_condition("punct_strip")
    assert _scored(cond, text) != normalise_text(text, strip_header=False)


@pytest.mark.parametrize("text", _PUNCT_STRIP_AS_RAW)
def test_punct_strip_scores_as_raw_on_the_near_misses(text):
    cond = conditions.get_condition("punct_strip")
    assert _scored(cond, text) == normalise_text(text, strip_header=False)


def test_punct_strip_scores_as_raw_on_every_other_character():
    # The docstring's "only", for one character between letters: every
    # character of the Basic Multilingual Plane that the strip removes
    # scores as under raw, unless it is a curly single quotation mark,
    # NFKC changes it, or it is a combining mark NFKC may join to a letter.
    cond = conditions.get_condition("punct_strip")
    checked = 0
    for cp in range(0x20, 0x10000):
        char = chr(cp)
        if (0xD800 <= cp <= 0xDFFF
                or not conditions._PUNCT_RE.fullmatch(char)
                or char in "‘’"
                or unicodedata.normalize("NFKC", char) != char
                or unicodedata.category(char).startswith("M")):
            continue
        text = f"ab{char}cd"
        assert _scored(cond, text) == normalise_text(text, strip_header=False), (
            f"U+{cp:04X}")
        checked += 1
    assert checked > 1000


def test_flagged_descriptions_say_so():
    for name in _FLAGGED:
        assert "scores exactly as raw" in conditions.get_condition(
            name).description, name


def test_filler_bracket_no_longer_claims_an_insertion_cost():
    text = conditions.get_condition("filler_bracket").description
    assert "increases WER" not in text
