"""Tests for the residual-PII artefact audit.

These tests construct tiny temporary output trees and exercise
``evaluation.audit_artefacts`` without any optional dependency. The leak
case places a masking-log CSV naming "Alice" beside a raw JSON that still
contains "Alice", and asserts the audit flags the leak. The clean case
asserts that, when no logged name appears in the sibling artefacts, no
leak is reported.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from evaluation.audit_artefacts import (
    TYPE_MASKING_LOG,
    TYPE_RAW_JSON,
    TYPE_TRANSCRIPT_TXT,
    TYPE_VTT,
    audit_directory,
    classify_artefact,
    extract_masked_names,
)


def _write_masking_log(path: Path, rows: list[tuple[str, str]]) -> None:
    """Write a minimal name_masking_logs CSV with (original, replacement) rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["filename", "order", "original", "replacement", "context_sentence"]
        )
        for i, (original, replacement) in enumerate(rows, start=1):
            writer.writerow(["rec.wav", i, original, replacement, "context"])


def test_classify_artefact_by_type(tmp_path: Path) -> None:
    logs = tmp_path / "name_masking_logs" / "rec" / "name_replacements.csv"
    assert classify_artefact(logs) == TYPE_MASKING_LOG
    assert classify_artefact(tmp_path / "a_transcript.json") == TYPE_RAW_JSON
    assert classify_artefact(tmp_path / "a.vtt") == TYPE_VTT
    assert classify_artefact(tmp_path / "transcript.txt") == TYPE_TRANSCRIPT_TXT


def test_extract_strips_trailing_punctuation(tmp_path: Path) -> None:
    log = tmp_path / "name_masking_logs" / "rec" / "name_replacements.csv"
    _write_masking_log(log, [("Pablo", "[NAME]"), ("Bernabeu,", "[SURNAME],")])
    names = extract_masked_names(log)
    # Trailing comma on "Bernabeu," must be stripped so it matches prose.
    assert names == {"Pablo", "Bernabeu"}


def test_audit_flags_leak_in_raw_json(tmp_path: Path) -> None:
    """A masking log naming "Alice" plus a sibling JSON containing "Alice"
    must be flagged as a residual-PII leak."""
    _write_masking_log(
        tmp_path / "name_masking_logs" / "rec" / "name_replacements.csv",
        [("Alice", "[NAME]")],
    )
    raw = tmp_path / "variants" / "rec_transcript.json"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text('{"text": "Hello Alice, welcome."}', encoding="utf-8")

    findings, masked_names = audit_directory(tmp_path)
    assert masked_names == {"Alice"}

    by_path = {f.path: f for f in findings}
    json_finding = by_path["variants/rec_transcript.json"]
    assert json_finding.artefact_type == TYPE_RAW_JSON
    assert json_finding.residual_pii_found is True
    assert "Alice" in json_finding.leaked_names
    # The raw JSON is unmasked by design, so this leak is expected, not a
    # broken privacy contract.
    assert json_finding.masked_by_design is False

    # The masking log itself stores the original but is never counted a leak.
    log_finding = by_path["name_masking_logs/rec/name_replacements.csv"]
    assert log_finding.artefact_type == TYPE_MASKING_LOG
    assert log_finding.residual_pii_found is False


def test_audit_clean_case_reports_no_leak(tmp_path: Path) -> None:
    """When the logged name does not appear in sibling artefacts, no leak
    is reported."""
    _write_masking_log(
        tmp_path / "name_masking_logs" / "rec" / "name_replacements.csv",
        [("Alice", "[NAME]")],
    )
    masked = tmp_path / "transcripts" / "rec" / "transcript.txt"
    masked.parent.mkdir(parents=True, exist_ok=True)
    masked.write_text("Hello [NAME], welcome.", encoding="utf-8")
    raw = tmp_path / "variants" / "rec_transcript.json"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text('{"text": "Hello [NAME], welcome."}', encoding="utf-8")

    findings, masked_names = audit_directory(tmp_path)
    assert masked_names == {"Alice"}
    assert all(not f.residual_pii_found for f in findings)


def test_masked_artefact_leak_is_distinguished(tmp_path: Path) -> None:
    """A masked-by-design .txt that still contains the original name is a
    genuine privacy-contract violation and must be flagged with
    masked_by_design=True."""
    _write_masking_log(
        tmp_path / "name_masking_logs" / "rec" / "name_replacements.csv",
        [("Alice", "[NAME]")],
    )
    leaky_masked = tmp_path / "transcripts" / "rec" / "transcript.txt"
    leaky_masked.parent.mkdir(parents=True, exist_ok=True)
    leaky_masked.write_text("Hello Alice, welcome.", encoding="utf-8")

    findings, _ = audit_directory(tmp_path)
    txt = next(f for f in findings if f.path.endswith("transcript.txt"))
    assert txt.masked_by_design is True
    assert txt.residual_pii_found is True


def test_missing_directory_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        audit_directory(tmp_path / "does_not_exist")
