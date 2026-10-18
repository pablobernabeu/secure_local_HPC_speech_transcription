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


def test_required_cff_keys_are_present():
    cff = _citation()
    for key in ("cff-version", "message", "title", "authors"):
        assert cff.get(key)
    assert cff["cff-version"] == "1.2.0"
