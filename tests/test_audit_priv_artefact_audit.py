"""Audit fixes EPRIV-05 and EPRIV-29 in ``evaluation.audit_artefacts``.

The pipeline's ``_transcript_redacted.json``/``.vtt`` are de-identified by
design, but the audit classified every JSON and VTT as raw, so a name left
in the redacted set was reported as expected rather than as a leak. The
JSON branch also classified any JSON (a summary, a manifest) as a
transcript.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.audit_artefacts import (
    TYPE_OTHER,
    TYPE_RAW_JSON,
    TYPE_REDACTED_JSON,
    TYPE_REDACTED_VTT,
    TYPE_VTT,
    audit_directory,
    classify_artefact,
)


def _log(root: Path, name: str) -> None:
    path = root / "name_masking_logs" / "rec" / "name_replacements.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["filename", "order", "original", "replacement",
                         "context_sentence"])
        writer.writerow(["rec", 1, name, "[NAME]", f"Hello {name}."])


def _transcript(path: Path, text: str, redacted: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"text": text, "redacted": redacted,
                                "segments": [{"text": text, "words": []}]}),
                    encoding="utf-8")


def test_files_are_ordered_the_same_way_on_every_platform(tmp_path):
    """A capitalised name sorts among the lower-case ones, as a Windows path
    sort places it, so the report's rows do not depend on the platform."""
    for name in ("b/x.txt", "README.md", "a.txt", "B2/y.txt"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("text", encoding="utf-8")
    findings, _ = audit_directory(tmp_path)
    assert [f.path for f in findings] == ["a.txt", "b/x.txt", "B2/y.txt", "README.md"]


def test_redacted_json_leak_is_a_masked_artefact_leak(tmp_path):
    _log(tmp_path, "Alice")
    _transcript(tmp_path / "rec_transcript.json", "Hello Alice.", False)
    _transcript(tmp_path / "rec_transcript_redacted.json",
                "Hello Alice.", True)                 # masking missed it
    findings, _ = audit_directory(tmp_path)
    by_path = {f.path: f for f in findings}

    raw = by_path["rec_transcript.json"]
    assert raw.artefact_type == TYPE_RAW_JSON and not raw.masked_by_design

    red = by_path["rec_transcript_redacted.json"]
    assert red.artefact_type == TYPE_REDACTED_JSON
    assert red.masked_by_design and red.residual_pii_found
    assert red.detail.startswith("MASKED-BY-DESIGN ARTEFACT LEAKS PII")


def test_clean_redacted_json_is_clean(tmp_path):
    _log(tmp_path, "Alice")
    _transcript(tmp_path / "rec_transcript_redacted.json",
                "Hello [NAME].", True)
    findings, _ = audit_directory(tmp_path)
    red = {f.path: f for f in findings}["rec_transcript_redacted.json"]
    assert red.masked_by_design and not red.residual_pii_found


def test_redacted_json_needs_the_payload_flag(tmp_path):
    # Named like a redacted file but written unredacted: stays raw.
    path = tmp_path / "rec_transcript_redacted.json"
    _transcript(path, "Hello Alice.", False)
    assert classify_artefact(path) == TYPE_RAW_JSON


def test_vtt_classified_by_suffix(tmp_path):
    assert classify_artefact(tmp_path / "rec_transcript.vtt") == TYPE_VTT
    assert classify_artefact(
        tmp_path / "rec_transcript_redacted.vtt") == TYPE_REDACTED_VTT


def test_non_transcript_json_is_other(tmp_path):
    path = tmp_path / "masking_summary.json"
    path.write_text(json.dumps({"overall": {"recall": 0.5}}), encoding="utf-8")
    assert classify_artefact(path) == TYPE_OTHER


def test_unreadable_json_is_still_scanned(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json Alice", encoding="utf-8")
    assert classify_artefact(path) == TYPE_RAW_JSON


def test_title_rows_are_not_names(tmp_path):
    """PRIV-01: an honorific in the log is not a name to look for."""
    from evaluation.audit_artefacts import extract_masked_names

    path = tmp_path / "log.csv"
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["filename", "order", "original", "replacement",
                         "context_sentence", "source"])
        writer.writerow(["rec", 1, "Dr", "[TITLE]", "By Dr Smith.", "title"])
        writer.writerow(["rec", 2, "Smith", "[SURNAME]", "By Dr Smith.",
                         "dictionary"])
    assert extract_masked_names(path) == {"Smith"}
    # A log written before the source column existed.
    legacy = tmp_path / "legacy.csv"
    with open(legacy, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["filename", "order", "original", "replacement",
                         "context_sentence"])
        writer.writerow(["rec", 1, "Prof", "[TITLE]", "Prof Smith.", ])
        writer.writerow(["rec", 2, "Smith", "[SURNAME]", "Prof Smith."])
    assert extract_masked_names(legacy) == {"Smith"}


def _log_finding(findings):
    return next(f for f in findings if f.path.startswith("name_masking_logs/"))


def test_a_log_without_the_original_column_is_reported(tmp_path, capsys):
    """Such a log gave no names, and every file was then reported clean."""
    path = tmp_path / "name_masking_logs" / "rec" / "name_replacements.csv"
    path.parent.mkdir(parents=True)
    path.write_text("filename,order,name,replacement\nrec,1,Alice,[NAME]\n",
                    encoding="utf-8")
    (tmp_path / "rec_transcript.txt").write_text("Hello Alice.", encoding="utf-8")
    findings, names = audit_directory(tmp_path)
    assert names == set()
    assert "has no 'original' column" in _log_finding(findings).detail
    assert "not scanned for" in capsys.readouterr().err
    # Not "no masking log in tree", nor "nothing to scan for": the log of
    # this recording holds names that could not be looked for.
    transcript = {f.path: f for f in findings}["rec_transcript.txt"]
    assert transcript.detail == (
        "not checked: the masking log name_masking_logs/rec/name_replacements.csv "
        "was not read in full, so the names it holds were not all looked for")
    assert transcript.status == "not_checked"


def test_an_undecodable_log_is_reported(tmp_path, capsys):
    path = tmp_path / "name_masking_logs" / "rec" / "name_replacements.csv"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"filename,order,original,replacement\nrec,1,\xff\xfe,[NAME]\n")
    findings, _ = audit_directory(tmp_path)
    assert _log_finding(findings).detail.startswith(
        "masking log held 2 undecodable byte sequence(s), read as U+FFFD")
    assert "Warning: masking log" in capsys.readouterr().err


def test_a_log_that_cannot_be_opened_is_reported(tmp_path, capsys, monkeypatch):
    _log(tmp_path, "Alice")
    target = tmp_path / "name_masking_logs" / "rec" / "name_replacements.csv"
    real_read_bytes = Path.read_bytes

    def read_bytes(self):
        if self == target:
            raise PermissionError("denied")
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    findings, names = audit_directory(tmp_path)
    assert names == set()
    assert _log_finding(findings).detail.startswith(
        "masking log could not be read (PermissionError: denied)")
    err = capsys.readouterr().err
    # The warning reads as a sentence ("masking log X is no 'original'
    # column" did not).
    assert f"masking log {target} could not be read" in err


def test_a_readable_log_has_the_usual_detail(tmp_path, capsys):
    _log(tmp_path, "Alice")
    findings, _ = audit_directory(tmp_path)
    assert _log_finding(findings).detail == (
        "masking log; stores 1 original name(s) by design (expected, not a leak)")
    assert capsys.readouterr().err == ""


def test_an_unreadable_transcript_is_skipped_not_clean(tmp_path, monkeypatch):
    """An unreadable file was scanned as empty text and reported clean."""
    _log(tmp_path, "Alice")
    target = tmp_path / "rec_transcript.txt"
    target.write_text("Hello Alice.", encoding="utf-8")
    real_read_text = Path.read_text

    def read_text(self, *args, **kwargs):
        if self == target:
            raise PermissionError("denied")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    findings, _ = audit_directory(tmp_path)
    finding = {f.path: f for f in findings}["rec_transcript.txt"]
    assert finding.detail == "skipped: unreadable file"
    assert not finding.residual_pii_found


def test_a_title_left_in_the_redacted_words_is_not_a_leak(
        transcription_module, tmp_path, monkeypatch):
    """The pipeline's own outputs: the redacted word list keeps "Dr".

    _redact_segments masks each word on its own, and the title rule needs
    the following name, so "Dr" survives in the redacted JSON's words while
    the log records it as a title. That file used to be reported as a
    de-identified artefact leaking a name.
    """
    import contextlib
    import io

    monkeypatch.chdir(tmp_path)           # save_replacement_log writes here
    with contextlib.redirect_stdout(io.StringIO()):
        mask_fn, get_log = transcription_module.create_enhanced_name_masker()
    words = ["It", "was", "signed", "by", "Dr", "Smith", "today."]
    chunks = [{"text": f" {w}", "timestamp": (i * 0.5, i * 0.5 + 0.5)}
              for i, w in enumerate(words)]
    with contextlib.redirect_stdout(io.StringIO()):
        written = transcription_module.write_timestamped_outputs(
            {"text": " ".join(words), "chunks": chunks},
            str(tmp_path), "rec", str(tmp_path / "rec.wav"), mask_fn=mask_fn)
        transcription_module.save_replacement_log(get_log(), "rec.wav")
    redacted = json.loads(Path(written["json_redacted"]).read_text("utf-8"))
    kept = [w.get("word") for s in redacted["segments"] for w in s["words"]]
    assert "Dr" in kept and "Smith" not in kept        # the premise

    findings, names = audit_directory(tmp_path)
    assert "Smith" in names and "Dr" not in names
    leaking = [f.path for f in findings
               if f.masked_by_design and f.residual_pii_found]
    assert leaking == []
    # The raw transcript still counts as holding the name.
    assert any(f.residual_pii_found and not f.masked_by_design
               for f in findings)
