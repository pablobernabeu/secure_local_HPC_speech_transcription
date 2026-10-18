"""transcription.py's --review- options reach the review, or stop the run.

The optional review checks (NEW-12) are confidence.py's. A run passes them
to the review it writes beside the timestamped outputs, so they are
checked before any audio is read: a bad value, or an option that would
change nothing, exits 2 and never reaches process_audio_file.
"""

from __future__ import annotations

import contextlib
import io
import sys

import pytest


@pytest.fixture()
def calls(transcription_module, monkeypatch):
    seen = []

    def _fake_process(*args, **kwargs):
        seen.append(kwargs)
        return True

    monkeypatch.setattr(transcription_module, "process_audio_file", _fake_process)
    return seen


def _main(transcription_module, monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["transcription.py", "rec.wav", *argv])
    with contextlib.redirect_stdout(io.StringIO()), \
            pytest.raises(SystemExit) as exc:
        transcription_module.main()
    return exc.value.code


@pytest.mark.parametrize("argv, message", [
    (["--timestamps", "--review-repeated-passage-window", "30"],
     "needs --review-repeated-passage-words"),
    (["--review-flag-zero-duration"], "need --timestamps or --speaker-attribution"),
    (["--review-repeated-passage-words", "8"],
     "need --timestamps or --speaker-attribution"),
    (["--timestamps", "--review-repeated-passage-words", "1"], "at least two"),
    (["--timestamps", "--review-repeated-passage-words", "8",
      "--review-repeated-passage-window", "0"], "finite and positive"),
])
def test_invalid_review_options_exit_before_any_audio(
        transcription_module, monkeypatch, capsys, calls, argv, message):
    assert _main(transcription_module, monkeypatch, *argv) == 2
    assert not calls
    assert message in capsys.readouterr().err


def test_valid_review_options_are_passed_with_the_default_window(
        transcription_module, monkeypatch, calls):
    code = _main(transcription_module, monkeypatch, "--speaker-attribution",
                 "--review-flag-zero-duration",
                 "--review-repeated-passage-words", "8")
    assert code == 0
    assert calls[0]["review_options"] == {
        'flag_zero_duration': True, 'repeated_passage_words': 8,
        'repeated_passage_window_s': 60.0}


def test_a_run_without_review_options_passes_none(
        transcription_module, monkeypatch, calls):
    assert _main(transcription_module, monkeypatch, "--timestamps") == 0
    assert calls[0]["review_options"] is None
