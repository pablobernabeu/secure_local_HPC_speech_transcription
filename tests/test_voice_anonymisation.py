"""Tests for the McAdams voice anonymisation.

An anonymiser that does not anonymise is worse than none, because it
invites a corpus to be shared on a false assurance. These tests check
that the transform does what it claims on signals whose properties are
known: that it moves the resonances, that it moves them in the direction
the coefficient dictates, that it leaves the signal finite and stable,
and that the identity setting really is identity.

Everything runs on synthetic audio, so no recording, model or GPU is
needed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

pytest.importorskip("scipy")

from voice_anonymisation import (  # noqa: E402
    DEFAULT_FRAME_S,
    LIMITER_KNEE,
    anonymise,
    levinson_durbin,
    lpc_order_for,
    overlap_weight,
    read_wav,
    shift_poles,
    write_wav,
)

SR = 16_000


def _voiced(duration_s=0.5, f0=120.0, formants=(700.0, 1200.0, 2600.0),
            sample_rate=SR, seed=0):
    """A crude voiced sound: a pulse train shaped by resonances.

    Not speech, but it has the structure the transform acts on, a
    harmonic excitation and a small number of spectral peaks.
    """
    from scipy.signal import lfilter
    n = int(duration_s * sample_rate)
    excitation = np.zeros(n)
    period = int(sample_rate / f0)
    excitation[::period] = 1.0
    rng = np.random.default_rng(seed)
    excitation += 0.01 * rng.standard_normal(n)

    signal = excitation
    for frequency in formants:
        radius, theta = 0.95, 2 * np.pi * frequency / sample_rate
        a = [1.0, -2 * radius * np.cos(theta), radius ** 2]
        signal = lfilter([1.0], a, signal)
    peak = np.max(np.abs(signal))
    return (signal / peak * 0.5).astype(np.float32)


def _spectral_peaks(signal, sample_rate=SR, count=3):
    """Frequencies of the strongest spectral peaks, low to high."""
    spectrum = np.abs(np.fft.rfft(signal * np.hanning(signal.size)))
    freqs = np.fft.rfftfreq(signal.size, 1 / sample_rate)
    # Smooth so harmonics do not masquerade as formants.
    kernel = np.ones(64) / 64
    envelope = np.convolve(spectrum, kernel, mode="same")
    interior = np.where((envelope[1:-1] > envelope[:-2])
                        & (envelope[1:-1] > envelope[2:]))[0] + 1
    strongest = interior[np.argsort(envelope[interior])[-count:]]
    return np.sort(freqs[strongest])


class TestLpcHelpers:
    def test_order_follows_the_sample_rate(self):
        assert lpc_order_for(16_000) == 18
        assert lpc_order_for(8_000) == 10

    def test_levinson_returns_a_monic_polynomial(self):
        signal = _voiced(0.05)
        auto = np.correlate(signal, signal, "full")[signal.size - 1:][:11]
        a = levinson_durbin(auto, 10)
        assert a.shape == (11,)
        assert a[0] == 1.0

    def test_a_silent_frame_yields_an_all_pass_filter(self):
        """Rather than dividing by a zero autocorrelation."""
        a = levinson_durbin(np.zeros(11), 10)
        assert a[0] == 1.0
        assert np.allclose(a[1:], 0.0)

    def test_the_estimated_filter_is_stable(self):
        """Every pole inside the unit circle, or synthesis would ring."""
        signal = _voiced(0.05)
        auto = np.correlate(signal, signal, "full")[signal.size - 1:][:19]
        a = levinson_durbin(auto, 18)
        assert np.all(np.abs(np.roots(a)) < 1.0)


class TestShiftPoles:
    def _filter_with_pole(self, radius, theta):
        return np.poly([radius * np.exp(1j * theta),
                        radius * np.exp(-1j * theta)]).real

    def test_alpha_of_one_changes_nothing(self):
        a = self._filter_with_pole(0.9, 0.5)
        assert np.allclose(shift_poles(a, 1.0), a)

    def test_the_pole_radius_is_preserved(self):
        """Radius sets stability; only the angle should move."""
        a = self._filter_with_pole(0.9, 0.8)
        moved = np.roots(shift_poles(a, 0.8))
        assert np.allclose(np.sort(np.abs(moved)), [0.9, 0.9], atol=1e-9)

    def test_a_stable_filter_stays_stable(self):
        for alpha in (0.5, 0.8, 1.2, 1.5):
            a = self._filter_with_pole(0.95, 1.0)
            assert np.all(np.abs(np.roots(shift_poles(a, alpha))) < 1.0)

    def test_an_angle_below_one_radian_rises_when_alpha_is_below_one(self):
        a = self._filter_with_pole(0.9, 0.5)
        moved = np.roots(shift_poles(a, 0.8))
        assert abs(np.angle(moved[0])) > 0.5

    def test_an_angle_above_one_radian_falls_when_alpha_is_below_one(self):
        """The warp is non-linear, which is what redistributes formants."""
        a = self._filter_with_pole(0.9, 2.0)
        moved = np.roots(shift_poles(a, 0.8))
        assert abs(np.angle(moved[0])) < 2.0

    def test_the_polynomial_stays_real(self):
        """A complex filter would put an imaginary part into real audio."""
        a = self._filter_with_pole(0.9, 1.0)
        assert np.isrealobj(shift_poles(a, 0.7))

    def test_a_real_pole_is_left_alone(self):
        a = np.poly([0.5]).real
        assert np.allclose(shift_poles(a, 0.8), a)


class TestAnonymise:
    def test_alpha_of_one_returns_the_input_unchanged(self):
        """The identity check: no coefficient, no change."""
        signal = _voiced(0.3)
        assert np.allclose(anonymise(signal, SR, alpha=1.0), signal)

    def test_the_length_and_rate_are_preserved(self):
        signal = _voiced(0.4)
        assert anonymise(signal, SR, alpha=0.8).shape == signal.shape

    def test_the_output_is_finite_and_bounded(self):
        """Synthesis through an unstable filter would blow up instead."""
        out = anonymise(_voiced(0.5), SR, alpha=0.7)
        assert np.all(np.isfinite(out))
        assert np.max(np.abs(out)) <= 1.0

    def test_the_formants_actually_move(self):
        """The claim. A transform that left them alone would disguise nothing."""
        signal = _voiced(0.5)
        out = anonymise(signal, SR, alpha=0.75)
        before = _spectral_peaks(signal)
        after = _spectral_peaks(out)
        shift = np.abs(after - before).max()
        assert shift > 50.0, (
            f"peaks moved only {shift:.1f} Hz; the voice is not disguised")

    def test_a_coefficient_further_from_one_moves_them_further(self):
        signal = _voiced(0.5)
        before = _spectral_peaks(signal)
        mild = np.abs(_spectral_peaks(anonymise(signal, SR, alpha=0.9)) - before).sum()
        strong = np.abs(_spectral_peaks(anonymise(signal, SR, alpha=0.6)) - before).sum()
        assert strong > mild

    def test_silence_stays_silent(self):
        """Inventing resonances for silence would add audible noise."""
        out = anonymise(np.zeros(SR, dtype=np.float32), SR, alpha=0.8)
        assert np.allclose(out, 0.0)

    def test_the_transform_is_deterministic(self):
        """An anonymised corpus must be regenerable exactly."""
        signal = _voiced(0.3)
        assert np.array_equal(anonymise(signal, SR, alpha=0.8),
                              anonymise(signal, SR, alpha=0.8))

    def test_loudness_is_preserved_at_realistic_recording_levels(self):
        """The bug that made anonymised audio transcribe *better*.

        The output was once scaled by its own peak, so one ringing sample
        set the gain for the whole file. At an input peak of 0.9 that
        returned audio twenty times quieter, and quiet audio makes the
        recogniser hallucinate less on silence, which moved the word
        error rate on its own.
        """
        for peak in (0.05, 0.3, 0.9, 0.99):
            signal = (_voiced(0.5) / np.max(np.abs(_voiced(0.5))) * peak
                      ).astype(np.float32)
            reference_rms = float(np.sqrt(np.mean(signal ** 2)))
            for alpha in (0.9, 0.8, 0.7):
                out = anonymise(signal, SR, alpha=alpha)
                ratio = float(np.sqrt(np.mean(out ** 2))) / reference_rms
                assert 0.4 < ratio < 1.6, (
                    f"peak {peak}, alpha {alpha}: loudness ratio {ratio:.2f}")

    def test_quiet_speech_is_not_amplified_to_full_scale(self):
        """A quiet recording should stay quiet, not be normalised up."""
        signal = (_voiced(0.5) / np.max(np.abs(_voiced(0.5))) * 0.05
                  ).astype(np.float32)
        out = anonymise(signal, SR, alpha=0.8)
        assert np.max(np.abs(out)) < 0.5

    def test_the_output_never_exceeds_full_scale(self):
        signal = (_voiced(0.5) / np.max(np.abs(_voiced(0.5))) * 0.99
                  ).astype(np.float32)
        for alpha in (0.9, 0.7, 0.5):
            out = anonymise(signal, SR, alpha=alpha)
            assert np.max(np.abs(out)) <= 1.0

    def test_audio_shorter_than_a_frame_is_handled(self):
        tiny = _voiced(0.005)
        out = anonymise(tiny, SR, alpha=0.8)
        assert out.shape == tiny.shape
        assert np.all(np.isfinite(out))

    def test_empty_audio_returns_empty(self):
        assert anonymise(np.zeros(0, dtype=np.float32), SR).size == 0


def _vowel_to_the_end(duration_s, radius=0.985, peak=0.5, seed=0):
    """A sustained vowel whose last sample is still voiced.

    The case EPRIV-02 was found on: a clip cut mid-vowel, so the final
    analysis frame holds speech and the synthesis filter rings past it.
    Sharper resonances than :func:`_voiced` ring for longer.
    """
    from scipy.signal import lfilter
    n = int(duration_s * SR)
    excitation = np.zeros(n)
    excitation[::int(SR / 120)] = 1.0
    excitation += 0.01 * np.random.default_rng(seed).standard_normal(n)
    signal = excitation
    for frequency in (700.0, 1200.0, 2600.0):
        theta = 2 * np.pi * frequency / SR
        signal = lfilter([1.0], [1.0, -2 * radius * np.cos(theta), radius ** 2],
                         signal)
    return (signal / np.max(np.abs(signal)) * peak).astype(np.float32)


def _rms(x):
    return float(np.sqrt(np.mean(np.square(np.asarray(x, dtype=np.float64)))))


class TestOverlapAddEdges:
    """EPRIV-02: the last frame divided by a near-zero window weight.

    Before the fix the final half-frame lay under one window only, so its
    samples were divided by that window squared, about 1.5e-7 two samples
    from the end. The synthesis filter rings past the frame, the ringing
    was amplified a thousandfold into a full-scale click, and matching the
    whole file's loudness then turned the speech down by up to 16 dB.
    """

    FRAME = int(round(DEFAULT_FRAME_S * SR))

    @pytest.mark.parametrize("n_samples", [1, 7, 159, 160, 161, 319, 320, 321,
                                           1000, 16_000, 19_201])
    def test_no_real_sample_is_divided_by_less_than_one_half(self, n_samples):
        weight = overlap_weight(n_samples, self.FRAME)
        assert weight.shape == (n_samples,)
        assert weight.min() >= 0.5 - 1e-6

    @pytest.mark.parametrize("frame", [16, 17, 320, 321, 441])
    def test_the_last_samples_are_fully_overlapped_for_any_frame(self, frame):
        """Odd frame lengths too, which a 22.05 kHz input produces."""
        weight = overlap_weight(3 * frame + 5, frame)
        assert weight[-3:].min() >= 0.5 - 1e-6

    def test_the_weight_is_not_constant(self):
        """The comment this replaced claimed Hann-squared sums to a constant."""
        weight = overlap_weight(4000, self.FRAME)
        assert weight.min() == pytest.approx(0.5, abs=1e-6)
        assert weight.max() == pytest.approx(1.0, abs=1e-6)

    @pytest.mark.parametrize("duration_s", [1.2, 2.5])
    @pytest.mark.parametrize("alpha", [0.5, 0.8, 0.9])
    def test_a_clip_voiced_to_its_last_sample_keeps_its_loudness(
            self, duration_s, alpha):
        """Body RMS within 1 dB of the input; it fell 6 to 16 dB before."""
        signal = _vowel_to_the_end(duration_s)
        out = anonymise(signal, SR, alpha=alpha)
        edge = int(0.025 * SR)
        ratio = _rms(out[edge:-edge]) / _rms(signal[edge:-edge])
        assert abs(20 * np.log10(ratio)) < 1.0, (
            f"body level changed by {20 * np.log10(ratio):+.1f} dB")

    def test_the_end_of_the_clip_carries_no_full_scale_click(self):
        """At a moderate warp the last 25 ms stays at the level of the body."""
        signal = _vowel_to_the_end(1.2)
        out = anonymise(signal, SR, alpha=0.8)
        edge = int(0.025 * SR)
        assert np.max(np.abs(out[-edge:])) < 1.5 * np.max(np.abs(out[:-edge]))
        assert np.count_nonzero(np.abs(out) > LIMITER_KNEE) == 0

    def test_the_control_is_still_the_identity_below_the_knee(self):
        """alpha = 1 through the full path returns the input."""
        signal = _vowel_to_the_end(1.2, peak=0.5)
        out = anonymise(signal, SR, alpha=1.0, force_resynthesis=True)
        assert np.max(np.abs(out - signal)) < 1e-6

    def test_the_control_changes_only_samples_above_the_knee(self):
        """The limiter is the one part of the path that is not transparent."""
        signal = _vowel_to_the_end(1.2, peak=0.99)
        out = anonymise(signal, SR, alpha=1.0, force_resynthesis=True)
        below = np.abs(signal) <= LIMITER_KNEE - 1e-4
        above = np.abs(signal) > LIMITER_KNEE + 1e-4
        assert np.any(above)
        assert np.max(np.abs(out[below] - signal[below])) < 1e-6
        assert np.all(np.abs(out[above]) < np.abs(signal[above]))
        assert np.all(np.abs(out[above]) > LIMITER_KNEE)


class TestWavRoundTrip:
    def test_a_waveform_survives_a_write_and_read(self, tmp_path):
        signal = _voiced(0.2)
        path = tmp_path / "a.wav"
        write_wav(path, signal, SR)
        back, rate = read_wav(path)
        assert rate == SR
        assert back.shape == signal.shape
        assert np.max(np.abs(back - signal)) < 1e-3   # 16-bit quantisation
