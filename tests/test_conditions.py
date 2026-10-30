"""Tests for the post-processing condition registry in evaluation.conditions.

These tests exercise the registry structure and the public behaviour of each
registered condition.  They do not require audio data, network access, or a
GPU.  They import the local ``transcription`` module (for the production
stages).  The Whisper normaliser needs transformers and openai-whisper's
spelling map; its tests skip where either is absent.
"""

from __future__ import annotations

import dataclasses

import pytest

from evaluation import conditions as _conditions_module
from evaluation.conditions import (
    _CONDITIONS,
    _SLUG_RE,
    get_condition,
    list_conditions,
)


def _whisper_norm_available() -> bool:
    """Whether whisper_norm can run here (transformers and the spelling map)."""
    try:
        import transformers  # noqa: F401
        _conditions_module.whisper_spelling_map_path()
    except ImportError:
        return False
    return True


def _require_whisper_norm():
    if not _whisper_norm_available():
        pytest.skip("whisper_norm needs transformers and openai-whisper's "
                    "spelling map")


_REQUIRED_FIELDS = (
    "name",
    "description",
    "transform",
    "apply_to_reference",
)


def test_registry_is_non_empty():
    assert len(_CONDITIONS) >= 3, (
        "At least three conditions must be registered "
        f"(found {len(_CONDITIONS)})."
    )


def test_condition_names_are_valid_slugs():
    for cond in list_conditions():
        assert _SLUG_RE.match(cond.name), (
            f"Condition name {cond.name!r} does not match {_SLUG_RE.pattern}"
        )


def test_condition_names_are_unique():
    names = [c.name for c in list_conditions()]
    assert len(names) == len(set(names)), (
        f"Duplicate condition names detected: {names}"
    )


def test_required_fields_non_empty():
    for cond in list_conditions():
        for field in ("name", "description"):
            value = getattr(cond, field)
            assert isinstance(value, str) and value.strip(), (
                f"Condition {cond.name!r} has empty {field!r}"
            )
        assert callable(cond.transform), (
            f"Condition {cond.name!r} transform is not callable"
        )
        assert isinstance(cond.apply_to_reference, bool), (
            f"Condition {cond.name!r} apply_to_reference is not a bool"
        )


def test_list_conditions_returns_alphabetical_order():
    names = [c.name for c in list_conditions()]
    assert names == sorted(names), (
        f"list_conditions() must return conditions in alphabetical order; "
        f"got {names}"
    )


def test_list_conditions_covers_all_registered():
    assert {c.name for c in list_conditions()} == set(_CONDITIONS)


def test_get_condition_returns_correct_object():
    for name in _CONDITIONS:
        assert get_condition(name) is _CONDITIONS[name]


def test_get_condition_raises_for_unknown_name():
    with pytest.raises(KeyError) as excinfo:
        get_condition("not_a_real_condition")
    msg = str(excinfo.value)
    assert "not_a_real_condition" in msg
    assert "Available conditions" in msg
    for name in _CONDITIONS:
        assert name in msg, (
            f"Error message must enumerate {name!r}; got {msg!r}"
        )


def test_condition_dataclass_is_immutable():
    cond = next(iter(_CONDITIONS.values()))
    with pytest.raises(dataclasses.FrozenInstanceError):
        # frozen dataclass should reject attribute assignment
        cond.name = "mutated"  # type: ignore[misc]


def test_known_conditions_are_registered():
    """The seven core conditions must all be present."""
    names = {c.name for c in list_conditions()}
    assert {"raw", "repetition_fix", "whisper_norm", "filler_strip", "dedup_window",
            "punct_strip", "case_fold"}.issubset(names), (
        f"Missing core conditions; found {names}"
    )


# ---------------------------------------------------------------------------
# Behavioural tests for individual conditions
# ---------------------------------------------------------------------------
def test_raw_is_identity():
    cond = get_condition("raw")
    assert cond.apply_to_reference is False
    for s in ["", "Hello world.", "Mixed CASE 1234.", "  spaces  "]:
        assert cond.transform(s) == s


def test_raw_does_not_apply_to_reference():
    """The raw condition must never modify the reference."""
    assert get_condition("raw").apply_to_reference is False


def test_repetition_fix_does_not_apply_to_reference():
    """Repetition fix is hypothesis-only by design."""
    assert get_condition("repetition_fix").apply_to_reference is False


def test_repetition_fix_truncates_repeated_loops():
    """The condition must shorten a clearly pathological repetition."""
    cond = get_condition("repetition_fix")
    # Twelve repetitions of the same short phrase — a textbook Whisper loop.
    text = ("the quick brown fox " * 12).strip()
    out = cond.transform(text)
    assert len(out) < len(text), (
        f"repetition_fix did not shorten a 12-fold repeated loop; "
        f"got {out!r}"
    )


def test_repetition_fix_leaves_clean_text_unchanged():
    """Non-repetitive text must pass through repetition_fix verbatim."""
    cond = get_condition("repetition_fix")
    text = "The cat sat on the mat and looked at the window."
    assert cond.transform(text) == text


def test_whisper_norm_applies_to_reference():
    """Whisper normalisation must be symmetric (both hypothesis and reference)."""
    assert get_condition("whisper_norm").apply_to_reference is True


def test_whisper_norm_expands_contractions():
    _require_whisper_norm()
    cond = get_condition("whisper_norm")
    assert cond.transform("isn't") == "is not"
    assert cond.transform("COULDN'T") == "could not"


def test_whisper_norm_lowercases_and_strips_punctuation():
    _require_whisper_norm()
    cond = get_condition("whisper_norm")
    out = cond.transform("Hello, World!")
    assert out == out.lower()
    # The Whisper normaliser strips trailing punctuation.
    assert "!" not in out
    assert "," not in out


def test_whisper_norm_handles_empty_string():
    _require_whisper_norm()
    cond = get_condition("whisper_norm")
    # Must not raise; result is permitted to be empty.
    assert isinstance(cond.transform(""), str)


def test_whisper_norm_maps_british_spellings_to_american():
    """EWER-05: the published normaliser treats colour and color as one word."""
    _require_whisper_norm()
    cond = get_condition("whisper_norm")
    assert cond.transform("The colour of honour") == \
        cond.transform("the color of honor")


# ---------------------------------------------------------------------------
# Behavioural tests for filler_strip
# ---------------------------------------------------------------------------
def test_filler_strip_does_not_apply_to_reference():
    """Filler stripping is hypothesis-only by design."""
    assert get_condition("filler_strip").apply_to_reference is False


def test_filler_strip_handles_empty_string():
    cond = get_condition("filler_strip")
    assert cond.transform("") == ""


def test_filler_strip_is_identity_on_clean_text():
    """Text without disfluency tokens must pass through unchanged."""
    cond = get_condition("filler_strip")
    text = "The cat sat on the mat and looked at the window."
    assert cond.transform(text) == text


def test_filler_strip_removes_standalone_fillers():
    cond = get_condition("filler_strip")
    cases = [
        ("um the meeting is at three", "the meeting is at three"),
        ("uh well I think so", "well I think so"),
        # Parenthetical fillers leave the surrounding comma intact;
        # downstream WER normalisation strips residual punctuation.
        ("the result, er, was surprising", "the result, was surprising"),
        ("hmm let me think", "let me think"),
        ("mm yes that is right", "yes that is right"),
    ]
    for inp, expected in cases:
        assert cond.transform(inp) == expected, (
            f"filler_strip({inp!r}) = {cond.transform(inp)!r}, "
            f"expected {expected!r}"
        )


def test_filler_strip_handles_length_variants():
    """Lengthened fillers (umm, uhh, errr) must also be stripped."""
    cond = get_condition("filler_strip")
    for variant in ("umm", "ummm", "uhh", "uhhh", "errr", "ahhh", "mmm", "hmmm"):
        out = cond.transform(f"so {variant} maybe later")
        assert out == "so maybe later", (
            f"variant {variant!r} not stripped; got {out!r}"
        )


def test_filler_strip_is_case_insensitive():
    cond = get_condition("filler_strip")
    assert cond.transform("UH yes") == "yes"
    assert cond.transform("Um, hello") == "hello"
    assert cond.transform("HMMMM right") == "right"


def test_filler_strip_preserves_backchannels():
    """Compound backchannels such as uh-huh and mm-hmm must survive."""
    cond = get_condition("filler_strip")
    for backchannel in ("uh-huh", "mm-hmm", "uh-uh"):
        text = f"she said {backchannel} firmly"
        assert cond.transform(text) == text, (
            f"backchannel {backchannel!r} should not be modified; "
            f"got {cond.transform(text)!r}"
        )


def test_filler_strip_preserves_embedded_substrings():
    """The regex must not match filler-like substrings inside real words."""
    cond = get_condition("filler_strip")
    # 'her' contains 'er'; 'hum' contains 'um'; 'thumb' contains 'um';
    # 'rumour' contains 'um'.  None of these should be touched.
    text = "her hum reached a thumb-sized rumour"
    assert cond.transform(text) == text


def test_filler_strip_preserves_lexical_hedges():
    """Lexical hedges with semantic content are deliberately out of scope."""
    cond = get_condition("filler_strip")
    text = "I mean, like, you know, sort of maybe"
    out = cond.transform(text)
    # 'like', 'you', 'know', 'sort', 'of', 'maybe' are not in the
    # filler list; the result must still contain them.
    for token in ("like", "you", "know", "sort", "of", "maybe"):
        assert token in out, (
            f"lexical hedge {token!r} was incorrectly stripped; got {out!r}"
        )


def test_filler_strip_is_idempotent():
    """A second application must produce the same string."""
    cond = get_condition("filler_strip")
    inputs = [
        "",
        "the cat sat on the mat",
        "um well uh I think so",
        "HMMMM right, er, maybe",
        "she said uh-huh firmly",
    ]
    for s in inputs:
        once  = cond.transform(s)
        twice = cond.transform(once)
        assert once == twice, (
            f"filler_strip not idempotent on {s!r}: "
            f"once={once!r}, twice={twice!r}"
        )


# ---------------------------------------------------------------------------
# Behavioural tests for dedup_window
# ---------------------------------------------------------------------------
def test_dedup_window_does_not_apply_to_reference():
    """Adjacent-duplicate collapse is hypothesis-only."""
    assert get_condition("dedup_window").apply_to_reference is False


def test_dedup_window_handles_empty_string():
    assert get_condition("dedup_window").transform("") == ""


def test_dedup_window_is_identity_on_clean_text():
    cond = get_condition("dedup_window")
    text = "the cat sat on the mat and looked at the window"
    assert cond.transform(text) == text


def test_dedup_window_collapses_simple_stutters():
    cond = get_condition("dedup_window")
    cases = [
        ("the the cat", "the cat"),
        ("I I went home", "I went home"),
        ("she said to to the man", "she said to the man"),
        ("they they they ran", "they ran"),
    ]
    for inp, expected in cases:
        out = cond.transform(inp)
        assert out == expected, (
            f"dedup_window({inp!r}) = {out!r}, expected {expected!r}"
        )


def test_dedup_window_is_case_insensitive_in_comparison():
    """Differently-cased duplicates collapse, keeping the first form."""
    cond = get_condition("dedup_window")
    assert cond.transform("THE the cat") == "THE cat"
    assert cond.transform("the THE cat") == "the cat"


def test_dedup_window_is_punctuation_insensitive_in_comparison():
    """Adjacent ``the,`` and ``the`` should still collapse."""
    cond = get_condition("dedup_window")
    # Comma-separated duplicate ("the, the") is recognised as a duplicate;
    # the first occurrence (with its comma) is preserved.
    assert cond.transform("the, the cat") == "the, cat"


def test_dedup_window_preserves_non_adjacent_repetition():
    """Repetition with intervening words must not be collapsed."""
    cond = get_condition("dedup_window")
    text = "the man the woman saw left"
    assert cond.transform(text) == text


def test_dedup_window_collapses_adjacent_grammatical_reduplication():
    """The one-token window does not spare grammatical doubling.

    The docstring once claimed that it did. Pinning the actual behaviour
    keeps the documentation honest, and part of the condition's measured
    cost comes from these deletions.
    """
    cond = get_condition("dedup_window")
    assert cond.transform("I said that that was wrong") == "I said that was wrong"
    assert cond.transform("had had enough") == "had enough"


def test_dedup_window_preserves_self_corrections():
    """A filler between repeated words blocks the collapse under window=1."""
    cond = get_condition("dedup_window")
    # ``I uh I went`` is a self-correction, not a stutter; with the
    # conservative one-token window the second ``I`` is NOT adjacent
    # to the first under our definition and must survive.
    text = "I uh I went home"
    assert cond.transform(text) == text


def test_dedup_window_collapses_runs_of_three_or_more():
    """A run of N identical tokens must collapse to a single token."""
    cond = get_condition("dedup_window")
    assert cond.transform("the the the the cat") == "the cat"
    assert cond.transform("no no no no") == "no"


def test_dedup_window_does_not_swallow_pure_punctuation_tokens():
    """A stray punctuation-only token between two real words must not
    cause either of them to be dropped."""
    cond = get_condition("dedup_window")
    # ``hello`` and ``world`` are not duplicates; the comma between
    # them tokenises as part of ``hello,`` so this is well-formed.
    assert cond.transform("hello, world") == "hello, world"


def test_dedup_window_is_idempotent():
    cond = get_condition("dedup_window")
    inputs = [
        "",
        "the cat sat on the mat",
        "the the cat",
        "they they they ran",
        "THE the cat",
        "the, the cat",
    ]
    for s in inputs:
        once  = cond.transform(s)
        twice = cond.transform(once)
        assert once == twice, (
            f"dedup_window not idempotent on {s!r}: "
            f"once={once!r}, twice={twice!r}"
        )


# ---------------------------------------------------------------------------
# Behavioural tests for punct_strip
# ---------------------------------------------------------------------------
def test_punct_strip_applies_to_reference():
    """Punctuation removal must be symmetric (both hypothesis and reference)."""
    assert get_condition("punct_strip").apply_to_reference is True


def test_punct_strip_handles_empty_string():
    assert get_condition("punct_strip").transform("") == ""


def test_punct_strip_is_identity_on_clean_text():
    """Text without any punctuation must pass through unchanged."""
    cond = get_condition("punct_strip")
    text = "the cat sat on the mat and looked at the window"
    assert cond.transform(text) == text


def test_punct_strip_removes_sentence_punctuation():
    cond = get_condition("punct_strip")
    cases = [
        ("Hello, world.", "Hello world"),
        ("She said: \"yes!\"", "She said yes"),
        ("one, two; three: four.", "one two three four"),
        ("(an aside) and the rest", "an aside and the rest"),
        ("dashes--like-this", "dashes like this"),
        ("question? answer!", "question answer"),
    ]
    for inp, expected in cases:
        out = cond.transform(inp)
        assert out == expected, (
            f"punct_strip({inp!r}) = {out!r}, expected {expected!r}"
        )


def test_punct_strip_preserves_apostrophes_in_contractions():
    """Intra-word apostrophes must survive so contractions stay as one token."""
    cond = get_condition("punct_strip")
    for text in ("don't", "isn't", "they're", "we've", "I'm"):
        assert cond.transform(text) == text, (
            f"apostrophe in {text!r} was incorrectly stripped"
        )
    # In context:
    assert cond.transform("she said, don't do that.") == "she said don't do that"


def test_punct_strip_collapses_whitespace_introduced_by_replacement():
    """A multi-character punctuation cluster must not leave multiple spaces."""
    cond = get_condition("punct_strip")
    assert cond.transform("hello,,,world") == "hello world"
    assert cond.transform("a -- b") == "a b"
    assert cond.transform("  leading,  spaces.  ") == "leading spaces"


def test_punct_strip_preserves_digits_and_underscores():
    """Digits and underscores are word characters and must survive."""
    cond = get_condition("punct_strip")
    assert cond.transform("call 999.") == "call 999"
    assert cond.transform("file_name.txt") == "file_name txt"


def test_punct_strip_is_idempotent():
    """A second application must produce the same string."""
    cond = get_condition("punct_strip")
    inputs = [
        "",
        "the cat sat on the mat",
        "Hello, world!",
        "don't do that.",
        "  multiple   spaces ,, here  ",
    ]
    for s in inputs:
        once  = cond.transform(s)
        twice = cond.transform(once)
        assert once == twice, (
            f"punct_strip not idempotent on {s!r}: "
            f"once={once!r}, twice={twice!r}"
        )


# ---------------------------------------------------------------------------
# Behavioural tests for case_fold
# ---------------------------------------------------------------------------
def test_case_fold_applies_to_reference():
    """Case folding must be symmetric (both hypothesis and reference)."""
    assert get_condition("case_fold").apply_to_reference is True


def test_case_fold_handles_empty_string():
    assert get_condition("case_fold").transform("") == ""


def test_case_fold_lowercases_ascii():
    cond = get_condition("case_fold")
    cases = [
        ("HELLO WORLD", "hello world"),
        ("Hello, World!", "hello, world!"),
        ("MixED CaSe TeXt", "mixed case text"),
        ("ALREADY lower", "already lower"),
    ]
    for inp, expected in cases:
        out = cond.transform(inp)
        assert out == expected, (
            f"case_fold({inp!r}) = {out!r}, expected {expected!r}"
        )


def test_case_fold_is_identity_on_lowercase():
    """Text already in lowercase must pass through unchanged."""
    cond = get_condition("case_fold")
    text = "the cat sat on the mat and looked at the window"
    assert cond.transform(text) == text


def test_case_fold_preserves_punctuation_and_digits():
    """Case folding must not touch punctuation, digits or whitespace."""
    cond = get_condition("case_fold")
    assert cond.transform("CALL 999, NOW!") == "call 999, now!"
    assert cond.transform("Don't") == "don't"
    assert cond.transform("  Two   Spaces  ") == "  two   spaces  "


def test_case_fold_uses_str_lower_not_casefold():
    """str.lower is used rather than str.casefold so that additional
    Unicode mappings such as German eszett to ss do not occur."""
    cond = get_condition("case_fold")
    # 'ß'.lower() is 'ß'; 'ß'.casefold() is 'ss'.  The condition must
    # match the former behaviour to remain a pure case-fold operation.
    assert cond.transform("ß") == "ß"
    assert cond.transform("STRAßE") == "straße"


def test_case_fold_is_idempotent():
    """A second application must produce the same string."""
    cond = get_condition("case_fold")
    inputs = [
        "",
        "Hello, World!",
        "ALL CAPS",
        "MixED",
        "already lower",
    ]
    for s in inputs:
        once  = cond.transform(s)
        twice = cond.transform(once)
        assert once == twice, (
            f"case_fold not idempotent on {s!r}: "
            f"once={once!r}, twice={twice!r}"
        )


# ---------------------------------------------------------------------------
# Tests for the atomic production-pipeline stages registered in Phase B
# ---------------------------------------------------------------------------
# The conditions added below mirror the seven atomic stages of
# transcription.clean_transcription_text together with the unicode
# strip that precedes them and the pipeline_full composite that
# chains all of them.  The tests check that the registered transform
# really does call into the same code path as the desktop pipeline,
# that the headline composite matches a hand-rolled composition of
# the stages, and that every registered condition is idempotent and
# safe on the empty string.

import transcription as _transcription_for_tests


# The ordered list of stages that pipeline_full must apply, in
# production order.  Matches the order in transcription.py and in the
# narrative description carried by the pipeline_full Condition.
_PIPELINE_FULL_STAGES = (
    "unicode_strip",
    "repetition_fix",
    "undefined_tag",
    "filler_bracket",
    "contraction_fix",
    "common_phrase_fix",
    "whitespace_normalise",
    "sentence_capitalise",
    "pronoun_i_fix",
    "punct_space_fix",
)


_PRODUCTION_FIXTURES = (
    "",
    "um the cat sat on the mat",
    "i think im going to the store. dont you?",
    "   undefined  things happen   here  ",
    "isn t it nice? he said. i feel like im flying.",
    "um um uh er ah the the the cat",
    "kind of you know i mean sort of",
    "[um] the cat said hello",
    'they said "hello" and (looked away) .',
    "we cant we dont we wont",
)


def test_registry_covers_production_stages():
    """Every atomic stage of clean_transcription_text plus
    remove_emojis_and_unicode_artifacts and detect_and_fix_repetitions
    must have a registered condition.  This guards against silent
    drift between the desktop pipeline and the benchmark."""
    stage_names = {f.__name__.lstrip("_") for f in _transcription_for_tests.CLEAN_TEXT_STAGES}
    registered = {c.name for c in list_conditions()}
    missing = stage_names - registered
    assert not missing, (
        f"Production clean-text stages without a registered condition: "
        f"{sorted(missing)}.  Registered: {sorted(registered)}."
    )
    for extra in ("unicode_strip", "repetition_fix", "pipeline_full"):
        assert extra in registered, f"Missing required condition: {extra}"


def test_pipeline_full_matches_production():
    """pipeline_full must produce exactly the text that transcription.py's
    own post-processing produces with --fix-spurious-repetitions, on every
    fixture (EWER-04: the composite is the opt-in configuration)."""
    cond = get_condition("pipeline_full")
    for s in _PRODUCTION_FIXTURES:
        production, _log = _transcription_for_tests.postprocess_transcript_text(
            s, "english", fix_repetitions=True)
        via = cond.transform(s)
        assert via == production, (
            f"pipeline_full diverges from production on {s!r}: "
            f"via={via!r}, production={production!r}"
        )


def test_pipeline_full_is_not_the_default_configuration():
    """A default run omits repetition repair, and pipeline_full does not.

    The composite used to be described as what every end-user receives;
    on a looping hypothesis the two configurations differ, which is why
    the description now names the flag.
    """
    looped = " ".join(["the cat sat on the mat"] * 12)
    default, _log = _transcription_for_tests.postprocess_transcript_text(
        looped, "english", fix_repetitions=False)
    assert get_condition("pipeline_full").transform(looped) != default
    assert "--fix-spurious-repetitions" in \
        get_condition("pipeline_full").description


def test_pipeline_full_is_ordered_composition():
    """pipeline_full must equal the chained application of the
    registered atomic conditions in the declared production order."""
    cond = get_condition("pipeline_full")
    transforms = [get_condition(n).transform for n in _PIPELINE_FULL_STAGES]
    for s in _PRODUCTION_FIXTURES:
        chained = s
        for fn in transforms:
            chained = fn(chained)
        assert cond.transform(s) == chained, (
            f"pipeline_full disagrees with chained atomic application on {s!r}"
        )


def test_all_conditions_idempotent():
    """Every registered condition must satisfy f(f(x)) == f(x).
    Catches regressions such as the original filler_bracket regex
    that produced [[um]] on a second pass."""
    failures = []
    for cond in list_conditions():
        if cond.name == "whisper_norm" and not _whisper_norm_available():
            continue
        for s in _PRODUCTION_FIXTURES:
            once = cond.transform(s)
            twice = cond.transform(once)
            if once != twice:
                failures.append((cond.name, s, once, twice))
    assert not failures, (
        "Non-idempotent conditions detected: "
        + "\n".join(
            f"  {name} on {s!r}: once={once!r}, twice={twice!r}"
            for name, s, once, twice in failures
        )
    )


def test_all_conditions_empty_string_safe():
    """Every registered condition must accept the empty string and
    return a string without raising."""
    for cond in list_conditions():
        if cond.name == "whisper_norm" and not _whisper_norm_available():
            continue
        result = cond.transform("")
        assert isinstance(result, str), (
            f"Condition {cond.name!r} returned non-string on empty input: "
            f"{type(result).__name__}"
        )


def test_unicode_strip_removes_artefacts_but_keeps_letters():
    cond = get_condition("unicode_strip")
    assert cond.apply_to_reference is False
    # The emoji is removed and adjacent whitespace is collapsed by the
    # same pass, so two ASCII tokens that flanked the emoji end up
    # separated by a single space.
    assert cond.transform("hello 🌍 world") == "hello world"
    assert cond.transform("naive cafe") == "naive cafe"
    # Plain ASCII input is left unchanged.
    assert cond.transform("plain ascii text") == "plain ascii text"
    # ASCII punctuation and symbols are untouched.
    assert cond.transform("cost $5 and 50% of it - really?") == \
        "cost $5 and 50% of it - really?"


def test_unicode_strip_preserves_diacritics():
    """Regression: the stage used to strip every non-ASCII codepoint, which
    silently destroyed the diacritics of any language that writes them
    (``était`` became ``tait``, ``Gerät`` became ``Gert``).  Measured on
    FLEURS, that corrupted the composite's output badly enough to roughly
    triple word error rate in French, German and Italian, while leaving
    Dutch -- which uses almost no diacritics -- untouched.  Letters and
    combining marks must survive whatever their script.
    """
    cond = get_condition("unicode_strip")
    for text in (
        "l'homme n'était pas là, c'est désagréable",     # French
        "ein tolles Gerät für die Universität",          # German
        "non era lì ma è tornato perché voleva",         # Italian
        "zażółć gęślą jaźń w Łodzi",                     # Polish
        "el niño comió una manzana pequeña en España",   # Spanish
    ):
        assert cond.transform(text) == text
    # An emoji is still stripped, without taking the accent with it.
    assert cond.transform("café 😀 ouvert") == "café ouvert"


def test_language_is_english_recognises_variants():
    from transcription import _language_is_english
    assert _language_is_english("english") is True
    assert _language_is_english("en") is True
    assert _language_is_english("en_us") is True
    assert _language_is_english("en-GB") is True
    assert _language_is_english(None) is True      # default backwards-compat
    assert _language_is_english("") is True
    assert _language_is_english("german") is False
    assert _language_is_english("french") is False


def test_clean_text_gates_english_only_stages():
    """The English-lexical stages are skipped on non-English text, so the
    German preposition 'im' is not rewritten to "I'm", while English keeps
    the full pipeline and the no-language default stays byte-for-byte."""
    from transcription import clean_transcription_text
    german = "das haus im jahr und im winter"
    english = "i think im going and its cold"
    # Non-English: 'im' survives (contraction_fix gated out).
    assert "I'm" not in clean_transcription_text(german, "german")
    assert "im jahr" in clean_transcription_text(german, "german")
    # English: 'im' -> "I'm", because 'im' is not an English word.
    out_en = clean_transcription_text(english, "english")
    assert "I'm going" in out_en
    # 'its' is left alone. This test used to require 'its' -> "it's",
    # which is the corruption the contraction table has since dropped:
    # rewriting the possessive is wrong far more often than it is right.
    assert "its cold" in out_en and "it's cold" not in out_en
    # The no-language default is exactly the English path.
    assert clean_transcription_text(english) == out_en


def test_normalise_language_token_handles_whisper_shapes():
    from transcription import _normalise_language_token
    assert _normalise_language_token("german") == "german"
    assert _normalise_language_token("  German ") == "german"
    assert _normalise_language_token("<|de|>") == "de"
    assert _normalise_language_token("<|en|>") == "en"
    assert _normalise_language_token(None) is None
    assert _normalise_language_token("") is None
    assert _normalise_language_token(123) is None


def test_detected_language_reads_top_level_and_chunks():
    """The top-level key (which transcribe_audio_only sets from
    detect_audio_language) wins; chunk values, the shape some transformers
    versions attach, are the fallback and are decided by majority."""
    from transcription import _detected_language
    # Top-level value wins outright.  The <|de|> form is what
    # detect_audio_language recovers from generation_config.lang_to_id.
    assert _detected_language({"text": "x", "language": "german"}) == "german"
    # The code is mapped to Whisper's name when transformers supplies the
    # table (T2-14), and kept as it is without transformers.
    assert _detected_language({"text": "x", "language": "<|de|>"}) in {
        "german", "de"}
    # Falls back to chunks.  The transformers ASR pipeline writes the full
    # lower-case language name on each chunk, so that is the shape tested.
    result = {"text": "x", "chunks": [
        {"text": "a", "language": "german"},
        {"text": "b", "language": "german"},
        {"text": "c", "language": "english"},   # one odd chunk
    ]}
    assert _detected_language(result) == "german"
    # A chunk whose language is None (what transformers 4.48-5.6 actually
    # produces) is ignored rather than being taken as a language.
    assert _detected_language({"text": "x", "chunks": [
        {"text": "a", "language": None}, {"text": "b", "language": None},
    ]}) is None
    # Nothing reported, or an unexpected shape, yields None.
    assert _detected_language({"text": "x"}) is None
    assert _detected_language({"text": "x", "chunks": []}) is None
    assert _detected_language({"text": "x", "chunks": "not-a-list"}) is None
    assert _detected_language("not a dict") is None
    assert _detected_language(None) is None


def test_detected_language_tie_breaks_away_from_english():
    """A tie must not resolve to English: concluding 'English' wrongly
    re-enables the English-only stages on a non-English transcript."""
    from transcription import _detected_language
    tied = {"text": "x", "chunks": [
        {"text": "a", "language": "english"},
        {"text": "b", "language": "german"},
    ]}
    assert _detected_language(tied) == "german"
    # Order must not change the outcome.
    tied_rev = {"text": "x", "chunks": list(reversed(tied["chunks"]))}
    assert _detected_language(tied_rev) == "german"


def test_language_is_english_survives_odd_input():
    """The classifier is on the detection path, so it must never raise."""
    from transcription import _language_is_english
    assert _language_is_english(123) is True      # unusable -> English default
    assert _language_is_english(["de"]) is True
    assert _language_is_english("   ") is True


def test_exclude_common_words_defaults_to_auto():
    """process_audio_file takes None for 'decide from the language actually
    used', so an auto-detected language drives the name-masking default too."""
    import inspect
    from transcription import process_audio_file, _language_is_english
    default = inspect.signature(process_audio_file).parameters[
        "exclude_common_words"].default
    assert default is None, "None is the sentinel meaning 'resolve from language'"
    # The resolution the function performs: filter common English words only
    # when the transcript is English.
    assert _language_is_english("english") is True
    assert _language_is_english("german") is False


def test_pronoun_i_fix_is_gated_and_english_is_unchanged():
    """The pronoun rule is English-only: 'i' is the Italian plural article,
    and capitalising it there corrupts the transcript."""
    from transcription import clean_transcription_text
    # The 'i' must sit mid-sentence to isolate the pronoun rule: a
    # sentence-initial 'i' is capitalised in Italian too, by the ungated
    # sentence_capitalise stage.
    italian = "sono qui i libri di paolo"
    assert "i libri" in clean_transcription_text(italian, "italian")
    # The same sentence under English gets the pronoun rule, showing the
    # gate is what makes the difference rather than the input.
    assert "I libri" in clean_transcription_text(italian, "english")
    # English still capitalises the pronoun mid-sentence, as before the split.
    assert "and I think" in clean_transcription_text("yes and i think so", "english")


def test_detected_language_drives_the_gate():
    """A detected non-English language gates the English-only stages, which
    is the path a user gets when they do not pass --language."""
    from transcription import _detected_language, clean_transcription_text
    german_result = {"text": "das haus im jahr", "language": "german"}
    detected = _detected_language(german_result)
    assert "I'm" not in clean_transcription_text(german_result["text"], detected)
    # An English detection keeps the full English pipeline.
    english_result = {"text": "the house im in", "language": "english"}
    assert "I'm" in clean_transcription_text(
        english_result["text"], _detected_language(english_result))
    # No detection at all falls back to the English default, unchanged.
    assert clean_transcription_text("the house im in", None) == \
        clean_transcription_text("the house im in")


def test_pipeline_full_is_language_aware():
    cond = get_condition("pipeline_full")
    assert cond.language_aware is True
    # The composite gates on language just as clean_transcription_text does.
    assert "I'm" not in cond.transform("das haus im jahr", "german")
    assert "I'm" in cond.transform("the house im in", "english")
    # Default (no language) matches the English call.
    assert cond.transform("the house im in") == \
        cond.transform("the house im in", "english")


def test_undefined_tag_marks_undefin_artefacts():
    cond = get_condition("undefined_tag")
    assert cond.apply_to_reference is False
    # The undefined-tag stage marks unbracketed undefin* tokens.
    assert "[undefined]" in cond.transform("the undefined thing")
    # Already-bracketed tokens are left in place by virtue of the
    # word-boundary anchors used in the underlying regex.
    assert cond.transform("[undefined] thing") == "[undefined] thing"


def test_filler_bracket_wraps_fillers_once():
    cond = get_condition("filler_bracket")
    assert cond.apply_to_reference is False
    assert cond.transform("um the cat") == "[um] the cat"
    # Idempotence on bracketed input is the load-bearing property.
    assert cond.transform("[um] the cat") == "[um] the cat"
    assert cond.transform("um um uh") == "[um] [um] [uh]"


def test_contraction_fix_repairs_apostrophes():
    cond = get_condition("contraction_fix")
    assert cond.apply_to_reference is False
    assert cond.transform("i think im going. dont you?") == \
        "i think I'm going. don't you?"
    # Space-split tokeniser artefacts must also be repaired.
    assert cond.transform("isn t it nice") == "isn't it nice"


def test_contraction_fix_never_rewrites_correct_english():
    """The repair must not fire on words that are already correct.

    Seven keys in the table were themselves ordinary English words, so
    the stage rewrote correct text into different text: "they were
    happy" became "they we're happy" and "its tail" became "it's tail".
    On LibriSpeech test-clean that damaged 228 utterances and improved
    none, and it accounted for the entire measured cost of the
    post-processing layer. Sentences below contain no recogniser
    artefact, so the stage must return each one unchanged.
    """
    cond = get_condition("contraction_fix")
    correct_english = [
        "they were happy to see us",
        "the dog wagged its tail",
        "we were told that its purpose was clear",
        "she shed a tear and they wed in june",
        "his id was checked at the door",
        "as is his wont he spoke in cant",
        "there were three of them",
    ]
    for sentence in correct_english:
        assert cond.transform(sentence) == sentence, (
            f"contraction_fix corrupted correct English: {sentence!r} -> "
            f"{cond.transform(sentence)!r}")


def test_contraction_table_holds_no_ordinary_english_word():
    """The invariant itself, checked against the table rather than samples.

    A spot-check only catches the words someone thought of. Every key is
    a bare ``\\bword\\b`` pattern, so the key can be read back out and
    tested for being a real word in its own right.
    """
    import transcription

    ordinary = {
        "were", "its", "wont", "cant", "shed", "wed", "id",
        "well", "hell", "shell", "ill", "lets", "marks", "aid", "led",
    }
    offenders = []
    for pattern in transcription._CONTRACTIONS:
        word = pattern.replace(r"\b", "")
        if word in ordinary:
            offenders.append(word)
    assert offenders == [], (
        "contraction_fix would rewrite these ordinary English words: "
        f"{offenders}")


def test_common_phrase_fix_capitalises_i():
    cond = get_condition("common_phrase_fix")
    assert cond.apply_to_reference is False
    # The hedge "i mean" is rewritten to "I mean".
    assert cond.transform("i mean it") == "I mean it"


def test_whitespace_normalise_collapses_runs():
    cond = get_condition("whitespace_normalise")
    assert cond.apply_to_reference is False
    # Internal runs of whitespace collapse to a single space; the stage
    # does not strip trailing whitespace because punctuation tidying is
    # handled by punct_space_fix later in the pipeline.
    assert cond.transform("hello   world") == "hello world"
    assert cond.transform("a , b , c") == "a, b, c"


def test_sentence_capitalise_capitalises_initial_and_i():
    cond = get_condition("sentence_capitalise")
    assert cond.apply_to_reference is False
    assert cond.transform("hello world") == "Hello world"
    assert cond.transform("i am here") == "I am here"
    # An already-capitalised sentence is left alone.
    assert cond.transform("Hello world") == "Hello world"


def test_punct_space_fix_normalises_punctuation():
    cond = get_condition("punct_space_fix")
    assert cond.apply_to_reference is False
    # The stage removes the space before a comma or full stop and puts one
    # after it. Exact outputs, because an identity function would pass a
    # looser check.
    assert cond.transform("hello , world .") == "hello, world."
    assert cond.transform("hello ,world") == "hello, world"
    assert cond.transform("hi .there") == "hi. there"


def test_punct_space_fix_keeps_numbers_whole():
    """A mark between two digits is part of the number (T1-04): the stage
    once turned ``3.5`` into ``3. 5``. Scoring was never affected, since
    normalise_text turns the mark into a space either way."""
    cond = get_condition("punct_space_fix")
    assert cond.transform("3.5") == "3.5"
    assert cond.transform("It rose 3.5 percent to $1,000 at 10:30.") == \
        "It rose 3.5 percent to $1,000 at 10:30."


def test_pipeline_full_does_not_apply_to_reference():
    cond = get_condition("pipeline_full")
    assert cond.apply_to_reference is False
