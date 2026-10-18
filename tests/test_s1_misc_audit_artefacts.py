"""EPRIV-25: the artefact audit sees lower-cased names and possessives.

The masker's main measured leak is the uncapitalised name, which the
case-sensitive verbatim scan cannot see, and a logged possessive
("Bernabeu's") matched only itself.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation import audit_artefacts as aa  # noqa: E402


def _log(tree: Path, rows):
    path = tree / "name_masking_logs" / "rec" / "name_replacements.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["filename", "order", "original", "replacement",
                         "context_sentence"])
        for i, (original, replacement) in enumerate(rows, start=1):
            writer.writerow(["rec.wav", i, original, replacement, "context"])


def test_possessives_are_stripped_from_logged_names(tmp_path):
    _log(tmp_path, [("Bernabeu's", "[SURNAME]'s"), ("Pablo’s", "[NAME]"),
                    ("James'", "[NAME]")])
    names = aa.extract_masked_names(
        tmp_path / "name_masking_logs" / "rec" / "name_replacements.csv")
    assert names == {"Bernabeu", "Pablo", "James"}


def test_a_lower_cased_name_is_reported_apart(tmp_path):
    _log(tmp_path, [("Pablo", "[NAME]")])
    (tmp_path / "talk_transcript.txt").write_text(
        "[NAME] introduced the talk. Thanks, pablo.", encoding="utf-8")
    findings, _ = aa.audit_directory(tmp_path)
    txt = next(f for f in findings if f.path == "talk_transcript.txt")
    assert txt.leaked_names == []
    assert txt.residual_pii_found is False
    assert txt.leaked_names_casefold == ["Pablo"]
    assert "ignoring case also matches Pablo" in txt.detail

    out = tmp_path / "audit"
    aa.write_csv(findings, out / "artefact_audit.csv")
    aa.write_json(findings, {"Pablo"}, out / "artefact_audit.json")
    with open(out / "artefact_audit.csv", encoding="utf-8", newline="") as fh:
        row = next(r for r in csv.DictReader(fh) if r["path"] == "talk_transcript.txt")
    assert row["leaked_names_casefold"] == "Pablo"
    summary = json.loads((out / "artefact_audit.json").read_text(encoding="utf-8"))["summary"]
    assert summary["masked_artefacts_casefold_only"] == 1
    assert summary["masked_artefacts_leaking"] == 0


def test_a_verbatim_leak_is_not_listed_twice(tmp_path):
    _log(tmp_path, [("Pablo", "[NAME]")])
    (tmp_path / "talk_transcript.txt").write_text("Pablo and pablo", encoding="utf-8")
    findings, _ = aa.audit_directory(tmp_path)
    txt = next(f for f in findings if f.path == "talk_transcript.txt")
    assert txt.leaked_names == ["Pablo"] and txt.leaked_names_casefold == []
