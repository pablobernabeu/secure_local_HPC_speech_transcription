"""Objective tests of the committed DER and timestamp benchmark results.

These tests make no network calls, require no GPU, and do not run any
model.  They operate entirely on the committed output files:

  output/evaluation/der_summary.json
  output/evaluation/der_report.csv
  output/evaluation/der_tuned/, der_oracle/ and der_concat/ (their summaries)
  output/evaluation/der_sweep*.csv and der_sweep*_selection.json (both sweeps)
  output/evaluation/timestamp_summary.json
  output/evaluation/timestamp_report.csv
  output/evaluation/timestamp_skipped.csv
  output/evaluation_vad_refine/ (the same three timestamp files)

Two kinds of assertion are made.

Arithmetic consistency
    The summary statistics reported in the JSON files must be derivable
    from the CSV rows to within floating-point tolerance.  This catches
    any mismatch between what the benchmark script computed and what it
    wrote to disk.

Plausibility bounds
    The numbers must fall within the ranges expected for
    ``pyannote/speaker-diarization-3.1`` on AMI IHM and
    ``openai/whisper-large-v3`` on AMI IHM timestamps.  The bounds are
    deliberately generous — they are not meant to assert that the results
    are optimal, only that they are not obviously wrong (e.g. due to a
    silent-fail that produces n_meetings = 0, or a unit mismatch that
    inflates errors by a factor of 1000).
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_DER_SUMMARY = _ROOT / "output" / "evaluation" / "der_summary.json"
_DER_REPORT = _ROOT / "output" / "evaluation" / "der_report.csv"
_TS_SUMMARY = _ROOT / "output" / "evaluation" / "timestamp_summary.json"
_TS_REPORT = _ROOT / "output" / "evaluation" / "timestamp_report.csv"
_TS_SKIPPED = _ROOT / "output" / "evaluation" / "timestamp_skipped.csv"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _load_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# ---------------------------------------------------------------------------
# DER results — file existence
# ---------------------------------------------------------------------------

class TestDerResultsExist:
    def test_der_summary_json_exists(self):
        assert _DER_SUMMARY.exists(), (
            f"{_DER_SUMMARY} not found; run evaluation/benchmark_der.py "
            "and commit the output."
        )

    def test_der_report_csv_exists(self):
        assert _DER_REPORT.exists(), (
            f"{_DER_REPORT} not found; run evaluation/benchmark_der.py "
            "and commit the output."
        )


# ---------------------------------------------------------------------------
# DER results — arithmetic consistency
# ---------------------------------------------------------------------------

class TestDerArithmeticConsistency:
    @pytest.fixture(autouse=True)
    def load(self):
        self.summary = _load_json(_DER_SUMMARY)
        self.rows = _load_csv(_DER_REPORT)

    def test_n_meetings_matches_csv_rows(self):
        assert self.summary["n_meetings"] == len(self.rows)

    def test_macro_der_is_mean_of_per_meeting_der(self):
        ders = [float(r["der"]) for r in self.rows]
        expected = sum(ders) / len(ders)
        assert self.summary["macro_der"] == pytest.approx(expected, rel=1e-4)

    def test_macro_missed_is_mean_of_per_meeting_missed(self):
        vals = [float(r["missed_speech"]) for r in self.rows]
        expected = sum(vals) / len(vals)
        assert self.summary["macro_missed"] == pytest.approx(expected, rel=1e-4)

    def test_macro_fa_is_mean_of_per_meeting_fa(self):
        vals = [float(r["false_alarm"]) for r in self.rows]
        expected = sum(vals) / len(vals)
        assert self.summary["macro_fa"] == pytest.approx(expected, rel=1e-4)

    def test_macro_confusion_is_mean_of_per_meeting_confusion(self):
        vals = [float(r["speaker_confusion"]) for r in self.rows]
        expected = sum(vals) / len(vals)
        assert self.summary["macro_confusion"] == pytest.approx(expected, rel=1e-4)

    def test_macro_der_components_sum_to_macro_der(self):
        # DER = missed + false_alarm + confusion (by definition)
        s = self.summary
        components = s["macro_missed"] + s["macro_fa"] + s["macro_confusion"]
        assert s["macro_der"] == pytest.approx(components, rel=1e-4)

    def test_total_ref_duration_is_positive_and_plausible(self):
        # total_ref_duration counts annotated speech, not total concatenated
        # meeting length (which includes silence gaps), so it is less than the
        # sum of duration_s in the CSV.  We verify it is positive and smaller
        # than that sum.
        total_meeting_dur = sum(float(r["duration_s"]) for r in self.rows)
        assert self.summary["total_ref_duration"] > 0.0
        assert self.summary["total_ref_duration"] <= total_meeting_dur

    def test_all_per_meeting_der_are_non_negative(self):
        for r in self.rows:
            assert float(r["der"]) >= 0.0, (
                f"Negative DER for meeting {r['meeting_id']}"
            )

    def test_metadata_fields_present(self):
        for key in ("dataset", "model", "collar_s"):
            assert key in self.summary, f"Missing key '{key}' in der_summary.json"


# ---------------------------------------------------------------------------
# DER results — plausibility bounds
# ---------------------------------------------------------------------------

class TestDerPlausibilityBounds:
    """Generous sanity-check bounds for pyannote/speaker-diarization-3.1
    on AMI IHM test.  Literature reports macro-DER in the range 15–45% for
    short-segment evaluations with a 0.25 s collar; values outside this range
    indicate a silent failure (e.g. n_meetings = 0) or a unit error.
    """

    @pytest.fixture(autouse=True)
    def load(self):
        self.summary = _load_json(_DER_SUMMARY)

    def test_n_meetings_at_least_one(self):
        assert self.summary["n_meetings"] >= 1, (
            "n_meetings = 0: all meetings were silently skipped, "
            "most likely due to a failed model download."
        )

    def test_macro_der_within_plausible_range(self):
        der = self.summary["macro_der"]
        assert 0.05 <= der <= 0.80, (
            f"macro_der={der:.3f} is outside the plausible range [0.05, 0.80]. "
            "Check for a unit error or silent model failure."
        )

    def test_micro_der_within_plausible_range(self):
        der = self.summary["micro_der"]
        assert 0.05 <= der <= 0.80, (
            f"micro_der={der:.3f} is outside the plausible range [0.05, 0.80]."
        )

    def test_missed_fa_confusion_each_non_negative(self):
        s = self.summary
        for key in ("macro_missed", "macro_fa", "macro_confusion"):
            assert s[key] >= 0.0, f"{key} is negative"

    def test_model_is_pyannote(self):
        assert "pyannote" in self.summary["model"]

    def test_dataset_is_ami(self):
        assert "ami" in self.summary["dataset"].lower()

    def test_collar_is_quarter_second(self):
        assert self.summary["collar_s"] == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# Timestamp results — file existence
# ---------------------------------------------------------------------------

class TestTimestampResultsExist:
    def test_timestamp_summary_json_exists(self):
        assert _TS_SUMMARY.exists(), (
            f"{_TS_SUMMARY} not found; run evaluation/benchmark_timestamps.py "
            "and commit the output."
        )

    def test_timestamp_report_csv_exists(self):
        assert _TS_REPORT.exists(), (
            f"{_TS_REPORT} not found; run evaluation/benchmark_timestamps.py "
            "and commit the output."
        )


# ---------------------------------------------------------------------------
# Timestamp results — arithmetic consistency
# ---------------------------------------------------------------------------

class TestTimestampArithmeticConsistency:
    @pytest.fixture(autouse=True)
    def load(self):
        self.summary = _load_json(_TS_SUMMARY)
        self.rows = _load_csv(_TS_REPORT)

    def test_n_matches_csv_rows(self):
        # Summary n counts scored rows. The report has held only scored rows
        # since a36b1d4, which lists the skipped ones in
        # timestamp_skipped.csv; the filter stays so that an older report
        # with empty or NaN rows is still counted correctly.
        scored = [
            r for r in self.rows
            if r.get("abs_start_error_s", "").strip() not in ("", "nan", "NaN")
        ]
        assert self.summary["n"] == len(scored)

    def test_mae_start_matches_csv(self):
        scored = [
            float(r["abs_start_error_s"]) for r in self.rows
            if r.get("abs_start_error_s", "").strip() not in ("", "nan", "NaN")
        ]
        expected = sum(scored) / len(scored)
        assert self.summary["mae_start"] == pytest.approx(expected, rel=1e-4)

    def test_mae_end_matches_csv(self):
        scored = [
            float(r["abs_end_error_s"]) for r in self.rows
            if r.get("abs_end_error_s", "").strip() not in ("", "nan", "NaN")
        ]
        expected = sum(scored) / len(scored)
        assert self.summary["mae_end"] == pytest.approx(expected, rel=1e-4)

    def test_rmse_start_matches_csv(self):
        start_errs = [
            float(r["start_error_s"]) for r in self.rows
            if r.get("start_error_s", "").strip() not in ("", "nan", "NaN")
        ]
        expected = math.sqrt(sum(e ** 2 for e in start_errs) / len(start_errs))
        assert self.summary["rmse_start"] == pytest.approx(expected, rel=1e-4)

    def test_rmse_end_matches_csv(self):
        end_errs = [
            float(r["end_error_s"]) for r in self.rows
            if r.get("end_error_s", "").strip() not in ("", "nan", "NaN")
        ]
        expected = math.sqrt(sum(e ** 2 for e in end_errs) / len(end_errs))
        assert self.summary["rmse_end"] == pytest.approx(expected, rel=1e-4)

    def test_mae_total_is_mean_of_abs_total(self):
        totals = [
            float(r["abs_start_error_s"]) + float(r["abs_end_error_s"])
            for r in self.rows
            if r.get("abs_start_error_s", "").strip() not in ("", "nan", "NaN")
        ]
        expected = sum(totals) / len(totals)
        assert self.summary["mae_total"] == pytest.approx(expected, rel=1e-4)

    def test_metadata_fields_present(self):
        for key in ("dataset", "model", "n", "mae_start", "mae_end"):
            assert key in self.summary, (
                f"Missing key '{key}' in timestamp_summary.json"
            )


# ---------------------------------------------------------------------------
# Timestamp results — plausibility bounds
# ---------------------------------------------------------------------------

class TestTimestampPlausibilityBounds:
    """Generous sanity-check bounds for openai/whisper-large-v3 on AMI IHM.
    Whisper's start MAE is typically < 100 ms and end MAE < 500 ms on
    well-segmented short clips.  Values outside these bounds indicate
    a unit error (e.g. samples instead of seconds) or a silent failure.
    """

    @pytest.fixture(autouse=True)
    def load(self):
        self.summary = _load_json(_TS_SUMMARY)

    def test_n_utterances_at_least_one(self):
        assert self.summary["n"] >= 1, (
            "n = 0: all utterances were silently skipped."
        )

    def test_mae_start_in_seconds_not_samples(self):
        # If start MAE > 1.0 s on short AMI clips, the values are likely in
        # samples or milliseconds rather than seconds.
        assert self.summary["mae_start"] < 1.0, (
            f"mae_start={self.summary['mae_start']:.4f} s exceeds 1.0 s; "
            "check for a unit error."
        )

    def test_mae_end_plausible(self):
        assert self.summary["mae_end"] < 2.0, (
            f"mae_end={self.summary['mae_end']:.4f} s exceeds 2.0 s."
        )

    def test_mae_values_non_negative(self):
        for key in ("mae_start", "mae_end", "mae_total", "rmse_start", "rmse_end"):
            assert self.summary[key] >= 0.0, f"{key} is negative"

    def test_model_is_whisper(self):
        assert "whisper" in self.summary["model"].lower()

    def test_dataset_is_ami(self):
        assert "ami" in self.summary["dataset"].lower()


# ---------------------------------------------------------------------------
# DER coverage — meeting-level structure
# ---------------------------------------------------------------------------

_EXPECTED_MEETINGS = {
    "EN2002a", "EN2002b", "EN2002c", "EN2002d",
    "ES2004a", "ES2004b", "ES2004c", "ES2004d",
    "IS1009a", "IS1009b", "IS1009c", "IS1009d",
    "TS3003a", "TS3003b", "TS3003c", "TS3003d",
}


class TestDerCoverage:
    """Checks that the per-meeting report covers exactly the 16 AMI IHM test
    meetings used in the benchmark, with no duplicates or missing entries."""

    @pytest.fixture(autouse=True)
    def load(self):
        self.rows = _load_csv(_DER_REPORT)
        self.meeting_ids = {r["meeting_id"] for r in self.rows}

    def test_all_16_expected_meetings_present(self):
        assert self.meeting_ids == _EXPECTED_MEETINGS, (
            f"Unexpected meeting IDs: {self.meeting_ids ^ _EXPECTED_MEETINGS}"
        )

    def test_no_duplicate_meeting_ids(self):
        ids = [r["meeting_id"] for r in self.rows]
        assert len(ids) == len(set(ids)), "Duplicate meeting_id found in DER report"

    def test_meetings_are_whole_recordings_not_excerpts(self):
        """Each meeting is now reconstructed in full, not sampled.

        The earlier benchmark took the first twenty-five utterances of
        each meeting, roughly a minute of audio. A silent return to that
        would shrink the corpus by a factor of thirty while leaving every
        other invariant here satisfied, so the extent is asserted
        directly.
        """
        for r in self.rows:
            assert int(r["n_utterances"]) > 100, (
                f"{r['meeting_id']}: only {r['n_utterances']} utterances; "
                "the report looks like an excerpt rather than a whole meeting"
            )
            assert float(r["duration_s"]) > 600, (
                f"{r['meeting_id']}: {r['duration_s']} s is too short for an "
                "AMI meeting"
            )

    def test_the_reference_contains_overlapping_speech(self):
        """The property that distinguishes a meeting from a concatenation."""
        overlaps = [float(r["overlap_fraction"]) for r in self.rows]
        assert min(overlaps) > 0.0, (
            "at least one meeting has no overlapping speech at all, which "
            "means the reconstruction is a concatenation rather than a mix"
        )
        assert max(overlaps) > 0.2

    def test_exactly_16_rows(self):
        assert len(self.rows) == 16

    def test_all_meeting_durations_positive(self):
        for r in self.rows:
            assert float(r["duration_s"]) > 0.0, (
                f"{r['meeting_id']}: duration_s = {r['duration_s']}"
            )


# ---------------------------------------------------------------------------
# DER per-row decomposition invariants
# ---------------------------------------------------------------------------

class TestDerPerRowDecomposition:
    """For each meeting, verify that the three DER components sum to the
    reported DER and that none of the components is negative.  These
    invariants hold by the definition of the DER decomposition and would
    fail only if the benchmark script serialised intermediate values
    incorrectly."""

    @pytest.fixture(autouse=True)
    def load(self):
        self.rows = _load_csv(_DER_REPORT)

    def test_components_sum_to_der_for_every_meeting(self):
        for r in self.rows:
            der = float(r["der"])
            total = (
                float(r["missed_speech"])
                + float(r["false_alarm"])
                + float(r["speaker_confusion"])
            )
            assert der == pytest.approx(total, abs=1e-4), (
                f"{r['meeting_id']}: der={der:.6f} but components sum to {total:.6f}"
            )

    def test_all_components_non_negative(self):
        for r in self.rows:
            for col in ("missed_speech", "false_alarm", "speaker_confusion"):
                assert float(r[col]) >= 0.0, (
                    f"{r['meeting_id']}: {col} = {r[col]} is negative"
                )

    def test_all_der_rates_non_negative(self):
        for r in self.rows:
            assert float(r["der"]) >= 0.0, (
                f"{r['meeting_id']}: der = {r['der']} is negative"
            )


# ---------------------------------------------------------------------------
# DER per-meeting pinned values (regression pins from ARC job 8976354 at
# code 9cb43e3, re-pinned from job 8534772's in aaffb81; the earlier 815b5a7
# values used the retired concatenation protocol). Only EN2002c moved
# between the two runs: since 2bb4224 (EDER-02) its reference keeps both
# speakers of the turn MEE071 and MEE073 share at 543.24-543.55 s.
# ---------------------------------------------------------------------------

_PINNED_DER: dict[str, dict] = {
    "EN2002a": {"der": 0.228197, "missed": 0.138256, "fa": 0.008521, "confusion": 0.081419,
                "duration_s": 2142.37, "hyp_speakers": 8},
    "EN2002b": {"der": 0.238898, "missed": 0.121387, "fa": 0.008839, "confusion": 0.108672,
                "duration_s": 1786.59, "hyp_speakers": 9},
    "EN2002c": {"der": 0.197617, "missed": 0.12365, "fa": 0.002023, "confusion": 0.071944,
                "duration_s": 2889.64, "hyp_speakers": 9},
    "EN2002d": {"der": 0.270383, "missed": 0.156768, "fa": 0.00796, "confusion": 0.105655,
                "duration_s": 2207.85, "hyp_speakers": 9},
    "ES2004a": {"der": 0.230978, "missed": 0.109838, "fa": 0.011357, "confusion": 0.109783,
                "duration_s": 1049.04, "hyp_speakers": 8},
    "ES2004b": {"der": 0.09146, "missed": 0.036556, "fa": 0.019098, "confusion": 0.035806,
                "duration_s": 2341.96, "hyp_speakers": 6},
    "ES2004c": {"der": 0.09069, "missed": 0.037402, "fa": 0.024872, "confusion": 0.028416,
                "duration_s": 2331.79, "hyp_speakers": 8},
    "ES2004d": {"der": 0.185013, "missed": 0.071655, "fa": 0.019876, "confusion": 0.093481,
                "duration_s": 2222.25, "hyp_speakers": 9},
    "IS1009a": {"der": 0.157102, "missed": 0.078232, "fa": 0.011408, "confusion": 0.067462,
                "duration_s": 805.72, "hyp_speakers": 5},
    "IS1009b": {"der": 0.104352, "missed": 0.046667, "fa": 0.009573, "confusion": 0.048112,
                "duration_s": 2026.9, "hyp_speakers": 6},
    "IS1009c": {"der": 0.075147, "missed": 0.028942, "fa": 0.00987, "confusion": 0.036336,
                "duration_s": 1789.19, "hyp_speakers": 8},
    "IS1009d": {"der": 0.153002, "missed": 0.057642, "fa": 0.011537, "confusion": 0.083822,
                "duration_s": 1925.75, "hyp_speakers": 7},
    "TS3003a": {"der": 0.181194, "missed": 0.108399, "fa": 0.008681, "confusion": 0.064114,
                "duration_s": 1476.39, "hyp_speakers": 5},
    "TS3003b": {"der": 0.072245, "missed": 0.032551, "fa": 0.022989, "confusion": 0.016705,
                "duration_s": 2149.36, "hyp_speakers": 7},
    "TS3003c": {"der": 0.136777, "missed": 0.061886, "fa": 0.015296, "confusion": 0.059595,
                "duration_s": 2280.36, "hyp_speakers": 8},
    "TS3003d": {"der": 0.23709, "missed": 0.101972, "fa": 0.017568, "confusion": 0.11755,
                "duration_s": 2591.56, "hyp_speakers": 6},
}


class TestDerPinnedPerMeetingValues:
    """Pin all 16 per-meeting DER values to the results from ARC job 8976354
    (pyannote/speaker-diarization-3.1 on AMI IHM test, rebuilt timeline
    protocol, code 9cb43e3, 2026-10-04), which repeated job 8534772
    (pinned in aaffb81 on 2026-08-10) after the EDER-02 fix. Any change in
    these values means the evaluation was re-run with a different
    configuration and the manuscript results must be updated."""

    @pytest.fixture(autouse=True)
    def load(self):
        self.rows = {r["meeting_id"]: r for r in _load_csv(_DER_REPORT)}

    def test_pinned_der_per_meeting(self):
        for mid, exp in _PINNED_DER.items():
            assert float(self.rows[mid]["der"]) == pytest.approx(exp["der"], rel=1e-4), (
                f"{mid}: DER changed from pinned value {exp['der']}"
            )

    def test_pinned_missed_speech_per_meeting(self):
        for mid, exp in _PINNED_DER.items():
            assert float(self.rows[mid]["missed_speech"]) == pytest.approx(
                exp["missed"], rel=1e-4), (
                f"{mid}: missed_speech changed from pinned value {exp['missed']}"
            )

    def test_pinned_false_alarm_per_meeting(self):
        for mid, exp in _PINNED_DER.items():
            assert float(self.rows[mid]["false_alarm"]) == pytest.approx(exp["fa"], rel=1e-4), (
                f"{mid}: false_alarm changed from pinned value {exp['fa']}"
            )

    def test_pinned_confusion_per_meeting(self):
        for mid, exp in _PINNED_DER.items():
            assert float(self.rows[mid]["speaker_confusion"]) == pytest.approx(
                exp["confusion"], rel=1e-4), (
                f"{mid}: speaker_confusion changed from pinned value {exp['confusion']}"
            )

    def test_pinned_duration_per_meeting(self):
        for mid, exp in _PINNED_DER.items():
            assert float(self.rows[mid]["duration_s"]) == pytest.approx(
                exp["duration_s"], rel=1e-3), (
                f"{mid}: duration_s changed from pinned value {exp['duration_s']}"
            )

    def test_pinned_hyp_speakers_per_meeting(self):
        for mid, exp in _PINNED_DER.items():
            assert int(self.rows[mid]["hyp_n_speakers"]) == exp["hyp_speakers"], (
                f"{mid}: hyp_n_speakers changed from pinned value "
                f"{exp['hyp_speakers']}"
            )


# ---------------------------------------------------------------------------
# DER series patterns (quality differences across AMI meeting series)
# ---------------------------------------------------------------------------

class TestDerSeriesPatterns:
    """Assert the patterns the reported results rest on.

    Every recording here is close-talking headset audio, so the spread
    across series is not a microphone effect. What separates them is how
    much of each meeting is spoken over: the EN2002 meetings carry a
    quarter to a third of their speech in overlap, the IS1009 meetings a
    twentieth to a ninth. These assertions therefore double as a check
    that reference and hypothesis have not been swapped, which would
    scramble the ranking entirely.
    """

    @pytest.fixture(autouse=True)
    def load(self):
        self.rows = {r["meeting_id"]: r for r in _load_csv(_DER_REPORT)}

    @staticmethod
    def _pearson(xs, ys):
        mx = sum(xs) / len(xs)
        my = sum(ys) / len(ys)
        num = sum((a - mx) * (b - my) for a, b in zip(xs, ys, strict=True))
        den = (sum((a - mx) ** 2 for a in xs)
               * sum((b - my) ** 2 for b in ys)) ** 0.5
        return num / den

    def _column(self, name):
        return [float(r[name]) for r in self.rows.values()]

    def _series_mean_der(self, prefix: str) -> float:
        vals = [float(r["der"]) for mid, r in self.rows.items() if mid.startswith(prefix)]
        return sum(vals) / len(vals)

    def test_en2002_has_highest_series_mean_der(self):
        en2002 = self._series_mean_der("EN2002")
        for prefix in ("ES2004", "IS1009", "TS3003"):
            assert en2002 > self._series_mean_der(prefix), (
                f"EN2002 mean DER ({en2002:.3f}) is not the highest series mean"
            )

    def test_is1009_has_lowest_series_mean_der(self):
        is1009 = self._series_mean_der("IS1009")
        for prefix in ("EN2002", "ES2004", "TS3003"):
            assert is1009 < self._series_mean_der(prefix), (
                f"IS1009 mean DER ({is1009:.3f}) is not the lowest series mean"
            )

    def test_worst_and_best_meetings_are_pinned(self):
        ders = {mid: float(r["der"]) for mid, r in self.rows.items()}
        assert max(ders, key=ders.get) == "EN2002d", (
            f"Expected EN2002d to have the highest DER; got "
            f"{max(ders, key=ders.get)}"
        )
        assert min(ders, key=ders.get) == "TS3003b", (
            f"Expected TS3003b to have the lowest DER; got "
            f"{min(ders, key=ders.get)}"
        )

    def test_der_rises_with_the_amount_of_overlapping_speech(self):
        """The manuscript's central explanation of the between-meeting spread.

        The earlier benchmark asserted the same explanation about audio
        that, being a concatenation, contained no overlap at all. Here it
        is a measurement.
        """
        r = self._pearson(self._column("overlap_fraction"), self._column("der"))
        assert r > 0.6, f"overlap and DER correlate at only r={r:.3f}"

    def test_overlap_acts_through_missed_speech(self):
        """pyannote 3.1 resolves at most two simultaneous speakers per
        window, so a third concurrent voice has no class to be assigned to
        and is lost rather than misattributed."""
        overlap = self._column("overlap_fraction")
        r_missed = self._pearson(overlap, self._column("missed_speech"))
        r_confusion = self._pearson(overlap, self._column("speaker_confusion"))
        assert r_missed > r_confusion, (
            f"missed speech tracks overlap at r={r_missed:.3f}, no more "
            f"strongly than confusion at r={r_confusion:.3f}"
        )

    def test_false_alarm_falls_as_overlap_rises(self):
        """Mechanically: a meeting dense with overlap leaves less silence
        in which a false alarm can occur."""
        r = self._pearson(self._column("overlap_fraction"),
                          self._column("false_alarm"))
        assert r < 0.0, f"false alarm does not fall with overlap (r={r:.3f})"

    def test_the_speaker_count_is_overestimated_in_every_meeting(self):
        """Motivates, and is not contradicted by, the finding that supplying
        the true count nevertheless makes diarisation worse."""
        for mid, r in self.rows.items():
            assert int(r["hyp_n_speakers"]) > int(r["n_speakers"]), (
                f"{mid}: found {r['hyp_n_speakers']} speakers for "
                f"{r['n_speakers']} present, which is not an overestimate"
            )

    def test_micro_and_macro_der_agree_closely(self):
        """With whole meetings of comparable length, duration weighting no
        longer moves the corpus figure appreciably. Under the earlier
        excerpt-based protocol the two differed by more than five points."""
        summary = _load_json(_DER_SUMMARY)
        assert abs(summary["micro_der"] - summary["macro_der"]) < 0.02, (
            f"micro_der ({summary['micro_der']:.4f}) and macro_der "
            f"({summary['macro_der']:.4f}) differ by more than two points"
        )

    def test_micro_der_within_per_meeting_range(self):
        """Micro-DER is a weighted average and must lie within the range
        spanned by the per-meeting DER values."""
        rows = list(self.rows.values())
        min_der = min(float(r["der"]) for r in rows)
        max_der = max(float(r["der"]) for r in rows)
        summary = _load_json(_DER_SUMMARY)
        assert min_der <= summary["micro_der"] <= max_der, (
            f"micro_der={summary['micro_der']:.4f} outside "
            f"[{min_der:.4f}, {max_der:.4f}]"
        )


# ---------------------------------------------------------------------------
# DER summary — tight regression pins
# ---------------------------------------------------------------------------

class TestDerPinnedSummaryValues:
    """Tight regression pins for der_summary.json.

    Produced by ARC job 8976354 at code 9cb43e3 on an NVIDIA L40S:
    pyannote/speaker-diarization-3.1 under pyannote.audio 3.4.0, over the
    AMI IHM test split reconstructed on the original meeting timeline, at
    the pipeline's shipped hyperparameters. It repeated job 8534772, whose
    values these replace: the EDER-02 fix (2bb4224) added 0.06 s of scored
    reference to EN2002c and moved no other meeting. Any change means the
    evaluation was re-run under a different configuration and the
    manuscript must be updated with it.
    """

    @pytest.fixture(autouse=True)
    def load(self):
        self.s = _load_json(_DER_SUMMARY)

    def test_n_meetings_is_16(self):
        assert self.s["n_meetings"] == 16

    def test_macro_der_pinned(self):
        assert self.s["macro_der"] == pytest.approx(0.16563410479707852, rel=1e-5)

    def test_micro_der_pinned(self):
        assert self.s["micro_der"] == pytest.approx(0.16618974750836943, rel=1e-5)

    def test_macro_missed_pinned(self):
        assert self.s["macro_missed"] == pytest.approx(0.0819876772777784, rel=1e-5)

    def test_macro_fa_pinned(self):
        assert self.s["macro_fa"] == pytest.approx(0.013091937076428327, rel=1e-5)

    def test_macro_confusion_pinned(self):
        assert self.s["macro_confusion"] == pytest.approx(0.07055449044287179, rel=1e-5)

    def test_total_ref_duration_pinned(self):
        assert self.s["total_ref_duration"] == pytest.approx(25533.446525182575, rel=1e-5)

    def test_the_reconstruction_mode_is_recorded(self):
        """A figure from the concatenation mode must never be mistaken for
        this one; the summary names which protocol produced it."""
        assert self.s["mix_mode"] == "timeline"
        assert self.s["split"] == "test"
        assert self.s["oracle_num_speakers"] is False

    def test_the_corpus_is_described_alongside_the_scores(self):
        corpus = self.s["corpus"]
        assert corpus["audio_hours"] == pytest.approx(8.894, abs=1e-3)
        assert corpus["overlap_fraction"] == pytest.approx(0.1534, abs=1e-4)


# ---------------------------------------------------------------------------
# DER re-run (wave 2a): provenance, and the development sweeps
# ---------------------------------------------------------------------------

_EVAL = _ROOT / "output" / "evaluation"
# Every committed DER artefact comes from ARC jobs 8976354 to 8976358 and
# 8976362, run from one clean clone at this commit (hpc/runs/der_*.env).
_DER_RERUN_COMMIT = "9cb43e3a4fa10ca4a7afe7e7c83a2c8de3cce915"
_DER_SUMMARIES = {
    "default": _DER_SUMMARY,
    "tuned": _EVAL / "der_tuned" / "der_summary.json",
    "oracle": _EVAL / "der_oracle" / "der_summary.json",
    "concat": _EVAL / "der_concat" / "der_summary.json",
}
_DER_SWEEPS = ("der_sweep", "der_sweep2")
_DER_AXES = ("clustering_threshold", "min_cluster_size", "min_duration_off")


def _der_cell(row: dict, prefix: str = "") -> tuple:
    """A sweep row's configuration, None for an axis left at its default."""
    return tuple(float(row[prefix + axis]) if row[prefix + axis] != "" else None
                 for axis in _DER_AXES)


class TestDerProvenance:
    """What every DER artefact records about the run that wrote it."""

    @pytest.mark.parametrize("name", sorted(_DER_SUMMARIES))
    def test_each_summary_names_a_clean_checkout_of_the_rerun_commit(self, name):
        from evaluation.der_metrics import COLLAR_CONVENTION, DEFAULT_COLLAR_S

        s = _load_json(_DER_SUMMARIES[name])
        assert s["run_metadata"]["git_commit"] == _DER_RERUN_COMMIT
        assert s["run_metadata"]["git_dirty"] is False
        assert s["pyannote_audio_version"] == "3.4.0"
        # EDER-01: the collar is pyannote.metrics' total width.
        assert s["collar_s"] == DEFAULT_COLLAR_S
        assert s["collar_convention"] == COLLAR_CONVENTION
        # EDER-06: every path scores the 16-bit signal the cache stores.
        assert s["audio_signal"].startswith("PCM_16 WAV read back as float32")

    @pytest.mark.parametrize("prefix", _DER_SWEEPS)
    def test_each_sweep_names_the_same_commit(self, prefix):
        from evaluation.der_metrics import COLLAR_CONVENTION, DEFAULT_COLLAR_S

        sel = _load_json(_EVAL / f"{prefix}_selection.json")
        assert sel["git_commit"] == _DER_RERUN_COMMIT
        assert sel["split"] == "validation"
        assert sel["collar_s"] == DEFAULT_COLLAR_S
        assert sel["collar_convention"] == COLLAR_CONVENTION

    def test_the_timeline_runs_share_one_reference_and_one_segmentation(self):
        """The default, tuned and oracle runs differ only in clustering, so
        they score the same reference (EN2002c's shared turn included, EDER-02)
        and, at an unchanged minimum pause, miss and invent the same speech.
        A summary left over from an earlier run would break this."""
        runs = [_load_json(_DER_SUMMARIES[n]) for n in ("default", "tuned", "oracle")]
        assert len({s["total_ref_duration"] for s in runs}) == 1
        for key in ("macro_missed", "macro_fa"):
            assert len({round(s[key], 5) for s in runs}) == 1, key


class TestDerDevelopmentSweeps:
    """The two development sweeps, ARC jobs 8976358 and 8976362."""

    @pytest.mark.parametrize("prefix", _DER_SWEEPS)
    def test_each_sweep_scores_the_pipeline_defaults_first(self, prefix):
        """Both now carry the defaults as cfg000; the August first sweep,
        job 8534758, predated that cell (ab929dd)."""
        rows = _load_csv(_EVAL / f"{prefix}_summary.csv")
        sel = _load_json(_EVAL / f"{prefix}_selection.json")
        assert rows[0]["config_id"] == "cfg000"
        assert _der_cell(rows[0]) == (None, None, None)
        defaults = sel["pipeline_defaults"]
        assert _der_cell(rows[0], "resolved_") == (
            defaults["clustering"]["threshold"],
            defaults["clustering"]["min_cluster_size"],
            defaults["segmentation"]["min_duration_off"])
        assert sel["baseline_in_grid"]["config_id"] == "cfg000"

    @pytest.mark.parametrize("prefix", _DER_SWEEPS)
    def test_the_selection_is_the_lowest_cell_of_the_summary(self, prefix):
        rows = _load_csv(_EVAL / f"{prefix}_summary.csv")
        sel = _load_json(_EVAL / f"{prefix}_selection.json")
        assert sel["n_configurations"] == len(rows)
        assert len({_der_cell(r, "resolved_") for r in rows}) == len(rows)
        best = min(rows, key=lambda r: float(r["macro_der"]))
        assert sel["best"]["config_id"] == best["config_id"]
        per_meeting = _load_csv(_EVAL / f"{prefix}.csv")
        for r in rows:
            ders = [float(m["der"]) for m in per_meeting
                    if m["config_id"] == r["config_id"]]
            assert len(ders) == int(r["n_meetings"]) == 18
            assert float(r["macro_der"]) == pytest.approx(sum(ders) / 18, abs=1e-6)

    def test_both_sweeps_select_the_configuration_the_tuned_run_scored(self):
        tuned = _load_json(_DER_SUMMARIES["tuned"])["hyperparameters"]
        scored = (tuned["clustering"]["threshold"],
                  tuned["clustering"]["min_cluster_size"],
                  tuned["segmentation"]["min_duration_off"])
        assert scored == (0.7, 12, 0.0)
        for prefix in _DER_SWEEPS:
            best = _load_json(_EVAL / f"{prefix}_selection.json")["best"]
            assert _der_cell(best, "resolved_") == scored, prefix

    def test_the_selected_cell_gains_under_a_tenth_of_a_point(self):
        """Pinned: macro DER 0.179346 at the selection against 0.179997 at
        the defaults, in both sweeps."""
        for prefix in _DER_SWEEPS:
            sel = _load_json(_EVAL / f"{prefix}_selection.json")
            assert sel["best"]["macro_der"] == pytest.approx(0.179346, abs=1e-6)
            assert sel["baseline_in_grid"]["macro_der"] == pytest.approx(0.179997, abs=1e-6)
            gain = sel["baseline_in_grid"]["macro_der"] - sel["best"]["macro_der"]
            assert 0 <= gain < 0.001, prefix

    def test_the_two_sweeps_agree_on_the_cells_they_share(self):
        """Both jobs scored the defaults and threshold 0.70 with no pause, on
        different nodes, and agree on every meeting of both cells."""
        def cells(prefix):
            out = {}
            for r in _load_csv(_EVAL / f"{prefix}.csv"):
                row = {k: v for k, v in r.items() if k != "config_id"}
                out.setdefault(_der_cell(r), []).append(row)
            return out

        first, second = cells("der_sweep"), cells("der_sweep2")
        shared = set(first) & set(second)
        assert shared == {(None, None, None), (0.7, 12.0, 0.0)}
        for cell in shared:
            assert first[cell] == second[cell], cell


# ---------------------------------------------------------------------------
# Timestamp coverage — audio-ID structure
# ---------------------------------------------------------------------------

class TestTimestampCoverage:
    """Structural checks on the 499 audio IDs recorded in timestamp_report.csv.

    The timestamp benchmark streamed the first 500 utterances of the AMI
    IHM test split, all of which fall in the EN2002a meeting (the meeting
    has 1,367 utterances in all; one of the 500 was skipped, leaving 499).
    The summary's sampling block has recorded this since ESTATS-12, as
    written by ARC job 8917980 (2026-09-27, code 6f9bf56), which reproduced
    the IDs, their order and every boundary of the first run, job 7737896
    (committed in 95413ea, 2026-05-29).
    The four speaker channels (H00–H03) correspond to the four close-talking
    microphones used in the EN2002a recording.
    """

    @pytest.fixture(autouse=True)
    def load(self):
        self.rows = _load_csv(_TS_REPORT)
        self.summary = _load_json(_TS_SUMMARY)

    def test_sampling_block_records_the_first_rows_of_one_meeting(self):
        sampling = self.summary["sampling"]
        assert sampling["limit"] == 500
        assert sampling["per_meeting"] is None
        assert sampling["utterances_per_meeting"] == {"EN2002a": 500}
        assert sampling["n_meetings"] == 1

    def test_every_streamed_row_is_scored_or_skipped(self):
        assert (self.summary["sampling"]["n_streamed"]
                == self.summary["n"] + self.summary["n_skipped"])

    def test_all_audio_ids_start_with_ami(self):
        for r in self.rows:
            assert r["audio_id"].startswith("AMI_"), (
                f"Unexpected audio_id prefix: {r['audio_id'][:20]}"
            )

    def test_all_utterances_from_en2002a(self):
        """All 499 rows come from the EN2002a meeting."""
        for r in self.rows:
            parts = r["audio_id"].split("_")
            assert parts[1] == "EN2002a", (
                f"Expected meeting EN2002a, got {parts[1]} in {r['audio_id']}"
            )

    def test_four_speaker_channels_represented(self):
        """EN2002a has four IHM microphone channels: H00, H01, H02, H03."""
        channels = {r["audio_id"].split("_")[2] for r in self.rows}
        assert channels == {"H00", "H01", "H02", "H03"}, (
            f"Unexpected channel set: {sorted(channels)}"
        )

    def test_n_matches_csv_row_count(self):
        """All 499 CSV rows were successfully scored; the single skipped
        utterance is listed in timestamp_skipped.csv instead."""
        assert self.summary["n"] == len(self.rows)


# ---------------------------------------------------------------------------
# Timestamp per-row structural invariants
# ---------------------------------------------------------------------------

class TestTimestampPerRowInvariants:
    """Column-level consistency checks that must hold for every scored row.

    These tests require no external data — they verify that the benchmark
    script serialised internally consistent values.  The four identities
    checked are:

    (1) start_error_s == pred_start_s  (since ref_start is always 0.0)
    (2) end_error_s == ref_duration_s - pred_end_s
    (3) abs_start_error_s == start_error_s  (start errors are non-negative)
    (4) abs_end_error_s == |end_error_s|
    """

    @pytest.fixture(autouse=True)
    def load(self):
        self.rows = [
            r for r in _load_csv(_TS_REPORT)
            if r.get("abs_start_error_s", "").strip() not in ("", "nan", "NaN")
        ]

    def test_start_error_equals_pred_start_for_all_rows(self):
        """start_error_s = hyp_start − 0.0 = pred_start_s."""
        for r in self.rows:
            assert float(r["start_error_s"]) == pytest.approx(
                float(r["pred_start_s"]), abs=1e-9
            ), f"start_error != pred_start in {r['audio_id']}"

    def test_end_error_equals_ref_minus_pred_end_for_all_rows(self):
        """end_error_s = ref_duration_s − pred_end_s."""
        for r in self.rows:
            expected = float(r["ref_duration_s"]) - float(r["pred_end_s"])
            assert float(r["end_error_s"]) == pytest.approx(expected, abs=1e-6), (
                f"end_error != ref − pred_end in {r['audio_id']}"
            )

    def test_abs_start_equals_start_error_for_all_rows(self):
        """abs_start_error_s == start_error_s because start errors cannot
        be negative (Whisper cannot predict a start before the clip begins)."""
        for r in self.rows:
            assert float(r["abs_start_error_s"]) == pytest.approx(
                float(r["start_error_s"]), abs=1e-9
            ), f"abs_start_error != start_error in {r['audio_id']}"

    def test_abs_end_equals_absolute_end_error_for_all_rows(self):
        for r in self.rows:
            assert float(r["abs_end_error_s"]) == pytest.approx(
                abs(float(r["end_error_s"])), abs=1e-9
            ), f"abs_end_error != |end_error| in {r['audio_id']}"

    def test_all_ref_durations_positive(self):
        for r in self.rows:
            assert float(r["ref_duration_s"]) > 0.0, (
                f"Non-positive ref_duration_s in {r['audio_id']}"
            )

    def test_all_pred_start_non_negative(self):
        for r in self.rows:
            assert float(r["pred_start_s"]) >= 0.0, (
                f"Negative pred_start_s in {r['audio_id']}"
            )


# ---------------------------------------------------------------------------
# Timestamp start-boundary bias
# ---------------------------------------------------------------------------

class TestTimestampStartBoundaryBias:
    """Checks relating to Whisper's near-zero start-boundary bias.

    The AMI IHM utterances are already trimmed to their speech content, so
    the ideal Whisper prediction is pred_start = 0.0 s.  Across 499 scored
    utterances, Whisper achieves exactly 0.0 s for 483 of them (96.8%),
    producing an MAE of only 8.7 ms.  A direct consequence of all start
    errors being non-negative is that the signed mean equals the MAE.
    """

    @pytest.fixture(autouse=True)
    def load(self):
        self.scored = [
            r for r in _load_csv(_TS_REPORT)
            if r.get("abs_start_error_s", "").strip() not in ("", "nan", "NaN")
        ]
        self.summary = _load_json(_TS_SUMMARY)

    def test_mean_start_error_equals_mae_start(self):
        """Because all start errors are >= 0, the signed mean equals the MAE.
        Failure would indicate at least one utterance with a negative
        pred_start_s, which should be physically impossible."""
        assert self.summary["mean_start_error"] == pytest.approx(
            self.summary["mae_start"], rel=1e-9
        )

    def test_majority_of_utterances_have_zero_pred_start(self):
        """At least 70% of utterances should have pred_start_s == 0.0.
        The actual fraction is 96.8% (483/499)."""
        zero_starts = sum(
            1 for r in self.scored if abs(float(r["pred_start_s"])) < 1e-6
        )
        fraction = zero_starts / len(self.scored)
        assert fraction > 0.70, (
            f"Only {fraction:.1%} of utterances have pred_start = 0; "
            "expected > 70%."
        )

    def test_mae_start_substantially_smaller_than_mae_end(self):
        """Start boundaries are near-perfect (8.7 ms MAE); end boundaries
        carry a heavy tail of early stops (127 ms MAE against a 10 ms
        median, ec91a66), not a systematic offset.  Start MAE should be at
        least five times smaller."""
        assert self.summary["mae_start"] * 5 < self.summary["mae_end"], (
            f"mae_start ({self.summary['mae_start']:.5f}) is not "
            f"substantially smaller than mae_end ({self.summary['mae_end']:.5f})"
        )

    def test_rmse_start_greater_than_mae_start(self):
        """Sparse non-zero start errors inflate RMSE above MAE."""
        assert self.summary["rmse_start"] > self.summary["mae_start"]

    def test_the_start_an_h100_pcie_moved_pinned(self):
        """The one boundary known to depend on the card. The reference is
        "But I don't know"; Whisper left out "But" and put the start at
        0.20 s on the P100 of job 7737896 and the H100 80GB HBM3 of job
        8917980, just before the 0.24 s at which the AMI word annotation
        puts "I". Job 7746137 ran the same decode on an H100 PCIe
        (htc-g055, 2026-05-31) and put it one timestamp step later, at
        0.22 s, which raises mae_start from 8.74 to 8.78 ms (8.8 where the
        manuscript rounds); every other row matched in every column that
        run wrote. A regenerated report that fails here came from a card
        that decodes this clip differently, so check the card before the
        code (hpc/runs/timestamps.env)."""
        (row,) = [r for r in self.scored
                  if r["audio_id"] == "AMI_EN2002a_H03_MEE071_0068404_0068460"]
        assert float(row["pred_start_s"]) == pytest.approx(0.20, abs=1e-9)
        assert row["hypothesis"] == "I don't know."


# ---------------------------------------------------------------------------
# Timestamp end-boundary distribution
# ---------------------------------------------------------------------------

class TestTimestampEndBoundaryDistribution:
    """Checks relating to the heavy-tailed end-boundary error distribution.

    End errors are dominated by a small number of large outliers, utterances
    where Whisper stopped very early (positive end_error) due to near-silence
    or hallucination.  The ratio RMSE / MAE for end errors is about 3.6
    (461 ms / 127 ms), confirming the presence of these heavy tails.  The
    median absolute end error is only 10 ms, half of Whisper's 20 ms
    timestamp step: every predicted boundary in the report lies on that
    grid, while 244 of the 499 reference durations end on an odd hundredth
    of a second, where the closest prediction possible is 10 ms out. The
    majority of utterances are therefore segmented as closely as the
    timestamps allow.
    """

    @pytest.fixture(autouse=True)
    def load(self):
        self.scored = [
            r for r in _load_csv(_TS_REPORT)
            if r.get("abs_end_error_s", "").strip() not in ("", "nan", "NaN")
        ]
        self.summary = _load_json(_TS_SUMMARY)

    def test_rmse_end_substantially_greater_than_mae_end(self):
        """RMSE / MAE > 2 for end errors, evidencing a heavy right tail."""
        assert self.summary["rmse_end"] > self.summary["mae_end"] * 2, (
            f"rmse_end ({self.summary['rmse_end']:.4f}) is not > 2 × "
            f"mae_end ({self.summary['mae_end']:.4f})"
        )

    def test_rmse_end_greater_than_rmse_start(self):
        """End errors are noisier than start errors."""
        assert self.summary["rmse_end"] > self.summary["rmse_start"]

    def test_median_abs_end_error_is_small(self):
        """The median absolute end error is 10 ms, half a timestamp step,
        confirming that the heavy tail comes from a minority of outliers."""
        abs_ends = sorted(float(r["abs_end_error_s"]) for r in self.scored)
        n = len(abs_ends)
        median = (
            abs_ends[n // 2]
            if n % 2
            else (abs_ends[n // 2 - 1] + abs_ends[n // 2]) / 2
        )
        assert median < 0.05, (
            f"Median absolute end error = {median:.4f} s; expected < 0.05 s"
        )

    def test_first_row_large_end_error_pinned(self):
        """AMI_EN2002a_H00_MEE073_0019663_0019800 is a documented outlier
        where Whisper predicted an end of 0.16 s against a 1.37 s clip,
        likely because the utterance contains near-silence after its first
        word.  This pin confirms the row has not been silently overwritten."""
        target = "AMI_EN2002a_H00_MEE073_0019663_0019800"
        rows_by_id = {r["audio_id"]: r for r in self.scored}
        assert target in rows_by_id, f"{target} not found in timestamp_report.csv"
        r = rows_by_id[target]
        assert float(r["abs_end_error_s"]) == pytest.approx(1.21, abs=0.005)
        assert float(r["ref_duration_s"]) == pytest.approx(1.37, abs=0.005)
        assert float(r["pred_end_s"]) == pytest.approx(0.16, abs=0.005)


# ---------------------------------------------------------------------------
# Timestamp summary — tight regression pins
# ---------------------------------------------------------------------------

class TestTimestampPinnedSummaryValues:
    """Tight tolerance regression pins for timestamp_summary.json.

    Produced by ARC job 8917980 (node htc-g059, NVIDIA H100 80GB HBM3, code
    6f9bf56, clean tree, openai/whisper-large-v3, 2026-09-27;
    hpc/runs/timestamps.env). It reproduced the first run, job 7737896
    (node htc-g032, Tesla P100-PCIE-16GB, 2026-05-28, committed in
    95413ea), in every report row and, to the last digit, in every
    statistic that run's summary held, so these pins did not move. The
    median and the 90th percentile are now computed from the unrounded
    errors, where ec91a66 took them from the four-decimal report, hence
    0.01 there and 0.009999999999999787 here for the same observation.
    A run on another card need not match the start pins: see
    TestTimestampStartBoundaryBias.test_the_start_an_h100_pcie_moved_pinned.
    """

    @pytest.fixture(autouse=True)
    def load(self):
        self.s = _load_json(_TS_SUMMARY)

    def test_n_is_499(self):
        assert self.s["n"] == 499

    def test_n_skipped_is_1(self):
        assert self.s.get("n_skipped") == 1

    def test_the_skip_was_an_untimed_tail(self):
        """ESTATS-02: the one skip is a final chunk without an end time."""
        assert self.s["skip_reasons"] == {
            "decode_error": 0, "resample_error": 0, "asr_error": 0,
            "no_chunks": 0, "untimed_tail": 1, "no_start_timestamp": 0,
        }
        assert self.s["n_missing_end_timestamp"] == 1

    def test_median_abs_end_error_pinned(self):
        assert self.s["median_abs_end_error"] == pytest.approx(0.01, abs=1e-9)

    def test_p90_abs_end_error_pinned(self):
        assert self.s["p90_abs_end_error"] == pytest.approx(0.15, abs=1e-9)

    def test_gross_and_truncation_rates_pinned(self):
        """41 of 499 ends are out by more than 0.5 s, all of them early."""
        assert self.s["gross_end_error_rate"] * self.s["n"] == pytest.approx(41)
        assert self.s["truncation_rate"] * self.s["n"] == pytest.approx(41)

    def test_decode_and_revisions_recorded(self):
        """ESTATS-12: the summary names the decode it came from."""
        assert self.s["whisper"]["dtype"] == "float16"
        assert self.s["whisper"]["gpu"] == "NVIDIA H100 80GB HBM3"
        assert self.s["whisper"]["chunk_length_s"] == 30
        assert self.s["whisper"]["stride_length_s"] == 5
        assert self.s["revisions"] == {
            "openai/whisper-large-v3": "06f233fe06e710322aca913c1bc4249a0d71fce1",
            "edinburghcstr/ami": "46f28f2503e2ec48f8867a84eef356c70476beab",
        }
        assert self.s["run"]["git_commit"].startswith("6f9bf56")
        assert self.s["run"]["git_dirty"] is False
        assert self.s["vad_refine"] is False
        assert self.s["vad_applied"] is False

    def test_mae_start_pinned(self):
        assert self.s["mae_start"] == pytest.approx(0.0087374749498998, rel=1e-5)

    def test_mae_end_pinned(self):
        assert self.s["mae_end"] == pytest.approx(0.12713464428857715, rel=1e-5)

    def test_mae_total_pinned(self):
        assert self.s["mae_total"] == pytest.approx(0.13587211923847695, rel=1e-5)

    def test_rmse_start_pinned(self):
        assert self.s["rmse_start"] == pytest.approx(0.07091726529579427, rel=1e-5)

    def test_rmse_end_pinned(self):
        assert self.s["rmse_end"] == pytest.approx(0.46053781630440555, rel=1e-5)

    def test_mean_start_error_pinned(self):
        assert self.s["mean_start_error"] == pytest.approx(0.0087374749498998, rel=1e-5)

    def test_mean_end_error_pinned(self):
        assert self.s["mean_end_error"] == pytest.approx(0.12024010521042085, rel=1e-5)


# ---------------------------------------------------------------------------
# Timestamp results: the utterances that were not scored
# ---------------------------------------------------------------------------

def _check_skipped_against_summary(skipped: list[dict], summary: dict,
                                   report: list[dict]) -> None:
    """The skipped list must account for every count the summary gives."""
    assert len(skipped) == summary["n_skipped"]
    tally: dict[str, int] = {}
    for r in skipped:
        tally[r["reason"]] = tally.get(r["reason"], 0) + 1
    assert tally == {k: v for k, v in summary["skip_reasons"].items() if v}
    assert summary["n_missing_end_timestamp"] == summary["skip_reasons"]["untimed_tail"]
    scored = {r["audio_id"] for r in report}
    assert not scored & {r["audio_id"] for r in skipped}


class TestTimestampSkipped:
    """timestamp_skipped.csv from ARC job 8917980 (see the pins above).

    ESTATS-02 bounded the untimed-tail change at one truncation (8.2 to
    8.0 per cent) and about 9 ms of MAE_end. Neither moved, because the one
    untimed tail is the only chunk of its utterance: the code before
    a36b1d4 found no timed chunk and skipped the utterance without a
    reason, and the code after it skips the same utterance with one. The
    clip is 3.17 s long and its reference is the single word "yeah", which
    Whisper wrote as "ha" 222 times, breaking off with no closing
    timestamp. The AMI word annotation (release 1.6.2) stretches that word
    over the whole clip and marks a laugh starting where the clip ends.
    """

    @pytest.fixture(autouse=True)
    def load(self):
        self.skipped = _load_csv(_TS_SKIPPED)
        self.summary = _load_json(_TS_SUMMARY)
        self.report = _load_csv(_TS_REPORT)

    def test_skipped_list_matches_the_summary(self):
        _check_skipped_against_summary(self.skipped, self.summary, self.report)

    def test_the_skipped_utterance_pinned(self):
        (row,) = self.skipped
        assert row["audio_id"] == "AMI_EN2002a_H01_FEO070_0147251_0147568"
        assert row["meeting_id"] == "EN2002a"
        assert row["reason"] == "untimed_tail"
        assert row["n_chunks"] == "1"
        words = {w.strip(",.").lower() for w in row["hypothesis"].split()}
        assert words == {"ha"}


# ---------------------------------------------------------------------------
# VAD end-boundary refinement (Silero VAD, max() operator)
# ---------------------------------------------------------------------------

_VAD_REFINE_TS_SUMMARY = _ROOT / "output" / "evaluation_vad_refine" / "timestamp_summary.json"
_VAD_REFINE_TS_REPORT = _ROOT / "output" / "evaluation_vad_refine" / "timestamp_report.csv"
_VAD_REFINE_TS_SKIPPED = _ROOT / "output" / "evaluation_vad_refine" / "timestamp_skipped.csv"


@pytest.mark.skipif(
    not _VAD_REFINE_TS_SUMMARY.exists(),
    reason="VAD-refined timestamp results not present; run with --vad-refine",
)
class TestVadRefineTimestampResultsExist:
    def test_summary_exists(self):
        assert _VAD_REFINE_TS_SUMMARY.exists()

    def test_report_exists(self):
        assert _VAD_REFINE_TS_REPORT.exists()


@pytest.mark.skipif(
    not _VAD_REFINE_TS_SUMMARY.exists(),
    reason="VAD-refined timestamp results not present; run with --vad-refine",
)
class TestVadRefineTimestampPinnedValues:
    """Regression pins for the VAD-refined timestamp benchmark.

    Produced by ARC job 8917981 (node htc-g059, NVIDIA H100 80GB HBM3, code
    6f9bf56, clean tree, openai/whisper-large-v3 + Silero VAD max()
    refinement from the tag snakers4/silero-vad:v6.2.1, 2026-09-27;
    hpc/runs/timestamps_vad.env). It reproduced the first committed run,
    job 7746221 (node htc-g033, Tesla P100-PCIE-16GB; code bb32915; Silero
    from the untagged repository; 2026-05-31; it replaced job 7746138, a
    min() attempt on an H100 PCIe on htc-g055), in every report row and, to
    the last digit, in every statistic that run's summary held, so the
    values pinned before did not move (DEPS-06, TESTS-10). The max()
    operator halves MAE_end relative to the baseline (0.127 s to 0.064 s)
    by moving 52 of the 499 ends later.
    """

    @pytest.fixture(autouse=True)
    def load(self):
        self.s = _load_json(_VAD_REFINE_TS_SUMMARY)

    def test_vad_refine_flag_is_true(self):
        assert self.s.get("vad_refine") is True

    def test_vad_was_applied_from_the_pinned_tag(self):
        """``vad_refine`` records the request; ``vad_applied``, the source
        and the failure counts record what happened (DEPS-06). The VAD heard
        no speech in 162 of the 499 clips and left those ends as Whisper
        put them."""
        assert self.s["vad_applied"] is True
        assert self.s["vad_source"] == "snakers4/silero-vad:v6.2.1"
        assert self.s["n_vad_exception"] == 0
        assert self.s["n_vad_no_speech"] == 162

    def test_n_is_499(self):
        assert self.s["n"] == 499

    def test_the_same_untimed_tail_was_skipped(self):
        assert self.s["n_skipped"] == 1
        assert self.s["n_missing_end_timestamp"] == 1

    def test_skipped_list_matches_the_summary(self):
        _check_skipped_against_summary(_load_csv(_VAD_REFINE_TS_SKIPPED), self.s,
                                       _load_csv(_VAD_REFINE_TS_REPORT))

    def test_robust_end_statistics_pinned(self):
        """Statistics the first run's summary predated (ec91a66)."""
        assert self.s["median_abs_end_error"] == pytest.approx(0.01, abs=1e-9)
        assert self.s["p90_abs_end_error"] == pytest.approx(0.09, abs=1e-9)
        assert self.s["gross_end_error_rate"] * self.s["n"] == pytest.approx(21)
        assert self.s["truncation_rate"] * self.s["n"] == pytest.approx(21)

    def test_mae_end_below_baseline(self):
        """VAD refinement must reduce MAE_end below the no-VAD baseline (0.127 s)."""
        assert self.s["mae_end"] < 0.127, (
            f"VAD-refined MAE_end ({self.s['mae_end']:.4f} s) is not below "
            "the baseline (0.127 s)"
        )

    def test_mae_end_pinned(self):
        assert self.s["mae_end"] == pytest.approx(0.06390819138276553, rel=1e-4)

    def test_rmse_end_pinned(self):
        assert self.s["rmse_end"] == pytest.approx(0.25356058650348934, rel=1e-4)

    def test_mae_start_unchanged(self):
        """VAD refinement touches only end boundaries; start MAE must be stable."""
        assert self.s["mae_start"] == pytest.approx(0.0087374749498998, rel=1e-4)

    def test_mae_total_pinned(self):
        assert self.s["mae_total"] == pytest.approx(0.07264566633266532, rel=1e-4)

    def test_mean_end_error_pinned(self):
        assert self.s["mean_end_error"] == pytest.approx(0.05701365230460922, rel=1e-4)


@pytest.mark.skipif(
    not _VAD_REFINE_TS_SUMMARY.exists(),
    reason="VAD-refined timestamp results not present; run with --vad-refine",
)
class TestVadRefineAgainstPlain:
    """The refined run against the plain one, row by row.

    Jobs 8917981 and 8917980 decoded the same 500 rows at the same commit on
    the same node and card type, so the VAD should be the only difference
    between their reports, and test_the_vad_changes_no_start_and_no_word
    checks that it is. The failure TESTS-10 describes, max() changed to
    min() with no test noticing, would show in the data as an end pulled
    earlier.
    """

    @pytest.fixture(autouse=True)
    def load(self):
        self.plain = _load_csv(_TS_REPORT)
        self.vad = _load_csv(_VAD_REFINE_TS_REPORT)

    def test_same_utterances_in_the_same_order(self):
        assert [r["audio_id"] for r in self.vad] == [r["audio_id"] for r in self.plain]

    def test_the_vad_changes_no_start_and_no_word(self):
        for p, v in zip(self.plain, self.vad, strict=True):
            assert v["pred_start_s"] == p["pred_start_s"], p["audio_id"]
            assert v["hypothesis"] == p["hypothesis"], p["audio_id"]
            assert v["n_chunks"] == p["n_chunks"], p["audio_id"]

    def test_the_vad_never_pulls_an_end_earlier(self):
        for p, v in zip(self.plain, self.vad, strict=True):
            assert float(v["pred_end_s"]) >= float(p["pred_end_s"]), p["audio_id"]

    def test_the_vad_extends_52_ends(self):
        extended = sum(1 for p, v in zip(self.plain, self.vad, strict=True)
                       if float(v["pred_end_s"]) > float(p["pred_end_s"]))
        assert extended == 52

    def test_gross_errors_left_are_a_subset_of_the_plain_ones(self):
        """Extension can only shorten an early stop, so it cannot make a
        new gross error: 20 of the 41 drop below 0.5 s and 21 remain."""
        def gross(rows):
            return {r["audio_id"] for r in rows if float(r["end_error_s"]) > 0.5}
        assert gross(self.vad) <= gross(self.plain)
        assert (len(gross(self.plain)), len(gross(self.vad))) == (41, 21)

    def test_the_same_utterance_was_skipped(self):
        assert _load_csv(_VAD_REFINE_TS_SKIPPED) == _load_csv(_TS_SKIPPED)


# ---------------------------------------------------------------------------
# Clustering threshold sweep — threshold=0.60
# ---------------------------------------------------------------------------

_CLUST_060_SUMMARY = _ROOT / "output" / "evaluation_clustering_0.60" / "der_summary.json"
_CLUST_060_REPORT = _ROOT / "output" / "evaluation_clustering_0.60" / "der_report.csv"


@pytest.mark.skipif(
    not _CLUST_060_SUMMARY.exists(),
    reason="Clustering-0.60 DER results not present",
)
class TestClustering060PinnedValues:
    """Regression pins for the DER benchmark at clustering_threshold=0.60.

    Produced by ARC job 7746222 (node htc-g034, Tesla P100-PCIE-16GB, code
    bb32915, 2026-05-31). The default-threshold confusion and missed speech
    below are those committed in 815b5a7, which job 7742188 wrote (node
    htc-g032, Tesla P100-PCIE-16GB, 2026-05-30). The lower threshold
    over-fragments speakers relative to the default (0.705), raising macro
    DER from 0.288 to 0.319, a negative result confirming the default is
    near-optimal.
    """

    @pytest.fixture(autouse=True)
    def load(self):
        self.s = _load_json(_CLUST_060_SUMMARY)
        self.rows = _load_csv(_CLUST_060_REPORT)

    def test_clustering_threshold_recorded(self):
        assert self.s.get("clustering_threshold") == pytest.approx(0.60, abs=1e-6)

    def test_n_meetings(self):
        assert self.s["n_meetings"] == 16

    def test_macro_der_pinned(self):
        assert self.s["macro_der"] == pytest.approx(0.31937828062122087, rel=1e-4)

    def test_macro_confusion_higher_than_baseline(self):
        """Lower clustering threshold increases speaker confusion vs default."""
        baseline_confusion = 0.10968286966032076  # 815b5a7, from job 7742188
        assert self.s["macro_confusion"] > baseline_confusion

    def test_macro_missed_unchanged(self):
        """Clustering threshold does not affect missed speech."""
        baseline_missed = 0.12660195592062648
        assert self.s["macro_missed"] == pytest.approx(baseline_missed, abs=1e-4)

    def test_arithmetic_consistency(self):
        s = self.s
        components = s["macro_missed"] + s["macro_fa"] + s["macro_confusion"]
        assert s["macro_der"] == pytest.approx(components, rel=1e-4)
