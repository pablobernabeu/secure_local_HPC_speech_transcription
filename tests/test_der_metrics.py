"""
Unit tests for evaluation.der_metrics.

All tests use synthetic pyannote.core.Annotation objects so that no audio,
no network access, and no ASR or diarisation models are required.  The
pyannote packages are imported via pytest.importorskip so that the test suite
remains green in environments that do not have pyannote.audio installed.
"""

import pytest


# ---------------------------------------------------------------------------
# annotation_from_segments
# ---------------------------------------------------------------------------

class TestAnnotationFromSegments:
    def setup_method(self):
        pytest.importorskip("pyannote.core")
        from evaluation.der_metrics import annotation_from_segments
        self.fn = annotation_from_segments

    def test_two_speakers_on_an_identical_span_both_survive(self):
        """EDER-02: on pyannote's default track the second turn replaced
        the first. AMI test EN2002c has such a pair at 543.24-543.55 s."""
        segs = [
            {"start": 543.24, "end": 543.55, "speaker": "MEE071"},
            {"start": 543.24, "end": 543.55, "speaker": "MEE073"},
        ]
        ann = self.fn(segs)
        assert sorted(label for _, _, label in ann.itertracks(yield_label=True)) \
            == ["MEE071", "MEE073"]

    def test_an_exact_repeat_by_one_speaker_is_kept_once(self):
        segs = [{"start": 1.0, "end": 2.0, "speaker": "A"}] * 2
        assert len(list(self.fn(segs).itertracks())) == 1

    def test_basic_creates_correct_number_of_tracks(self):
        segs = [
            {"start": 0.0, "end": 2.0, "speaker": "A"},
            {"start": 2.5, "end": 5.0, "speaker": "B"},
        ]
        ann = self.fn(segs, uri="test_meeting")
        assert ann.uri == "test_meeting"
        assert len(list(ann.itertracks())) == 2
        labels = ann.labels()
        assert "A" in labels and "B" in labels

    def test_empty_segments_returns_empty_annotation(self):
        ann = self.fn([], uri="empty")
        assert len(list(ann.itertracks())) == 0

    def test_zero_duration_segment_is_skipped(self):
        segs = [
            {"start": 1.0, "end": 1.0, "speaker": "A"},  # duration = 0, should be skipped
            {"start": 2.0, "end": 3.0, "speaker": "B"},
        ]
        ann = self.fn(segs)
        # Only the B segment should be present.
        labels = ann.labels()
        assert "B" in labels
        assert "A" not in labels

    def test_uri_defaults_to_meeting(self):
        ann = self.fn([{"start": 0.0, "end": 1.0, "speaker": "A"}])
        assert ann.uri == "meeting"


# ---------------------------------------------------------------------------
# compute_der
# ---------------------------------------------------------------------------

class TestComputeDer:
    def setup_method(self):
        pytest.importorskip("pyannote.metrics")
        from evaluation.der_metrics import annotation_from_segments, compute_der
        self.ann = annotation_from_segments
        self.compute = compute_der

    def _ref(self, segs):
        return self.ann(segs, uri="meeting")

    def test_perfect_hypothesis_gives_zero_der(self):
        segs = [
            {"start": 0.0, "end": 5.0, "speaker": "A"},
            {"start": 5.5, "end": 10.0, "speaker": "B"},
        ]
        ref = self._ref(segs)
        hyp = self._ref(segs)
        result = self.compute(ref, hyp)
        assert result["der"] == pytest.approx(0.0, abs=1e-6)
        assert result["missed_speech"] == pytest.approx(0.0, abs=1e-6)
        assert result["false_alarm"] == pytest.approx(0.0, abs=1e-6)
        assert result["speaker_confusion"] == pytest.approx(0.0, abs=1e-6)

    def test_empty_hypothesis_missed_speech_dominates(self):
        segs = [{"start": 0.0, "end": 10.0, "speaker": "A"}]
        ref = self._ref(segs)
        hyp = self.ann([], uri="meeting")
        result = self.compute(ref, hyp, collar=0.0)
        # All reference speech is missed; DER should be >= 1.
        assert result["der"] >= 1.0
        assert result["_missed_abs"] > 0.0

    def test_speaker_confusion_counted(self):
        # Reference: A speaks for the first half, B for the second half.
        # Hypothesis uses a single speaker label for both halves.
        # After optimal speaker mapping (hypothesis speaker → A), the second
        # half is scored as speaker confusion, so _confusion_abs > 0.
        ref_segs = [
            {"start": 0.0, "end": 5.0, "speaker": "A"},
            {"start": 5.0, "end": 10.0, "speaker": "B"},
        ]
        hyp_segs = [{"start": 0.0, "end": 10.0, "speaker": "only_one"}]
        ref = self._ref(ref_segs)
        hyp = self.ann(hyp_segs, uri="meeting")
        result = self.compute(ref, hyp, collar=0.0)
        # Exactly the second half is confusion, and nothing else is wrong.
        assert result["speaker_confusion"] == pytest.approx(0.5, abs=1e-9)
        assert result["missed_speech"] == pytest.approx(0.0, abs=1e-9)
        assert result["false_alarm"] == pytest.approx(0.0, abs=1e-9)
        assert result["der"] == pytest.approx(0.5, abs=1e-9)

    def test_speech_beyond_the_reference_is_false_alarm(self):
        """The only test that gives the false-alarm mapping a nonzero value."""
        ref = self._ref([{"start": 0.0, "end": 10.0, "speaker": "A"}])
        hyp = self._ref([{"start": 0.0, "end": 12.0, "speaker": "A"}])
        result = self.compute(ref, hyp, collar=0.0)
        assert result["false_alarm"] == pytest.approx(0.2, abs=1e-9)
        assert result["missed_speech"] == pytest.approx(0.0, abs=1e-9)
        assert result["speaker_confusion"] == pytest.approx(0.0, abs=1e-9)
        assert result["_fa_abs"] == pytest.approx(2.0, abs=1e-9)

    def test_speech_cut_short_is_missed(self):
        ref = self._ref([{"start": 0.0, "end": 10.0, "speaker": "A"}])
        hyp = self._ref([{"start": 0.0, "end": 8.0, "speaker": "A"}])
        result = self.compute(ref, hyp, collar=0.0)
        assert result["missed_speech"] == pytest.approx(0.2, abs=1e-9)
        assert result["false_alarm"] == pytest.approx(0.0, abs=1e-9)
        assert result["speaker_confusion"] == pytest.approx(0.0, abs=1e-9)

    def test_both_speakers_on_an_identical_span_are_scored(self):
        """A hypothesis naming only one of two speakers who share a span
        misses the other; before EDER-02 the reference lost one of them
        and the run scored zero error over half the true speech."""
        both = [{"start": 0.0, "end": 4.0, "speaker": "A"},
                {"start": 0.0, "end": 4.0, "speaker": "B"}]
        ref = self._ref(both)
        hyp = self._ref([{"start": 0.0, "end": 4.0, "speaker": "x"}])
        result = self.compute(ref, hyp, collar=0.0)
        assert result["total_ref_duration"] == pytest.approx(8.0)
        assert result["_missed_abs"] == pytest.approx(4.0)
        assert result["der"] == pytest.approx(0.5)

    def test_result_keys_present(self):
        segs = [{"start": 0.0, "end": 2.0, "speaker": "A"}]
        ref = hyp = self._ref(segs)
        result = self.compute(ref, hyp)
        required_keys = {
            "uri", "der", "missed_speech", "false_alarm",
            "speaker_confusion", "total_ref_duration",
            "_missed_abs", "_fa_abs", "_confusion_abs",
        }
        assert required_keys.issubset(result.keys())

    def test_total_ref_duration_is_positive(self):
        segs = [{"start": 0.0, "end": 3.0, "speaker": "A"}]
        ref = hyp = self._ref(segs)
        result = self.compute(ref, hyp)
        assert result["total_ref_duration"] > 0.0


# ---------------------------------------------------------------------------
# rates_from_components (no pyannote needed)
# ---------------------------------------------------------------------------

class TestRatesFromComponents:
    """The component-name mapping, pinned where pyannote is not installed.

    A swap of 'missed detection' and 'false alarm' leaves total DER
    unchanged, so only a test on the individual keys can catch it.
    """

    def setup_method(self):
        from evaluation.der_metrics import rates_from_components
        self.fn = rates_from_components

    def _components(self, **overrides):
        base = {"total": 10.0, "correct": 7.0, "missed detection": 1.0,
                "false alarm": 2.0, "confusion": 3.0}
        base.update(overrides)
        return base

    def test_each_component_reaches_its_own_key(self):
        result = self.fn(self._components(), uri="m")
        assert result["missed_speech"] == pytest.approx(0.1)
        assert result["false_alarm"] == pytest.approx(0.2)
        assert result["speaker_confusion"] == pytest.approx(0.3)
        assert result["der"] == pytest.approx(0.6)
        assert (result["_missed_abs"], result["_fa_abs"],
                result["_confusion_abs"]) == (1.0, 2.0, 3.0)
        assert result["total_ref_duration"] == 10.0
        assert result["uri"] == "m"

    @pytest.mark.parametrize("key", ["missed detection", "false alarm",
                                     "confusion", "total"])
    def test_a_missing_component_raises_instead_of_reading_as_zero(self, key):
        components = self._components()
        del components[key]
        with pytest.raises(KeyError, match=key):
            self.fn(components)

    def test_no_reference_speech_gives_zero_rates(self):
        zero = {"total": 0.0, "missed detection": 0.0, "false alarm": 0.0,
                "confusion": 0.0}
        result = self.fn(zero)
        assert result["der"] == 0.0 and result["false_alarm"] == 0.0


# ---------------------------------------------------------------------------
# aggregate_der
# ---------------------------------------------------------------------------

class TestAggregateDer:
    def setup_method(self):
        pytest.importorskip("pyannote.metrics")
        from evaluation.der_metrics import aggregate_der
        self.agg = aggregate_der

    def _mock_result(self, der, total, missed_frac=0.0, fa_frac=0.0, confusion_frac=0.0):
        missed_abs = total * missed_frac
        fa_abs = total * fa_frac
        confusion_abs = total * confusion_frac
        return {
            "uri": "mock",
            "der": der,
            "missed_speech": missed_frac,
            "false_alarm": fa_frac,
            "speaker_confusion": confusion_frac,
            "total_ref_duration": total,
            "_missed_abs": missed_abs,
            "_fa_abs": fa_abs,
            "_confusion_abs": confusion_abs,
        }

    def test_empty_input_returns_zero_dict(self):
        """A sentinel, not a score: aggregating nothing gives zeros, which
        is why benchmark_der and sweep_der refuse to report a run that
        scored no meeting (tests/test_audit_der_outputs.py)."""
        result = self.agg([])
        assert result["n_meetings"] == 0
        assert result["macro_der"] == 0.0
        assert result["micro_der"] == 0.0

    def test_single_meeting_macro_equals_micro(self):
        r = self._mock_result(der=0.2, total=10.0, confusion_frac=0.2)
        result = self.agg([r])
        assert result["n_meetings"] == 1
        assert result["macro_der"] == pytest.approx(0.2)
        assert result["micro_der"] == pytest.approx(0.2)

    def test_micro_der_is_duration_weighted(self):
        # Short meeting: DER=0.5, long meeting: DER=0.1
        # Micro DER should be closer to 0.1 than to 0.5.
        short = self._mock_result(der=0.5, total=2.0, confusion_frac=0.5)
        long_ = self._mock_result(der=0.1, total=18.0, confusion_frac=0.1)
        result = self.agg([short, long_])
        # Manually: (0.5*2 + 0.1*18) / (2+18) = (1.0 + 1.8) / 20 = 0.14
        assert result["micro_der"] == pytest.approx(0.14, abs=1e-6)
        assert result["macro_der"] == pytest.approx(0.3, abs=1e-6)

    def test_total_ref_duration_sums_correctly(self):
        r1 = self._mock_result(der=0.0, total=10.0)
        r2 = self._mock_result(der=0.0, total=5.5)
        result = self.agg([r1, r2])
        assert result["total_ref_duration"] == pytest.approx(15.5)
