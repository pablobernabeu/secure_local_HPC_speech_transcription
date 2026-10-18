"""Tests for diarisation tag stripping in WER normalisation.

normalise_text needs no jiwer (evaluation.wer defers that import to the
scoring step), so these run everywhere.
"""

from __future__ import annotations

from evaluation import wer


def test_bracketed_speaker_tags_removed():
    text = "[SPEAKER_00] hello world [SPEAKER_01] goodbye"
    out = wer.normalise_text(text)
    assert "speaker" not in out
    assert "hello world goodbye" in out


def test_bare_speaker_tags_with_colon_removed():
    text = "SPEAKER_00: hello\nSPEAKER_01: goodbye"
    out = wer.normalise_text(text)
    assert "speaker" not in out
    assert "hello" in out
    assert "goodbye" in out


def test_hyphenated_speaker_tags_removed():
    text = "SPEAKER-01 hello SPEAKER-02 goodbye"
    out = wer.normalise_text(text)
    assert "speaker" not in out


def test_case_insensitive_match():
    text = "speaker_00 hello Speaker_01 world"
    out = wer.normalise_text(text)
    assert "speaker" not in out
    assert "hello" in out and "world" in out


def test_speaker_strip_does_not_eat_real_words():
    # Words like "speaker" without an index must NOT be stripped.
    text = "the speaker said hello"
    out = wer.normalise_text(text)
    assert "speaker" in out
    assert out == "the speaker said hello"


def test_wer_score_unchanged_by_speaker_tags():
    import pytest
    pytest.importorskip("jiwer")
    ref = wer.normalise_text("hello world goodbye")
    hyp_plain = "hello world goodbye"
    hyp_tagged = "[SPEAKER_00] hello world [SPEAKER_01] goodbye"
    n_plain = wer.normalise_text(hyp_plain)
    n_tagged = wer.normalise_text(hyp_tagged)
    assert n_plain == n_tagged
    assert wer.compute_metrics(ref, n_tagged)["wer"] == 0.0


def test_uppercase_reference_text_is_lowercased():
    # AMI (Edinburgh Meeting Corpus) stores reference transcriptions in
    # upper case (Kaldi AMI S5 convention).  normalise_text must lowercase
    # it before WER scoring so that hypothesis and reference are compared
    # on equal footing.
    text = "THE QUICK BROWN FOX JUMPED OVER THE LAZY DOG"
    assert wer.normalise_text(text) == "the quick brown fox jumped over the lazy dog"
