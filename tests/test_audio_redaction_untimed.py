"""audio_redaction refuses to leave a name audible without saying so.

Review finding SC-18: find_name_spans skips every word without both
timestamps, so a name word Whisper left untimed stayed audible while the
tool wrote its output and exited 0, and a redacted transcript whose
segment text held more placeholders than its timed words was reported only
when no timed word carried one at all. A second finding of the review of
29 October 2026: main() promised exit 2 for a transcript it cannot read,
but a file in another encoding or a top-level JSON list ended the run with
a traceback and exit 1.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import sys
from pathlib import Path

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import audio_redaction as ar

SR = 1000


def _stub_mask(text: str) -> str:
    """Mask 'Aaron' the way the real masker does, keeping punctuation."""
    return " ".join("[NAME]" + "".join(re.findall(r"[^\w]", w))
                    if re.sub(r"[^\w]", "", w) == "Aaron" else w
                    for w in text.split())


def _write_audio(path: Path, seconds: float = 3.0) -> None:
    ar.write_wav(path, np.full(int(seconds * SR), 0.5, dtype=np.float32), SR)


def _raw_with_untimed_final_name() -> dict:
    return {"language": "english", "segments": [{"text": "Hello Aaron, bye Aaron.", "words": [
        {"word": " Hello", "start": 0.0, "end": 0.5},
        {"word": " Aaron,", "start": 0.5, "end": 1.0},
        {"word": " bye", "start": 1.0, "end": 1.5},
        # The final chunk's word, which Whisper left without an end.
        {"word": " Aaron.", "start": 1.5, "end": None},
    ]}]}


def test_an_untimed_name_word_in_a_raw_transcript_is_counted():
    assert ar.count_untimed_names(_raw_with_untimed_final_name(), _stub_mask) == 1
    # The timed one is still a span.
    assert ar.find_name_spans(_raw_with_untimed_final_name(), _stub_mask) == [(0.5, 1.0)]


def test_a_raw_segment_without_words_counts_its_names():
    payload = {"segments": [{"text": "Hello Aaron."}]}
    assert ar.count_untimed_names(payload, _stub_mask) == 1
    assert ar.count_untimed_names({"text": "Aaron and Aaron"}, _stub_mask) == 2


def _run(tmp_path, payload, *extra, name="talk_transcript.json"):
    transcript = tmp_path / name
    transcript.write_text(json.dumps(payload), encoding="utf-8")
    audio, out = tmp_path / "talk.wav", tmp_path / "out.wav"
    _write_audio(audio)
    rc = ar.main(["--audio", str(audio), "--transcript", str(transcript),
                  "--out", str(out), "--pad", "0", *extra])
    return rc, out


def test_the_cli_refuses_an_untimed_name_in_a_raw_transcript(tmp_path, monkeypatch,
                                                              capsys):
    monkeypatch.setattr(ar, "_rebuild_masker",
                        lambda *a, **k: (_stub_mask, "a stub masker"))
    rc, out = _run(tmp_path, _raw_with_untimed_final_name())
    assert rc == 3 and not out.exists()
    err = capsys.readouterr().err
    assert "1 name word(s) without word timestamps" in err
    assert "--allow-untimed-names" in err

    rc, out = _run(tmp_path, _raw_with_untimed_final_name(), "--allow-untimed-names")
    assert rc == 0 and out.exists()
    captured = capsys.readouterr()
    assert "Warning: 1 name word(s) without word timestamps" in captured.err
    assert "names without word timestamps, left audible: 1" in captured.out
    samples, _ = ar.read_wav(out)
    assert np.all(samples[500:1000] == 0.0)          # the timed name


def _redacted_with_more_placeholders_than_timed_words() -> dict:
    return {"redacted": True, "segments": [{"text": "[NAME] met [NAME].", "words": [
        {"word": " [NAME]", "start": 0.0, "end": 0.5},
        {"word": " met", "start": 0.5, "end": 1.0},
        {"word": " [NAME].", "start": None, "end": None},
    ]}]}


def test_the_cli_refuses_placeholders_no_timed_word_carries(tmp_path, capsys):
    payload = _redacted_with_more_placeholders_than_timed_words()
    assert ar.count_untimed_names(payload) == 1
    rc, out = _run(tmp_path, payload, name="talk_transcript_redacted.json")
    assert rc == 3 and not out.exists()
    assert ("1 placeholder(s) in the segment text carried by no timed word"
            in capsys.readouterr().err)
    rc, out = _run(tmp_path, payload, "--allow-untimed-names",
                   name="talk_transcript_redacted.json")
    assert rc == 0 and out.exists()


def test_a_title_kept_in_the_redacted_words_raises_no_alarm(transcription_module,
                                                            tmp_path, capsys):
    """The pipeline's own redacted set: the segment text has [TITLE], the
    word list keeps "Dr", and only [SURNAME] is a name."""
    with contextlib.redirect_stdout(io.StringIO()):
        mask_fn, _ = transcription_module.create_enhanced_name_masker()
    words = ["It", "was", "signed", "by", "Dr", "Smith", "today."]
    chunks = [{"text": f" {w}", "timestamp": (i * 0.4, i * 0.4 + 0.4)}
              for i, w in enumerate(words)]
    with contextlib.redirect_stdout(io.StringIO()):
        written = transcription_module.write_timestamped_outputs(
            {"text": " ".join(words), "chunks": chunks},
            str(tmp_path), "talk", str(tmp_path / "talk.wav"), mask_fn=mask_fn)
    redacted = json.loads(Path(written["json_redacted"]).read_text("utf-8"))
    assert "[TITLE]" in redacted["segments"][0]["text"]       # the premise
    assert ar.count_untimed_names(redacted) == 0
    audio, out = tmp_path / "talk.wav", tmp_path / "out.wav"
    _write_audio(audio)
    assert ar.main(["--audio", str(audio), "--transcript", written["json_redacted"],
                    "--out", str(out)]) == 0
    assert "names without word timestamps, left audible: 0" in capsys.readouterr().out


@pytest.mark.parametrize("raw", [
    json.dumps({"segments": [], "text": "Café"}).encode("utf-16"),
    '{"text": "Café Aaron", "segments": []}'.encode("cp1252"),
    b'[{"text": "Aaron"}]',
    b'{"segments": {"0": {"text": "Aaron"}}}',
    b'{"segments": [{"words": "Aaron"}]}',
])
def test_an_unreadable_transcript_exits_2_without_a_traceback(tmp_path, capsys, raw):
    transcript = tmp_path / "t.json"
    transcript.write_bytes(raw)
    audio, out = tmp_path / "a.wav", tmp_path / "out.wav"
    _write_audio(audio)
    assert ar.main(["--audio", str(audio), "--transcript", str(transcript),
                    "--out", str(out)]) == 2
    assert not out.exists()
    assert "could not read the transcript" in capsys.readouterr().err


def test_an_unreadable_redacted_sibling_exits_2(tmp_path, capsys):
    raw = tmp_path / "talk_transcript.json"
    raw.write_text(json.dumps(_raw_with_untimed_final_name()), encoding="utf-8")
    sibling = tmp_path / "talk_transcript_redacted.json"
    sibling.write_bytes(json.dumps({"redacted": True, "segments": []})
                        .encode("utf-16"))
    audio, out = tmp_path / "talk.wav", tmp_path / "out.wav"
    _write_audio(audio)
    assert ar.main(["--audio", str(audio), "--transcript", str(raw),
                    "--out", str(out)]) == 2
    assert not out.exists()
    assert f"could not read {sibling}" in capsys.readouterr().err
