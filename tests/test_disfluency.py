"""Tests for the filler-preservation scorer.

The measurement exists because aggregate word error rate cannot
distinguish a condition that keeps every hesitation from one that deletes
every hesitation: the rate counts how many words differ, not which. These
tests pin the two rates apart, and pin the refusal to report a rate whose
denominator is zero, which is the way a benchmark most easily invents a
result.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation.disfluency import (
    aggregate,
    count_fillers,
    score_dump,
    score_pair,
)


class TestCountFillers:
    def test_counts_each_occurrence_not_each_type(self):
        """Losing one of three is not the same as losing all three."""
        assert sum(count_fillers("uh well uh yes uh").values()) == 3

    def test_is_case_insensitive_and_folds_to_lower(self):
        assert count_fillers("Um UH er")["um"] == 1
        assert count_fillers("Um UH er")["uh"] == 1

    def test_bracketed_fillers_count_as_the_filler_they_wrap(self):
        """The filler_bracket stage marks them; it does not remove them."""
        assert count_fillers("so [uh] then [um] right") == count_fillers("so uh then um right")

    def test_a_filler_inside_a_word_is_not_counted(self):
        """Word boundaries matter: 'ah' must not fire inside 'ahead'."""
        assert count_fillers("ahead of the summary") == count_fillers("")

    def test_ordinary_prose_has_none(self):
        assert sum(count_fillers("the committee agreed to publish").values()) == 0

    def test_empty_and_missing_text_are_safe(self):
        assert count_fillers("") == count_fillers(None)


class TestScorePair:
    def test_a_condition_that_keeps_fillers_retains_all_of_them(self):
        s = score_pair("so uh yes", "so uh yes", "So uh yes.")
        assert s["raw_fillers"] == 1
        assert s["retained"] == 1

    def test_a_condition_that_strips_fillers_retains_none(self):
        s = score_pair("so uh yes", "so uh yes", "so yes")
        assert s["raw_fillers"] == 1
        assert s["retained"] == 0

    def test_partial_loss_is_counted_per_token(self):
        """Three reduced to one is one survivor, not full survival."""
        s = score_pair("uh uh uh", "uh uh uh", "uh")
        assert s["raw_fillers"] == 3
        assert s["retained"] == 1

    def test_reference_recall_is_separate_from_retention(self):
        """A filler the model never heard cannot be preserved downstream."""
        s = score_pair("so uh yes", "so yes", "so yes")
        assert s["reference_fillers"] == 1
        assert s["raw_fillers"] == 0
        assert s["retained"] == 0            # nothing was there to keep
        assert s["reference_recovered"] == 0  # and the reference filler is lost

    def test_an_invented_filler_does_not_count_as_recovery(self):
        s = score_pair("so yes", "so uh yes", "so uh yes")
        assert s["reference_fillers"] == 0
        assert s["reference_recovered"] == 0
        assert s["output_fillers"] == 1


class TestAggregate:
    def _rows(self, *triples):
        return [score_pair(*t) for t in triples]

    def test_rates_are_token_weighted_across_utterances(self):
        rows = self._rows(("uh uh", "uh uh", "uh"),      # 1 of 2 kept
                          ("uh uh", "uh uh", "uh uh"))   # 2 of 2 kept
        summary = aggregate(rows)
        assert summary["raw_fillers"] == 4
        assert summary["retained"] == 3
        assert summary["retention"] == pytest.approx(0.75)

    def test_a_rate_with_no_denominator_is_none_not_zero_or_one(self):
        """The failure this benchmark could most easily fake."""
        summary = aggregate(self._rows(("no fillers here",) * 3))
        assert summary["raw_fillers"] == 0
        assert summary["retention"] is None
        assert summary["reference_recall"] is None
        assert summary["output_over_reference"] is None

    def test_reference_recall_reported_even_when_retention_is_undefined(self):
        """The model heard nothing, but the reference still had fillers."""
        summary = aggregate(self._rows(("so uh yes", "so yes", "so yes")))
        assert summary["retention"] is None
        assert summary["reference_recall"] == pytest.approx(0.0)

    def test_counts_utterances(self):
        assert aggregate(self._rows(("a",) * 3, ("b",) * 3))["n_utterances"] == 2

    def test_an_empty_input_does_not_divide_by_zero(self):
        summary = aggregate([])
        assert summary["n_utterances"] == 0
        assert summary["retention"] is None


class TestScoreDump:
    def _write(self, path, rows):
        fields = ["uid", "condition", "reference", "hypothesis_raw",
                  "hypothesis_transformed", "wer"]
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for r in rows:
                writer.writerow(r)

    def test_conditions_are_scored_separately(self, tmp_path):
        """The comparison the benchmark exists to make.

        The whisper_norm row's reference is written transformed, as
        benchmark_wer wrote it before the dump split its reference columns
        (ESTATS-01); recall is still scored against the transcriber's."""
        path = tmp_path / "dump.csv"
        self._write(path, [
            {"uid": "u1", "condition": "pipeline_full", "reference": "so uh yes",
             "hypothesis_raw": "so uh yes",
             "hypothesis_transformed": "So [uh] yes.", "wer": "0.0"},
            {"uid": "u1", "condition": "whisper_norm", "reference": "so yes",
             "hypothesis_raw": "so uh yes",
             "hypothesis_transformed": "so yes", "wer": "0.3"},
        ])
        summary = score_dump(path)
        assert summary["pipeline_full"]["retention"] == pytest.approx(1.0)
        assert summary["whisper_norm"]["retention"] == pytest.approx(0.0)
        assert summary["whisper_norm"]["reference_fillers"] == 1
        assert summary["whisper_norm"]["reference_recall"] == pytest.approx(0.0)

    def test_rows_of_the_same_condition_are_pooled(self, tmp_path):
        path = tmp_path / "dump.csv"
        self._write(path, [
            {"uid": f"u{i}", "condition": "raw", "reference": "uh",
             "hypothesis_raw": "uh", "hypothesis_transformed": "uh",
             "wer": "0.0"} for i in range(3)
        ])
        summary = score_dump(path)
        assert summary["raw"]["n_utterances"] == 3
        assert summary["raw"]["retention"] == pytest.approx(1.0)

    def test_a_dump_with_only_a_header_yields_nothing(self, tmp_path):
        path = tmp_path / "dump.csv"
        self._write(path, [])
        assert score_dump(path) == {}


# ---------------------------------------------------------------------------
# Detection vocabulary
#
# The workflow holds two filler lists and neither contains the other:
# transcription.FILLER_TOKENS has the backchannels uhuh/uhhuh, while the
# pattern behind filler_strip has erm/uhm/hm and lengthened spellings. A
# scorer narrower than either would shrink its own denominator, so that a
# condition deleting every "erm" would score as having preserved fillers,
# none having been counted. These tests keep the detector a superset.
# ---------------------------------------------------------------------------

class TestDetectionVocabulary:
    def test_it_sees_everything_the_bracketing_list_names(self):
        from transcription import FILLER_TOKENS
        for token in FILLER_TOKENS:
            assert sum(count_fillers(f"yes {token} really").values()) == 1, (
                f"{token!r} is bracketed by the pipeline but invisible here")

    def test_it_sees_everything_filler_strip_removes(self):
        """Otherwise its removals would not register as removals."""
        from evaluation.conditions import get_condition
        strip = get_condition("filler_strip")
        for token in ("um", "uh", "uhm", "umm", "erm", "er", "ah", "mm",
                      "mhm", "hmm", "hm", "ummm", "uhhh"):
            probe = f"yes {token} really"
            if strip.transform(probe) != probe:          # it removed something
                assert sum(count_fillers(probe).values()) >= 1, (
                    f"filler_strip removes {token!r} but the scorer cannot "
                    "see it, so the removal would go uncounted")

    def test_lengthened_spellings_count_as_the_same_filler(self):
        assert count_fillers("ummm") == count_fillers("um")
        assert count_fillers("uhhh") == count_fillers("uh")
        assert count_fillers("uhhuh") == count_fillers("uhuh")

    def test_distinct_fillers_do_not_merge(self):
        """Canonicalisation must not collapse different hesitations."""
        assert count_fillers("mm") != count_fillers("mhm")
        assert count_fillers("er") != count_fillers("erm")

    def test_a_rewritten_length_still_counts_as_preserved(self):
        """The reason canonicalisation exists."""
        s = score_pair("so ummm yes", "so ummm yes", "so um yes")
        assert s["retained"] == 1

    def test_word_boundaries_still_hold_for_the_wider_vocabulary(self):
        for word in ("ahead", "summary", "hermit", "farmer", "erman"):
            assert sum(count_fillers(word).values()) == 0, word


class TestConditionAudit:
    def test_the_production_composite_keeps_every_filler(self, ):
        """The claim the manuscript makes, checked against the transforms."""
        from evaluation.disfluency import audit_conditions
        audit = audit_conditions(("pipeline_full",))
        assert all(audit["pipeline_full"].values())

    def test_the_scoring_normaliser_removes_only_some(self):
        """A partial removal is the awkward case for a filler-bearing design."""
        from evaluation.disfluency import audit_conditions
        audit = audit_conditions(("whisper_norm",))
        if "whisper_norm" not in audit:
            pytest.skip("whisper_norm needs openai-whisper's spelling map")
        kept = audit["whisper_norm"]
        assert not kept["um"] and not kept["uh"]
        assert kept["er"] and kept["ah"]

    def test_an_unregistered_name_is_left_out_aloud(self, capsys):
        """A misspelt condition used to vanish from the table without a word."""
        from evaluation.disfluency import audit_conditions
        audit = audit_conditions(("raw", "pipline_full"))
        assert list(audit) == ["raw"]
        err = capsys.readouterr().err
        assert "'pipline_full' is not a registered condition" in err
        # The registered names, which say what the misspelling should be.
        assert "Available conditions:" in err and "pipeline_full" in err

    def test_the_audit_honours_conditions(self, tmp_path):
        """--audit-conditions used to ignore --conditions and probe the
        default five whatever was asked."""
        import json

        from evaluation.disfluency import main
        out = tmp_path / "audit.json"
        assert main(["--audit-conditions", "--conditions", "filler_strip,raw",
                     "--json", str(out)]) == 0
        written = json.loads(out.read_text(encoding="utf-8"))
        assert list(written["conditions"]) == ["filler_strip", "raw"]
        assert written["conditions_selected"] == ["filler_strip", "raw"]

    def test_an_audit_with_nothing_to_run_exits_2(self, capsys):
        from evaluation.disfluency import main
        assert main(["--audit-conditions", "--conditions", "pipline_full"]) == 2
        assert "no condition left to audit" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Hyphenated backchannels
#
# AMI writes its backchannels hyphenated ("MM-HMM", "UH-HUH"). A detector
# whose word boundaries excluded the hyphen could not see them at all, yet
# it could see the pieces once filler_bracket split them into
# "[Mm]-[hmm]". That asymmetry made the pilot report more fillers leaving
# pipeline_full than entered it, which is impossible for a stage that only
# adds brackets.
# ---------------------------------------------------------------------------

class TestHyphenatedFillers:
    def test_a_hyphenated_backchannel_is_seen(self):
        assert sum(count_fillers("Mm-hmm.").values()) == 1
        assert sum(count_fillers("uh-huh").values()) == 1

    def test_the_ami_reference_spelling_is_seen(self):
        """The corpus writes them in capitals."""
        assert sum(count_fillers("MM-HMM").values()) == 1

    def test_a_compound_counts_once_not_once_per_element(self):
        assert count_fillers("mm-hmm") == count_fillers("mhm")

    def test_bracketing_a_compound_does_not_change_its_count(self):
        """The exact regression: [Mm]-[hmm] must equal Mm-hmm."""
        assert count_fillers("[Mm]-[hmm].") == count_fillers("Mm-hmm.")

    def test_bracketing_never_increases_the_count(self, ):
        """A stage that only marks fillers cannot create them."""
        from evaluation.conditions import get_condition
        bracket = get_condition("filler_bracket")
        for text in ("Mm-hmm.", "uh-huh", "so um yes", "er, well",
                     "Mm-hmm. Uh-huh. Um."):
            before = sum(count_fillers(text).values())
            after = sum(count_fillers(bracket.transform(text)).values())
            assert after == before, (
                f"{text!r}: {before} fillers became {after} after bracketing")

    def test_retention_of_a_bracketed_compound_is_complete(self):
        s = score_pair("MM-HMM", " Mm-hmm.", "[Mm]-[hmm].")
        assert s["raw_fillers"] == 1
        assert s["retained"] == 1
        assert s["reference_recovered"] == 1

    def test_hyphenated_real_words_are_not_fillers(self):
        for word in ("well-mannered", "co-author", "mother-in-law",
                     "t-shirt", "re-erm"):
            assert sum(count_fillers(word).values()) == 0, word

    def test_output_never_exceeds_input_for_a_marking_stage(self):
        """Stated as the invariant, since violating it is what happened."""
        s = score_pair("", "Mm-hmm. Um. Uh-huh.", "[Mm]-[hmm]. [Um]. [Uh]-[huh].")
        assert s["output_fillers"] == s["raw_fillers"]
