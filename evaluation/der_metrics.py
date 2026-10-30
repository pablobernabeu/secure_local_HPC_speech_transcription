#!/usr/bin/env python3
"""
Pure helper functions for diarisation error rate (DER) computation.

These helpers carry no dependency on audio processing, transcription models,
or the HuggingFace datasets library.  The only external dependencies are
``pyannote.core`` and ``pyannote.metrics``, which are part of the
``pyannote.audio`` installation already required by the main pipeline.

Functions
---------
annotation_from_segments(segments, uri='meeting')
    Build a :class:`pyannote.core.Annotation` from a list of segment dicts.

compute_der(reference, hypothesis, collar=0.25, skip_overlap=False)
    Compute diarisation error rate and its three components for one meeting.

aggregate_der(results)
    Aggregate a list of per-meeting DER result dicts into corpus totals.

The scoring collar
------------------
Every figure is scored with ``collar=0.25`` in the pyannote.metrics
convention, where the collar is the *total* width of the unscored region
centred on each reference boundary: pyannote.metrics 3.2.1 builds
``Segment(t - .5 * collar, t + .5 * collar)`` around every boundary ``t``
(``utils.UEMSupportMixin.extrude``). A 0.25 s collar here therefore leaves
±0.125 s unscored, which is ``md-eval -c 0.125``. It is not the NIST Rich
Transcription ``-c 0.25`` convention (±0.25 s, ``collar=0.5`` here), and
the pyannote/speaker-diarization-3.1 model card reports collar-free DER, so
neither is directly comparable with these figures.

Two turns on one span
---------------------
:func:`annotation_from_segments` gives every turn its own track. Until
this was fixed (2bb4224) it stored every turn on pyannote's default track
``'_'``, so a second speaker whose turn had exactly the same start and
end as another's replaced it. The AMI timeline caches behind the
committed results hold one such pair per split: test EN2002c at
543.24-543.55 s (MEE071, MEE073) and validation IB4002 at
1405.10-1406.34 s (FIO093, MIO091). The hypothesis side went through the
same function. The hypotheses were not saved, so how often pyannote
emitted two speakers on an identical span is unknown, but the re-run
described below moved no meeting other than these two.

The bound on the August test figures (reference side), which ARC job
8534772 scored before the fix. Adding one reference turn of scored
duration ``d`` changes missed speech, false alarm, confusion and scored
reference time ``T`` by at most ``d`` each (the optimal speaker
mapping's cost moves by at most ``d`` too), so a meeting's DER moves by
at most ``d * (1 + DER) / T``. For EN2002c, ``d`` is 0.31 s (only 0.06 s
lies outside the collars, since both boundaries are shared with the
retained turn), DER was 0.197622, and ``T`` is at least its 2614.65 s of
speech less the collars round its at most 2 x 1469 boundaries (734.5 s),
so at least 1880 s. EN2002c's DER could therefore move by at most 2.0e-4
(0.02 percentage points); the macro test DER, the mean of 16 meetings, by
at most 1.3e-5; and the micro test DER, over 25,533 s of scored
reference time, by at most ``0.31 * (1 + 0.1662) / 25533 = 1.5e-5``. The
printed 16.6 per cent is unaffected at one decimal. The August validation
sweeps (der_sweep*.csv) were affected on IB4002 alone in the same way,
with ``d`` 1.24 s (0.99 s scored).

The committed figures come from the re-run at 9cb43e3 (ARC jobs 8976354
to 8976358 and 8976362, 2026-10-04), which measured these moves against
the August files. EN2002c gained 0.06 s of scored reference time, and its
DER moved by 5e-6, from 0.197622 to 0.197617. The macro and micro test
DER moved by at most 2.8e-7 and 5.9e-7 across the shipped, oracle and
tuned runs, well inside the bounds above. IB4002's DER moved by at most
3.7e-4 in a sweep cell, and every other meeting of every run is unchanged
at six decimals.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

#: Scoring collar in seconds, pyannote.metrics convention: the total width
#: of the unscored region centred on each reference boundary, so 0.25 means
#: ±0.125 s (``md-eval -c 0.125``; see the module docstring). The one
#: definition every DER entry point imports, so that development sweeps and
#: test-split reports cannot be scored under different collars.
DEFAULT_COLLAR_S = 0.25
#: How the collar value is to be read, written beside ``collar_s`` in every
#: DER summary so that the number cannot be mistaken for the NIST
#: half-width.
COLLAR_CONVENTION = ("pyannote.metrics total width, centred on each "
                     "reference boundary: collar_s/2 either side")


def annotation_from_segments(
    segments: Sequence[dict],
    uri: str = "meeting",
):
    """Return a ``pyannote.core.Annotation`` built from *segments*.

    Parameters
    ----------
    segments:
        Iterable of dicts, each with keys ``start`` (float, seconds),
        ``end`` (float, seconds) and ``speaker`` (str).  Segments may
        overlap, and two speakers may share exactly the same span.
        Segments with ``end <= start`` are skipped.
    uri:
        Uniform resource identifier used to identify the recording in
        pyannote metric reports.  Defaults to ``'meeting'``.

    Returns
    -------
    pyannote.core.Annotation
        One track per distinct ``(start, end, speaker)`` turn.

    Notes
    -----
    Each turn is stored on its own track. ``annotation[segment] = label``
    means ``annotation[segment, '_'] = label`` in pyannote.core 5.0, so a
    second speaker on an identical span used to overwrite the first
    (EDER-02; see the module docstring for the committed turns it hit).
    An exact repeat of a turn by the same speaker is kept once: on its own
    track pyannote.metrics would count that speaker twice over the span,
    whereas the shared track used to collapse it.
    """
    from pyannote.core import Annotation, Segment

    ann = Annotation(uri=uri)
    seen: set[tuple[float, float, str]] = set()
    for seg in segments:
        start = float(seg["start"])
        end = float(seg["end"])
        speaker = str(seg["speaker"])
        if end > start and (start, end, speaker) not in seen:
            ann[Segment(start, end), len(seen)] = speaker
            seen.add((start, end, speaker))
    return ann


def compute_der(
    reference,
    hypothesis,
    collar: float = DEFAULT_COLLAR_S,
    skip_overlap: bool = False,
) -> dict:
    """Compute the diarisation error rate for one meeting.

    Parameters
    ----------
    reference:
        Ground-truth ``pyannote.core.Annotation``.
    hypothesis:
        System output ``pyannote.core.Annotation``.
    collar:
        Total width, in seconds, of the unscored region centred on each
        reference boundary (pyannote.metrics convention): 0.25 leaves
        ±0.125 s unscored, which is ``md-eval -c 0.125``. The NIST RT
        ±0.25 s collar would be 0.5 here.
    skip_overlap:
        When ``True``, segments where two or more speakers are active
        simultaneously are excluded from both the numerator and denominator.
        Defaults to ``False`` (overlap regions are scored as speaker
        confusion).

    Returns
    -------
    dict
        Keys: ``'uri'``, ``'der'``, ``'missed_speech'``,
        ``'false_alarm'``, ``'speaker_confusion'``,
        ``'total_ref_duration'`` (scored reference time in seconds,
        speaker-weighted and collar-excluded), and the absolute component
        durations ``'_missed_abs'``, ``'_fa_abs'``, ``'_confusion_abs'``.
        All rates are fractions in [0, ∞).
    """
    from pyannote.metrics.diarization import DiarizationErrorRate

    metric = DiarizationErrorRate(
        collar=collar,
        skip_overlap=skip_overlap,
    )
    components = metric.compute_components(reference, hypothesis)
    return rates_from_components(components, uri=reference.uri or "")


#: The pyannote.metrics component names this module maps, in the order
#: missed speech, false alarm, speaker confusion, scored reference time.
_COMPONENT_KEYS = ("missed detection", "false alarm", "confusion", "total")


def rates_from_components(components, uri: str = "") -> dict:
    """Turn pyannote.metrics DER components into the result dict.

    Separated from :func:`compute_der` so the mapping from pyannote's
    component names to this project's keys can be tested without
    pyannote. A missing component raises instead of defaulting to zero: a
    renamed key in a pyannote.metrics upgrade would otherwise zero that
    component, and the swap of two keys would pass unnoticed.

    Parameters
    ----------
    components:
        Mapping with at least ``'missed detection'``, ``'false alarm'``,
        ``'confusion'`` and ``'total'`` (seconds).
    uri:
        Recording identifier copied into the result.

    Returns
    -------
    dict
        As documented in :func:`compute_der`.

    Raises
    ------
    KeyError
        When any of the four components is absent.
    """
    missing = [k for k in _COMPONENT_KEYS if k not in components]
    if missing:
        raise KeyError(
            f"pyannote.metrics returned no {missing} component(s) (it gave "
            f"{sorted(components)}); the DER decomposition cannot be mapped.")
    total = components["total"]
    missed = components["missed detection"]
    fa = components["false alarm"]
    confusion = components["confusion"]

    der = (missed + fa + confusion) / total if total > 0 else 0.0

    return {
        "uri": uri,
        "der": float(der),
        "missed_speech": float(missed / total) if total else 0.0,
        "false_alarm": float(fa / total) if total else 0.0,
        "speaker_confusion": float(confusion / total) if total else 0.0,
        "total_ref_duration": float(total),
        # Absolute component durations for re-aggregation.
        "_missed_abs": float(missed),
        "_fa_abs": float(fa),
        "_confusion_abs": float(confusion),
    }


def aggregate_der(results: Iterable[dict]) -> dict:
    """Aggregate per-meeting DER results into corpus-level totals.

    Two aggregates are returned, matching the convention used for WER
    reporting in the rest of this project. The macro rates are the
    unweighted mean of the per-meeting rates, so every meeting counts
    equally whatever its length. The micro DER pools error time over
    pooled scored reference time, so long meetings weigh more.

    ``total_ref_duration`` is pyannote's ``total``: scored reference time,
    counted once per active speaker (two overlapping speakers count
    twice) and with the collar regions removed. It is therefore not the
    corpus's speech duration, which counts overlapped time once.

    An empty input returns zeros. That is a sentinel, not a score, and
    the benchmark and sweep refuse to report a run that scored nothing.

    Parameters
    ----------
    results:
        Iterable of dicts as returned by :func:`compute_der`.

    Returns
    -------
    dict
        Keys: ``'n_meetings'``, ``'total_ref_duration'``,
        ``'macro_der'``, ``'micro_der'``,
        ``'macro_missed'``, ``'macro_fa'``, ``'macro_confusion'``.
    """
    rows = list(results)
    if not rows:
        return {
            "n_meetings": 0,
            "total_ref_duration": 0.0,
            "macro_der": 0.0,
            "micro_der": 0.0,
            "macro_missed": 0.0,
            "macro_fa": 0.0,
            "macro_confusion": 0.0,
        }

    n = len(rows)
    macro_der = sum(r["der"] for r in rows) / n
    macro_missed = sum(r["missed_speech"] for r in rows) / n
    macro_fa = sum(r["false_alarm"] for r in rows) / n
    macro_confusion = sum(r["speaker_confusion"] for r in rows) / n

    total_duration = sum(r["total_ref_duration"] for r in rows)
    total_missed = sum(r["_missed_abs"] for r in rows)
    total_fa = sum(r["_fa_abs"] for r in rows)
    total_confusion = sum(r["_confusion_abs"] for r in rows)
    micro_der = ((total_missed + total_fa + total_confusion) / total_duration
                 if total_duration else 0.0)

    return {
        "n_meetings": n,
        "total_ref_duration": float(total_duration),
        "macro_der": float(macro_der),
        "micro_der": float(micro_der),
        "macro_missed": float(macro_missed),
        "macro_fa": float(macro_fa),
        "macro_confusion": float(macro_confusion),
    }
