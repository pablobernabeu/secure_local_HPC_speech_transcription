"""The masker's honorific list and the benchmark's copy stay identical.

Audit finding T1-13: the list was retyped in evaluation/benchmark_masking.py,
where it decides which [TITLE] placeholders leave the precision
denominator. Until the benchmark imports TITLE_WORDS, this test catches
drift between the two.
"""

from __future__ import annotations


def test_benchmark_copy_matches(transcription_module):
    from evaluation.benchmark_masking import _TITLE_WORDS
    assert set(transcription_module.TITLE_WORDS) == set(_TITLE_WORDS)
