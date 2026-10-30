"""CITATION.cff stays valid CFF 1.2.0 and agrees with setup.py (DOCS-15).

The full schema check needs the CFF schema, which is not vendored; these
tests cover the two defects the audit found: a ``preferred-citation`` given
as a BibTeX string (the schema requires a reference object, so GitHub's
"Cite this repository" and Zenodo's import rejected the file) and a missing
``repository-code``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parent.parent


def _citation() -> dict:
    return yaml.safe_load((REPO / "CITATION.cff").read_text(encoding="utf-8"))


def test_preferred_citation_is_absent_or_a_reference_object():
    ref = _citation().get("preferred-citation")
    assert ref is None or isinstance(ref, dict)


def test_repository_code_matches_setup_py():
    setup_py = (REPO / "setup.py").read_text(encoding="utf-8")
    match = re.search(r'^_REPO_URL = "([^"]+)"', setup_py, re.M)
    assert match
    assert _citation()["repository-code"] == match.group(1)


def test_release_version_agrees_across_setup_citation_and_versions_csv():
    """setup.py and CITATION.cff retype the release that versions.csv records.

    The three are updated by hand at each release (docs/release_readiness.md),
    and nothing compared them, so one left behind would go unnoticed. The
    newest release is the one transcription._latest_release returns, the
    function that stamps it on transcripts, imported here rather than copied
    so that the test cannot drift from it.
    """
    import csv

    from transcription import _latest_release

    newest = _latest_release(REPO / "versions.csv")
    assert newest
    with (REPO / "versions.csv").open(encoding="utf-8", newline="") as handle:
        dates = {row["date"].strip() for row in csv.DictReader(handle)
                 if (row.get("version") or "").strip() == newest}
    assert len(dates) == 1, f"release {newest} is listed with dates {sorted(dates)}"
    setup_py = (REPO / "setup.py").read_text(encoding="utf-8")
    match = re.search(r'^\s*version="([^"]+)"', setup_py, re.M)
    assert match
    cff = _citation()
    assert match.group(1) == newest
    assert str(cff["version"]) == newest
    assert str(cff["date-released"]) == dates.pop()


def test_required_cff_keys_are_present():
    cff = _citation()
    for key in ("cff-version", "message", "title", "authors"):
        assert cff.get(key)
    assert cff["cff-version"] == "1.2.0"
