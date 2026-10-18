"""Tests for the anonymisation metrics.

The linkage rate is the measurement that decides whether the transform
protects anyone, so its own correctness matters more than most. It is
easy to write a version that flatters the method: comparing a released
clip against the very recording it came from, or reporting a rate without
the chance level that makes it interpretable.

Embeddings are supplied directly, so no model, audio or GPU is needed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation.benchmark_anonymisation import (  # noqa: E402
    cosine_similarity,
    degenerate_baselines,
    linkage_rate,
    pooled_wer,
    sample_by_meeting,
    summarise,
)


class TestCosineSimilarity:
    def test_identical_vectors_are_one(self):
        v = np.array([1.0, 2.0, 3.0])
        assert cosine_similarity(v, v) == pytest.approx(1.0)

    def test_opposite_vectors_are_minus_one(self):
        v = np.array([1.0, 0.0])
        assert cosine_similarity(v, -v) == pytest.approx(-1.0)

    def test_orthogonal_vectors_are_zero(self):
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_magnitude_does_not_matter(self):
        assert cosine_similarity([1.0, 1.0], [5.0, 5.0]) == pytest.approx(1.0)

    def test_a_zero_vector_does_not_divide_by_zero(self):
        assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


class TestLinkageRate:
    def _embeddings(self, vectors):
        return [np.array(v, dtype=float) for v in vectors]

    def test_an_anonymiser_that_does_nothing_scores_one(self):
        """Unchanged embeddings still point at their own speaker."""
        originals = self._embeddings([[1, 0], [0.99, 0.1], [0, 1], [0.1, 0.99]])
        speakers = ["A", "A", "B", "B"]
        result = linkage_rate(originals, originals, speakers)
        assert result["linkage_rate"] == pytest.approx(1.0)
        # One same-speaker recording among each probe's three candidates,
        # not one over the two speakers (EPRIV-04).
        assert result["chance"] == pytest.approx(1 / 3, abs=1e-4)

    def test_a_perfect_anonymiser_scores_at_or_below_chance(self):
        """Swapping the speakers' regions sends every match to the other."""
        originals = self._embeddings([[1, 0], [0.99, 0.1], [0, 1], [0.1, 0.99]])
        anonymised = self._embeddings([[0, 1], [0.1, 0.99], [1, 0], [0.99, 0.1]])
        result = linkage_rate(anonymised, originals, ["A", "A", "B", "B"])
        assert result["linkage_rate"] == pytest.approx(0.0)

    def test_an_utterance_is_never_matched_against_its_own_recording(self):
        """Otherwise every anonymiser would look useless.

        Each A utterance is nearest to its own original by construction,
        and A's two recordings are far apart; the honest question is
        whether it still matches the speaker's *other* recording, which
        here it does not. Allowing the self-match would score 1.0.
        """
        originals = self._embeddings([[1, 0], [0, 1], [0.9, 0.1]])
        result = linkage_rate(originals, originals, ["A", "A", "B"])
        assert result["trials"] == 2
        assert result["linkage_rate"] == pytest.approx(0.0)

    def test_a_speaker_with_no_other_recording_is_not_a_trial(self):
        """EPRIV-04: a forced miss is excluded and counted, not scored.

        Utterance 0 has no same-speaker partner, so no method could link
        it. Counting it as a trial made this 2/3 and made any transform
        look more protective than it is.
        """
        originals = self._embeddings([[1, 0], [0, 1], [0, 1]])
        result = linkage_rate(originals, originals, ["A", "B", "B"])
        assert result["trials"] == 2
        assert result["n_singleton_excluded"] == 1
        assert result["linkage_rate"] == pytest.approx(1.0)
        # Each B probe searches {A, the other B}: one right answer in two.
        assert result["chance"] == pytest.approx(0.5)

    def test_chance_is_the_random_candidate_rate_not_one_over_speakers(self):
        """EPRIV-04: sum_s n_s(n_s-1) / (n(n-1)), 1/7 here, not 1/4."""
        originals = self._embeddings([[1, 0], [0.9, 0.1], [0, 1], [0.1, 0.9],
                                      [1, 1], [0.9, 1], [-1, 0], [-0.9, 0.1]])
        result = linkage_rate(originals, originals,
                              ["A", "A", "B", "B", "C", "C", "D", "D"])
        assert result["chance"] == pytest.approx(1 / 7, abs=1e-4)
        assert result["distinct_speakers"] == 4

    def test_fewer_than_two_utterances_cannot_be_scored(self):
        result = linkage_rate([np.array([1.0])], [np.array([1.0])], ["A"])
        assert result["linkage_rate"] is None
        assert result["trials"] == 0

    def test_trials_count_every_utterance_with_a_same_speaker_candidate(self):
        originals = self._embeddings([[1, 0], [0, 1], [1, 1], [0.5, 1]])
        result = linkage_rate(originals, originals, ["A", "B", "A", "B"])
        assert result["trials"] == 4
        assert result["n_singleton_excluded"] == 0


class _Pair:
    """A stand-in for evaluation.wer.PairResult, counts only."""

    def __init__(self, substitutions=0, deletions=0, insertions=0,
                 reference_words=10, wer=0.0, hypothesis_words=None):
        self.substitutions = substitutions
        self.deletions = deletions
        self.insertions = insertions
        self.reference_words = reference_words
        self.wer = wer
        if hypothesis_words is not None:
            self.hypothesis_words = hypothesis_words


class TestPooledWer:
    def test_errors_are_pooled_over_reference_words(self):
        results = [_Pair(substitutions=1, reference_words=10),
                   _Pair(insertions=3, reference_words=10)]
        assert pooled_wer(results) == pytest.approx(0.2)

    def test_a_short_reference_no_longer_sets_the_scale(self):
        """The failure this replaced.

        One hallucinated utterance against a one-word reference scores
        30.0 on its own. A mean of rates would report over 1500% error
        for these two; pooling reports 30 of 101 words.
        """
        results = [_Pair(insertions=30, reference_words=1, wer=30.0),
                   _Pair(reference_words=100, wer=0.0)]
        mean_of_rates = (30.0 + 0.0) / 2
        assert mean_of_rates == pytest.approx(15.0)
        assert pooled_wer(results) == pytest.approx(30 / 101, abs=1e-4)

    def test_pooling_still_lets_one_looped_utterance_dominate(self):
        """The limit of the repair above, which the guard exists for.

        Substitutions and deletions are capped by the reference length,
        so pooling really does stop a short utterance dominating through
        those. Insertions have no ceiling. In the case above, the
        one-word utterance supplies every one of the 30 errors, so the
        corpus rate is its rate and nothing else's.
        """
        looped = _Pair(insertions=30, reference_words=1, wer=30.0)
        clean = _Pair(reference_words=100, wer=0.0)
        assert pooled_wer([looped, clean]) == pytest.approx(30 / 101, abs=1e-4)
        assert pooled_wer([clean]) == pytest.approx(0.0)
        assert degenerate_baselines([looped, clean]) == [0]

    def test_unscored_utterances_are_skipped(self):
        results = [None, _Pair(substitutions=2, reference_words=10)]
        assert pooled_wer(results) == pytest.approx(0.2)

    def test_no_results_reports_nothing(self):
        assert pooled_wer([]) is None
        assert pooled_wer([None]) is None

    def test_no_reference_words_does_not_divide_by_zero(self):
        assert pooled_wer([_Pair(insertions=5, reference_words=0)]) is None


class TestSummarise:
    def test_the_cost_is_the_difference_in_pooled_rate(self):
        before = [_Pair(substitutions=3, reference_words=10)]
        after = [_Pair(substitutions=5, reference_words=10)]
        s = summarise([0.4], before, after,
                      {"linkage_rate": 0.2, "trials": 1, "chance": 0.5})
        assert s["wer_original"] == pytest.approx(0.3)
        assert s["wer_anonymised"] == pytest.approx(0.5)
        assert s["wer_cost"] == pytest.approx(0.2)

    def test_the_averaging_convention_is_recorded(self):
        """So a reader knows which estimator produced the number."""
        s = summarise([0.1], [_Pair()], [_Pair()],
                      {"linkage_rate": None, "trials": 0, "chance": None})
        assert "micro" in s["wer_averaging"]

    def test_missing_scores_are_skipped_not_counted_as_zero(self):
        s = summarise([0.4], [_Pair(substitutions=2, reference_words=10), None],
                      [_Pair(substitutions=3, reference_words=10), None],
                      {"linkage_rate": None, "trials": 0, "chance": None})
        assert s["wer_original"] == pytest.approx(0.2)
        assert s["wer_anonymised"] == pytest.approx(0.3)

    def test_the_linkage_fields_are_carried_through(self):
        s = summarise([0.1], [_Pair()], [_Pair()],
                      {"linkage_rate": 0.4, "trials": 9, "chance": 0.25})
        assert s["linkage_rate"] == 0.4
        assert s["trials"] == 9
        assert s["chance"] == 0.25

    def test_an_empty_run_reports_nothing_rather_than_zero(self):
        s = summarise([], [], [], {"linkage_rate": None, "trials": 0,
                                   "chance": None})
        assert s["n_utterances"] == 0
        assert s["mean_self_similarity"] is None
        assert s["wer_cost"] is None


class TestResynthesisControl:
    """The cost of warping must be measured against warping's absence.

    Passing a signal through linear prediction and back is not
    transparent and tends to suppress noise. Scoring a warped condition
    against the raw input therefore charges the warping for a change the
    resynthesis made, and in a first run that made an anonymised
    condition appear to transcribe better than the original.
    """

    def test_the_cost_is_measured_against_the_control_when_given(self):
        raw = [_Pair(substitutions=6, reference_words=10)]      # 0.6
        control = [_Pair(substitutions=3, reference_words=10)]  # 0.3
        warped = [_Pair(substitutions=5, reference_words=10)]   # 0.5
        s = summarise([0.4], raw, warped,
                      {"linkage_rate": 0.8, "trials": 1, "chance": 0.25},
                      results_control=control)
        assert s["wer_resynthesis_control"] == pytest.approx(0.3)
        # 0.5 against the control's 0.3, not against the raw 0.6.
        assert s["wer_cost"] == pytest.approx(0.2)
        assert s["wer_cost_baseline"] == "resynthesis control"

    def test_without_a_control_the_baseline_is_named_as_the_raw_input(self):
        """So a reader can tell which comparison produced the number."""
        s = summarise([0.4], [_Pair(substitutions=4, reference_words=10)],
                      [_Pair(substitutions=6, reference_words=10)],
                      {"linkage_rate": None, "trials": 0, "chance": None})
        assert s["wer_cost_baseline"] == "raw original"
        assert s["wer_resynthesis_control"] is None
        assert s["wer_cost"] == pytest.approx(0.2)

    def test_resynthesis_alone_can_beat_the_raw_input(self):
        """Recorded rather than suppressed: it is a real effect.

        A control that scores better than the raw input says the
        analysis-synthesis pass helped, which is worth knowing and is not
        a fault in the measurement.
        """
        s = summarise([0.4], [_Pair(substitutions=6, reference_words=10)],
                      [_Pair(substitutions=4, reference_words=10)],
                      {"linkage_rate": None, "trials": 0, "chance": None},
                      results_control=[_Pair(substitutions=3, reference_words=10)])
        assert s["wer_resynthesis_control"] < s["wer_original"]
        assert s["wer_cost"] == pytest.approx(0.1)


class TestForceResynthesis:
    def test_alpha_one_is_a_no_op_by_default(self):
        from voice_anonymisation import anonymise
        signal = np.linspace(-0.4, 0.4, 8000).astype(np.float32)
        assert np.array_equal(anonymise(signal, 16000, alpha=1.0), signal)

    def test_alpha_one_can_be_forced_through_the_full_path(self):
        """Which is what makes a matched control possible."""
        from voice_anonymisation import anonymise
        rng = np.random.default_rng(0)
        signal = (0.3 * rng.standard_normal(8000)).astype(np.float32)
        forced = anonymise(signal, 16000, alpha=1.0, force_resynthesis=True)
        assert forced.shape == signal.shape
        assert not np.array_equal(forced, signal)
        assert np.all(np.isfinite(forced))


class TestImpossibleCostIsFlagged:
    """Warping cannot make audio easier to transcribe.

    A negative cost means the comparison is measuring something other
    than the warping, so it is flagged. It is no longer withheld: on the
    real corpus the cause turned out to be identifiable, and reporting
    the flag beside the guarded estimate tells the reader more than
    reporting nothing did.
    """

    def test_a_negative_cost_is_flagged(self):
        s = summarise([0.4], [_Pair(substitutions=5, reference_words=10)],
                      [_Pair(substitutions=2, reference_words=10)],
                      {"linkage_rate": 0.9, "trials": 1, "chance": 0.25})
        assert s["wer_cost_sign_anomaly"] is True

    def test_the_observed_rates_are_still_reported(self):
        """Flagging the derived figure must not hide the evidence."""
        s = summarise([0.4], [_Pair(substitutions=5, reference_words=10)],
                      [_Pair(substitutions=2, reference_words=10)],
                      {"linkage_rate": 0.9, "trials": 1, "chance": 0.25})
        assert s["wer_original"] == pytest.approx(0.5)
        assert s["wer_anonymised"] == pytest.approx(0.2)

    def test_a_plausible_cost_is_reported_normally(self):
        s = summarise([0.4], [_Pair(substitutions=2, reference_words=10)],
                      [_Pair(substitutions=5, reference_words=10)],
                      {"linkage_rate": 0.9, "trials": 1, "chance": 0.25})
        assert s["wer_cost"] == pytest.approx(0.3)
        assert s["wer_cost_sign_anomaly"] is None

    def test_an_equal_rate_is_not_treated_as_impossible(self):
        s = summarise([0.4], [_Pair(substitutions=3, reference_words=10)],
                      [_Pair(substitutions=3, reference_words=10)],
                      {"linkage_rate": 0.9, "trials": 1, "chance": 0.25})
        assert s["wer_cost"] == pytest.approx(0.0)
        assert s["wer_cost_sign_anomaly"] is None


class TestDegenerateBaselines:
    """The utterances the recogniser looped on, on the unmodified audio.

    Pooling stops a short reference dominating through substitutions and
    deletions, which are capped by the reference length. Insertions are
    not capped, so one looped utterance can still supply most of the
    error of a small corpus. On the AMI subset two one-word references
    drew 221-word hypotheses and between them carried 58% of the
    baseline's error.
    """

    def test_a_looped_hypothesis_is_found(self):
        results = [_Pair(insertions=220, reference_words=1,
                         hypothesis_words=221),
                   _Pair(substitutions=1, reference_words=10,
                         hypothesis_words=10)]
        assert degenerate_baselines(results) == [0]

    def test_a_long_hypothesis_matching_a_long_reference_is_not_degenerate(self):
        """Length alone is not the signal; the ratio to the reference is."""
        results = [_Pair(substitutions=5, reference_words=200,
                         hypothesis_words=200)]
        assert degenerate_baselines(results) == []

    def test_a_short_hypothesis_over_the_ratio_is_not_degenerate(self):
        """Two words against one is a bad transcript, not a loop."""
        results = [_Pair(insertions=1, reference_words=1, hypothesis_words=2)]
        assert degenerate_baselines(results) == []

    def test_unscored_utterances_are_skipped(self):
        assert degenerate_baselines([None]) == []

    def test_the_hypothesis_length_is_inferred_when_absent(self):
        """Older records kept the counts but not the length."""
        results = [_Pair(insertions=220, reference_words=1)]
        assert degenerate_baselines(results) == [0]

    def test_the_guarded_cost_drops_them_from_both_arms(self):
        """Paired: the same utterances leave the baseline and the warp."""
        before = [_Pair(insertions=220, reference_words=1, hypothesis_words=221),
                  _Pair(substitutions=2, reference_words=10, hypothesis_words=10)]
        after = [_Pair(reference_words=1, hypothesis_words=1),
                 _Pair(substitutions=4, reference_words=10, hypothesis_words=10)]
        s = summarise([0.4], before, after,
                      {"linkage_rate": 0.9, "trials": 2, "chance": 0.25})
        # Ungarded, the loop swamps everything and the warp looks better.
        assert s["wer_cost"] < 0
        assert s["wer_cost_sign_anomaly"] is True
        # Guarded, the surviving utterance shows the warp costing 0.2.
        assert s["n_degenerate_baselines"] == 1
        assert s["wer_original_guarded"] == pytest.approx(0.2)
        assert s["wer_anonymised_guarded"] == pytest.approx(0.4)
        assert s["wer_cost_guarded"] == pytest.approx(0.2)

    def test_the_share_of_error_the_drop_removes_is_reported(self):
        """The evidence for preferring the guarded estimate."""
        before = [_Pair(insertions=220, reference_words=1, hypothesis_words=221),
                  _Pair(substitutions=2, reference_words=10, hypothesis_words=10)]
        s = summarise([0.4], before, before,
                      {"linkage_rate": 0.9, "trials": 2, "chance": 0.25})
        assert s["degenerate_baseline_error_share"] == pytest.approx(220 / 222, abs=1e-3)

    def test_a_clean_baseline_leaves_both_estimates_equal(self):
        before = [_Pair(substitutions=2, reference_words=10, hypothesis_words=10)]
        after = [_Pair(substitutions=4, reference_words=10, hypothesis_words=10)]
        s = summarise([0.4], before, after,
                      {"linkage_rate": 0.9, "trials": 1, "chance": 0.25})
        assert s["n_degenerate_baselines"] == 0
        assert s["wer_cost_guarded"] == pytest.approx(s["wer_cost"])

    def test_only_the_baseline_is_screened(self):
        """A warp that provokes a loop has damaged the transcript.

        Excluding those would hide the very cost the benchmark measures,
        so the screen never looks at the transformed condition.
        """
        before = [_Pair(substitutions=2, reference_words=10, hypothesis_words=10)]
        after = [_Pair(insertions=220, reference_words=10, hypothesis_words=230)]
        s = summarise([0.4], before, after,
                      {"linkage_rate": 0.9, "trials": 1, "chance": 0.25})
        assert s["n_degenerate_baselines"] == 0
        assert s["wer_cost_guarded"] == pytest.approx(21.8)

    def test_the_screen_follows_the_control_when_one_is_given(self):
        """The baseline of the comparison is the control, so screen that."""
        raw = [_Pair(substitutions=2, reference_words=10, hypothesis_words=10),
               _Pair(substitutions=2, reference_words=10, hypothesis_words=10)]
        control = [_Pair(insertions=220, reference_words=1, hypothesis_words=221),
                   _Pair(substitutions=2, reference_words=10, hypothesis_words=10)]
        warped = [_Pair(reference_words=1, hypothesis_words=1),
                  _Pair(substitutions=4, reference_words=10, hypothesis_words=10)]
        s = summarise([0.4], raw, warped,
                      {"linkage_rate": 0.9, "trials": 2, "chance": 0.25},
                      results_control=control)
        assert s["n_degenerate_baselines"] == 1
        assert s["wer_cost_guarded"] == pytest.approx(0.2)


class TestSampleByMeeting:
    """The candidate set decides how strong the linkage test is.

    A sample read from the front of the split takes one meeting and four
    speakers. Spreading the same budget over the meetings buys speakers
    and sessions at no extra decoding cost. The cap counts accepted
    utterances, so a row a filter rejects does not use up a meeting's
    share (EPRIV-03).
    """

    def _grouped(self, meetings, per):
        return [(f"M{m}", [{"audio_id": f"M{m}_u{i}"} for i in range(per)])
                for m in range(meetings)]

    @staticmethod
    def _keep(mid, row):
        return (mid, row)

    def test_without_a_cap_it_reads_from_the_front(self):
        """The single-meeting configuration: the front of the split, first meeting only.

        It repeats the August runs' settings, not their sample, because
        group_rows_by_meeting now hands each meeting over in start-time
        order (see test_s1_anon_sampling).
        """
        picked, counts = sample_by_meeting(self._grouped(4, 50), 10, None,
                                           self._keep)
        assert len(picked) == 10
        assert {m for m, _ in picked} == {"M0"}
        assert counts == {"M0": 10}

    def test_a_cap_spreads_the_sample_over_meetings(self):
        picked, counts = sample_by_meeting(self._grouped(4, 50), 12, 3,
                                           self._keep)
        assert len(picked) == 12
        assert counts == {"M0": 3, "M1": 3, "M2": 3, "M3": 3}

    def test_no_meeting_exceeds_the_cap(self):
        picked, counts = sample_by_meeting(self._grouped(8, 50), 40, 5,
                                           self._keep)
        assert max(counts.values()) <= 5
        assert len(picked) == 40

    def test_the_limit_is_still_respected(self):
        picked, _ = sample_by_meeting(self._grouped(8, 50), 7, 5, self._keep)
        assert len(picked) == 7

    def test_a_short_meeting_does_not_stall_the_sample(self):
        """A meeting with fewer rows than the cap contributes what it has."""
        grouped = [("M0", [{"audio_id": "a"}]),
                   ("M1", [{"audio_id": f"b{i}"} for i in range(9)])]
        picked, counts = sample_by_meeting(grouped, 6, 5, self._keep)
        assert len(picked) == 6
        assert counts == {"M0": 1, "M1": 5}

    def test_running_out_of_meetings_returns_what_there_is(self):
        picked, _ = sample_by_meeting(self._grouped(2, 3), 100, 2, self._keep)
        assert len(picked) == 4

    def test_the_meeting_id_travels_with_each_row(self):
        picked, _ = sample_by_meeting(self._grouped(3, 4), 6, 2, self._keep)
        for mid, row in picked:
            assert row["audio_id"].startswith(mid)

    def test_rejected_rows_do_not_count_against_the_cap(self):
        """The first rows of M0 fail a filter; M0 still supplies its two."""
        def accept(mid, row):
            return None if row["audio_id"] in {"M0_u0", "M0_u1"} else row
        picked, counts = sample_by_meeting(self._grouped(2, 5), 100, 2, accept)
        assert counts == {"M0": 2, "M1": 2}
        assert [r["audio_id"] for r in picked][:2] == ["M0_u2", "M0_u3"]

    def test_a_meeting_with_nothing_usable_is_recorded_as_zero(self):
        def accept(mid, row):
            return None if mid == "M1" else row
        _, counts = sample_by_meeting(self._grouped(3, 4), 100, 2, accept)
        assert counts == {"M0": 2, "M1": 0, "M2": 2}

    def test_a_cap_below_one_is_refused(self):
        with pytest.raises(ValueError):
            sample_by_meeting(self._grouped(1, 1), 1, 0, self._keep)
