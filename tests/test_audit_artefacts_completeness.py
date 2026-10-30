"""The residual-PII audit says when it could not check a file.

From the code review of 29 October 2026: the fix for unreadable masking
logs (08211c3) covered only a tree whose every log failed. When one
recording's log among several could not be read, that recording's
transcripts were still reported "clean: no logged original name found";
the console said "No masking logs found in the tree." whenever no name was
recovered; the JSON summary and the exit status ignored unreadable logs and
skipped files; a log was decoded strictly, so one bad byte lost every name
of its decode chunk; and the review report, which copies the text of each
flagged segment, was filed as "other" and never scanned.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation import audit_artefacts as aa

_HEADER = ["filename", "order", "original", "replacement", "context_sentence"]


def _log(path: Path, *names: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(_HEADER)
        for i, name in enumerate(names, start=1):
            writer.writerow(["rec.wav", i, name, "[NAME]", "context"])


def _bad_log(path: Path) -> None:
    """A log without the 'original' column."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("filename,order,name,replacement\nrec,1,Bob,[NAME]\n",
                    encoding="utf-8")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _by_path(tree: Path):
    findings, names = aa.audit_directory(tree)
    return {f.path: f for f in findings}, names


def test_one_bad_log_among_several_marks_only_its_recording(tmp_path):
    """The example tree's layout: name_masking_logs/<rec>/<log>.csv."""
    _log(tmp_path / "name_masking_logs" / "rec_a" / "name_replacements.csv", "Alice")
    _bad_log(tmp_path / "name_masking_logs" / "rec_b" / "name_replacements.csv")
    _write(tmp_path / "transcripts" / "rec_a" / "transcript.txt", "Hello [NAME].")
    _write(tmp_path / "transcripts" / "rec_b" / "transcript.txt", "Hello Bob.")
    by_path, names = _by_path(tmp_path)
    assert names == {"Alice"}
    a = by_path["transcripts/rec_a/transcript.txt"]
    assert a.status == aa.STATUS_SCANNED
    assert a.detail == "clean: no logged original name found"
    b = by_path["transcripts/rec_b/transcript.txt"]
    assert b.status == aa.STATUS_NOT_CHECKED
    assert b.detail.startswith("not checked: the masking log "
                               "name_masking_logs/rec_b/name_replacements.csv")
    assert not b.residual_pii_found


def test_the_pipelines_flat_log_layout_is_tied_to_its_recording(tmp_path):
    """save_replacement_log writes name_masking_logs/name_replacements_<rec>.csv
    and the transcripts are <rec>_transcript.txt."""
    _log(tmp_path / "name_masking_logs" / "name_replacements_rec_a.csv", "Alice")
    _bad_log(tmp_path / "name_masking_logs" / "name_replacements_rec_b.csv")
    _write(tmp_path / "output" / "transcripts" / "rec_a_transcript.txt", "Hi [NAME].")
    _write(tmp_path / "output" / "transcripts" / "rec_b_transcript.txt", "Hi Bob.")
    by_path, _ = _by_path(tmp_path)
    assert by_path["output/transcripts/rec_a_transcript.txt"].status == aa.STATUS_SCANNED
    assert (by_path["output/transcripts/rec_b_transcript.txt"].status
            == aa.STATUS_NOT_CHECKED)


def test_a_bad_log_tied_to_no_artefact_marks_every_artefact(tmp_path):
    """Transcripts written under another --output-name cannot be tied to the
    log, so any of them may hold its names."""
    _log(tmp_path / "name_masking_logs" / "name_replacements_rec_a.csv", "Alice")
    _bad_log(tmp_path / "name_masking_logs" / "name_replacements_interview.csv")
    _write(tmp_path / "rec_a_transcript.txt", "Hi [NAME].")
    _write(tmp_path / "session_transcript.txt", "Hi Bob.")
    by_path, _ = _by_path(tmp_path)
    assert by_path["rec_a_transcript.txt"].status == aa.STATUS_NOT_CHECKED
    assert by_path["session_transcript.txt"].status == aa.STATUS_NOT_CHECKED


def test_a_leak_is_still_reported_in_a_file_not_checked(tmp_path):
    _log(tmp_path / "name_masking_logs" / "rec_a" / "name_replacements.csv", "Alice")
    _bad_log(tmp_path / "name_masking_logs" / "rec_b" / "name_replacements.csv")
    _write(tmp_path / "transcripts" / "rec_b" / "transcript.txt", "Hello Alice.")
    by_path, _ = _by_path(tmp_path)
    b = by_path["transcripts/rec_b/transcript.txt"]
    assert b.residual_pii_found and b.status == aa.STATUS_NOT_CHECKED
    assert b.detail.startswith("MASKED-BY-DESIGN ARTEFACT LEAKS PII: contains Alice; "
                               "the masking log")


def test_one_bad_byte_costs_only_its_own_name(tmp_path, capsys):
    """A strict decode lost every name of the chunk the bad byte fell in."""
    path = tmp_path / "name_masking_logs" / "rec" / "name_replacements.csv"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"filename,order,original,replacement\n"
                     b"rec,1,Alice,[NAME]\nrec,2,B\xffb,[NAME]\nrec,3,Carol,[NAME]\n")
    assert aa.extract_masked_names(path) == {"Alice", "Carol"}
    names, problem = aa._read_masked_names(path)
    assert problem == "held 1 undecodable byte sequence(s), read as U+FFFD"
    # A U+FFFD written in the file is not counted as a replacement.
    path.write_bytes("filename,order,original,replacement\nrec,1,Alice,\ufffd\n"
                     .encode())
    assert aa._read_masked_names(path) == ({"Alice"}, None)


def _run_main(tree: Path, out: Path, capsys):
    rc = aa.main(["--dir", str(tree), "--output-dir", str(out)])
    captured = capsys.readouterr()
    summary = json.loads((out / "artefact_audit.json").read_text(encoding="utf-8"))
    return rc, captured.out, summary["summary"]


def test_a_complete_audit_exits_zero(tmp_path, capsys):
    tree = tmp_path / "tree"
    _log(tree / "name_masking_logs" / "rec" / "name_replacements.csv", "Alice")
    _write(tree / "rec_transcript.txt", "Hello Alice.")        # a leak
    rc, out, summary = _run_main(tree, tmp_path / "audit", capsys)
    assert rc == 0                      # a leak alone does not change it
    assert summary["audit_complete"] is True
    assert summary["masking_logs_not_read_in_full"] == []
    assert summary["skipped_files"] == []
    assert summary["files_not_checked"] == []
    assert summary["n_masking_logs"] == 1
    assert "INCOMPLETE" not in out


def test_an_unreadable_log_makes_the_audit_incomplete(tmp_path, capsys):
    tree = tmp_path / "tree"
    _log(tree / "name_masking_logs" / "rec_a" / "name_replacements.csv", "Alice")
    _bad_log(tree / "name_masking_logs" / "rec_b" / "name_replacements.csv")
    _write(tree / "rec_b_transcript.txt", "Hello Bob.")
    rc, out, summary = _run_main(tree, tmp_path / "audit", capsys)
    assert rc == aa.EXIT_INCOMPLETE == 3
    assert summary["audit_complete"] is False
    assert summary["masking_logs_not_read_in_full"] == [
        "name_masking_logs/rec_b/name_replacements.csv"]
    assert summary["files_not_checked"] == ["rec_b_transcript.txt"]
    assert "Masking logs not read in full: 1" in out
    assert "INCOMPLETE AUDIT" in out


def test_a_skipped_file_makes_the_audit_incomplete(tmp_path, capsys, monkeypatch):
    tree = tmp_path / "tree"
    _log(tree / "name_masking_logs" / "rec" / "name_replacements.csv", "Alice")
    _write(tree / "rec_transcript.txt", "Hello [NAME].")
    monkeypatch.setattr(aa, "_read_text_file", lambda path: None)
    rc, out, summary = _run_main(tree, tmp_path / "audit", capsys)
    assert rc == 3
    assert summary["skipped_files"] == ["rec_transcript.txt"]
    assert "Artefacts skipped as unreadable: 1" in out


@pytest.mark.parametrize("setup, expected", [
    ("none", "No masking logs found in the tree."),
    ("empty", "The 1 masking log(s) in the tree give no original name."),
    ("bad", "No original name recovered: none of the 1 masking log(s) "
            "could be read in full."),
])
def test_the_console_says_why_no_name_was_recovered(tmp_path, capsys, setup,
                                                    expected):
    tree = tmp_path / "tree"
    log = tree / "name_masking_logs" / "rec" / "name_replacements.csv"
    if setup == "empty":
        _log(log)
    elif setup == "bad":
        _bad_log(log)
    _write(tree / "rec_transcript.txt", "Hello Bob.")
    _rc, out, _summary = _run_main(tree, tmp_path / "audit", capsys)
    assert expected in out
    if setup != "none":
        assert "No masking logs found" not in out


def _review(path: Path, text: str, redacted: bool) -> None:
    """The shape of transcription.write_review_file's report."""
    _write(path, json.dumps({
        "summary": {"segments": 1, "flagged": 1},
        "flagged": [{"index": 0, "text": text, "flags": ["high_speech_rate"]}],
        "redacted": redacted,
    }))


def test_the_review_report_is_classified_by_its_redacted_flag(tmp_path):
    _review(tmp_path / "rec_review.json", "Hi [NAME].", True)
    _review(tmp_path / "raw_review.json", "Hi Alice.", False)
    assert aa.classify_artefact(tmp_path / "rec_review.json") == aa.TYPE_REDACTED_REVIEW
    assert aa.classify_artefact(tmp_path / "raw_review.json") == aa.TYPE_RAW_REVIEW
    # A summary without a flagged list stays "other".
    _write(tmp_path / "run_summary.json", json.dumps({"summary": {}}))
    assert aa.classify_artefact(tmp_path / "run_summary.json") == aa.TYPE_OTHER


def test_a_name_in_a_redacted_review_is_a_masked_leak(tmp_path):
    _log(tmp_path / "name_masking_logs" / "rec" / "name_replacements.csv", "Alice")
    _review(tmp_path / "rec_review.json", "Thanks, Alice.", True)
    _review(tmp_path / "rec_raw_review.json", "Thanks, Alice.", False)
    by_path, _ = _by_path(tmp_path)
    red = by_path["rec_review.json"]
    assert red.masked_by_design and red.residual_pii_found
    assert red.detail.startswith("MASKED-BY-DESIGN ARTEFACT LEAKS PII")
    raw = by_path["rec_raw_review.json"]
    assert not raw.masked_by_design and raw.residual_pii_found


def test_the_pipelines_review_is_scanned(transcription_module, tmp_path):
    """write_review_file's own output, masked, is a clean masked artefact."""
    import contextlib
    import io

    with contextlib.redirect_stdout(io.StringIO()):
        mask_fn, _ = transcription_module.create_enhanced_name_masker()
    words = "Alice " * 40
    segments = [{"start": 0.0, "end": 1.0, "text": f"Thanks {words}".strip()}]
    transcription_module.write_review_file(
        segments, tmp_path / "rec_review.json", mask_fn=mask_fn)
    review = json.loads((tmp_path / "rec_review.json").read_text("utf-8"))
    assert review["flagged"], "the premise: the segment is flagged"
    _log(tmp_path / "name_masking_logs" / "rec" / "name_replacements.csv", "Alice")
    by_path, _ = _by_path(tmp_path)
    finding = by_path["rec_review.json"]
    assert finding.artefact_type == aa.TYPE_REDACTED_REVIEW
    assert finding.status == aa.STATUS_SCANNED
    assert not finding.residual_pii_found
