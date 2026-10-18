"""Speaker-attributed transcripts keep one paragraph per turn.

Audit finding T3-04: the clean-up chain collapses whitespace, and the
masker rejoins sentences with spaces, so every ``\\n\\n`` turn break was lost
and the .txt and .docx came out as a single paragraph.

Audit finding PIPE-01: cleaning each turn on its own capitalised the first
word of a turn that starts mid-sentence, and the masker then took an
ordinary word such as "art" or "mark" for a name.
"""

from __future__ import annotations

import contextlib
import io

import pytest

ATTRIBUTED = ("[SPEAKER_00] Hello there.\n\n"
              "[SPEAKER_01] hi, how are you, Sarah?\n\n"
              "[SPEAKER_00] fine. John Smith says hi.")


@pytest.fixture(scope="module")
def masker(transcription_module):
    with contextlib.redirect_stdout(io.StringIO()):
        return transcription_module.create_enhanced_name_masker()


def test_turn_breaks_survive_cleaning(transcription_module):
    m = transcription_module
    out, log = m.postprocess_transcript_text(ATTRIBUTED, "english",
                                             speaker_turns=True)
    assert out == ("[SPEAKER_00] Hello there.\n\n"
                   "[SPEAKER_01] Hi, how are you, Sarah?\n\n"
                   "[SPEAKER_00] Fine. John Smith says hi.")
    assert log == []


def test_turn_breaks_survive_masking_and_log_is_whole(transcription_module,
                                                      masker):
    m = transcription_module
    mask, get_log = masker
    out, log = m.postprocess_transcript_text(
        ATTRIBUTED, "english", mask_fn=mask, get_log=get_log,
        filename="rec.wav", speaker_turns=True)
    assert out.split("\n\n") == [
        "[SPEAKER_00] Hello there.",
        "[SPEAKER_01] Hi, how are you, [NAME]?",
        "[SPEAKER_00] Fine. [NAME] [SURNAME] says hi.",
    ]
    assert [r['original'] for r in log] == ["Sarah?", "John", "Smith"]
    assert [r['order'] for r in log] == [1, 2, 3]


def test_plain_text_goes_through_the_chain_unchanged(transcription_module,
                                                     masker):
    m = transcription_module
    mask, get_log = masker
    text = "hello there. i met Sarah   today.\n\nwe talked. uh ok"
    expected = m.clean_transcription_text(
        m.detect_and_fix_repetitions(
            m.remove_emojis_and_unicode_artifacts(text)), "english")
    expected = mask(expected, "rec.wav")
    out, log = m.postprocess_transcript_text(
        text, "english", fix_repetitions=True, mask_fn=mask,
        get_log=get_log, filename="rec.wav")
    assert out == expected
    assert [r['original'] for r in log] == ["Sarah"]


def _plain(attributed):
    """The same words without labels or turn breaks, as the plain .txt has."""
    return " ".join(p.split("] ", 1)[1] for p in attributed.split("\n\n"))


@pytest.mark.parametrize("attributed, second_turn", [
    ("[SPEAKER_00] What really matters here is the\n\n"
     "[SPEAKER_01] art of listening.",
     "[SPEAKER_01] art of listening."),
    ("[SPEAKER_00] You should\n\n[SPEAKER_01] mark the date.",
     "[SPEAKER_01] mark the date."),
])
def test_mid_sentence_turn_keeps_its_lower_case_word(transcription_module,
                                                     masker, attributed,
                                                     second_turn):
    m = transcription_module
    mask, get_log = masker
    out, log = m.postprocess_transcript_text(
        attributed, "english", mask_fn=mask, get_log=get_log,
        filename="rec.wav", speaker_turns=True)
    assert out.split("\n\n")[1] == second_turn
    assert log == []
    # The plain transcript of the same run must reach the same decisions.
    _, plain_log = m.postprocess_transcript_text(
        _plain(attributed), "english", mask_fn=mask, get_log=get_log,
        filename="rec.wav")
    assert [r['original'] for r in log] == [r['original'] for r in plain_log]


def test_mid_sentence_turn_keeps_the_english_pronoun_capital(
        transcription_module):
    # "I" is capitalised by the English-only stages wherever it stands, so
    # restoring the raw initial must not undo it.
    m = transcription_module
    out, _ = m.postprocess_transcript_text(
        "[SPEAKER_00] and then\n\n[SPEAKER_01] i think so, and\n\n"
        "[SPEAKER_00] im fine.", "english", speaker_turns=True)
    assert out.split("\n\n")[1:] == ["[SPEAKER_01] I think so, and",
                                      "[SPEAKER_00] I'm fine."]


def test_mid_sentence_turn_keeps_italian_article_lower_case(
        transcription_module):
    # Outside English "i" is an ordinary word (the Italian plural article).
    m = transcription_module
    out, _ = m.postprocess_transcript_text(
        "[SPEAKER_00] ho letto\n\n[SPEAKER_01] i libri.", "italian",
        speaker_turns=True)
    assert out.split("\n\n")[1] == "[SPEAKER_01] i libri."


def test_turn_after_a_closing_quote_still_opens_a_sentence(
        transcription_module):
    m = transcription_module
    out, _ = m.postprocess_transcript_text(
        '[SPEAKER_00] She said "stop."\n\n[SPEAKER_01] right.', "english",
        speaker_turns=True)
    assert out.split("\n\n")[1] == "[SPEAKER_01] Right."


def test_word_document_gets_one_paragraph_per_turn(transcription_module,
                                                   tmp_path):
    m = transcription_module
    docx = pytest.importorskip("docx")
    out, _ = m.postprocess_transcript_text(ATTRIBUTED, "english",
                                           speaker_turns=True)
    path = tmp_path / "t.docx"
    with contextlib.redirect_stdout(io.StringIO()):
        assert m.create_word_document(out, str(path), "rec.wav")
    body = [p.text for p in docx.Document(str(path)).paragraphs
            if p.text.startswith("[SPEAKER_")]
    assert len(body) == 3
