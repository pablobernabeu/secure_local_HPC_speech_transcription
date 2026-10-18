"""Language selection for the name dictionary fails loudly, never silently.

Audit findings T1-06 and T3-02: a capitalised, ISO-coded, misspelt or empty
language list, or a missing ``data/curated_names.csv``, used to load an
empty dictionary. Nothing was masked while the transcript header still said
names had been masked.
"""

from __future__ import annotations

import contextlib
import inspect
import io
import sys

import pytest

SENTENCE = "I told Sarah and John Smith."
MASKED = "I told [NAME] and [NAME] [SURNAME]."


def _masker(m, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        mask, _ = m.create_enhanced_name_masker(**kwargs)
    return mask


def test_languages_come_from_the_csv(transcription_module):
    m = transcription_module
    assert m.curated_name_languages() == sorted([
        'arabic', 'chinese', 'english', 'french', 'german', 'hindi',
        'italian', 'polynesian', 'spanish'])


def test_lower_case_lists_behave_as_before(transcription_module):
    m = transcription_module
    assert _masker(m)(SENTENCE) == MASKED
    assert _masker(m, selected_languages=['english'])(SENTENCE) == MASKED


def test_capitalised_language_is_normalised(transcription_module):
    m = transcription_module
    assert _masker(m, selected_languages=['English'])(SENTENCE) == MASKED
    assert _masker(m, selected_languages=[' ENGLISH ', 'english'])(SENTENCE) \
        == MASKED


@pytest.mark.parametrize("langs", [[], ['spansh'], ['en'], ['english', 'polish']])
def test_empty_or_unknown_language_raises(transcription_module, langs):
    m = transcription_module
    with pytest.raises(ValueError, match="Choose from"):
        _masker(m, selected_languages=langs)


def test_missing_csv_raises(transcription_module, tmp_path, monkeypatch):
    m = transcription_module
    monkeypatch.setattr(m, "CURATED_NAMES_CSV", tmp_path / "absent.csv")
    with pytest.raises(FileNotFoundError, match="curated name dictionary"):
        _masker(m)


def test_malformed_csv_raises(transcription_module, tmp_path, monkeypatch):
    m = transcription_module
    bad = tmp_path / "names.csv"
    bad.write_text("nombre,tipo\nSarah,first\n", encoding="utf-8")
    monkeypatch.setattr(m, "CURATED_NAMES_CSV", bad)
    with pytest.raises(RuntimeError, match="could not be read"):
        _masker(m)


def test_empty_dictionary_after_exclusions_raises(transcription_module,
                                                  tmp_path, monkeypatch):
    m = transcription_module
    tiny = tmp_path / "names.csv"
    tiny.write_text("name,type,language\nSarah,first,english\n",
                    encoding="utf-8")
    monkeypatch.setattr(m, "CURATED_NAMES_CSV", tiny)
    with pytest.raises(ValueError, match="dictionary is empty"):
        _masker(m, excluded_names={"sarah"})


def _run_main(m, monkeypatch, argv):
    captured = {}
    signature = inspect.signature(m.process_audio_file)

    def fake_process(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        captured['selected_languages'] = bound.arguments['selected_languages']
        return True

    monkeypatch.setattr(m, "process_audio_file", fake_process)
    monkeypatch.setattr(sys, "argv", ["transcription.py", "rec.wav", *argv])
    with contextlib.redirect_stdout(io.StringIO()), \
            contextlib.redirect_stderr(io.StringIO()):
        with pytest.raises(SystemExit) as exc:
            m.main()
    return exc.value.code, captured


def test_cli_lower_cases_languages(transcription_module, monkeypatch):
    m = transcription_module
    code, captured = _run_main(m, monkeypatch, [
        "--mask-personal-names", "--languages-for-name-masking", "English",
        "Spanish"])
    assert code == 0
    assert captured['selected_languages'] == ['english', 'spanish']


@pytest.mark.parametrize("argv", [
    ["--mask-personal-names", "--languages-for-name-masking"],
    ["--mask-personal-names", "--languages-for-name-masking", "en"],
])
def test_cli_rejects_empty_or_unknown(transcription_module, monkeypatch, argv):
    m = transcription_module
    code, captured = _run_main(m, monkeypatch, argv)
    assert code == 2
    assert captured == {}
