"""Tests for the run-to-run variation comparator.

The reproducibility claim rests on the same audio producing the same
words twice, which on a GPU is not automatic. This comparator is what
turns that from an assumption into a number, so its own failure modes
matter: reporting agreement it did not observe, or comparing a run
against a truncated one and calling the result perfect.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation.determinism import (  # noqa: E402
    compare,
    compare_files,
    read_hypotheses,
    word_edit_distance,
)


class TestWordEditDistance:
    def test_identical_strings_are_zero_apart(self):
        assert word_edit_distance("the cat sat", "the cat sat") == 0

    def test_one_substitution(self):
        assert word_edit_distance("the cat sat", "the dog sat") == 1

    def test_insertion_and_deletion(self):
        assert word_edit_distance("the cat", "the big cat") == 1
        assert word_edit_distance("the big cat", "the cat") == 1

    def test_it_works_on_words_not_characters(self):
        """'cat' and 'cats' differ by one word, not by one letter."""
        assert word_edit_distance("cat", "cats") == 1

    def test_empty_against_non_empty(self):
        assert word_edit_distance("", "a b c") == 3
        assert word_edit_distance("a b c", "") == 3
        assert word_edit_distance("", "") == 0

    def test_none_is_treated_as_empty(self):
        assert word_edit_distance(None, "a") == 1


class TestCompare:
    def test_two_identical_runs_agree_completely(self):
        run = {"u1": "the cat sat", "u2": "on the mat"}
        summary = compare({"a": dict(run), "b": dict(run)})
        assert summary["exact_match_rate"] == pytest.approx(1.0)
        assert summary["differing"] == 0
        assert summary["max_word_divergence"] == 0.0

    def test_a_single_differing_utterance_is_found(self):
        summary = compare({
            "a": {"u1": "the cat sat", "u2": "on the mat"},
            "b": {"u1": "the cat sat", "u2": "on the hat"},
        })
        assert summary["identical"] == 1
        assert summary["differing"] == 1
        assert summary["exact_match_rate"] == pytest.approx(0.5)
        assert summary["most_divergent"] == ["u2"]

    def test_divergence_is_scaled_by_utterance_length(self):
        """One word in three is worse than one word in twenty."""
        short = compare({"a": {"u": "a b c"}, "b": {"u": "a b z"}})
        long = compare({"a": {"u": " ".join("abcdefghijklmnopqrst")},
                        "b": {"u": " ".join("abcdefghijklmnopqrsz")}})
        assert short["max_word_divergence"] > long["max_word_divergence"]

    def test_utterances_missing_from_a_run_are_dropped_and_reported(self):
        """A truncated run must not read as perfect agreement."""
        summary = compare({
            "a": {"u1": "x", "u2": "y", "u3": "z"},
            "b": {"u1": "x"},
        })
        assert summary["utterances_compared"] == 1
        assert summary["utterances_dropped_per_run"]["a"] == 2
        assert summary["exact_match_rate"] == pytest.approx(1.0)

    def test_three_runs_compare_pairwise(self):
        summary = compare({
            "a": {"u": "one two"},
            "b": {"u": "one two"},
            "c": {"u": "one three"},
        })
        assert summary["differing"] == 1
        assert summary["runs"] == ["a", "b", "c"]

    def test_a_single_run_cannot_measure_determinism(self):
        with pytest.raises(ValueError, match="at least two"):
            compare({"only": {"u": "x"}})

    def test_no_shared_utterances_does_not_divide_by_zero(self):
        summary = compare({"a": {"u1": "x"}, "b": {"u2": "y"}})
        assert summary["utterances_compared"] == 0
        assert summary["exact_match_rate"] is None


class TestReadHypotheses:
    def _dump(self, path, rows):
        fields = ["uid", "condition", "reference", "hypothesis_raw",
                  "hypothesis_transformed", "wer"]
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for r in rows:
                writer.writerow(r)

    def test_only_the_requested_condition_is_read(self, tmp_path):
        """Comparing across conditions would measure the transform, not the run."""
        path = tmp_path / "run.csv"
        self._dump(path, [
            {"uid": "u1", "condition": "raw", "reference": "r",
             "hypothesis_raw": "model output",
             "hypothesis_transformed": "model output", "wer": "0"},
            {"uid": "u1", "condition": "pipeline_full", "reference": "r",
             "hypothesis_raw": "model output",
             "hypothesis_transformed": "Model output.", "wer": "0"},
        ])
        assert read_hypotheses(path, "raw") == {"u1": "model output"}

    def test_files_are_labelled_by_their_stem(self, tmp_path):
        for name in ("seed0", "seed1"):
            self._dump(tmp_path / f"{name}.csv", [
                {"uid": "u1", "condition": "raw", "reference": "r",
                 "hypothesis_raw": "same", "hypothesis_transformed": "same",
                 "wer": "0"}])
        summary = compare_files([tmp_path / "seed0.csv", tmp_path / "seed1.csv"])
        assert summary["runs"] == ["seed0", "seed1"]
        assert summary["exact_match_rate"] == pytest.approx(1.0)
