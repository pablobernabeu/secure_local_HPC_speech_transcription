#!/usr/bin/env python3
"""
Disguise a speaker's voice while leaving the words intelligible.

Masking removes names from the transcript, and ``audio_redaction`` silences
them in the recording. Neither touches the voice itself, and a voice is
biometric: a recording with every name bleeped can still be matched to the
person who produced it, which matters for any corpus that will be shared,
archived or deposited.

This module applies the McAdams transformation, the anonymisation baseline
of the VoicePrivacy Challenge (Tomashenko et al., Interspeech 2020;
Patino et al., 2021). The vocal-tract resonances that carry much of a
speaker's identity are estimated per frame by linear prediction, and each
resonance is moved by raising the angle of its pole to a power:

.. math:: \\phi' = \\phi^{\\alpha}

With :math:`\\alpha = 1` nothing moves. Below 1 the low resonances rise
and the high ones fall, and above 1 the reverse, warping the formant
pattern away from the speaker's own while leaving the excitation, and so
the pitch contour, timing and most of the intelligibility, in place.

Why this method rather than a neural voice conversion. It runs on a CPU
in about real time, needs no model download, and is deterministic, so an
anonymised corpus can be regenerated from the original exactly. It is
also a published baseline rather than an invention of this project, which
matters for a claim about privacy: the protection it offers is
characterised in the literature and is known to be partial.

**It is a disguise, not a guarantee.** The transformation is public and
invertible in principle by an attacker who knows :math:`\\alpha`, and
published evaluations show speaker verification systems still perform
above chance against it. Treat it as raising the cost of identification,
not as removing the possibility, and do not rely on it alone where the
consequences of re-identification are serious.

Usage::

    python -m voice_anonymisation --audio interview.wav \\
        --out interview_anon.wav --alpha 0.8
"""

from __future__ import annotations

import argparse
import sys
import wave
from pathlib import Path

import numpy as np

#: Default McAdams coefficient. The VoicePrivacy baseline uses 0.8, which
#: shifts formants audibly while keeping speech intelligible; values far
#: from 1 disguise more and degrade the words.
DEFAULT_ALPHA = 0.8
#: Analysis frame in seconds. Long enough for a stable linear-prediction
#: estimate, short enough that the vocal tract is roughly constant across it.
DEFAULT_FRAME_S = 0.020
#: Poles within this distance of the origin are passed through: their angle
#: is ill-defined, so there is no resonance to move. Poles near the unit
#: circle, the sharp resonances that can ring, are warped like any other.
_MIN_POLE_RADIUS = 1e-6
#: Output samples louder than this are compressed by :func:`_match_loudness`
#: and every quieter sample is left exactly alone. Public so the benchmark
#: can count how many samples a run pushed into the knee.
LIMITER_KNEE = 0.9
#: The smallest overlap-add weight a real sample may be divided by. Two
#: squared periodic Hann windows half a frame apart sum to
#: sin^4 + cos^4, which lies between 0.5 and 1, so once the signal is
#: padded by a whole frame at each end every real sample reaches at least
#: 0.5. The tolerance absorbs floating-point round-off at the minima.
_MIN_OVERLAP_WEIGHT = 0.5 - 1e-6


def lpc_order_for(sample_rate: int) -> int:
    """Return a linear-prediction order appropriate to *sample_rate*.

    The usual rule of thumb is two coefficients per kilohertz plus a
    small allowance, which gives roughly one pole pair per expected
    formant with a few spare for spectral tilt.
    """
    return int(sample_rate / 1000) + 2


def levinson_durbin(autocorrelation: np.ndarray, order: int) -> np.ndarray:
    """Solve the Yule-Walker equations for linear-prediction coefficients.

    Returns the polynomial ``[1, a1, ..., ap]`` such that filtering the
    signal by it yields the prediction residual. Implemented here rather
    than taken from ``librosa`` so the module needs only NumPy, matching
    the rest of the audio path.

    Falls back to the trivial all-pass polynomial when the recursion
    breaks down, which happens on a silent or constant frame where the
    autocorrelation is singular.
    """
    a = np.zeros(order + 1, dtype=np.float64)
    a[0] = 1.0
    error = float(autocorrelation[0])
    if error <= 0:
        return a

    for i in range(1, order + 1):
        acc = autocorrelation[i] + np.dot(a[1:i], autocorrelation[i - 1:0:-1])
        reflection = -acc / error
        if not np.isfinite(reflection) or abs(reflection) >= 1.0:
            # Outside the unit circle the recursion is unstable; keep what
            # has been solved so far rather than returning a filter that
            # would ring on synthesis.
            return a
        previous = a[1:i].copy()
        a[1:i] += reflection * previous[::-1]
        a[i] = reflection
        error *= (1.0 - reflection * reflection)
        if error <= 0:
            return a
    return a


def shift_poles(coefficients: np.ndarray, alpha: float) -> np.ndarray:
    """Warp the resonances of a linear-prediction filter by *alpha*.

    Each complex pole keeps its radius and has its angle raised to the
    power *alpha*. The radius is deliberately untouched: it sets the
    bandwidth of the resonance and, more importantly, its distance from
    the unit circle, so preserving it keeps a stable filter stable.

    Real poles carry no formant and are passed through. Poles are handled
    in conjugate pairs so the reconstructed polynomial stays real, which
    it must to filter a real signal without introducing an imaginary
    component.
    """
    if alpha == 1.0:
        return np.asarray(coefficients, dtype=np.float64)

    poles = np.roots(coefficients)
    if poles.size == 0:
        return np.asarray(coefficients, dtype=np.float64)

    shifted = []
    for pole in poles:
        radius = abs(pole)
        angle = np.angle(pole)
        if radius < _MIN_POLE_RADIUS or abs(angle) < 1e-12 or abs(abs(angle) - np.pi) < 1e-12:
            shifted.append(pole)          # real pole: no formant to move
            continue
        new_angle = np.sign(angle) * (abs(angle) ** alpha)
        shifted.append(radius * np.exp(1j * new_angle))

    rebuilt = np.poly(np.asarray(shifted))
    return np.real(rebuilt)


def anonymise(audio: np.ndarray, sample_rate: int,
              alpha: float = DEFAULT_ALPHA,
              frame_s: float = DEFAULT_FRAME_S,
              order: int | None = None,
              force_resynthesis: bool = False) -> np.ndarray:
    """Return *audio* with its formant pattern warped by *alpha*.

    The signal is processed in half-overlapping Hann-windowed frames. For
    each frame the linear-prediction filter is estimated, the residual is
    obtained by inverse filtering, the filter's poles are shifted, and the
    residual is passed through the shifted filter. Each processed frame is
    windowed again and overlap-added, and the sum is divided by the summed
    squared windows. That weight is not constant: at fifty per cent hop it
    runs between 0.5 and 1 (sin^4 + cos^4). Dividing by it is what makes an
    unmodified frame reconstruct the input exactly.

    The signal is padded with a whole frame of zeros at each end before
    framing and trimmed afterwards, so every real sample lies under two
    frames and is divided by a weight of at least 0.5. Without the padding
    the last half-frame lay under one window only, whose square falls to
    about 1.5e-7 two samples from the end, and the filter's ringing there
    was divided by it: a clip voiced up to its last sample came back with a
    full-scale click, and the loudness match below then turned the rest of
    the file down by up to 16 dB to pay for it (audit finding EPRIV-02).
    The loudness gain is set from the fully overlapped samples only, which
    after the padding is every sample of the input.

    Frames too quiet to estimate a filter from are copied through
    unchanged, since inventing resonances for silence would add noise
    where the recording has none.

    An *alpha* of one returns the input untouched, which is what
    production wants: there is no reason to resynthesise a signal that is
    not being warped. *force_resynthesis* runs the full analysis-synthesis
    path at any alpha instead. At alpha one that path is, since the
    loudness fix in 5f1a3ea, the identity up to floating-point round-off:
    the poles are not moved, the synthesis filter inverts the analysis
    filter exactly, overlap-add restores the frame, and the loudness match
    has unit gain, so only samples above the :data:`LIMITER_KNEE` of
    :func:`_match_loudness` could change. (When 359624a introduced the
    option the path was not transparent, because the gain was then set by
    the peak.) The benchmark keeps the control as a regression check on
    that path: its word error rate should equal the original's, and a
    difference means the analysis-synthesis path has started to alter the
    signal.

    Parameters
    ----------
    audio, sample_rate:
        Mono waveform and its rate in Hz.
    alpha:
        McAdams coefficient; 1 moves nothing.
    frame_s:
        Analysis frame length in seconds; frames overlap by half.
    order:
        Linear-prediction order; defaults to :func:`lpc_order_for`.
    force_resynthesis:
        Run the full path even at alpha one (see above).

    Returns a float32 copy the length of *audio*. Deterministic; no RNG.
    Input shorter than a frame is processed too, since the padding gives
    it whole frames to be analysed in.
    """
    from scipy.signal import lfilter

    signal = np.asarray(audio, dtype=np.float64).reshape(-1)
    if signal.size == 0 or (alpha == 1.0 and not force_resynthesis):
        return np.asarray(audio, dtype=np.float32).reshape(-1).copy()

    frame = max(16, int(round(frame_s * sample_rate)))
    if order is None:
        order = lpc_order_for(sample_rate)
    order = max(2, min(order, frame - 2))

    window = _window(frame)
    # A whole frame is two hops, so padding by it keeps the frame grid
    # aligned with the input while putting every real sample under two
    # windows (see the docstring). Zeros rather than a reflection: an
    # all-zero frame is passed through untouched, and the filter's ringing
    # past the last real sample lands in padding that is trimmed off.
    pad = frame
    padded = np.concatenate([np.zeros(pad), signal, np.zeros(pad)])
    output = np.zeros(padded.size, dtype=np.float64)

    for start in _frame_starts(signal.size, frame):
        block = padded[start:start + frame]
        windowed = block * window

        if not np.any(windowed):
            processed = windowed
        else:
            autocorrelation = np.correlate(windowed, windowed, mode="full")
            autocorrelation = autocorrelation[windowed.size - 1:][:order + 1]
            if autocorrelation.size < order + 1 or autocorrelation[0] <= 0:
                processed = windowed
            else:
                a = levinson_durbin(autocorrelation, order)
                shifted = shift_poles(a, alpha)
                if shifted.size < 2 or not np.all(np.isfinite(shifted)):
                    processed = windowed
                else:
                    residual = lfilter(a, [1.0], windowed)
                    processed = lfilter([1.0], shifted, residual)
                    if not np.all(np.isfinite(processed)):
                        processed = windowed

        output[start:start + frame] += processed * window

    output = output[pad:pad + signal.size]
    weight = overlap_weight(signal.size, frame)
    # After the padding every real sample should be fully overlapped. The
    # check stays so that a change to the frame geometry cannot bring the
    # near-zero divisor back silently: a sample below the floor is copied
    # from the input instead of being divided, and is left out of the gain.
    full = weight >= _MIN_OVERLAP_WEIGHT
    result = signal.copy()
    result[full] = output[full] / weight[full]

    return _match_loudness(result, signal, mask=full).astype(np.float32)


def _window(frame: int) -> np.ndarray:
    """Return the periodic Hann window of *frame* samples used throughout."""
    return np.hanning(frame + 1)[:frame]


def _frame_starts(n_samples: int, frame: int) -> range:
    """Return the frame offsets into a signal padded by *frame* at each end.

    The hop is half a frame, and the last offset is the last one whose
    frame fits inside the padded signal, so the final real sample is
    always covered by two frames.
    """
    return range(0, n_samples + frame + 1, frame // 2)


def overlap_weight(n_samples: int, frame: int) -> np.ndarray:
    """Return the overlap-add divisor :func:`anonymise` applies per sample.

    Built from the same framing as :func:`anonymise` (a one-frame zero pad
    at each end, a hop of half a frame, a periodic Hann window applied at
    analysis and again at synthesis): the summed squared windows over the
    *n_samples* real samples. Public so the property the padding exists
    for, that no real sample is divided by less than 0.5, can be checked
    for any length.

    Parameters
    ----------
    n_samples:
        Length of the input signal.
    frame:
        Frame length in samples, as :func:`anonymise` derives it.

    Returns
    -------
    numpy.ndarray
        Float64 array of length *n_samples*. Pure; no side effects.
    """
    window = _window(frame)
    weight = np.zeros(n_samples + 2 * frame, dtype=np.float64)
    for start in _frame_starts(n_samples, frame):
        weight[start:start + frame] += window * window
    return weight[frame:frame + n_samples]


def _match_loudness(result: np.ndarray, reference: np.ndarray,
                    mask: np.ndarray | None = None) -> np.ndarray:
    """Restore the reference's loudness, then clip the rare transient.

    The synthesis filter rings at frame boundaries and throws occasional
    large samples. Dividing the whole signal by its peak, as this function
    first did, lets one such sample set the gain for the entire file: at a
    realistic input peak of 0.9 the output came back twenty times quieter,
    and quiet audio makes the recogniser hallucinate less on silence, so
    an anonymised condition appeared to transcribe *better* than the
    original. The loudness change, not the formant warping, was doing the
    work.

    Matching the root-mean-square instead sets the gain from the whole
    signal rather than from its worst sample. Any transient that still
    exceeds full scale is clipped, which distorts a handful of samples
    rather than attenuating every one of them.

    Parameters
    ----------
    result:
        The resynthesised signal, float64.
    reference:
        The input it should match in loudness, the same length.
    mask:
        Optional boolean array selecting the samples the gain is computed
        over (the fully overlapped ones, see :func:`anonymise`). The gain
        is still applied to every sample. ``None`` uses all of them.

    Returns the rescaled and knee-limited signal, float64 in [-1, 1].
    Pure; *result* is not modified in place.
    """
    if result.size == 0:
        return result
    if mask is None or not np.any(mask):
        mask = np.ones(result.size, dtype=bool)
    reference_rms = float(np.sqrt(np.mean(np.square(reference[mask]))))
    result_rms = float(np.sqrt(np.mean(np.square(result[mask]))))
    if result_rms > 0 and reference_rms > 0:
        result = result * (reference_rms / result_rms)
    else:
        result = result.copy()

    # Hard clipping at full scale removes enough energy to undo the match
    # it was meant to protect: at one setting the signal came back half as
    # loud again. Samples below the knee are therefore left exactly alone,
    # and only those above it are compressed, so the transient is tamed
    # without the rest of the waveform paying for it.
    knee = LIMITER_KNEE
    magnitude = np.abs(result)
    loud = magnitude > knee
    if np.any(loud):
        excess = (magnitude[loud] - knee) / (1.0 - knee)
        result[loud] = (np.sign(result[loud])
                        * (knee + (1.0 - knee) * np.tanh(excess)))
    return np.clip(result, -1.0, 1.0)


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

# The WAV reader, writer and loader are shared with audio_redaction, which
# held an identical copy. One copy means one error contract: the library
# functions raise ValueError or ImportError, and only main() turns that into
# an exit message. read_wav, write_wav and _load_audio stay importable from
# here for existing callers.
from audio_redaction import load_audio as _load_audio  # noqa: E402
from audio_redaction import read_wav, write_wav  # noqa: E402,F401


def main(argv=None) -> int:
    """Anonymise ``--audio`` at ``--alpha`` and write ``--out``.

    Returns 0 on success and 2 when the input is missing or cannot be read.
    Side effects: reads the input audio, writes the output WAV (creating
    its directory) and prints a short report. Deterministic; uses no RNG.
    """
    parser = argparse.ArgumentParser(
        prog="voice_anonymisation",
        description="Disguise a speaker's voice by warping the formant "
                    "pattern, leaving the words intelligible.")
    parser.add_argument("--audio", type=Path, required=True,
                        help="input audio (WAV natively; others need librosa)")
    parser.add_argument("--out", type=Path, required=True,
                        help="output WAV path")
    parser.add_argument("--alpha", type=float, default=DEFAULT_ALPHA,
                        help="McAdams coefficient; 1.0 is a no-op, further "
                             "from 1 disguises more and degrades the words "
                             "more (default: %(default)s)")
    parser.add_argument("--frame-ms", type=float,
                        default=DEFAULT_FRAME_S * 1000,
                        help="analysis frame in milliseconds "
                             "(default: %(default)s)")
    args = parser.parse_args(argv)

    if not args.audio.exists():
        print(f"  no such audio: {args.audio}", file=sys.stderr)
        return 2

    try:
        audio, sample_rate = _load_audio(args.audio)
    except (OSError, ValueError, ImportError, wave.Error) as exc:
        print(f"  could not read {args.audio}: {exc}", file=sys.stderr)
        return 2
    print(f"  read {args.audio}  ({audio.size / sample_rate:.1f} s @ "
          f"{sample_rate} Hz)")
    if args.alpha == 1.0:
        print("  alpha is 1.0, which is a no-op; nothing will be disguised")

    anonymised = anonymise(audio, sample_rate, alpha=args.alpha,
                           frame_s=args.frame_ms / 1000.0)
    write_wav(args.out, anonymised, sample_rate)
    print(f"  wrote {args.out}  (alpha={args.alpha})")
    print("  This is a disguise, not a guarantee: the transformation is "
          "public,\n  and speaker verification still performs above chance "
          "against it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
