"""Tests for VAD threshold application in the diarisation path.

These live in their own file rather than alongside the other diarisation
tests because that module ends with a module-level
``pytest.importorskip("pyannote.audio")``, which skips everything defined
after it. None of the behaviour here needs pyannote, and it should be
exercised on every machine that runs the suite.

The behaviour under test is a reporting guarantee: ``setattr`` on an
ordinary Python object always succeeds, so an assignment to a name the
pipeline never reads is indistinguishable from a real override unless the
value is read back. The earlier implementation took the assignment at
face value and told the user the threshold had been applied while the
pipeline went on using its default.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import transcription


class _Spec:
    def __init__(self, powerset):
        self.powerset = powerset


class _Model:
    def __init__(self, powerset):
        self.specifications = _Spec(powerset)


class _Segmentation:
    def __init__(self, powerset):
        self.model = _Model(powerset)


class PowersetPipeline:
    """pyannote 3.x: no binary threshold exists anywhere on the pipeline."""

    def __init__(self):
        self._segmentation = _Segmentation(powerset=True)


class BinaryPipeline:
    """pyannote 3.x SpeakerDiarization on a binary segmentation model.

    Its segmentation parameters are ``threshold`` and ``min_duration_off``
    (pyannote/audio/pipelines/speaker_diarization.py, 3.4.0), so there is
    an onset threshold and no offset.
    """

    class _Params:
        def __init__(self):
            self.threshold = 0.5
            self.min_duration_off = 0.0

    def __init__(self):
        self._segmentation = _Segmentation(powerset=False)
        self.segmentation = BinaryPipeline._Params()


class VadPipeline:
    """pyannote 3.x VoiceActivityDetection on a binary segmentation model.

    Top-level ``onset`` and ``offset`` hyperparameters
    (pyannote/audio/pipelines/voice_activity_detection.py, 3.4.0); such a
    pipeline can be loaded through --diarization-config.
    """

    def __init__(self):
        self._segmentation = _Segmentation(powerset=False)
        self.onset = 0.5
        self.offset = 0.5


class DeafPipeline:
    """Accepts every write and reads back nothing: the trap case."""

    def __init__(self):
        object.__setattr__(self, "_segmentation", _Segmentation(powerset=False))

    def __setattr__(self, name, value):
        pass                      # swallows the write, exactly as the bug did

    def __getattr__(self, name):
        raise AttributeError(name)


# ---------------------------------------------------------------------------
# _diarization_uses_powerset
# ---------------------------------------------------------------------------

def test_powerset_head_is_detected():
    assert transcription._diarization_uses_powerset(PowersetPipeline()) is True


def test_binary_head_is_detected():
    assert transcription._diarization_uses_powerset(BinaryPipeline()) is False


def test_an_unfamiliar_object_is_not_assumed_to_be_powerset():
    assert transcription._diarization_uses_powerset(object()) is False


# ---------------------------------------------------------------------------
# _apply_vad_thresholds
# ---------------------------------------------------------------------------

def test_no_thresholds_requested_says_nothing():
    applied, message = transcription._apply_vad_thresholds(BinaryPipeline())
    assert applied == {}
    assert message is None


def test_powerset_pipeline_reports_no_effect_rather_than_success():
    applied, message = transcription._apply_vad_thresholds(
        PowersetPipeline(), vad_onset=0.3)
    assert applied == {}
    assert "no effect" in message
    assert "defaults were used" in message


def test_binary_diarisation_pipeline_applies_onset_and_reports_offset():
    """SpeakerDiarization has an onset threshold and no offset (T2-19)."""
    pipe = BinaryPipeline()
    applied, message = transcription._apply_vad_thresholds(
        pipe, vad_onset=0.3, vad_offset=0.2)
    assert applied == {"onset": 0.3}
    assert pipe.segmentation.threshold == 0.3
    assert not hasattr(pipe.segmentation, "offset")
    assert message.startswith("VAD thresholds applied")
    assert "no effect: offset" in message


def test_vad_pipeline_applies_and_confirms_both_thresholds():
    pipe = VadPipeline()
    applied, message = transcription._apply_vad_thresholds(
        pipe, vad_onset=0.3, vad_offset=0.2)
    assert applied == {"onset": 0.3, "offset": 0.2}
    assert (pipe.onset, pipe.offset) == (0.3, 0.2)
    assert message == "VAD thresholds applied: offset=0.2, onset=0.3"


def test_pyannote_2_attribute_names_are_no_longer_tried():
    """The 2.x names exist on no supported pyannote version (T2-19)."""
    class Legacy:
        def __init__(self):
            self._segmentation = _Segmentation(powerset=False)
            self.segmentation_onset = 0.5
            self.segmentation_offset = 0.5

    pipe = Legacy()
    applied, message = transcription._apply_vad_thresholds(
        pipe, vad_onset=0.3, vad_offset=0.2)
    assert applied == {}
    assert "Could not apply" in message
    assert (pipe.segmentation_onset, pipe.segmentation_offset) == (0.5, 0.5)


def test_a_pipeline_that_swallows_the_write_is_not_reported_as_applied():
    """The regression this helper exists for."""
    applied, message = transcription._apply_vad_thresholds(
        DeafPipeline(), vad_onset=0.3)
    assert applied == {}
    assert "Could not apply" in message


def test_partial_application_names_the_threshold_that_did_not_take():
    class OnsetOnly:
        class _Params:
            def __init__(self):
                self.threshold = 0.5      # no offset attribute at all

        def __init__(self):
            self._segmentation = _Segmentation(powerset=False)
            self.segmentation = OnsetOnly._Params()

    applied, message = transcription._apply_vad_thresholds(
        OnsetOnly(), vad_onset=0.3, vad_offset=0.2)
    assert applied == {"onset": 0.3}
    assert "no effect: offset" in message


# ---------------------------------------------------------------------------
# _speaker_count_kwargs
# ---------------------------------------------------------------------------

def test_no_hint_passes_nothing_to_the_pipeline():
    assert transcription._speaker_count_kwargs() == {}


def test_an_exact_count_is_passed_through():
    assert transcription._speaker_count_kwargs(num_speakers=2) == {
        "num_speakers": 2}


def test_an_exact_count_replaces_a_range_rather_than_joining_it():
    """pyannote rejects num_speakers alongside min/max."""
    assert transcription._speaker_count_kwargs(
        num_speakers=2, min_speakers=1, max_speakers=8) == {"num_speakers": 2}


def test_a_range_is_passed_as_bounds():
    assert transcription._speaker_count_kwargs(
        min_speakers=2, max_speakers=6) == {"min_speakers": 2, "max_speakers": 6}


def test_one_sided_bounds_are_allowed():
    assert transcription._speaker_count_kwargs(max_speakers=4) == {
        "max_speakers": 4}
    assert transcription._speaker_count_kwargs(min_speakers=3) == {
        "min_speakers": 3}


def test_counts_below_one_cannot_describe_a_recording_and_are_dropped():
    assert transcription._speaker_count_kwargs(num_speakers=0) == {}
    assert transcription._speaker_count_kwargs(min_speakers=0,
                                               max_speakers=0) == {}


def test_an_inverted_range_is_rejected_rather_than_silently_reordered():
    import pytest
    with pytest.raises(ValueError, match="exceeds"):
        transcription._speaker_count_kwargs(min_speakers=5, max_speakers=2)


def test_string_counts_from_a_config_file_are_accepted():
    assert transcription._speaker_count_kwargs(num_speakers="3") == {
        "num_speakers": 3}
