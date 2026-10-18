"""Tests for the redacted parallel timestamped artefacts.

The artefact audit found that the timestamped ``.json`` and ``.vtt`` are
written from the raw model output and so retain any spoken name. The
pipeline now writes a masked parallel set beside them, and can suppress the
unredacted set entirely. These tests pin that behaviour with a stub masker,
so they need no name database and no model.

The load-bearing test is :func:`test_no_name_survives_anywhere_in_redacted`.
Segment words are stored under the key ``word`` by
``_build_segments_from_chunks`` while the shipped example artefacts once used
``text``; an earlier draft of the redactor masked only ``text`` and so left
every word-level name in place in a file labelled "redacted". Asserting
against the serialised payload as a whole, rather than against the fields
the redactor happens to know about, is what catches that class of mistake.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from transcription import _redact_segments, write_timestamped_outputs  # noqa: E402

_NAMES = ("Bernabeu", "David")


def _stub_masker(text: str) -> str:
    """Replace the two test names wherever they appear."""
    for name in _NAMES:
        text = text.replace(name, "[NAME]")
    return text


def _result():
    """A pipeline result whose chunks drive the real segment builder."""
    return {
        "text": "Welcome David Bernabeu to the study",
        "chunks": [
            {"text": "Welcome", "timestamp": (0.0, 0.5)},
            {"text": "David", "timestamp": (0.5, 1.0)},
            {"text": "Bernabeu", "timestamp": (1.0, 1.6)},
            {"text": "study", "timestamp": (1.6, 2.0)},
        ],
    }


def test_redact_segments_masks_both_text_keys():
    """Word text may live under 'word' or 'text'; both must be masked."""
    segments = [{
        "start": 0.0, "end": 1.0, "text": "David here",
        "words": [{"word": "David", "start": 0.0, "end": 0.5},
                  {"text": "Bernabeu", "start": 0.5, "end": 1.0}],
    }]
    out = _redact_segments(segments, _stub_masker)
    assert out[0]["text"] == "[NAME] here"
    assert out[0]["words"][0]["word"] == "[NAME]"
    assert out[0]["words"][1]["text"] == "[NAME]"
    # Timings and any other field are untouched.
    assert out[0]["words"][0]["start"] == 0.0
    assert out[0]["end"] == 1.0
    # The input is not mutated.
    assert segments[0]["words"][0]["word"] == "David"


def test_redact_segments_preserves_speaker_labels():
    segments = [{"start": 0.0, "end": 1.0, "text": "David spoke",
                 "speaker": "SPEAKER_01", "words": []}]
    out = _redact_segments(segments, _stub_masker)
    assert out[0]["speaker"] == "SPEAKER_01"
    assert out[0]["text"] == "[NAME] spoke"


def test_both_sets_written_and_flagged(tmp_path):
    written = write_timestamped_outputs(
        _result(), str(tmp_path), "demo", "demo.wav",
        model="m", language="english", mask_fn=_stub_masker)
    for key in ("json", "vtt", "json_redacted", "vtt_redacted"):
        assert key in written, f"missing {key}"
        assert Path(written[key]).exists()
    assert json.loads(Path(written["json"]).read_text(encoding="utf-8"))["redacted"] is False
    assert json.loads(Path(written["json_redacted"]).read_text(encoding="utf-8"))["redacted"] is True


def test_no_name_survives_anywhere_in_redacted(tmp_path):
    """No injected name may appear anywhere in the redacted payload.

    Checked against the whole serialised file rather than named fields, so a
    text-bearing key the redactor does not know about still fails the test.
    """
    written = write_timestamped_outputs(
        _result(), str(tmp_path), "demo", "demo.wav",
        model="m", language="english", mask_fn=_stub_masker)

    redacted_json = Path(written["json_redacted"]).read_text(encoding="utf-8")
    redacted_vtt = Path(written["vtt_redacted"]).read_text(encoding="utf-8")
    for name in _NAMES:
        assert name not in redacted_json, f"{name} leaked into the redacted JSON"
        assert name not in redacted_vtt, f"{name} leaked into the redacted VTT"

    # The raw set is the control: it is expected to retain the names, which
    # is why the redacted parallel exists at all.
    raw_json = Path(written["json"]).read_text(encoding="utf-8")
    assert any(name in raw_json for name in _NAMES)


def test_timings_identical_between_the_two_sets(tmp_path):
    written = write_timestamped_outputs(
        _result(), str(tmp_path), "demo", "demo.wav",
        model="m", language="english", mask_fn=_stub_masker)
    raw = json.loads(Path(written["json"]).read_text(encoding="utf-8"))
    red = json.loads(Path(written["json_redacted"]).read_text(encoding="utf-8"))
    spans = lambda d: [(s["start"], s["end"]) for s in d["segments"]]  # noqa: E731
    assert spans(raw) == spans(red)
    assert spans(raw), "expected at least one segment"


def test_write_raw_false_suppresses_the_unredacted_set(tmp_path):
    written = write_timestamped_outputs(
        _result(), str(tmp_path), "demo", "demo.wav",
        model="m", language="english", mask_fn=_stub_masker, write_raw=False)
    assert "json" not in written and "vtt" not in written
    assert "json_redacted" in written and "vtt_redacted" in written
    # Nothing unredacted is left on disk for an exporter to pick up.
    for path in tmp_path.iterdir():
        assert "_redacted" in path.name, f"unredacted artefact remains: {path.name}"


def test_without_a_masker_only_the_raw_set_is_written(tmp_path):
    """Masking off keeps the previous behaviour exactly."""
    written = write_timestamped_outputs(
        _result(), str(tmp_path), "demo", "demo.wav",
        model="m", language="english")
    assert "json" in written and "vtt" in written
    assert "json_redacted" not in written and "vtt_redacted" not in written
