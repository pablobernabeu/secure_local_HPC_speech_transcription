#!/usr/bin/env python3
"""
Pure helper functions for segment-level timestamp accuracy measurement.

No dependency on audio processing, transcription models, or the HuggingFace
datasets library.  Depends only on the Python standard library.

Functions
---------
boundary_error(hyp_start, hyp_end, ref_duration)
    Return the signed and absolute start and end boundary errors in seconds
    for one utterance, given the hypothesis timestamps and the known
    reference duration.

aggregate_boundary_errors(records)
    Aggregate per-utterance error dicts into a summary with MAE and RMSE.

Notes on interpretation
-----------------------
Each AMI IHM audio row is cut at its annotated segment, so the reference
boundaries are 0.0 s and the clip's duration. The annotated end can include
trailing non-speech, so the reference end is the end of the clip, not a
measured end of speech. The start-boundary MAE therefore captures how far
Whisper's first timestamp lies from the clip start, and the end-boundary MAE
how far its last timestamp lies from the clip end.

A positive start error means Whisper's first timestamp is after 0.0; a
negative start error means it is before 0.0 (which cannot happen physically
and indicates a clipping artefact in the audio or a timestamp-offset bug).
A positive end error means Whisper's last timestamp ends before the clip
does, which need not mean that words were left out (see
:func:`aggregate_boundary_errors`); a negative end error means it extends
beyond the audio duration (a clipping or hallucination indicator).
"""

from __future__ import annotations

import math
from collections.abc import Iterable


# A boundary error beyond this is counted as gross: half a second is far
# more than a calibration difference between Whisper's timestamp tokens and
# the annotation. It is a statement about where the timestamp falls, not
# about the words: most clips with a gross end error on the committed run
# lost none (see aggregate_boundary_errors). Used for the tail rate and for
# the truncation rate that names its direction.
GROSS_ERROR_S = 0.5

#: The metrics :func:`aggregate_boundary_errors` reports beside ``n``.
_METRIC_KEYS = (
    "mae_start", "mae_end", "mae_total", "rmse_start", "rmse_end",
    "mean_start_error", "mean_end_error", "median_abs_end_error",
    "p90_abs_end_error", "gross_end_error_rate", "truncation_rate",
)


def _percentile(sorted_values, fraction: float) -> float | None:
    """Return the *fraction* quantile of an already-sorted sequence.

    The estimator is the observation nearest the linear-interpolation
    position: index ``round((n - 1) * fraction)``, with Python's
    round-half-to-even breaking ties, which is numpy's
    ``percentile(..., method="nearest")``. The result is therefore always
    an observed value rather than an interpolation between two of them;
    with a heavy tail an interpolated quantile invites reading a value that
    no utterance actually had.

    It is not the textbook nearest-rank estimator (the ``ceil(n *
    fraction)``-th value). On even-length input the median is the upper or
    the lower middle value depending on where the half falls (``[1, 2, 3,
    4]`` gives 3, ``[1, 2, 3, 4, 5, 6]`` gives 3), and for the committed
    499 end errors the 90th percentile is the 449th value, one rank below
    nearest-rank's 450th (0.15 s against 0.16 s). The estimator is kept
    because the published table reports its value (ESTATS-16).

    Returns ``None`` for an empty sequence, which has no quantile.
    """
    if not sorted_values:
        return None
    index = int(round(fraction * (len(sorted_values) - 1)))
    return sorted_values[max(0, min(index, len(sorted_values) - 1))]


def boundary_error(
    hyp_start: float,
    hyp_end: float,
    ref_duration: float,
) -> dict:
    """Return boundary errors for one utterance.

    Parameters
    ----------
    hyp_start:
        Predicted start of speech in seconds relative to the audio clip
        (should be near 0.0 for a correctly trimmed utterance).
    hyp_end:
        Predicted end of speech in seconds relative to the audio clip.
    ref_duration:
        Known duration of the audio clip in seconds (= end_time - begin_time
        from the AMI annotation).

    Returns
    -------
    dict
        Keys:
        ``'start_error'`` — ``hyp_start - 0.0`` (positive = late start).
        ``'end_error'``   — ``ref_duration - hyp_end`` (positive = the last
        timestamp ends before the clip does).
        ``'abs_start_error'``, ``'abs_end_error'``, ``'abs_total_error'``.
    """
    start_error = float(hyp_start)           # ref_start is always 0.0
    end_error = float(ref_duration - hyp_end)  # positive if it ends before the clip
    return {
        "start_error": start_error,
        "end_error": end_error,
        "abs_start_error": abs(start_error),
        "abs_end_error": abs(end_error),
        "abs_total_error": abs(start_error) + abs(end_error),
    }


def aggregate_boundary_errors(records: Iterable[dict]) -> dict:
    """Aggregate per-utterance boundary error dicts into corpus-level totals.

    Parameters
    ----------
    records:
        Iterable of dicts as returned by :func:`boundary_error`, each
        optionally supplemented with ``'audio_id'`` for traceability.

    Returns
    -------
    dict
        The means and root-mean-squares (``'mae_start'``, ``'mae_end'``,
        ``'mae_total'``, ``'rmse_start'``, ``'rmse_end'``,
        ``'mean_start_error'``, ``'mean_end_error'``), and alongside them a
        robust summary: ``'median_abs_end_error'``, ``'p90_abs_end_error'``,
        ``'gross_end_error_rate'`` and ``'truncation_rate'``.

    Why both.  On the AMI IHM split the end-boundary error is not a
    systematic offset that a constant correction could remove; it is a
    small number of gross errors dragging an otherwise excellent mean.
    Half the utterances land within a few milliseconds of the reference
    while roughly one in twelve is out by more than half a second, and
    those few contribute the large majority of the mean absolute error.
    Reporting only a mean therefore describes neither the typical
    utterance nor the tail, so the median and the tail rate are reported
    next to it.

    ``'truncation_rate'`` is the share of utterances whose ``end_error``
    exceeds :data:`GROSS_ERROR_S`: Whisper's last predicted timestamp ends
    more than half a second before the clip does. It separates the gross
    end errors in that direction from a run-on past the clip end. The
    reference end is the annotated segment end, which can include trailing
    non-speech, so the rate measures where the last timestamp falls and not
    how many words were lost: most such clips contain every reference word.
    On the committed 499-utterance run, 41 utterances are counted. Joined on
    their ids to the whisper_norm WER report of the same model
    (``sweep_reports_postfix_ami``), which scores all 41, 32 of them have no
    deleted reference word, among them all 18 with a one-word reference.
    The name is historical: it was chosen when these errors were read as
    early truncation, the model ceasing to transcribe part-way, and it is
    kept because the committed ``timestamp_summary.json`` and the tests and
    tables that read it use it.

    With no records every metric is ``None`` (JSON ``null``) beside
    ``n = 0``: an error or a rate over no utterances is undefined, and a
    0.0 invented for that case would read as a perfect run, in the table
    as much as in the JSON. :mod:`evaluation.disfluency` follows the same
    rule, and :mod:`evaluation.benchmark_timestamps` also fails its run
    in that case (ESTATS-14).
    """
    rows = list(records)
    n = len(rows)
    if n == 0:
        return {"n": 0, **dict.fromkeys(_METRIC_KEYS)}

    mae_start = sum(r["abs_start_error"] for r in rows) / n
    mae_end = sum(r["abs_end_error"] for r in rows) / n
    mae_total = sum(r["abs_total_error"] for r in rows) / n
    rmse_start = math.sqrt(sum(r["start_error"] ** 2 for r in rows) / n)
    rmse_end = math.sqrt(sum(r["end_error"] ** 2 for r in rows) / n)
    mean_start = sum(r["start_error"] for r in rows) / n
    mean_end = sum(r["end_error"] for r in rows) / n

    abs_end = sorted(r["abs_end_error"] for r in rows)
    gross = sum(1 for x in abs_end if x > GROSS_ERROR_S)
    truncated = sum(1 for r in rows if r["end_error"] > GROSS_ERROR_S)

    return {
        "n": n,
        "mae_start": float(mae_start),
        "mae_end": float(mae_end),
        "mae_total": float(mae_total),
        "rmse_start": float(rmse_start),
        "rmse_end": float(rmse_end),
        "mean_start_error": float(mean_start),
        "mean_end_error": float(mean_end),
        "median_abs_end_error": float(_percentile(abs_end, 0.50)),
        "p90_abs_end_error": float(_percentile(abs_end, 0.90)),
        "gross_end_error_rate": float(gross / n),
        "truncation_rate": float(truncated / n),
    }
