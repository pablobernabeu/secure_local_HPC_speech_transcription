#!/usr/bin/env python3
"""
Measure what voice anonymisation costs and what it buys.

An anonymiser that does not anonymise is worse than none, because a
corpus gets shared on the strength of it. Shipping the transform is
therefore not the deliverable; the deliverable is the curve relating the
privacy it provides to the intelligibility it destroys, so that a
researcher can choose a coefficient with the trade-off in front of them.

Two questions, one per side of that trade.

**Does the voice stop being recognisable?** Speaker embeddings are
extracted for the original and the anonymised audio of each utterance,
and two things are reported. The self-similarity is the cosine between an
utterance and its own anonymised version, which says how far the voice
moved. The linkage rate is the sharper measure: for each anonymised
utterance, find its nearest neighbour among the *original* recordings of
the other utterances and ask whether that neighbour is the same speaker.
This is the attack a curious recipient would actually mount, having the
released audio and a set of known voices. Chance is the probability that
a candidate drawn at random from the same set shares the probe's speaker,
which is sum_s n_s(n_s - 1) / (n(n - 1)) over speakers with n_s
utterances each, and equals one over the number of speakers only when
they contribute equally. The ceiling is the rate the untransformed
recordings reach against each other, and an anonymiser that leaves the
linkage rate near it has done nothing whatever.

Within one AMI meeting each speaker wears one headset throughout, so a
nearest neighbour from the same meeting can match the channel instead of
the voice. The rate is therefore also reported with the candidates
restricted to other meetings, and to other meetings on a different
headset channel (see :data:`CANDIDATE_SETS`).

**Do the words survive?** The same utterances are transcribed before and
after, and the word error rate of each is scored against the corpus
reference. The difference is what the disguise costs the transcript.

Reporting only the first would flatter the method, and reporting only the
second would miss its purpose.

Usage::

    python -m evaluation.benchmark_anonymisation --output-dir output/evaluation

With no options this is the single-meeting configuration behind
``output/evaluation/anonymisation_single_meeting/``: the first 200 usable
utterances of the AMI IHM test split, which are the opening of its first
meeting, EN2002a, in start-time order, at alphas 0.5, 0.7, 0.8 and 0.9.
The committed main result, ``output/evaluation/anonymisation_summary.json``,
adds ``--limit 400 --per-meeting 25`` (``hpc/runs/anonymisation.env``). The
requested options, the git commit, the package versions and the pinned
model revisions are written into the summary, so a result can be traced to
the invocation that produced it, and so is the reason when the speaker
embeddings had to come from a fallback instead of the diarisation
pipeline.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from evaluation.ami_meetings import SAMPLE_RATE  # noqa: E402,F401
from voice_anonymisation import DEFAULT_FRAME_S, LIMITER_KNEE, anonymise  # noqa: E402

# The single-meeting configuration, committed in
# output/evaluation/anonymisation_single_meeting/ (n_utterances 200; by_alpha
# 0.5, 0.7, 0.8, 0.9; no per-meeting cap). The committed main result uses the
# same alphas with 400 utterances and a cap of 25 per meeting.
PUBLISHED_LIMIT = 200
PUBLISHED_ALPHAS = (0.5, 0.7, 0.8, 0.9)
DEFAULT_ASR_MODEL = "openai/whisper-large-v3"
#: The diarisation pipeline whose bundled speaker-embedding model the
#: benchmark reuses (see :func:`_load_embedder`). transcription.py holds
#: the same identifier as DEFAULT_DIARIZATION_MODEL.
DIARISATION_PIPELINE = "pyannote/speaker-diarization-3.1"
# Appended to the embedding source when it came from that pipeline, and
# read back to decide which repository's revision the summary records.
_VIA_PIPELINE = " (via the diarisation pipeline)"
_SPLIT = "test"

#: The candidate sets the linkage rate is reported over, and what each
#: holds for a probe utterance. ``all`` is the set every earlier summary
#: used, so its figures stay under the original flat keys.
CANDIDATE_SETS = {
    "all": "every other original recording",
    "within_meeting": "other original recordings from the probe's meeting",
    "cross_meeting": "original recordings from other meetings",
    "cross_meeting_cross_channel": (
        "original recordings from other meetings on a different headset "
        "channel"),
}

# AMI IHM utterance ids read AMI_<meeting>_<channel>_<speaker>_<begin>_<end>.
_AUDIO_ID = re.compile(r"^AMI_[^_]+_(H\d+)_")


# ---------------------------------------------------------------------------
# Metrics (pure, so they can be tested without a model)
# ---------------------------------------------------------------------------

def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine between two embeddings, zero when either has no magnitude."""
    a = np.asarray(a, dtype=np.float64).reshape(-1)
    b = np.asarray(b, dtype=np.float64).reshape(-1)
    denominator = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denominator) if denominator else 0.0


def _unit_rows(vectors) -> np.ndarray:
    """Stack embeddings as rows of unit length; a zero row stays zero.

    A zero row then has cosine 0 with everything, as in
    :func:`cosine_similarity`.
    """
    matrix = np.vstack([np.asarray(v, dtype=np.float64).reshape(-1)
                        for v in vectors])
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return np.divide(matrix, norms, out=np.zeros_like(matrix),
                     where=norms > 0)


def _codes(labels) -> np.ndarray:
    """Map hashable labels to integer codes so they compare elementwise."""
    index: dict = {}
    return np.array([index.setdefault(label, len(index)) for label in labels],
                    dtype=np.int64)


def linkage_rate(anonymised, originals, speakers, candidates=None) -> dict:
    """How often an anonymised utterance still points at its own speaker.

    *anonymised* and *originals* are sequences of embeddings in the same
    order, and *speakers* the speaker label of each. For every anonymised
    utterance the nearest original by cosine is found among its
    candidates. The utterance's own original recording is never a
    candidate, since matching a released clip to the very clip it came
    from is not the attack of interest: the question is whether the voice
    still identifies the person across different recordings.

    A probe whose speaker has no other recording among its candidates
    cannot be matched correctly by any method, so it is not a trial: it
    is excluded and counted in ``n_singleton_excluded``. Counting it would
    add a forced miss and make the transformation look more protective
    than it is (audit finding EPRIV-04).

    Chance is the probability that a candidate drawn uniformly at random
    from the probe's own candidate set shares its speaker, averaged over
    the trials actually scored. With every other recording as candidates
    and no singletons that is sum_s n_s(n_s - 1) / (n(n - 1)); it is one
    over the number of speakers only when every speaker contributes the
    same number of utterances, and with nine utterances from one speaker
    and one from another it is 0.89 where one over the speakers gives 0.5.

    Parameters
    ----------
    anonymised, originals:
        Embeddings, one per utterance, in the same order.
    speakers:
        Speaker label of each utterance.
    candidates:
        Optional ``n`` by ``n`` boolean array; ``candidates[i, j]`` lets
        original *j* be matched to anonymised *i*. The diagonal is always
        excluded. ``None`` allows every other recording. See
        :func:`linkage_by_candidate_set` for the restrictions reported.

    Returns
    -------
    dict
        ``linkage_rate`` and ``chance`` (``None`` without trials),
        ``trials``, ``distinct_speakers`` (over all utterances) and
        ``n_singleton_excluded``. Pure; no side effects.

    Raises
    ------
    ValueError
        When *candidates* is not ``n`` by ``n``.
    """
    labels = list(speakers)
    n = len(labels)
    distinct = len(set(labels))
    if n < 2:
        return {"linkage_rate": None, "trials": 0, "chance": None,
                "distinct_speakers": distinct, "n_singleton_excluded": n}

    similarity = _unit_rows(anonymised) @ _unit_rows(originals).T
    if candidates is None:
        allowed = np.ones((n, n), dtype=bool)
    else:
        allowed = np.array(candidates, dtype=bool)
        if allowed.shape != (n, n):
            raise ValueError(
                f"candidates must be {n} by {n}, got {allowed.shape}")
    np.fill_diagonal(allowed, False)   # the same recording, not a different one
    ids = _codes(labels)
    same = ids[:, None] == ids[None, :]

    correct = trials = excluded = 0
    chance_total = 0.0
    for i in range(n):
        pool = allowed[i]
        n_same = int(np.count_nonzero(pool & same[i]))
        if n_same == 0:
            excluded += 1
            continue
        # argmax takes the first of equal scores, as the pairwise loop this
        # replaced did with its strict comparison.
        best = int(np.argmax(np.where(pool, similarity[i], -np.inf)))
        trials += 1
        correct += int(same[i, best])
        chance_total += n_same / int(np.count_nonzero(pool))

    return {
        "linkage_rate": round(correct / trials, 4) if trials else None,
        "trials": trials,
        "chance": round(chance_total / trials, 4) if trials else None,
        "distinct_speakers": distinct,
        "n_singleton_excluded": excluded,
    }


def linkage_by_candidate_set(anonymised, originals, speakers, meetings=None,
                             channels=None) -> dict:
    """Return :func:`linkage_rate` for each set in :data:`CANDIDATE_SETS`.

    Within one AMI meeting a speaker keeps one headset channel, so the
    nearest other recording from the same meeting can be matched on the
    microphone's response and noise floor as much as on the voice (audit
    finding EPRIV-15). Restricting the candidates to other meetings asks
    for the same speaker in another session. Where a speaker also keeps
    the channel across sessions, as :func:`speaker_channel_check` finds
    for some AMI series, the channel-mismatched set removes that cue too.

    Parameters
    ----------
    anonymised, originals, speakers:
        As for :func:`linkage_rate`.
    meetings:
        Meeting id of each utterance, or ``None`` to report ``all`` only.
    channels:
        Headset channel of each utterance (``None`` where unknown), or
        ``None`` to omit the channel-mismatched set. An utterance with an
        unknown channel is never a channel-mismatched candidate.

    Returns
    -------
    dict
        ``{set name: linkage_rate(...) result}``. Pure; no side effects.
    """
    sets = {"all": None}
    if meetings is not None:
        m = _codes(meetings)
        same_meeting = m[:, None] == m[None, :]
        sets["within_meeting"] = same_meeting
        sets["cross_meeting"] = ~same_meeting
        if channels is not None:
            known = np.array([c is not None for c in channels])
            c = _codes(channels)
            other_channel = ((c[:, None] != c[None, :])
                             & known[:, None] & known[None, :])
            sets["cross_meeting_cross_channel"] = ~same_meeting & other_channel
    return {name: linkage_rate(anonymised, originals, speakers, mask)
            for name, mask in sets.items()}


def _flat_linkage(by_set: dict) -> dict:
    """Return the linkage fields a per-alpha summary carries.

    The ``all`` figures keep the flat keys every earlier summary used, so
    ``linkage_rate`` and ``chance`` keep their meaning. The within- and
    cross-meeting figures are added beside them under suffixed keys, and
    every set in full under ``linkage_by_candidates``.
    """
    flat = dict(by_set["all"])
    for name in ("within_meeting", "cross_meeting"):
        if name in by_set:
            flat[f"linkage_rate_{name}"] = by_set[name]["linkage_rate"]
            flat[f"chance_{name}"] = by_set[name]["chance"]
    flat["linkage_by_candidates"] = by_set
    return flat


def speaker_channel_check(speakers, meetings, channels) -> dict:
    """Say whether each speaker keeps one headset channel across meetings.

    The answer decides whether restricting linkage candidates to other
    meetings is enough to remove the channel as a cue (audit finding
    EPRIV-15). It is read from the sample itself, since the AMI metadata
    carries the channel with every utterance. In the committed
    400-utterance multi-meeting sample (job 8917989) the EN2002 speakers
    change channel from session to session, while the ES2004, IS1009 and
    TS3003 speakers keep theirs, so only the EN2002 speakers have a
    channel-mismatched candidate. A channel label names a recording channel
    only; whether the same physical headset stayed on it is not in the
    metadata.

    Parameters
    ----------
    speakers, meetings, channels:
        Per-utterance labels; a ``None`` channel is ignored.

    Returns
    -------
    dict
        ``speakers_in_several_meetings``, the sorted speaker lists
        ``keep_channel`` and ``change_channel`` (both drawn from speakers
        seen in several meetings), and ``channels``, mapping each speaker
        to ``{meeting: [channels]}``. Pure; no side effects.
    """
    by_speaker: dict = {}
    for speaker, meeting, channel in zip(speakers, meetings, channels,
                                         strict=True):
        seen = by_speaker.setdefault(speaker, {}).setdefault(meeting, set())
        if channel is not None:
            seen.add(channel)
    several = {s: m for s, m in by_speaker.items() if len(m) > 1}
    keep = sorted(s for s, m in several.items()
                  if len(set().union(*m.values())) == 1)
    return {
        "speakers_in_several_meetings": len(several),
        "keep_channel": keep,
        "change_channel": sorted(s for s in several if s not in keep),
        "channels": {s: {m: sorted(c) for m, c in sorted(ms.items())}
                     for s, ms in sorted(by_speaker.items())},
    }


def pooled_wer(results) -> float | None:
    """Corpus word error rate: total errors over total reference words.

    Averaging per-utterance rates is the wrong estimator here and gives a
    badly misleading answer. AMI utterances are short, many references are
    a single word, and a hallucinated thirty-word hypothesis against a
    one-word reference scores 30.0. A handful of those dominate a mean of
    rates, which is how a first run of this benchmark reported 358% error
    on unmodified audio.

    Pooling the alignment counts instead weights every reference word
    equally, which is the convention the rest of the project reports as
    micro-averaged word error rate.

    Pooling bounds the damage but does not remove it. Substitutions and
    deletions cannot exceed the reference length, so pooling really does
    stop a short utterance dominating through those. Insertions have no
    such ceiling: a 221-word hallucination against a one-word reference
    contributes 221 to the numerator and 1 to the denominator whichever
    way the average is taken. See :func:`degenerate_baselines`, which
    finds those utterances so that a comparison can be reported without
    them as well as with them.
    """
    results = [r for r in results if r is not None]
    if not results:
        return None
    errors = sum(r.substitutions + r.deletions + r.insertions for r in results)
    words = sum(r.reference_words for r in results)
    return round(errors / words, 4) if words else None


# A hypothesis this many times longer than its reference, and this many
# words long in absolute terms, is not a transcript with errors in it: it
# is the decoder having looped. Both conditions are required so that a
# two-word hypothesis against a one-word reference is not called a
# hallucination. The observed separation on AMI is wide enough that the
# exact values do not matter: the degenerate utterances scored 221.0 and
# the worst well-behaved one scored 4.0.
DEGENERATE_LENGTH_FACTOR = 5
DEGENERATE_LENGTH_FLOOR = 20


def degenerate_baselines(results) -> list:
    """Indices where the recogniser looped on the *unmodified* audio.

    An utterance the baseline recogniser hallucinated through carries an
    unbounded number of insertions, so it can supply most of the pooled
    error of a small corpus on its own. Whether a transformation happens
    to interrupt that loop is not a fact about intelligibility, and on
    the 200-utterance AMI subset used here it is the difference between a
    warped condition appearing to transcribe better than its own input
    and appearing, correctly, to transcribe worse.

    Only the baseline is screened, never the transformed condition. A
    transformation that provokes a hallucination has genuinely damaged
    the transcript, and excluding those utterances would hide exactly the
    cost this benchmark exists to measure.

    This is the single definition of the screen. The report CSV carries
    its result per utterance (``degenerate_baseline``) and the summary its
    thresholds (:func:`degenerate_baseline_criterion`), so that a reader
    of the report does not have to re-derive it (audit finding EPRIV-16).

    Returns the positions to drop, so that the same utterances can be
    dropped from both arms and the comparison stays paired.
    """
    degenerate = []
    for i, r in enumerate(results):
        if r is None:
            continue
        reference = getattr(r, "reference_words", 0)
        hypothesis = getattr(r, "hypothesis_words", None)
        if hypothesis is None:      # older records kept counts, not lengths
            hypothesis = reference + getattr(r, "insertions", 0) - getattr(r, "deletions", 0)
        if (hypothesis >= DEGENERATE_LENGTH_FLOOR
                and hypothesis > DEGENERATE_LENGTH_FACTOR * max(reference, 1)):
            degenerate.append(i)
    return degenerate


def degenerate_baseline_criterion(screened_arm: str | None = None) -> dict:
    """Describe the loop screen of :func:`degenerate_baselines`.

    Written into the summary so the thresholds travel with the result.

    Parameters
    ----------
    screened_arm:
        The arm the screen was applied to (see :func:`baseline_arm`).

    Returns
    -------
    dict
        The rule, its two thresholds, the arm and the report column that
        carries the per-utterance result. Pure; no side effects.
    """
    return {
        "rule": ("hypothesis_words >= length_floor and hypothesis_words > "
                 "length_factor * max(reference_words, 1)"),
        "hypothesis_words_fallback": (
            "reference_words + insertions - deletions, for records without "
            "a hypothesis length"),
        "length_factor": DEGENERATE_LENGTH_FACTOR,
        "length_floor": DEGENERATE_LENGTH_FLOOR,
        "screened_arm": screened_arm,
        "report_column": "degenerate_baseline",
    }


def baseline_arm(results_before, results_control=None):
    """Return ``(results, name)`` for the arm the cost is measured against.

    The resynthesis control when one is supplied and scored, otherwise the
    raw original. :func:`summarise` and the per-utterance flag in
    :func:`run` both take the arm from here, so they cannot screen
    different arms.
    """
    if results_control and pooled_wer(results_control) is not None:
        return list(results_control), "resynthesis control"
    return list(results_before), "raw original"


def _without(results, drop) -> list:
    """Return *results* without the positions in *drop*, order kept."""
    drop = set(drop)
    return [r for i, r in enumerate(results) if i not in drop]


def _rms(x) -> float:
    """Root-mean-square of *x*, zero for an empty array."""
    x = np.asarray(x, dtype=np.float64)
    return float(np.sqrt(np.mean(np.square(x)))) if x.size else 0.0


def level_ratio(originals, anonymised, edge: int = 0) -> float | None:
    """Loudness of the anonymised audio relative to the original.

    Verified rather than assumed. The transform once returned audio up to
    twenty times quieter, because one ringing sample set the gain for a
    whole file, and quiet audio makes the recogniser hallucinate less on
    silence. That alone moved the word error rate, so an anonymised
    condition appeared to transcribe better than the original. Any
    comparison of intelligibility is only meaningful while this stays
    near one.

    Parameters
    ----------
    originals, anonymised:
        Waveforms in the same order.
    edge:
        Samples dropped from each end of both signals first. A whole-file
        ratio includes any transient at the clip edges, which can hide an
        attenuated body (audit finding EPRIV-02); a positive *edge* gives
        the body-only ratio. Pairs left with no samples are skipped.

    Returns the mean per-utterance RMS ratio, or ``None`` when no pair has
    a non-silent original. Pure; no side effects.
    """
    pairs = []
    for o, a in zip(originals, anonymised, strict=True):
        o = np.asarray(o)
        a = np.asarray(a)
        if edge:
            if min(o.size, a.size) <= 2 * edge:
                continue
            o, a = o[edge:-edge], a[edge:-edge]
        pairs.append((_rms(o), _rms(a)))
    pairs = [(o, a) for o, a in pairs if o > 0]
    if not pairs:
        return None
    return round(float(np.mean([a / o for o, a in pairs])), 4)


def summarise(similarities, results_before, results_after, linkage,
              results_control=None, level=None) -> dict:
    """Combine the two sides of the trade-off into one record.

    The arguments are ``PairResult`` objects, or ``None`` for an utterance
    that could not be scored.

    *results_control* is the resynthesised-but-unwarped condition, and the
    cost is measured against it when it is supplied. The control was
    introduced (359624a) because resynthesis was then not transparent.
    Since the loudness fix (5f1a3ea) it is the identity up to the limiter
    knee (see :func:`voice_anonymisation.anonymise`), so its word error
    rate equals the original's, as in the committed summary, and it now
    serves as a regression check on the analysis-synthesis path rather
    than as a distinct baseline. Without the control the cost falls back
    to the raw original.

    Which arm is the baseline is recorded twice, under ``wer_cost_baseline``
    (the older key) and ``wer_baseline_name``. The guarded baseline is
    emitted as ``wer_baseline_guarded``, pooled over that arm. It is also
    emitted under its older name ``wer_original_guarded``, with the same
    value, so that summaries written before and after the rename compare
    directly (audit finding EPRIV-28). Despite that name it is the guarded
    *baseline*, which is the control whenever one is supplied; the raw
    original's rate is ``wer_original``, unguarded.

    Returns a flat dict of the WER, cost, degenerate-baseline and linkage
    fields. Pure; no side effects.

    Two costs come back. ``wer_cost`` pools every utterance, and
    ``wer_cost_guarded`` pools every utterance on which the baseline
    recogniser did not loop. The second is the one to report, and
    ``n_degenerate_baselines`` with
    ``degenerate_baseline_error_share`` are the evidence for preferring
    it; the first is kept so that the exclusion is visible rather than
    silent.
    """
    def _mean(values):
        values = [v for v in values if v is not None]
        return round(float(np.mean(values)), 4) if values else None

    before, after = pooled_wer(results_before), pooled_wer(results_after)
    control = pooled_wer(results_control) if results_control else None
    baseline_results, baseline_name = baseline_arm(results_before,
                                                   results_control)
    baseline = pooled_wer(baseline_results)

    # Utterances the baseline recogniser looped on are dropped from both
    # arms, and the comparison is reported a second time without them.
    # Warping a signal cannot make it easier to transcribe, so a negative
    # cost means something other than the warping is being measured; on
    # this corpus it is whether the warp happened to interrupt a
    # hallucination the baseline had fallen into. Both figures are
    # published, because the reader needs to see the anomaly and the
    # estimate that survives it.
    dropped = degenerate_baselines(baseline_results)
    if dropped:
        guarded_baseline = pooled_wer(_without(baseline_results, dropped))
        guarded_after = pooled_wer(_without(results_after, dropped))
        baseline_errors = sum(
            r.substitutions + r.deletions + r.insertions
            for r in baseline_results if r is not None)
        dropped_errors = sum(
            baseline_results[i].substitutions + baseline_results[i].deletions
            + baseline_results[i].insertions
            for i in dropped if baseline_results[i] is not None)
    else:
        guarded_baseline, guarded_after = baseline, after
        baseline_errors = dropped_errors = 0

    def _cost(hi, lo):
        return round(hi - lo, 4) if hi is not None and lo is not None else None

    suspect = (baseline is not None and after is not None and after < baseline)
    return {
        "n_utterances": len(similarities),
        "mean_self_similarity": _mean(similarities),
        "wer_original": before,
        "wer_resynthesis_control": control,
        "wer_anonymised": after,
        "wer_cost": _cost(after, baseline),
        "wer_cost_baseline": baseline_name,
        "wer_baseline_name": baseline_name,
        "wer_cost_sign_anomaly": suspect or None,
        # The estimate the paper reports, and the evidence for preferring it.
        "n_degenerate_baselines": len(dropped),
        "degenerate_baseline_error_share": (
            round(dropped_errors / baseline_errors, 4)
            if baseline_errors else None),
        "wer_baseline_guarded": guarded_baseline,
        # The older name for wer_baseline_guarded, same value (see above).
        "wer_original_guarded": guarded_baseline,
        "wer_anonymised_guarded": guarded_after,
        "wer_cost_guarded": _cost(guarded_after, guarded_baseline),
        "wer_averaging": "micro (pooled errors over pooled reference words)",
        "level_ratio": level,
        "level_matched": (None if level is None else bool(0.8 <= level <= 1.25)),
        **linkage,
    }


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------

def sample_by_meeting(grouped, limit, per_meeting, accept):
    """Accept utterances meeting by meeting, up to a cap and a total.

    *grouped* yields ``(meeting_id, rows)`` pairs in stream order, and
    *accept* is called as ``accept(meeting_id, row)`` on each row in turn,
    returning the item to keep or ``None`` when a filter rejects the row.
    Rows of a meeting are tried in the order *grouped* gives them until
    *per_meeting* have been accepted or the meeting runs out, and the walk
    stops as soon as *limit* items have been accepted. From
    :func:`evaluation.ami_meetings.group_rows_by_meeting`, as in
    :func:`_load_utterances`, that order is start time, so a meeting is
    sampled from its opening minutes.

    The cap counts accepted rows, not rows read. The version this replaced
    capped the rows read at twice *per_meeting* and then filled the budget
    in stream order, so one meeting could supply up to twice the cap while
    the summary recorded the cap as given: the 400-utterance run of job
    8781723, capped at 25, took up to 42 from one meeting and reached 13
    of the 16 test meetings (audit finding EPRIV-03). A meeting with fewer
    usable rows than the cap contributes what it has, and the shortfall is
    not made up elsewhere, so every meeting is held to the same cap.

    Why spread at all: the linkage test is only as strong as its
    candidate set, and reading the split from the front takes every
    utterance from whichever meeting streams first, which on AMI's test
    split is four speakers. Spreading the same budget over meetings buys
    speakers and sessions at no extra decoding cost.

    Parameters
    ----------
    grouped:
        Iterable of ``(meeting_id, rows)``.
    limit:
        Total to accept.
    per_meeting:
        Most to accept from one meeting, or ``None`` to read every
        meeting in order until *limit*. That is the configuration of the
        August runs, job 8556951 (the first committed result, 0c4055d)
        and its level-matched re-run, job 8573363 (472ac19), but not their
        sample: both took the rows in the order the dataset streams them,
        unsorted, and drew the same 200 utterances, only 36 of which are
        among the 200 this draws.
    accept:
        The filter and decoder, as described above.

    Returns
    -------
    (items, accepted_by_meeting)
        The accepted items in order, and ``{meeting_id: count}`` for every
        meeting reached, zero counts included.

    Raises
    ------
    ValueError
        When *per_meeting* is given and below one.
    """
    if per_meeting is not None and per_meeting < 1:
        raise ValueError(f"per_meeting must be at least 1, got {per_meeting}")
    items: list = []
    accepted: dict = {}
    if limit <= 0:
        return items, accepted
    for mid, rows in grouped:
        taken = 0
        for row in rows:
            if per_meeting is not None and taken >= per_meeting:
                break
            item = accept(mid, row)
            if item is None:
                continue
            items.append(item)
            taken += 1
            if len(items) >= limit:
                accepted[mid] = taken
                return items, accepted
        accepted[mid] = taken
    return items, accepted


def sampling_description(per_meeting: int | None) -> str:
    """Describe the sample :func:`_load_utterances` draws, for the summary.

    Both branches name the order within a meeting. Summaries written before
    this said "in stream order" for the uncapped sample, which was true of
    the meetings only (see :func:`sample_by_meeting`).

    Parameters
    ----------
    per_meeting:
        The cap on accepted utterances per meeting, or ``None``.

    Returns
    -------
    str
        One phrase. Pure; no side effects.
    """
    within = "each meeting read from its start, in start-time order"
    if per_meeting:
        return (f"meeting by meeting, at most {per_meeting} accepted per "
                f"meeting, {within}")
    return (f"first usable utterances of the split, meetings in stream order "
            f"and {within}")


def _channel_of(row) -> str | None:
    """Return the headset channel of an AMI row (``"H00"``), or ``None``.

    Read from the row's ``microphone_id`` when present, otherwise from its
    ``audio_id``, which in the IHM release reads
    ``AMI_<meeting>_<channel>_<speaker>_<begin>_<end>``.
    """
    channel = row.get("microphone_id")
    if channel:
        return str(channel)
    match = _AUDIO_ID.match(str(row.get("audio_id", "")))
    return match.group(1) if match else None


def _load_utterances(limit, hf_token, per_meeting=None, skipped=None):
    """Decode the chosen utterances, skipping any that cannot be embedded.

    Meetings are read in stream order and each is decoded row by row, in
    start-time order because
    :func:`evaluation.ami_meetings.group_rows_by_meeting` sorts a
    meeting's rows by ``begin_time``, until *per_meeting* rows pass the
    filters or it runs out (see :func:`sample_by_meeting`).

    Parameters
    ----------
    limit:
        Number of utterances to return, at most.
    hf_token:
        Hugging Face token for the gated AMI dataset.
    per_meeting:
        Cap on accepted utterances per meeting, or ``None``.
    skipped:
        Optional dict; when given, the counts of rows passed over are
        added to it under ``undecodable``, ``wrong_sample_rate`` and
        ``too_short``, so the summary can say what the sample excluded.

    Returns a list of dicts with ``uid``, ``speaker``, ``meeting``,
    ``channel``, ``audio`` and ``reference``; the per-meeting counts follow
    from ``meeting``. Side effects: streams the dataset over the network.
    """
    from evaluation.ami_meetings import group_rows_by_meeting  # noqa: PLC0415
    from evaluation.benchmark_der import _decode_audio_bytes, _stream_ami  # noqa: PLC0415
    if skipped is None:
        skipped = {}
    for key in ("undecodable", "wrong_sample_rate", "too_short"):
        skipped.setdefault(key, 0)

    def accept(mid, row):
        try:
            audio, sample_rate = _decode_audio_bytes(row["audio"])
        except Exception:  # noqa: BLE001
            skipped["undecodable"] += 1
            return None
        if sample_rate != SAMPLE_RATE:
            skipped["wrong_sample_rate"] += 1
            return None
        if len(audio) < SAMPLE_RATE:
            skipped["too_short"] += 1
            return None           # too short to embed a voice from
        return {"uid": row["audio_id"],
                "speaker": row["speaker_id"],
                "meeting": mid,
                "channel": _channel_of(row),
                "audio": np.asarray(audio, dtype=np.float32),
                "reference": row.get("text", "")}

    utterances, _ = sample_by_meeting(
        group_rows_by_meeting(_stream_ami(_SPLIT, hf_token)),
        limit, per_meeting, accept)
    return utterances


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------

def _git_commit() -> str | None:
    """Return the checked-out commit of this repository, or ``None``."""
    from provenance import git_commit

    return git_commit(_ROOT)[0]


# The token keyword and the revision spelling each loader takes are read
# from its signature (audit findings DEPS-10, DEPS-04); the helpers are
# shared with the DER benchmark and the fine-tuning script.
from evaluation.hub_loading import pinned_checkpoint as _pinned_checkpoint  # noqa: E402
from evaluation.hub_loading import token_kwargs as _token_kwargs  # noqa: E402


def _failure(exc: BaseException) -> str:
    """One line saying why a load failed: the exception's type and message."""
    return f"{type(exc).__name__}: {exc}"


def _load_embedder(hf_token, failures=None):
    """Return a callable mapping a waveform to a speaker embedding.

    The diarisation pipeline this workflow already depends on carries a
    speaker-embedding model inside it, so that one is preferred: it needs
    no licence the workflow has not already accepted, and it means the
    voice the benchmark measures is the voice the workflow's own
    diarisation would compare. ``pyannote/embedding`` is a separate gated
    repository, and reaching for it first made this job fail on a licence
    rather than on anything to do with anonymisation.

    Falls back to loading an embedding model directly, and finally says
    which conditions need accepting rather than dying on an
    ``AttributeError`` from deep inside the loader.

    *failures*, when given, receives the reason each source that was tried
    and not used failed, in the order tried: the diarisation pipeline under
    :data:`DIARISATION_PIPELINE`, then each fallback model under its name.
    :func:`run` writes them into the summary. The pipeline's reason used to
    go to stderr only, and the fallback models' nowhere, so a summary whose
    embeddings came from a fallback did not say that one had happened, or
    why.

    Returns ``(embed, source)``. Side effects: downloads or reads the
    pyannote models from the cache, uses a GPU when one is available, and
    prints each failure to stderr.
    """
    import torch
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    failures = {} if failures is None else failures
    embedder = None
    source = "unknown"
    try:
        from pyannote.audio import Pipeline
        checkpoint, pin = _pinned_checkpoint(Pipeline.from_pretrained,
                                             DIARISATION_PIPELINE)
        pipeline = Pipeline.from_pretrained(
            checkpoint, **pin,
            **_token_kwargs(Pipeline.from_pretrained, hf_token))
        if pipeline is None:
            # pyannote 3.x prints a notice and returns None, rather than
            # raising, for a gated model it cannot open.
            failures[DIARISATION_PIPELINE] = (
                "pyannote returned no pipeline (gated model: token missing "
                "or terms not accepted)")
        else:
            pipeline.to(device)
            embedder = getattr(pipeline, "_embedding", None)
            if embedder is None:
                failures[DIARISATION_PIPELINE] = (
                    "the loaded pipeline carries no embedding model (_embedding)")
            else:
                name = (getattr(embedder, "embedding", None)
                        or "speaker-diarization-3.1 bundled embedding")
                source = f"{name}{_VIA_PIPELINE}"
                print(f"  embeddings from {source}", flush=True)
    except Exception as exc:  # noqa: BLE001
        failures[DIARISATION_PIPELINE] = _failure(exc)
    if DIARISATION_PIPELINE in failures:
        print(f"  could not reuse the diarisation pipeline "
              f"({failures[DIARISATION_PIPELINE]})", file=sys.stderr)

    if embedder is None:
        from pyannote.audio.pipelines.speaker_verification import (
            PretrainedSpeakerEmbedding)
        token = _token_kwargs(PretrainedSpeakerEmbedding, hf_token)
        for name in ("pyannote/wespeaker-voxceleb-resnet34-LM",
                     "pyannote/embedding"):
            try:
                embedder = PretrainedSpeakerEmbedding(
                    name, device=device, **token)
                source = name
                print(f"  embeddings from {name}", flush=True)
                break
            except Exception as exc:  # noqa: BLE001
                embedder = None
                failures[name] = _failure(exc)
                print(f"  could not load {name} ({failures[name]})",
                      file=sys.stderr)

    if embedder is None:
        raise SystemExit(
            "No speaker-embedding model could be loaded. Every candidate is "
            "gated on the HuggingFace Hub, so accept the conditions for "
            "pyannote/speaker-diarization-3.1 (which carries one) or for "
            "pyannote/wespeaker-voxceleb-resnet34-LM, using the account whose "
            "token is in hf_token.txt. Each attempt failed with: "
            + "; ".join(f"{name}: {reason}" for name, reason in failures.items()))

    def embed(waveform: np.ndarray) -> np.ndarray:
        """Return the speaker embedding of one mono 16 kHz waveform."""
        tensor = torch.from_numpy(
            np.asarray(waveform, dtype=np.float32)).reshape(1, 1, -1)
        with torch.no_grad():
            vector = embedder(tensor.to(device))
        if hasattr(vector, "detach"):
            vector = vector.detach().cpu().numpy()
        return np.asarray(vector, dtype=np.float64).reshape(-1)

    return embed, source


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _errors(result) -> int | None:
    """Substitutions, deletions and insertions of one scored pair."""
    if result is None:
        return None
    return result.substitutions + result.deletions + result.insertions


def run(output_dir: Path, limit: int, alphas, hf_token=None,
        model_id: str = DEFAULT_ASR_MODEL,
        per_meeting: int | None = None) -> dict:
    """Score anonymisation at each coefficient in *alphas*.

    Parameters
    ----------
    output_dir:
        Where the report and summary are written.
    limit:
        Number of AMI test utterances to score.
    alphas:
        McAdams coefficients to compare.
    hf_token:
        Hugging Face token for the gated AMI dataset and pyannote models.
    model_id:
        The Whisper checkpoint that transcribes every condition, loaded at
        its pinned revision when :mod:`evaluation.revisions` lists one.
    per_meeting:
        Caps how many utterances are accepted from any one meeting, which
        spreads the sample over speakers and sessions (see
        :func:`sample_by_meeting`). Left unset, the sample is read from
        the front of the split, the single-meeting configuration, though
        not in the order the August runs read it (see
        :func:`sample_by_meeting`).

    Returns
    -------
    dict
        The per-alpha summaries, keyed by ``str(alpha)``.

    Raises
    ------
    ImportError
        If jiwer is not installed, before any data or model is loaded.

    Side effects: streams AMI and downloads the pyannote and Whisper
    models over the network (or reads them from the cache), uses a GPU
    when one is available, runs git to record the commit, and writes
    (overwriting) ``anonymisation_report.csv`` and
    ``anonymisation_summary.json`` in *output_dir*. The transform is
    deterministic and no RNG is used here, though GPU decoding may not be
    bit-reproducible.
    """
    from evaluation.benchmark_der import _AMI_CONFIG, _AMI_DATASET
    from evaluation.revisions import revision_for, revisions_used
    from evaluation.wer import (
        PairResult, compute_metrics, normalise_text, require_jiwer)
    from provenance import run_metadata

    # evaluation.wer imports without jiwer, and wer_of below turns a
    # scoring failure into a missing score. Without this check a missing
    # scorer would decode every condition on the GPU and then write a
    # summary whose WER fields are all null, with exit status 0.
    require_jiwer()

    output_dir.mkdir(parents=True, exist_ok=True)
    report = output_dir / "anonymisation_report.csv"
    summary_path = output_dir / "anonymisation_summary.json"
    # The git state is read before anything is written, leaving out the
    # two files this run rewrites, as provenance.write_sidecar does for the
    # CSV-only writers. Read after the report, as it was, a regeneration
    # in place in a checkout counted the run's own report as uncommitted
    # code.
    run_meta = run_metadata(repo_dir=_ROOT, ignore=(report, summary_path))

    print("Loading AMI utterances...", flush=True)
    skipped: dict = {}
    utterances = _load_utterances(limit, hf_token, per_meeting=per_meeting,
                                  skipped=skipped)
    speakers = [u["speaker"] for u in utterances]
    meetings = [u["meeting"] for u in utterances]
    channels = [u.get("channel") for u in utterances]
    # Insertion order is stream order, so the counts read as the sample
    # was drawn.
    accepted_by_meeting = dict(Counter(meetings))
    print(f"  {len(utterances)} utterances, {len(set(speakers))} speakers, "
          f"{len(accepted_by_meeting)} meeting(s): {accepted_by_meeting}",
          flush=True)

    embedding_failures: dict = {}
    embed, embedding_model = _load_embedder(hf_token, failures=embedding_failures)
    originals = [embed(u["audio"]) for u in utterances]
    # The rate the untransformed recordings reach against each other: what
    # a release with no anonymisation at all would give an attacker.
    ceiling = linkage_by_candidate_set(originals, originals, speakers,
                                       meetings, channels)
    print(f"  linkage ceiling {ceiling['all']['linkage_rate']} "
          f"(chance {ceiling['all']['chance']})", flush=True)

    from transformers import pipeline
    import torch
    # torch_dtype, not dtype: the dtype keyword needs transformers 4.56,
    # above the floor requirements.txt and preflight still allow.
    asr = pipeline("automatic-speech-recognition", model=model_id,
                   revision=revision_for(model_id),
                   device=0 if torch.cuda.is_available() else -1,
                   torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32)

    def transcribe(waveform):
        """Return Whisper's text for one waveform at SAMPLE_RATE."""
        out = asr({"array": np.asarray(waveform, dtype=float),
                   "sampling_rate": SAMPLE_RATE})
        return out.get("text", "") if isinstance(out, dict) else str(out)

    def wer_of(hypothesis, reference, uid=""):
        """Score one pair, keeping the counts a pooled rate needs."""
        ref = normalise_text(reference, strip_header=False)
        hyp = normalise_text(hypothesis, strip_header=False)
        if not ref.strip():
            return None
        try:
            return PairResult(name=uid, **compute_metrics(ref, hyp))
        except ImportError:
            # A missing scorer is not an unscorable utterance.
            raise
        except Exception:  # noqa: BLE001
            return None

    print("  transcribing the originals...", flush=True)
    wer_before = [wer_of(transcribe(u["audio"]), u["reference"], u["uid"])
                  for u in utterances]

    # The control: the same analysis-synthesis path with no warping. Since
    # 5f1a3ea that path returns its input (up to the limiter knee), so this
    # decode should score exactly as the original does; it is kept as a
    # check that the path has not started to alter the signal.
    print("  transcribing the resynthesis control (alpha = 1)...", flush=True)
    wer_control = [
        wer_of(transcribe(anonymise(u["audio"], SAMPLE_RATE, alpha=1.0,
                                    force_resynthesis=True)),
               u["reference"], u["uid"])
        for u in utterances]

    # The loop screen is a property of the baseline arm, so it is computed
    # once, from the same arm summarise() screens, and written per row.
    baseline_results, baseline_name = baseline_arm(wer_before, wer_control)
    looped = set(degenerate_baselines(baseline_results))
    # One analysis frame at each end: the span a clip-edge transient
    # could occupy, excluded from the body-only level ratio.
    edge = int(round(DEFAULT_FRAME_S * SAMPLE_RATE))

    rows, summaries = [], {}
    for alpha in alphas:
        print(f"\n--- alpha = {alpha} ---", flush=True)
        anonymised_audio = [anonymise(u["audio"], SAMPLE_RATE, alpha=alpha)
                            for u in utterances]
        anonymised_emb = [embed(a) for a in anonymised_audio]
        similarities = [cosine_similarity(o, a)
                        for o, a in zip(originals, anonymised_emb, strict=True)]
        wer_after = [wer_of(transcribe(a), u["reference"], u["uid"])
                     for a, u in zip(anonymised_audio, utterances, strict=True)]
        knee = [int(np.count_nonzero(np.abs(a) > LIMITER_KNEE))
                for a in anonymised_audio]

        by_set = linkage_by_candidate_set(anonymised_emb, originals, speakers,
                                          meetings, channels)
        original_audio = [u["audio"] for u in utterances]
        summary = summarise(
            similarities, wer_before, wer_after, _flat_linkage(by_set),
            results_control=wer_control,
            level=level_ratio(original_audio, anonymised_audio))
        summary["level_ratio_body"] = level_ratio(original_audio,
                                                  anonymised_audio, edge=edge)
        summary["n_knee_compressed_samples"] = sum(knee)
        summary["alpha"] = alpha
        summaries[str(alpha)] = summary
        print(f"  self-similarity {summary['mean_self_similarity']}  "
              f"linkage {summary['linkage_rate']} (chance {summary['chance']}); "
              f"cross-meeting {summary.get('linkage_rate_cross_meeting')} "
              f"(chance {summary.get('chance_cross_meeting')})", flush=True)
        print(f"    WER raw {summary['wer_original']}  "
              f"warped {summary['wer_anonymised']}  "
              f"cost {summary['wer_cost']} vs {summary['wer_baseline_name']}",
              flush=True)
        print(f"    dropping {summary['n_degenerate_baselines']} looped "
              f"baseline(s) carrying "
              f"{summary['degenerate_baseline_error_share']} of baseline error: "
              f"cost {summary['wer_cost_guarded']}", flush=True)
        print(f"    level ratio {summary['level_ratio']} "
              f"(body {summary['level_ratio_body']}, matched: "
              f"{summary['level_matched']}); "
              f"{summary['n_knee_compressed_samples']} sample(s) in the knee",
              flush=True)

        # The alignment counts go into the report, not only the rates, so
        # that a reader can re-pool the corpus, and the loop screen goes in
        # as a flag, so that the guarded figures can be re-pooled without
        # re-deriving it. New columns are appended, so a reader selecting
        # the older ones by name is unaffected.
        for i, (u, sim, wb, wc, wa) in enumerate(zip(
                utterances, similarities, wer_before, wer_control, wer_after,
                strict=True)):
            original_rms = _rms(u["audio"])
            rows.append({"alpha": alpha, "uid": u["uid"], "speaker": u["speaker"],
                         "self_similarity": round(sim, 6),
                         "wer_original": wb.wer if wb else None,
                         "wer_control": wc.wer if wc else None,
                         "wer_anonymised": wa.wer if wa else None,
                         "reference_words": wb.reference_words if wb else 0,
                         "hypothesis_words_original": wb.hypothesis_words if wb else 0,
                         "hypothesis_words_control": wc.hypothesis_words if wc else 0,
                         "hypothesis_words_anonymised": wa.hypothesis_words if wa else 0,
                         "insertions_original": wb.insertions if wb else 0,
                         "insertions_anonymised": wa.insertions if wa else 0,
                         "meeting": u["meeting"],
                         "channel": u.get("channel"),
                         "insertions_control": wc.insertions if wc else 0,
                         "errors_original": _errors(wb),
                         "errors_control": _errors(wc),
                         "errors_anonymised": _errors(wa),
                         "degenerate_baseline": int(i in looped),
                         "level_ratio": (round(_rms(anonymised_audio[i])
                                               / original_rms, 4)
                                         if original_rms > 0 else None),
                         "knee_samples": knee[i]})

    with report.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else
                                ["alpha", "uid", "speaker", "self_similarity",
                                 "wer_original", "wer_anonymised"])
        writer.writeheader()
        writer.writerows(rows)

    computed_sets = list(ceiling)
    # The repositories behind the embeddings: the diarisation pipeline and
    # the embedding model inside it, or the embedding model loaded alone.
    via_pipeline = embedding_model.endswith(_VIA_PIPELINE)
    embedding_repo = (embedding_model[:-len(_VIA_PIPELINE)] if via_pipeline
                      else embedding_model)
    embedding_unpinned = [embedding_repo] if "/" in embedding_repo else []
    embedding_repos = ([DIARISATION_PIPELINE] if via_pipeline else []) + embedding_unpinned
    summary_path.write_text(json.dumps(
        {"corpus": f"{_AMI_DATASET}/{_AMI_CONFIG}/{_SPLIT}",
         "n_utterances": len(utterances),
         "rows_skipped": skipped,
         "requested": {"limit": limit, "alphas": list(alphas),
                       "per_meeting": per_meeting, "model": model_id},
         "git_commit": _git_commit(),
         "n_meetings": len(accepted_by_meeting),
         "meetings": sorted(accepted_by_meeting),
         "accepted_by_meeting": accepted_by_meeting,
         "n_speakers": len(set(speakers)),
         "per_meeting_cap": per_meeting,
         "sampling": sampling_description(per_meeting),
         "asr_model": model_id,
         "embedding_model": embedding_model,
         # Why the embeddings did not come from the diarisation pipeline
         # (null when they did), and why each fallback model tried before
         # the one named above could not be loaded. The first fallback is
         # the WeSpeaker model speaker-diarization-3.1 names, built by the
         # same PretrainedSpeakerEmbedding factory from the cache's main,
         # so it changes how the model was loaded, not which. Only the
         # last, pyannote/embedding, is another model. Either way the
         # summary, and not only the job's stderr, says that a fallback
         # happened and why.
         "embedding_pipeline_error": embedding_failures.get(DIARISATION_PIPELINE),
         "embedding_fallback_errors": {
             name: reason for name, reason in embedding_failures.items()
             if name != DIARISATION_PIPELINE},
         "degenerate_baseline_criterion":
             degenerate_baseline_criterion(baseline_name),
         "linkage_candidate_sets": {k: CANDIDATE_SETS[k] for k in computed_sets},
         "linkage_ceiling": ceiling,
         "speaker_channels": speaker_channel_check(speakers, meetings,
                                                   channels),
         # A repository the registry does not list (pyannote/embedding, the
         # last fallback) records its revision as None.
         "revisions": revisions_used(model_id, *embedding_repos, _AMI_DATASET),
         # The recogniser, the diarisation pipeline and AMI (through
         # ami_meetings.stream_ami) are loaded at the revisions above. The
         # embedding model is loaded by name, from the pipeline's
         # config.yaml or by PretrainedSpeakerEmbedding, and pyannote 3.x
         # takes no revision there, so it resolves to the cache's main: the
         # registry's snapshot where the cache holds only that one, but not
         # something this run enforced (audit finding DEPS-04).
         "revisions_not_enforced": embedding_unpinned,
         "run_metadata": run_meta,
         "by_alpha": summaries}, indent=2), encoding="utf-8")
    print(f"\nReport:  {report}\nSummary: {summary_path}")
    return summaries


def main(argv=None) -> int:
    """Parse the command line and call :func:`run`; returns 0.

    The defaults are the single-meeting configuration (see the module
    docstring). Side effects are those of :func:`run`, plus reading the
    Hugging Face token file.
    """
    parser = argparse.ArgumentParser(
        description="Measure the privacy and intelligibility of voice "
                    "anonymisation.")
    parser.add_argument("--output-dir", type=Path,
                        default=_ROOT / "output" / "evaluation")
    parser.add_argument("--limit", type=int, default=PUBLISHED_LIMIT,
                        help="utterances to score (default: %(default)s, "
                             "the single-meeting configuration; the main "
                             "result used 400)")
    parser.add_argument("--alphas", type=float, nargs="+",
                        default=list(PUBLISHED_ALPHAS),
                        help="McAdams coefficients to compare (default: "
                             "%(default)s, as in both committed runs)")
    parser.add_argument("--model", default=DEFAULT_ASR_MODEL)
    parser.add_argument(
        "--per-meeting", type=int, default=None, dest="per_meeting",
        metavar="N",
        help=(
            "Accept at most N utterances from any one meeting, decoding "
            "each meeting from its start until N pass the filters or it "
            "runs out.  Spreading the sample over meetings adds speakers "
            "and sessions, which lowers the chance level and makes the "
            "cross-meeting linkage measurable; the main result used 25.  "
            "Omit to read from the front of the split, as the "
            "single-meeting configuration does."
        ),
    )
    args = parser.parse_args(argv)
    if args.per_meeting is not None and args.per_meeting < 1:
        parser.error("--per-meeting must be at least 1")

    from evaluation.benchmark_der import _load_hf_token
    run(args.output_dir, args.limit, args.alphas, _load_hf_token(), args.model,
        per_meeting=args.per_meeting)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
