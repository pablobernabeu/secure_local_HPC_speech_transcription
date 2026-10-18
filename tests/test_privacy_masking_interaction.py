"""Tests that name masking and speaker tagging compose correctly.

The two privacy/attribution layers run in sequence inside
``process_audio_file``: speaker labels are applied first, then any
configured name-masking transform. Because the speaker tags have the
form ``[SPEAKER_00]`` they must survive the masking pass unchanged, and
in turn the WER normaliser must be able to strip both tags and any
masked-name placeholders without confusing them with real tokens.

Every test here runs production code: the speaker regex is the one in
``evaluation/wer.py`` and the masker is
``transcription.create_enhanced_name_masker``. An earlier version used a
copied regex and a stand-in masker, so it could not fail on a change to
either (audit finding TESTS-07).
"""

from __future__ import annotations

import ast
import contextlib
import io
import re
from pathlib import Path

import pytest

_WER_PY = Path(__file__).resolve().parent.parent / "evaluation" / "wer.py"
_PLACEHOLDER_RE = re.compile(r"\[(?:NAME|SURNAME|TITLE)\][^\w\s]*")


def _speaker_re() -> re.Pattern:
    """Return ``evaluation.wer._SPEAKER_RE``.

    ``evaluation.wer`` refuses to import without jiwer, which is not
    installed everywhere these tests run, so when the import fails the
    compiled pattern is rebuilt from the assignment in the module source.
    Either way the pattern is the production one, not a copy.
    """
    try:
        from evaluation.wer import _SPEAKER_RE  # noqa: PLC0415
        return _SPEAKER_RE
    except ImportError:
        pass
    tree = ast.parse(_WER_PY.read_text(encoding="utf-8"))
    for node in tree.body:
        if (isinstance(node, ast.Assign)
                and any(getattr(t, "id", None) == "_SPEAKER_RE"
                        for t in node.targets)):
            call = node.value
            pattern = ast.literal_eval(call.args[0])
            flags = re.IGNORECASE if any(
                getattr(a, "attr", None) == "IGNORECASE"
                for a in list(call.args[1:]) + [k.value for k in call.keywords]
            ) else 0
            return re.compile(pattern, flags)
    raise AssertionError("_SPEAKER_RE not found in evaluation/wer.py")


def _masker(module, case_insensitive):
    with contextlib.redirect_stdout(io.StringIO()):
        mask, _ = module.create_enhanced_name_masker(
            case_insensitive=case_insensitive)
    return mask


_ATTRIBUTED = [
    {'start': 0.0, 'end': 0.5, 'text': 'Maria', 'speaker': 'SPEAKER_00'},
    {'start': 0.6, 'end': 1.0, 'text': 'said hi.', 'speaker': 'SPEAKER_00'},
    {'start': 3.0, 'end': 3.5, 'text': 'Ahmed replied', 'speaker': 'SPEAKER_01'},
]


def test_speaker_tag_pattern_does_not_match_plain_words():
    pattern = _speaker_re()
    assert pattern.search("[SPEAKER_00] hi") is not None
    assert pattern.search("SPEAKER_01: hello") is not None
    assert pattern.search("SPEAKER-12 world") is not None
    # Plain English must not match.
    assert pattern.search("the speaker said hello") is None
    assert pattern.search("speakers") is None


def test_format_attributed_text_produces_strippable_tags(transcription_module):
    """The transcript form emitted by attribution must round-trip cleanly
    through the WER normaliser's speaker strip without leaking tags."""
    m = transcription_module
    attributed = [
        {'start': 0.0, 'end': 0.5, 'text': 'hello', 'speaker': 'SPEAKER_00'},
        {'start': 0.6, 'end': 1.0, 'text': 'world', 'speaker': 'SPEAKER_00'},
        {'start': 3.0, 'end': 3.5, 'text': 'goodbye', 'speaker': 'SPEAKER_01'},
    ]
    text = m._format_attributed_text(attributed)
    stripped = re.sub(r"\s+", " ", _speaker_re().sub(" ", text)).strip()
    assert stripped == "hello world goodbye"


@pytest.mark.parametrize("case_insensitive", [False, True])
def test_real_masker_preserves_speaker_tags(transcription_module,
                                            case_insensitive):
    m = transcription_module
    text = m._format_attributed_text(_ATTRIBUTED)
    masked = _masker(m, case_insensitive)(text)
    assert "[SPEAKER_00]" in masked and "[SPEAKER_01]" in masked
    assert "Maria" not in masked and "Ahmed" not in masked
    # Tags first, then placeholders: nothing but the spoken words is left.
    no_tags = _speaker_re().sub(" ", masked)
    cleaned = re.sub(r"\s+", " ", _PLACEHOLDER_RE.sub(" ", no_tags)).strip()
    assert cleaned == "said hi. replied"


@pytest.mark.xfail(strict=True, reason=(
    "The masker splits on whitespace and rejoins with single spaces, so "
    "the blank line between speaker turns is lost when a whole attributed "
    "transcript is masked in one call. The pipeline avoids this by masking "
    "each turn separately (transcription.postprocess_transcript_text, T3-04); "
    "the masker itself still flattens, which this test records."))
def test_real_masker_keeps_turn_separators(transcription_module):
    m = transcription_module
    text = m._format_attributed_text(_ATTRIBUTED)
    assert "\n\n" in text
    assert _masker(m, False)(text).count("\n\n") == text.count("\n\n")
