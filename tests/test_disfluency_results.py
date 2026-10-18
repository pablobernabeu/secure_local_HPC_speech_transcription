"""Pins the committed filler-preservation results.

``output/evaluation/disfluency_summary.json`` and ``disfluency_report.csv``
score the AMI dump of the audit's Large v3 sweep (ARC job 8917985, code
6f9bf56) under ``raw``, ``pipeline_full`` and ``whisper_norm``; the
:mod:`evaluation.disfluency` docstring gives the command. These tests check
that the two files agree with each other and with the scorer's own
arithmetic, and that they were made with the detector the code now holds,
so a change to the detector without a rescore fails here. They also pin
the figures the manuscript's disfluency section reads, from the
``conditions`` block, so that a regenerated file which moves one of them
is noticed before the manuscript prints it.

No model, audio or dump is needed: the tests read the committed files only.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from evaluation import disfluency
from transcription import FILLER_TOKENS

_EVAL = Path(__file__).resolve().parents[1] / "output" / "evaluation"
_SUMMARY = _EVAL / "disfluency_summary.json"
_REPORT = _EVAL / "disfluency_report.csv"
_CONDITIONS = ("raw", "pipeline_full", "whisper_norm")
_BLOCKS = {"own": "conditions", "shared": "conditions_shared_set"}
_COUNTS = ("n_utterances", "n_reference_unknown", "reference_fillers",
           "raw_fillers", "output_fillers", "output_marked", "retained",
           "reference_recovered")
_RATES = ("retention", "reference_recall", "output_over_reference")


@pytest.fixture(scope="module")
def summary() -> dict:
    return json.loads(_SUMMARY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def report() -> list[dict]:
    with _REPORT.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


class TestProvenance:
    def test_it_was_counted_with_the_current_detector(self, summary):
        """A detector change that is not followed by a rescore fails here."""
        assert summary["detector_pattern"] == disfluency._FILLER_PATTERN.pattern
        assert summary["filler_tokens"] == list(FILLER_TOKENS)

    def test_recall_divides_by_the_transcriber_reference(self, summary):
        """ESTATS-01: never by a reference a condition transformed."""
        assert summary["reference_source"] == "reference_raw column"
        for block in _BLOCKS.values():
            for name in _CONDITIONS:
                assert summary[block][name]["n_reference_unknown"] == 0

    def test_it_names_the_dump_it_scored(self, summary):
        """The SHA-256 sha256sum prints for the sweep's AMI dump on ARC.

        The digest identifies the input; ``source`` is only the path the
        dump was given by, which depends on where the rescore ran.
        """
        assert summary["source"].endswith("wer_hypotheses_ami_whisper-large-v3.csv")
        assert summary["source_sha256"] == (
            "3fa3957260f28a3af42ee0deadcda4445a1fd5142b94ba316127e2e4190716bf")
        assert summary["conditions_selected"] == list(_CONDITIONS)
        assert summary["run_metadata"]["git_dirty"] is False

    def test_it_holds_the_two_blocks_and_no_other(self, summary):
        """The manuscript reads ``conditions``; a block renamed or added
        under another name would leave it reading the wrong set."""
        blocks = {key for key, value in summary.items()
                  if key.startswith("conditions") and isinstance(value, dict)}
        assert blocks == set(_BLOCKS.values())


class TestConsistency:
    @pytest.mark.parametrize("block", sorted(_BLOCKS.values()))
    @pytest.mark.parametrize("name", _CONDITIONS)
    def test_rates_follow_from_the_counts(self, summary, block, name):
        s = summary[block][name]
        assert s["retention"] == round(s["retained"] / s["raw_fillers"], 4)
        assert s["reference_recall"] == round(
            s["reference_recovered"] / s["reference_fillers"], 4)
        assert s["output_over_reference"] == round(
            s["output_fillers"] / s["reference_fillers"], 4)
        assert s["retained"] <= min(s["raw_fillers"], s["output_fillers"])
        assert s["reference_recovered"] <= min(s["reference_fillers"],
                                               s["output_fillers"])
        assert s["output_marked"] <= s["output_fillers"]

    def test_the_shared_block_is_one_set_of_utterances(self, summary):
        sizes = {summary["conditions_shared_set"][n]["n_utterances"]
                 for n in _CONDITIONS}
        assert sizes == {summary["n_shared_utterances"]}

    def test_each_own_set_accounts_for_every_utterance(self, summary):
        for name in _CONDITIONS:
            own = summary["conditions"][name]
            assert own["n_utterances"] + own["n_utterances_dropped"] == \
                summary["n_utterances"]

    def test_the_csv_holds_the_json(self, summary, report):
        assert {(r["condition"], r["set"]) for r in report} == {
            (n, s) for n in _CONDITIONS for s in _BLOCKS}
        for row in report:
            s = summary[_BLOCKS[row["set"]]][row["condition"]]
            for field in _COUNTS:
                assert int(row[field]) == s[field], (row["condition"], field)
            for field in _RATES:
                assert float(row[field]) == s[field], (row["condition"], field)


class TestPinnedFigures:
    """The figures as committed; a rescore that moves one must say why."""

    def test_the_corpus_and_the_normaliser_discard(self, summary):
        """The discard paragraph's arithmetic, on the block it reads."""
        assert summary["n_utterances"] == 12643
        assert summary["n_shared_utterances"] == 11653
        block = summary["conditions"]
        raw, norm = block["raw"], block["whisper_norm"]
        assert raw["n_utterances"] == summary["n_utterances"]
        assert raw["n_utterances"] - norm["n_utterances"] == \
            norm["n_utterances_dropped"] == 990
        # The discarded utterances held 838 of the model's 1,195 fillers.
        assert raw["raw_fillers"] - norm["raw_fillers"] == 838

    @pytest.mark.parametrize("name", ["raw", "pipeline_full"])
    def test_the_whole_split(self, summary, name):
        """Each condition's own set: all 12,643 utterances."""
        s = summary["conditions"][name]
        assert (s["reference_fillers"], s["raw_fillers"], s["output_fillers"],
                s["retained"], s["reference_recovered"]) == \
            (4072, 1195, 1195, 1195, 802)
        assert (s["retention"], s["reference_recall"]) == (1.0, 0.197)

    @pytest.mark.parametrize("name", ["raw", "pipeline_full"])
    def test_the_shared_set(self, summary, name):
        """The 11,653 utterances the normaliser also scores."""
        s = summary["conditions_shared_set"][name]
        assert (s["reference_fillers"], s["raw_fillers"], s["output_fillers"],
                s["retained"], s["reference_recovered"]) == \
            (3066, 357, 357, 357, 226)
        assert (s["retention"], s["reference_recall"]) == (1.0, 0.0737)

    @pytest.mark.parametrize("block", sorted(_BLOCKS.values()))
    def test_the_normaliser(self, summary, block):
        """Its own set is the shared set, so both blocks agree."""
        s = summary[block]["whisper_norm"]
        assert (s["n_utterances"], s["reference_fillers"], s["raw_fillers"],
                s["output_fillers"], s["retained"], s["reference_recovered"]) == \
            (11653, 3066, 357, 2, 2, 0)
        assert (s["retention"], s["reference_recall"]) == (0.0056, 0.0)

    def test_the_composite_keeps_what_the_model_emits(self, summary):
        """The manuscript's claim, on both sets: a marking-only layer."""
        for block in _BLOCKS.values():
            full = summary[block]["pipeline_full"]
            raw = summary[block]["raw"]
            assert full["retained"] == full["raw_fillers"] == raw["raw_fillers"]
            assert full["output_fillers"] == full["raw_fillers"]

    def test_the_composite_marks_all_but_the_lengthened_spellings(self, summary):
        """XREF-08: four kept fillers are spelt outside the bracketing list
        (one "Errr...", two "Mmm", one "Mm-mm-mm"); one of them lies in the
        shared set. Nothing else marks a filler."""
        assert summary["conditions"]["pipeline_full"]["output_marked"] == 1191
        assert summary["conditions_shared_set"]["pipeline_full"][
            "output_marked"] == 356
        for block in _BLOCKS.values():
            assert summary[block]["raw"]["output_marked"] == 0
            assert summary[block]["whisper_norm"]["output_marked"] == 0
