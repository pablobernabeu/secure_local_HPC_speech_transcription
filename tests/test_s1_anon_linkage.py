"""Stage-1 fixes EPRIV-04 and EPRIV-15 in the anonymisation linkage test.

EPRIV-04: chance was one over the number of distinct speakers, and a
speaker with a single utterance was scored as a trial no method could win.
EPRIV-15: every candidate came from the probe's own meeting, where each
speaker wears one headset throughout, so a match could key on the channel.

Embeddings are supplied directly; no model, audio or network.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation import benchmark_anonymisation as ba  # noqa: E402


def _random(n, rng, dim=16):
    return [rng.standard_normal(dim) for _ in range(n)]


class TestChanceLevel:
    def test_imbalanced_speakers_are_not_read_against_one_over_speakers(self):
        """Nine utterances from A and one from B, embeddings pure noise.

        A transform that removed every trace of the voice scores about
        8/9 here, because eight of an A probe's nine candidates are A.
        Read against the old chance of 0.5 that looked like
        re-identification. B has no partner and is not a trial.
        """
        rng = np.random.default_rng(0)
        speakers = ["A"] * 9 + ["B"]
        rates = []
        for _ in range(400):
            result = ba.linkage_rate(_random(10, rng), _random(10, rng), speakers)
            rates.append(result["linkage_rate"])
        assert result["trials"] == 9
        assert result["n_singleton_excluded"] == 1
        assert result["chance"] == pytest.approx(8 / 9, abs=1e-4)
        assert np.mean(rates) == pytest.approx(result["chance"], abs=0.03)

    def test_without_singletons_chance_is_the_closed_form(self):
        """sum_s n_s(n_s-1) / (n(n-1)) = (6 + 2 + 20) / 90 for 3, 2 and 5."""
        rng = np.random.default_rng(1)
        speakers = ["A"] * 3 + ["B"] * 2 + ["C"] * 5
        rates = []
        for _ in range(400):
            result = ba.linkage_rate(_random(10, rng), _random(10, rng), speakers)
            rates.append(result["linkage_rate"])
        assert result["chance"] == pytest.approx(28 / 90, abs=1e-4)
        assert result["n_singleton_excluded"] == 0
        assert np.mean(rates) == pytest.approx(28 / 90, abs=0.03)

    def test_every_utterance_a_singleton_gives_no_trials(self):
        e = [np.array([1.0, 0.0]), np.array([0.0, 1.0])]
        result = ba.linkage_rate(e, e, ["A", "B"])
        assert result["trials"] == 0
        assert result["linkage_rate"] is None
        assert result["chance"] is None
        assert result["n_singleton_excluded"] == 2

    def test_a_candidate_mask_of_the_wrong_shape_is_refused(self):
        e = [np.array([1.0]), np.array([2.0])]
        with pytest.raises(ValueError):
            ba.linkage_rate(e, e, ["A", "A"], candidates=np.ones((3, 3), bool))


def _rotating_channels(noise=0.01, seed=0):
    """Three speakers in two meetings, each changing headset between them.

    Two utterances per speaker per meeting. The embedding carries the
    headset channel and nothing of the voice, which is what a transform
    that removed the voice but kept the microphone would leave.
    """
    channel_of = {("m1", "S1"): 0, ("m1", "S2"): 1, ("m1", "S3"): 2,
                  ("m2", "S1"): 1, ("m2", "S2"): 2, ("m2", "S3"): 0}
    rng = np.random.default_rng(seed)
    speakers, meetings, channels, embeddings = [], [], [], []
    for (meeting, speaker), channel in channel_of.items():
        for _ in range(2):
            speakers.append(speaker)
            meetings.append(meeting)
            channels.append(f"H0{channel}")
            vector = np.zeros(3)
            vector[channel] = 1.0
            embeddings.append(vector + noise * rng.standard_normal(3))
    return embeddings, speakers, meetings, channels


class TestCandidateSets:
    def test_within_meeting_linkage_can_be_channel_matching_alone(self):
        """EPRIV-15: perfect within-meeting linkage from the channel only."""
        emb, speakers, meetings, channels = _rotating_channels()
        sets = ba.linkage_by_candidate_set(emb, emb, speakers, meetings,
                                           channels)
        assert sets["within_meeting"]["linkage_rate"] == pytest.approx(1.0)
        # Across meetings the same channel now belongs to someone else, so
        # a channel-keyed match points at the wrong speaker every time.
        assert sets["cross_meeting"]["linkage_rate"] == pytest.approx(0.0)

    def test_each_set_has_its_own_chance_level(self):
        emb, speakers, meetings, channels = _rotating_channels()
        sets = ba.linkage_by_candidate_set(emb, emb, speakers, meetings,
                                           channels)
        # Within a meeting: 1 same-speaker recording among 5 others.
        assert sets["within_meeting"]["chance"] == pytest.approx(1 / 5)
        # Other meeting: 2 of that meeting's 6 recordings.
        assert sets["cross_meeting"]["chance"] == pytest.approx(2 / 6, abs=1e-4)
        # Other meeting, other channel: 2 of the 4 left.
        assert sets["cross_meeting_cross_channel"]["chance"] == pytest.approx(0.5)
        # Everything but the probe: 3 of 11.
        assert sets["all"]["chance"] == pytest.approx(3 / 11, abs=1e-4)

    def test_a_single_meeting_has_no_cross_meeting_trials(self):
        """The committed single-meeting run: all linkage is within-meeting."""
        rng = np.random.default_rng(2)
        speakers = ["A", "A", "B", "B"]
        emb = _random(4, rng)
        sets = ba.linkage_by_candidate_set(emb, emb, speakers, ["m1"] * 4,
                                           ["H00", "H00", "H01", "H01"])
        assert sets["cross_meeting"]["trials"] == 0
        assert sets["cross_meeting"]["linkage_rate"] is None
        assert sets["cross_meeting"]["n_singleton_excluded"] == 4
        assert sets["within_meeting"] == sets["all"]

    def test_without_meetings_only_the_full_set_is_reported(self):
        rng = np.random.default_rng(3)
        emb = _random(4, rng)
        sets = ba.linkage_by_candidate_set(emb, emb, ["A", "A", "B", "B"])
        assert list(sets) == ["all"]

    def test_an_unknown_channel_is_never_channel_mismatched(self):
        rng = np.random.default_rng(4)
        emb = _random(4, rng)
        sets = ba.linkage_by_candidate_set(
            emb, emb, ["A", "B", "A", "B"], ["m1", "m1", "m2", "m2"],
            [None, "H01", None, "H01"])
        assert sets["cross_meeting_cross_channel"]["trials"] == 0

    def test_the_flat_keys_keep_their_meaning(self):
        """linkage_rate and chance stay the all-candidates figures."""
        emb, speakers, meetings, channels = _rotating_channels()
        sets = ba.linkage_by_candidate_set(emb, emb, speakers, meetings,
                                           channels)
        flat = ba._flat_linkage(sets)
        assert flat["linkage_rate"] == sets["all"]["linkage_rate"]
        assert flat["chance"] == sets["all"]["chance"]
        assert flat["linkage_rate_within_meeting"] == pytest.approx(1.0)
        assert flat["linkage_rate_cross_meeting"] == pytest.approx(0.0)
        assert flat["chance_cross_meeting"] == pytest.approx(1 / 3, abs=1e-4)
        assert set(flat["linkage_by_candidates"]) == set(ba.CANDIDATE_SETS)


class TestSpeakerChannelCheck:
    def test_keeping_and_changing_speakers_are_told_apart(self):
        """EN2002 speakers changed channel; ES2004 and IS1009 kept theirs."""
        check = ba.speaker_channel_check(
            ["S1", "S1", "S2", "S2", "S3"],
            ["m1", "m2", "m1", "m2", "m1"],
            ["H00", "H00", "H01", "H02", "H03"])
        assert check["speakers_in_several_meetings"] == 2
        assert check["keep_channel"] == ["S1"]
        assert check["change_channel"] == ["S2"]
        assert check["channels"]["S2"] == {"m1": ["H01"], "m2": ["H02"]}

    def test_an_unknown_channel_is_ignored(self):
        check = ba.speaker_channel_check(["S1", "S1"], ["m1", "m2"],
                                         ["H00", None])
        assert check["keep_channel"] == ["S1"]


class TestChannelOfRow:
    def test_the_microphone_field_is_preferred(self):
        assert ba._channel_of({"microphone_id": "H03",
                               "audio_id": "AMI_EN2002a_H00_MEE073_1_2"}) == "H03"

    def test_the_audio_id_is_the_fallback(self):
        assert ba._channel_of(
            {"audio_id": "AMI_EN2002a_H02_FEO072_0035713_0035849"}) == "H02"

    def test_an_unrecognised_row_has_no_channel(self):
        assert ba._channel_of({"audio_id": "u3"}) is None
