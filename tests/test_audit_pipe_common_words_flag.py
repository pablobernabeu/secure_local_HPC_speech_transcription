"""The common-word filter for name masking can be switched either way.

Audit finding T3-12: the flag was ``store_true`` with ``default=None``, so
no spelling could turn the filter off for an English run and the
documented ``=false`` form was an argparse error.
"""

from __future__ import annotations

import contextlib
import inspect
import io
import sys

import pytest


@pytest.mark.parametrize("flag, expected", [
    ([], None),
    (["--exclude-common-english-words-from-name-masking"], True),
    (["--no-exclude-common-english-words-from-name-masking"], False),
])
def test_flag_values(transcription_module, monkeypatch, flag, expected):
    m = transcription_module
    signature = inspect.signature(m.process_audio_file)
    captured = {}

    def fake(*args, **kwargs):
        captured.update(signature.bind(*args, **kwargs).arguments)
        return True

    monkeypatch.setattr(m, "process_audio_file", fake)
    monkeypatch.setattr(sys, "argv", ["transcription.py", "rec.wav", *flag])
    with contextlib.redirect_stdout(io.StringIO()):
        with pytest.raises(SystemExit) as exc:
            m.main()
    assert exc.value.code == 0
    assert captured['exclude_common_words'] is expected
