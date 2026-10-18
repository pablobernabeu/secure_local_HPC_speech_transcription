"""EPRIV-23 and EPRIV-32 in ``evaluation.benchmark_podcast``.

A missing manifest dropped every coverage figure silently, and an empty
audio_file matched the first episode. speech_s summed caption-sized
segment spans, pauses and overlaps included, and the median gap was the
upper median.
"""

from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation import benchmark_podcast as bp  # noqa: E402

_DURATIONS = {
    "ep01_the-architecture-of-meaning-inside-the-words-we-use": 2305.0,
    "ep05_beyond-the-cloud-reclaiming-data-sovereignty-in-speech-trans": 1938.0,
}


class TestMatchDuration:
    def test_an_empty_audio_file_matches_nothing(self):
        assert bp._match_duration({"audio_file": ""}, _DURATIONS) == (None, "no_audio_file")
        assert bp._match_duration({}, _DURATIONS) == (None, "no_audio_file")

    def test_exact_stem(self):
        audio = "ep01_the-architecture-of-meaning-inside-the-words-we-use.m4a"
        assert bp._match_duration({"audio_file": audio}, _DURATIONS) == (2305.0, "exact")

    def test_the_derived_wav_matches_its_episode(self):
        audio = "/data/ep05_beyond-the-cloud-reclaiming-data-sovereignty-in-speech-trans_16k.wav"
        assert bp._match_duration({"audio_file": audio}, _DURATIONS) == (1938.0, "episode")

    def test_ambiguous_and_unmatched(self):
        durations = {**_DURATIONS, "ep05_other": 10.0}
        assert bp._match_duration({"audio_file": "ep05_x_16k.wav"}, durations) \
            == (None, "ambiguous")
        assert bp._match_duration({"audio_file": "ep50_x.wav"}, _DURATIONS) \
            == (None, "unmatched")
        assert bp._match_duration({"audio_file": "interview.wav"}, _DURATIONS) \
            == (None, "unmatched")


def test_a_named_manifest_that_is_missing_is_an_error(tmp_path, monkeypatch):
    with pytest.raises(FileNotFoundError):
        bp._duration_lookup(tmp_path / "manifest.json")
    assert bp._duration_lookup(None) == {}

    transcript = tmp_path / "t.json"
    transcript.write_text(json.dumps({"text": "hi"}), encoding="utf-8")
    fake = types.ModuleType("transcription")
    fake.create_enhanced_name_masker = lambda: pytest.fail("masker built first")
    monkeypatch.setitem(sys.modules, "transcription", fake)
    assert bp.main(["--transcript", str(transcript), "--output-dir",
                    str(tmp_path / "out"), "--manifest",
                    str(tmp_path / "absent.json")]) == 2


def test_a_named_manifest_without_durations_is_an_error(tmp_path, monkeypatch):
    """A manifest that lists no episode duration is refused like a missing
    one: carrying on would drop every coverage figure without a warning,
    since there is nothing to match against."""
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"episodes": [{"filename": "ep05_x.m4a"}]}),
                        encoding="utf-8")
    transcript = tmp_path / "t.json"
    transcript.write_text(json.dumps({"audio_file": "ep05_x_16k.wav"}), encoding="utf-8")
    fake = types.ModuleType("transcription")
    fake.create_enhanced_name_masker = lambda: pytest.fail("masker built first")
    monkeypatch.setitem(sys.modules, "transcription", fake)
    assert bp.main(["--transcript", str(transcript), "--output-dir",
                    str(tmp_path / "out"), "--manifest", str(manifest)]) == 2
    assert not (tmp_path / "out").exists()


def test_the_case_study_recording_has_a_duration_in_the_committed_manifest():
    """The case-study job's default recording, and the 16 kHz WAV the job
    decodes it to, each match one episode of the committed manifest, which
    the job falls back to on ARC (NEW-06)."""
    script = (PROJECT_ROOT / "hpc" / "submit_case_study.sh").read_text(encoding="utf-8")
    default = re.search(r'^DEFAULT_AUDIO="\$\{DATA\}/codex_mentis/audio/([^"/]+)"$',
                        script, re.MULTILINE)
    assert default, "DEFAULT_AUDIO not found in hpc/submit_case_study.sh"
    stem = Path(default.group(1)).stem
    durations = bp._duration_lookup(PROJECT_ROOT / "data" / "codex_mentis" / "manifest.json")
    assert durations.get(stem, 0) > 0
    decoded = {"audio_file": f"/data/codex_mentis/audio/{stem}_16k.wav"}
    assert bp._match_duration(decoded, durations) == (durations[stem], "episode")


def test_duration_source_is_recorded(tmp_path, monkeypatch, capsys):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"episodes": [
        {"filename": "ep05_beyond.m4a", "duration_s": 20.0}]}), encoding="utf-8")
    words = [{"text": "a", "start": 0.0, "end": 1.0}]
    good = tmp_path / "a.json"
    good.write_text(json.dumps({"audio_file": "ep05_beyond_16k.wav", "segments": [
        {"start": 0.0, "end": 2.0, "text": "a", "words": words}]}), encoding="utf-8")
    none = tmp_path / "b.json"
    none.write_text(json.dumps({"segments": [
        {"start": 0.0, "end": 2.0, "text": "a", "words": words}]}), encoding="utf-8")
    fake = types.ModuleType("transcription")
    fake.create_enhanced_name_masker = lambda: (lambda s: s, None)
    monkeypatch.setitem(sys.modules, "transcription", fake)
    out = tmp_path / "out"
    assert bp.main(["--transcript", str(tmp_path), "--output-dir", str(out),
                    "--manifest", str(manifest)]) == 0
    per_file = {r["file"]: r["timestamps"] for r in json.loads(
        (out / "podcast_eval_summary.json").read_text("utf-8"))["per_file"]}
    assert per_file["a.json"]["duration_source"] == "episode"
    assert per_file["a.json"]["coverage_ratio"] == pytest.approx(0.05)
    assert per_file["b.json"]["duration_source"] == "no_audio_file"
    assert "coverage_ratio" not in per_file["b.json"]
    assert "b.json: no episode duration" in capsys.readouterr().err


def test_speech_is_the_union_of_words_not_the_sum_of_segments():
    t = {"segments": [
        {"start": 0.0, "end": 3.0, "text": "a b",
         "words": [{"start": 0.0, "end": 1.0}, {"start": 2.0, "end": 3.0}]},
        # Overlaps the first segment by a second.
        {"start": 2.0, "end": 5.0, "text": "c",
         "words": [{"start": 2.5, "end": 4.0}]},
    ]}
    m = bp.timestamp_metrics(t)
    assert m["speech_s"] == pytest.approx(3.0)         # [0,1] and [2,4]
    assert m["segment_span_s"] == pytest.approx(5.0)   # [0,5], not 3 + 3
    assert m["n_overlaps"] == 1


def test_median_gap_is_the_median():
    t = {"segments": [{"start": s, "end": e, "text": "x"} for s, e in
                      [(0, 1), (2, 3), (6, 7), (8, 9), (13, 14)]]}
    # Gaps 1, 3, 1, 4: the median is 2.0; the old upper median gave 3.
    assert bp.timestamp_metrics(t)["median_gap_s"] == pytest.approx(2.0)


def test_union_length_ignores_empty_intervals():
    assert bp._union_length([(1.0, 1.0), (3.0, 2.0)]) == 0.0
    assert bp._union_length([(0.0, 2.0), (1.0, 3.0), (5.0, 6.0)]) == pytest.approx(4.0)
