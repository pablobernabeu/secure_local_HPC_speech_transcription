"""Tests for the corpus-level metric aggregation in ``evaluation.wer``.

The pair-level metrics WER, MER, WIL and CER are computed by ``jiwer`` and
need not be retested here.  These tests exercise the aggregation layer
that pools per-pair :class:`PairResult` objects into the corpus-level
summary used by the WER CLI, the benchmark CLI and the manuscript.
"""

from __future__ import annotations

import math

import pytest

pytest.importorskip("jiwer")

from evaluation.wer import PairResult, aggregate  # noqa: E402


def _pair(
    name: str,
    *,
    wer: float,
    mer: float,
    wil: float,
    cer: float,
    hits: int,
    subs: int,
    dels: int,
    ins: int,
) -> PairResult:
    """Construct a ``PairResult`` with the four metric counts derived
    consistently from the alignment counts supplied."""
    return PairResult(
        name=name,
        wer=wer,
        mer=mer,
        wil=wil,
        cer=cer,
        hits=hits,
        substitutions=subs,
        deletions=dels,
        insertions=ins,
        reference_words=hits + subs + dels,
        hypothesis_words=hits + subs + ins,
    )


def test_aggregate_empty_returns_empty_dict():
    assert aggregate([]) == {}


def test_aggregate_preserves_legacy_keys():
    """The keys that existed before the MER/WIL/CER extension must
    still be present and carry their previous semantics so downstream
    consumers (benchmark CLI, manuscript fallbacks) do not break."""
    rs = [
        _pair("a", wer=0.10, mer=0.09, wil=0.18, cer=0.05,
              hits=9, subs=1, dels=0, ins=0),
    ]
    s = aggregate(rs)
    for key in (
        "files", "macro_wer", "micro_wer",
        "total_reference_words", "total_substitutions",
        "total_deletions", "total_insertions",
    ):
        assert key in s, f"legacy key {key!r} missing from aggregate output"


def test_aggregate_macro_metrics_are_unweighted_means():
    rs = [
        _pair("a", wer=0.10, mer=0.10, wil=0.20, cer=0.05,
              hits=9, subs=1, dels=0, ins=0),
        _pair("b", wer=0.30, mer=0.30, wil=0.50, cer=0.15,
              hits=7, subs=3, dels=0, ins=0),
    ]
    s = aggregate(rs)
    assert s["files"] == 2
    assert math.isclose(s["macro_wer"], 0.20)
    assert math.isclose(s["macro_mer"], 0.20)
    assert math.isclose(s["macro_wil"], 0.35)
    assert math.isclose(s["macro_cer"], 0.10)


def test_aggregate_micro_wer_pools_counts():
    """Micro-WER is pooled errors over pooled reference words; the
    second pair's larger reference count dominates."""
    rs = [
        _pair("small", wer=0.50, mer=0.50, wil=0.75, cer=0.40,
              hits=1, subs=1, dels=0, ins=0),
        _pair("large", wer=0.10, mer=0.10, wil=0.20, cer=0.05,
              hits=90, subs=10, dels=0, ins=0),
    ]
    s = aggregate(rs)
    # 11 errors over 102 reference words.
    assert math.isclose(s["micro_wer"], 11 / 102)
    # 11 errors / (11 errors + 91 hits) = 11/102 as well in this case.
    assert math.isclose(s["micro_mer"], 11 / 102)


def test_aggregate_micro_mer_handles_zero_alignment_safely():
    """An empty corpus produces no aggregate; a corpus with zero
    alignment tokens (no hits and no errors) should not divide by zero
    and should produce a NaN micro value rather than raising."""
    rs = [
        _pair("empty_alignment", wer=0.0, mer=0.0, wil=0.0, cer=0.0,
              hits=0, subs=0, dels=0, ins=0),
    ]
    s = aggregate(rs)
    assert math.isnan(s["micro_wer"])
    assert math.isnan(s["micro_mer"])


def test_aggregate_pooled_counts_are_summed():
    rs = [
        _pair("a", wer=0.10, mer=0.10, wil=0.20, cer=0.05,
              hits=9, subs=1, dels=0, ins=0),
        _pair("b", wer=0.30, mer=0.30, wil=0.50, cer=0.15,
              hits=7, subs=3, dels=0, ins=2),
    ]
    s = aggregate(rs)
    assert s["total_hits"] == 16
    assert s["total_substitutions"] == 4
    assert s["total_deletions"] == 0
    assert s["total_insertions"] == 2
    assert s["total_reference_words"] == 20
    assert s["total_hypothesis_words"] == 22
