"""Audit fixes for ``audio_redaction`` (EPRIV-01, EPRIV-13, EPRIV-30).

The first version read word text under ``text`` only, while the pipeline
writes it under ``word``, so on any transcript ``transcription.py`` produced
it found no names, wrote an unredacted copy and exited 0. These tests drive
the span finder and the command line with the real pipeline writers, not
hand-built dicts in the example-artefact shape.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import audio_redaction as ar  # noqa: E402

SR = 1000


def _stub_mask(text: str) -> str:
    """Mask 'Aaron' the way the real masker does, keeping punctuation."""
    out = []
    for word in text.split():
        core = re.sub(r"[^\w]", "", word)
        if core == "Aaron":
            out.append("[NAME]" + "".join(re.findall(r"[^\w]", word)))
        else:
            out.append(word)
    return " ".join(out)


def _chunks():
    return [
        {"text": " Hello", "timestamp": (0.0, 0.5)},
        {"text": " Aaron,", "timestamp": (0.5, 1.0)},
        {"text": " there.", "timestamp": (1.0, 1.5)},
    ]


def _write_pipeline_outputs(module, tmp_path, mask_fn=_stub_mask, chunks=None):
    chunks = chunks or _chunks()
    text = "".join(c["text"] for c in chunks).strip()
    written = module.write_timestamped_outputs(
        {"text": text, "chunks": chunks},
        str(tmp_path), "talk", str(tmp_path / "talk.wav"), mask_fn=mask_fn)
    return Path(written["json"]), Path(written.get("json_redacted", ""))


def _write_audio(path: Path, seconds: float = 2.0) -> None:
    ar.write_wav(path, np.full(int(seconds * SR), 0.5, dtype=np.float32), SR)


def test_word_keys_match_the_pipeline(transcription_module):
    assert tuple(transcription_module._TEXT_KEYS) == ar._WORD_TEXT_KEYS


def test_raw_pipeline_segments_yield_the_name_span(transcription_module):
    segments = transcription_module._build_segments_from_chunks(_chunks())
    assert "word" in segments[0]["words"][0]           # the pipeline's key
    spans = ar.find_name_spans({"segments": segments}, _stub_mask)
    assert spans == [(0.5, 1.0)]


def test_real_masker_on_raw_pipeline_segments(transcription_module):
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        mask_fn, _ = transcription_module.create_enhanced_name_masker()
    segments = transcription_module._build_segments_from_chunks(_chunks())
    assert ar.find_name_spans({"segments": segments}, mask_fn) == [(0.5, 1.0)]


def test_redacted_segments_use_the_placeholders(transcription_module):
    segments = transcription_module._build_segments_from_chunks(_chunks())
    redacted = transcription_module._redact_segments(segments, _stub_mask)
    payload = {"redacted": True, "segments": redacted}
    # No masker needed: the placeholder is the run's decision.
    assert ar.find_name_spans(payload) == [(0.5, 1.0)]


def test_raw_transcript_without_masker_is_refused():
    with pytest.raises(ValueError):
        ar.find_name_spans({"segments": []})


def test_non_masker_bracket_tags_are_not_names():
    payload = {"redacted": True, "segments": [{"words": [
        {"word": "[MUSIC]", "start": 0.0, "end": 0.4},
        {"word": "[SURNAME].", "start": 0.4, "end": 0.9},
    ]}]}
    assert ar.find_name_spans(payload) == [(0.4, 0.9)]


def test_cli_on_raw_json_uses_the_redacted_sibling(transcription_module, tmp_path,
                                                   monkeypatch, capsys):
    raw_json, red_json = _write_pipeline_outputs(transcription_module, tmp_path)
    assert red_json.is_file()
    audio, out = tmp_path / "talk.wav", tmp_path / "out.wav"
    _write_audio(audio)
    # The real masker would silence 'Aaron' too, so without this the test
    # passed with the sibling lookup disabled (PRIV-03).
    monkeypatch.setattr(ar, "_rebuild_masker", lambda *a, **k: pytest.fail(
        "a masker was rebuilt although the redacted sibling exists"))
    rc = ar.main(["--audio", str(audio), "--transcript", str(raw_json),
                  "--out", str(out), "--pad", "0"])
    assert rc == 0
    assert ("decisions: the run's own redaction decisions in "
            "talk_transcript_redacted.json") in capsys.readouterr().out
    samples, _ = ar.read_wav(out)
    assert np.all(samples[500:1000] == 0.0)
    assert np.all(samples[:500] != 0.0) and np.all(samples[1000:] != 0.0)


@pytest.mark.parametrize("flag, expected", [
    ([], True),       # English transcript: on by default, as in transcription.py
    (["--exclude-common-english-words-from-name-masking"], True),
    (["--no-exclude-common-english-words-from-name-masking"], False),
])
def test_the_common_word_filter_can_be_switched_off(
        transcription_module, tmp_path, monkeypatch, flag, expected):
    """PRIV-05: the --no- form transcription.py accepts was an error here."""
    seen = {}

    def fake_masker(**kwargs):
        seen.update(kwargs)
        return _stub_mask, (lambda: [])

    # _rebuild_masker imports from whatever module is registered under
    # the name, which the fixture has made the loaded transcription.py.
    monkeypatch.setattr(sys.modules["transcription"],
                        "create_enhanced_name_masker", fake_masker)
    transcript = tmp_path / "talk_transcript.json"      # no redacted sibling
    transcript.write_text(json.dumps({"language": "english", "segments": [
        {"words": [{"word": " Aaron", "start": 0.5, "end": 1.0}]}]}),
        encoding="utf-8")
    audio, out = tmp_path / "talk.wav", tmp_path / "out.wav"
    _write_audio(audio)
    assert ar.main(["--audio", str(audio), "--transcript", str(transcript),
                    "--out", str(out)] + flag) == 0
    assert seen["exclude_common_words"] is expected


def test_cli_on_redacted_json(transcription_module, tmp_path, capsys):
    _raw, red_json = _write_pipeline_outputs(transcription_module, tmp_path)
    audio, out = tmp_path / "talk.wav", tmp_path / "out.wav"
    _write_audio(audio)
    rc = ar.main(["--audio", str(audio), "--transcript", str(red_json),
                  "--out", str(out), "--pad", "0.1"])
    assert rc == 0
    # The report counts the padded stretch that was actually silenced.
    assert "0.70s of audio" in capsys.readouterr().out


def test_cli_refuses_to_write_an_unredacted_copy(transcription_module, tmp_path):
    chunks = [{"text": " Hello", "timestamp": (0.0, 0.5)},
              {"text": " there.", "timestamp": (0.5, 1.0)}]
    _raw, red_json = _write_pipeline_outputs(
        transcription_module, tmp_path, chunks=chunks)
    audio, out = tmp_path / "talk.wav", tmp_path / "out.wav"
    _write_audio(audio)
    args = ["--audio", str(audio), "--transcript", str(red_json),
            "--out", str(out)]
    assert ar.main(args) == 3
    assert not out.exists()
    assert ar.main(args + ["--allow-empty"]) == 0
    assert out.exists()


def test_cli_fails_when_words_have_no_readable_text(tmp_path):
    transcript = tmp_path / "t.json"
    transcript.write_text(json.dumps({"redacted": True, "segments": [
        {"words": [{"token": "[NAME]", "start": 0.0, "end": 0.5}]}]}),
        encoding="utf-8")
    audio, out = tmp_path / "a.wav", tmp_path / "out.wav"
    _write_audio(audio)
    assert ar.main(["--audio", str(audio), "--transcript", str(transcript),
                    "--out", str(out), "--allow-empty"]) == 3
    assert not out.exists()


def test_cli_fails_when_placeholders_have_no_timed_word(tmp_path):
    transcript = tmp_path / "t.json"
    transcript.write_text(json.dumps({
        "redacted": True, "text": "Hello [NAME].",
        "segments": [{"text": "Hello [NAME].", "words": []}]}),
        encoding="utf-8")
    audio, out = tmp_path / "a.wav", tmp_path / "out.wav"
    _write_audio(audio)
    assert ar.main(["--audio", str(audio), "--transcript", str(transcript),
                    "--out", str(out), "--allow-empty"]) == 3
    assert not out.exists()


def test_cli_rejects_a_sibling_from_another_run(transcription_module, tmp_path):
    raw_json, red_json = _write_pipeline_outputs(transcription_module, tmp_path)
    payload = json.loads(red_json.read_text(encoding="utf-8"))
    payload["segments"][0]["words"][0]["start"] = 0.2
    red_json.write_text(json.dumps(payload), encoding="utf-8")
    audio, out = tmp_path / "talk.wav", tmp_path / "out.wav"
    _write_audio(audio)
    assert ar.main(["--audio", str(audio), "--transcript", str(raw_json),
                    "--out", str(out)]) == 2
    assert not out.exists()


def test_padded_spans_match_what_is_silenced():
    spans = [(1.0, 1.3), (5.0, 5.3)]
    padded = ar.padded_spans(spans, 0.05, duration_s=5.32)
    assert padded == [(0.95, 1.35), (4.95, 5.32)]
    assert ar.redacted_duration(padded) == pytest.approx(0.77)
