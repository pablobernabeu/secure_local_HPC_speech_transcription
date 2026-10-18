"""Unit tests for ``evaluation.benchmark_masking``.

These tests exercise the scorer and the metric aggregation on tiny,
hand-built cases with a stub masker, so they run without any optional
dependency (no torch / transformers / the real curated database).  The
two headline behaviours of the masker are checked directly:

* a capitalised, in-dictionary name is redacted -> the case is a hit and
  recall is 1.0;
* a lower-cased, out-of-dictionary name is missed -> the case leaks and
  recall is 0.0 (leakage 1.0).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.benchmark_masking import (  # noqa: E402
    _Case,
    _score_case,
    summarise,
)


def _stub_masker(known_capitalised):
    """Return a mask function that redacts only the given Title-cased names.

    The stub mimics the real masker's two defining rules without the
    database: it replaces a token with ``[NAME]`` only when the token is in
    *known_capitalised* exactly (so lower-cased variants are missed, and
    unknown names are missed).  Surrounding punctuation is preserved.
    """
    known = set(known_capitalised)

    def mask(text: str) -> str:
        out = []
        for tok in text.split():
            core = tok.rstrip(".!?,")
            tail = tok[len(core):]
            out.append("[NAME]" + tail if core in known else tok)
        return " ".join(out)

    return mask


def _make_case(name, sentence, *, in_db, casing, morphology="bare"):
    return _Case(
        name=name,
        language="english",
        in_db=in_db,
        kind="first",
        casing=casing,
        position="mid",
        morphology=morphology,
        template="x {name} y",
        gold_token=name,
        sentence=sentence,
    )


def test_known_capitalised_name_is_a_hit():
    """A redacted in-dictionary name scores a hit (recall 1, no leak)."""
    case = _make_case(
        "Ahmed",
        "Yesterday the patient told Ahmed about the results.",
        in_db=True,
        casing="title",
    )
    _score_case(case, _stub_masker({"Ahmed"}))
    assert case.hit is True
    assert case.false_positives == 0
    assert case.replaced_total == 1

    summary = summarise([case], seed=0, n_per_cell=1)
    assert summary["overall"]["recall"] == 1.0
    assert summary["overall"]["leakage"] == 0.0
    assert summary["overall"]["precision"] == 1.0


def test_lowercase_out_of_db_name_leaks():
    """A lower-cased out-of-dictionary name is missed (recall 0, leak 1)."""
    case = _make_case(
        "bjork",
        "Yesterday the patient told bjork about the results.",
        in_db=False,
        casing="lower",
    )
    # The stub only knows the Title-cased form, so the lower-cased token is
    # never redacted -- exactly the masker's capitalisation blind spot.
    _score_case(case, _stub_masker({"Bjork"}))
    assert case.hit is False
    assert case.replaced_total == 0

    summary = summarise([case], seed=0, n_per_cell=1)
    assert summary["overall"]["recall"] == 0.0
    assert summary["overall"]["leakage"] == 1.0


def test_content_token_false_positive_lowers_precision():
    """A carrier content token wrongly redacted counts as a false positive."""
    case = _make_case(
        "Ahmed",
        "Yesterday the patient told Ahmed about the results.",
        in_db=True,
        casing="title",
    )
    # The stub over-masks the carrier word "patient" as well as the name.
    _score_case(case, _stub_masker({"Ahmed", "patient"}))
    assert case.hit is True
    assert case.false_positives == 1
    assert case.replaced_total == 2

    summary = summarise([case], seed=0, n_per_cell=1)
    assert summary["overall"]["recall"] == 1.0
    assert summary["overall"]["precision"] == pytest.approx(0.5)


def test_breakdowns_split_by_casing_and_membership():
    """The summary separates in_db / out_of_db and title / lower cells."""
    hit = _make_case(
        "Ahmed",
        "Yesterday the patient told Ahmed about the results.",
        in_db=True,
        casing="title",
    )
    leak = _make_case(
        "bjork",
        "Yesterday the patient told bjork about the results.",
        in_db=False,
        casing="lower",
    )
    masker = _stub_masker({"Ahmed", "Bjork"})
    _score_case(hit, masker)
    _score_case(leak, masker)

    summary = summarise([hit, leak], seed=42, n_per_cell=1)
    assert summary["n"] == 2
    assert summary["seed"] == 42
    assert summary["by_in_db"]["in_db"]["recall"] == 1.0
    assert summary["by_in_db"]["out_of_db"]["leakage"] == 1.0
    assert summary["by_casing"]["title"]["recall"] == 1.0
    assert summary["by_casing"]["lower"]["recall"] == 0.0


def test_by_morphology_breakdown_present():
    """The summary splits bare vs possessive cases."""
    bare = _make_case(
        "Ahmed", "Yesterday the patient told Ahmed about the results.",
        in_db=True, casing="title", morphology="bare",
    )
    poss = _make_case(
        "Ahmed's", "Yesterday the patient told Ahmed's about the results.",
        in_db=True, casing="title", morphology="possessive",
    )
    masker = _stub_masker({"Ahmed", "Ahmed's"})
    _score_case(bare, masker)
    _score_case(poss, masker)
    summary = summarise([bare, poss], seed=0, n_per_cell=1)
    assert set(summary["by_morphology"]) == {"bare", "possessive"}
    assert summary["by_morphology"]["possessive"]["recall"] == 1.0


def test_real_masker_redacts_possessive_and_lowercase_under_ci():
    """Regression: the real masker masks a capitalised possessive, and a
    lower-cased name only under case_insensitive=True."""
    import contextlib
    import csv
    import io

    from transcription import create_enhanced_name_masker

    # An in-dictionary English first name of reasonable length.
    with open(PROJECT_ROOT / "data" / "curated_names.csv", encoding="utf-8") as fh:
        names = [
            r["name"] for r in csv.DictReader(fh)
            if r["type"] == "first" and r["language"] == "english"
            and len(r["name"]) >= 4
        ]
    name = names[0].capitalize()

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        mask, _ = create_enhanced_name_masker()
        mask_ci, _ = create_enhanced_name_masker(case_insensitive=True)

    # Capitalised possessive is now redacted (clitic stripping).
    assert "[NAME]" in mask(f"I met {name}'s friend.")
    # An internal apostrophe must not be mistaken for a clitic.
    assert mask("I met O'Brien today.") == "I met O'Brien today."
    # Lower-cased name leaks by default but is caught under case_insensitive.
    assert "[NAME]" not in mask(f"i met {name.lower()} today.")
    assert "[NAME]" in mask_ci(f"i met {name.lower()} today.")
