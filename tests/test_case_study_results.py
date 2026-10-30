"""Objective tests of the committed case study in output/case_study/.

These tests make no network calls and run no model. They read the files
ARC job 9124852 wrote (hpc/runs/case_study.env): its structural evaluation,
podcast_eval_summary.json and podcast_eval_report.csv, and its review and
run manifest, codex_mentis_ep05_review.json and
codex_mentis_ep05_manifest.json.

Three kinds of assertion are made. The manifest must vouch for itself and
for the review committed beside it, which is a byte-for-byte copy of the
job's file, and must name the run's code and the published recording. The
four files must describe one transcript, and the report must be the summary
flattened. And the headline figures are pinned, so that replacing the case
study is a deliberate change that updates this module too.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from evaluation import benchmark_podcast as bp
from provenance import canonical_json, sha256_bytes

_CASE = _ROOT / "output" / "case_study"
_COMMIT = "fc652ab8714435260bdea037efcf83b277c22115"
_REVIEW = "codex_mentis_ep05_review.json"


def _json(name: str) -> dict:
    return json.loads((_CASE / name).read_text(encoding="utf-8"))


def _manifest() -> dict:
    return _json("codex_mentis_ep05_manifest.json")


def _evaluation() -> dict:
    [record] = _json("podcast_eval_summary.json")["per_file"]
    return record


def _episode() -> dict:
    corpus = json.loads((_ROOT / "data" / "codex_mentis" / "manifest.json")
                        .read_text(encoding="utf-8"))
    [episode] = [e for e in corpus["episodes"] if e["filename"].startswith("ep05_")]
    return episode


def test_the_manifest_digest_covers_its_own_content():
    manifest = _manifest()
    body = {k: v for k, v in manifest.items()
            if k not in ("manifest_sha256", "signature")}
    assert manifest["manifest_sha256"] == sha256_bytes(canonical_json(body))
    assert "signature" not in manifest


def test_the_committed_review_is_the_one_the_manifest_lists():
    """CRLF is read as LF, so a checkout that converted the line endings
    still compares the bytes the job wrote."""
    [entry] = [a for a in _manifest()["artefacts"] if a["path"] == _REVIEW]
    data = (_CASE / _REVIEW).read_bytes().replace(b"\r\n", b"\n")
    assert (len(data), hashlib.sha256(data).hexdigest()) == \
        (entry["bytes"], entry["sha256"])


def test_the_manifest_lists_nine_artefacts_and_not_the_masking_log():
    paths = [a["path"] for a in _manifest()["artefacts"]]
    assert len(paths) == 9
    assert all(p.startswith("codex_mentis_ep05_") for p in paths)
    assert not any("name_replacements" in p for p in paths)


def test_the_run_is_the_recorded_one():
    software = _manifest()["provenance"]["software"]
    assert (software["git_commit"], software["git_dirty"]) == (_COMMIT, False)
    assert software["packages"]["gliner"] is None      # no NER stage ran
    record = (_ROOT / "hpc" / "runs" / "case_study.env").read_text(encoding="utf-8")
    assert "Job 9124852 (case_study)" in record
    assert f"code {_COMMIT[:7]} with a clean tree" in record


def test_the_manifest_names_the_published_recording():
    source = _manifest()["source_audio"]
    episode = _episode()
    assert (source["name"], source["bytes"], source["sha256"]) == \
        (episode["filename"], episode["bytes"], episode["sha256"])
    assert _manifest()["input_audio"]["name"] == \
        Path(episode["filename"]).stem + "_16k.wav"


def test_the_report_is_the_summary_flattened():
    with (_CASE / "podcast_eval_report.csv").open(newline="", encoding="utf-8") as fh:
        [row] = list(csv.DictReader(fh))
    assert row == {k: str(v) for k, v in bp._flatten(_evaluation()).items()}


def test_the_evaluation_and_the_review_describe_one_transcript():
    timestamps = _evaluation()["timestamps"]
    review = _json(_REVIEW)
    assert review["summary"]["segments"] == timestamps["n_segments"]
    assert review["truncation"]["last_segment_end_s"] == timestamps["span_end_s"]
    # The evaluation takes the feed's whole seconds from the corpus manifest,
    # the review the length of the decoded WAV.
    assert (timestamps["audio_duration_s"], timestamps["duration_source"]) == \
        (_episode()["duration_s"], "episode")
    assert review["truncation"]["audio_duration_s"] == 1938.87


def test_the_headline_figures():
    record = _evaluation()
    assert {k: record["timestamps"][k] for k in (
        "n_segments", "n_words", "n_words_timed", "monotonicity_violations",
        "n_overlaps", "speech_s", "segment_span_s", "coverage_ratio",
        "segment_coverage_ratio", "end_drift_s")} == {
        "n_segments": 403, "n_words": 5477, "n_words_timed": 5477,
        "monotonicity_violations": 0, "n_overlaps": 0, "speech_s": 1841.42,
        "segment_span_s": 1882.12, "coverage_ratio": 0.9502,
        "segment_coverage_ratio": 0.9712, "end_drift_s": 1.66}
    diarisation = record["diarisation"]
    assert (diarisation["n_speakers"], diarisation["speaker_count_error"],
            diarisation["n_turns"]) == (2, 0, 170)
    # The fourth redaction is the [TITLE] of "Dr." in the closing credits
    # (NEW-09).
    assert (record["masking"]["n_redacted"], record["masking"]["n_tokens"]) == (4, 5382)
    review = _json(_REVIEW)
    rate, passage, zero = "high_speech_rate", "repeated_passage", "zero_duration"
    assert [(f["index"], f["flags"]) for f in review["flagged"]] == [
        (3, [rate]),
        (46, [passage]), (47, [passage]), (48, [passage]), (49, [passage, rate]),
        (50, [zero, passage]), (51, [zero, passage]), (52, [zero, passage]),
        (53, [passage]),
        (84, [passage, rate]), (85, [passage]), (86, [passage]),
        (287, [rate])]
    assert review["truncation"]["truncated"] is False


def test_the_review_ran_the_optional_checks_the_manifest_records():
    """NEW-12: the job enables both optional checks, and the manifest
    records the same settings the review applied."""
    settings = {"flag_zero_duration": True, "repeated_passage_words": 8,
                "repeated_passage_window_s": 60.0}
    assert _json(_REVIEW)["optional_checks"] == settings
    assert _manifest()["provenance"]["review_settings"] == settings
    links = {f["index"]: f.get("repeated_passage_with")
             for f in _json(_REVIEW)["flagged"]}
    # The zero-length copy at 189.98 s and the speech it repeats.
    assert {i: links[i] for i in range(46, 54)} == {
        46: [50, 51], 47: [50, 51], 48: [51, 52], 49: [52, 53],
        50: [46, 47], 51: [46, 47], 52: [47, 48], 53: [48, 49]}
    # The copy crammed into cue 84 and the passage spoken after it.
    assert (links[84], links[85], links[86]) == ([85], [84], [84])
