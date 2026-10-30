"""Stage-1 fixes to the standalone scorer, evaluation.wer.

EWER-07: .vtt references were read as raw text, so the WEBVTT header and
every cue's timestamps were scored as reference words.
NEW-01: transcription.py writes <stem>_transcript.txt, .json and .vtt side
by side, and every one of them was paired with the same reference, so one
recording counted two or three times.
EWER-11: the scorer's default outputs were the LibriSpeech benchmark's
headline files.

Pure functions only: nothing here needs jiwer.
"""

from __future__ import annotations

import json
from pathlib import Path

from evaluation import wer

_VTT = (
    "\ufeffWEBVTT\r\n"
    "Kind: captions\r\n"
    "\r\n"
    "NOTE produced by transcription.py\r\n"
    "\r\n"
    "1\r\n"
    "00:00:00.000 --> 00:00:02.500 align:start\r\n"
    "<v SPEAKER_00>Hello world, it&#39;s &amp; fine.</v>\r\n"
    "\r\n"
    "00:01.000 --> 00:02.000\r\n"
    "second <i>line</i>\r\n"
    "continues here\r\n"
    "\r\n"
    "STYLE\r\n"
    "::cue { color: lime }\r\n"
)


def test_vtt_cue_text_only():
    assert wer._vtt_text(_VTT) == (
        "Hello world, it's & fine. second line continues here")


def test_a_vtt_reference_scores_like_its_text(tmp_path):
    """The regression: timestamps and the header are no longer words."""
    vtt = tmp_path / "rec.vtt"
    # Bytes, so the CRLF line ends reach the file as written (text mode
    # would turn each into CR CR LF on Windows).
    vtt.write_bytes(_VTT.encode("utf-8"))
    txt = tmp_path / "rec.txt"
    txt.write_text("Hello world, it's & fine. second line continues here",
                   encoding="utf-8")
    as_vtt = wer.normalise_text(wer._read_text(vtt))
    assert as_vtt == wer.normalise_text(wer._read_text(txt))
    assert "webvtt" not in as_vtt and "00" not in as_vtt.split()


def test_the_pipeline_vtt_layout_is_read(tmp_path):
    """The exact shape transcription.py writes: a voice tag per cue."""
    vtt = tmp_path / "x_transcript.vtt"
    vtt.write_text("WEBVTT\n\n1\n00:00:00.000 --> 00:00:01.000\n"
                   "<v SPEAKER_01>Good morning.</v>\n\n", encoding="utf-8")
    assert wer._read_text(vtt) == "Good morning."


def _touch(directory: Path, *names: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_text("hello world", encoding="utf-8")


def test_one_recording_is_paired_once(tmp_path, capsys):
    refs, hyps = tmp_path / "ref", tmp_path / "hyp"
    _touch(refs, "rec.txt")
    _touch(hyps, "rec_transcript.txt", "rec_transcript.json",
           "rec_transcript.vtt")
    pairs = wer._match_files(refs, hyps)
    assert [(r.name, h.name) for r, h in pairs] == [
        ("rec.txt", "rec_transcript.txt")]
    assert "scoring rec_transcript.txt only" in capsys.readouterr().err


def test_the_format_can_be_chosen(tmp_path):
    refs, hyps = tmp_path / "ref", tmp_path / "hyp"
    _touch(refs, "rec.txt")
    _touch(hyps, "rec_transcript.txt", "rec_transcript.json")
    (hyps / "rec_transcript.json").write_text(
        json.dumps({"text": "hello"}), encoding="utf-8")
    pairs = wer._match_files(refs, hyps, hypothesis_format="json")
    assert [h.name for _, h in pairs] == ["rec_transcript.json"]


def test_two_hypothesis_stems_for_one_reference_are_not_both_scored(
        tmp_path, capsys):
    refs, hyps = tmp_path / "ref", tmp_path / "hyp"
    _touch(refs, "rec.txt", "other.vtt")
    _touch(hyps, "rec.txt", "rec_transcript.txt", "other_transcript.json")
    pairs = wer._match_files(refs, hyps)
    assert sorted((r.name, h.name) for r, h in pairs) == [
        ("other.vtt", "other_transcript.json"), ("rec.txt", "rec.txt")]
    assert "already paired" in capsys.readouterr().err


def test_a_reference_in_two_formats_is_read_once(tmp_path, capsys):
    refs, hyps = tmp_path / "ref", tmp_path / "hyp"
    _touch(refs, "rec.txt", "rec.vtt")
    _touch(hyps, "rec_transcript.txt")
    pairs = wer._match_files(refs, hyps)
    assert [r.name for r, _ in pairs] == ["rec.txt"]
    assert "reference 'rec'" in capsys.readouterr().err


def test_the_default_outputs_are_not_the_benchmark_headline():
    args = wer._build_parser().parse_args(["--hypothesis", "h",
                                           "--reference", "r"])
    assert Path(args.report).name == "wer_report_transcripts.csv"
    assert Path(args.summary).name == "wer_summary_transcripts.json"
    assert args.hypothesis_format is None


def test_the_summary_says_what_it_scored(tmp_path):
    r = wer.PairResult(name="a", wer=0.5, mer=0.5, wil=0.5, cer=0.1, hits=1,
                       substitutions=1, deletions=0, insertions=0,
                       reference_words=2, hypothesis_words=2)
    path = tmp_path / "s.json"
    wer.write_summary_json([r], path, evaluation={"tool": "evaluation.wer"},
                           run_meta={"git_commit": "abc"})
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["evaluation"] == {"tool": "evaluation.wer"}
    assert payload["run_metadata"] == {"git_commit": "abc"}
    assert "benchmark" not in payload
    assert payload["summary"]["files"] == 1
    # Without the optional blocks the established shape is unchanged.
    wer.write_summary_json([r], path)
    assert set(json.loads(path.read_text(encoding="utf-8"))) == {
        "summary", "per_file"}


def _unscorable_pairs(tmp_path: Path) -> tuple[Path, Path]:
    """Two matched pairs that fail before jiwer is needed: an empty
    reference (ValueError) and a hypothesis JSON that does not parse."""
    refs, hyps = tmp_path / "ref", tmp_path / "hyp"
    refs.mkdir()
    hyps.mkdir()
    (refs / "empty.txt").write_text("  ,  ", encoding="utf-8")
    (hyps / "empty.txt").write_text("hello", encoding="utf-8")
    (refs / "broken.txt").write_text("hello world", encoding="utf-8")
    (hyps / "broken.json").write_text("{not json", encoding="utf-8")
    return refs, hyps


def test_a_skipped_pair_is_counted_and_named(tmp_path, capsys):
    """SC-19: a pair that failed to score left only a stderr line, so a
    summary over fewer pairs than were matched read as complete."""
    refs, hyps = _unscorable_pairs(tmp_path)
    skipped: list[dict] = []
    assert wer.evaluate_directory(refs, hyps, skipped=skipped) == []
    assert [(s["hypothesis"], s["reference"]) for s in skipped] == [
        ("broken.json", "broken.txt"), ("empty.txt", "empty.txt")]
    assert skipped[0]["error"].startswith("JSONDecodeError: ")
    assert skipped[1]["error"].startswith("ValueError: Reference text is empty")
    assert capsys.readouterr().err.count("Skipping") == 2
    # Without a list the call behaves as it always has.
    assert wer.evaluate_directory(refs, hyps) == []


def test_the_summary_records_the_skipped_pairs(tmp_path):
    refs, hyps = _unscorable_pairs(tmp_path)
    report, summary = tmp_path / "out" / "r.csv", tmp_path / "out" / "s.json"
    assert wer.main(["--hypothesis", str(hyps), "--reference", str(refs),
                     "--report", str(report), "--summary", str(summary)]) == 0
    payload = json.loads(summary.read_text(encoding="utf-8"))
    assert payload["summary"] == {"n_skipped_pairs": 2}
    assert [s["hypothesis"] for s in payload["skipped_pairs"]] == [
        "broken.json", "empty.txt"]
    assert payload["per_file"] == []


def test_a_summary_with_nothing_skipped_says_so(tmp_path):
    r = wer.PairResult(name="a", wer=0.5, mer=0.5, wil=0.5, cer=0.1, hits=1,
                       substitutions=1, deletions=0, insertions=0,
                       reference_words=2, hypothesis_words=2)
    path = tmp_path / "s.json"
    wer.write_summary_json([r], path, skipped=[])
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["summary"]["n_skipped_pairs"] == 0
    assert payload["summary"]["files"] == 1
    assert payload["skipped_pairs"] == []
