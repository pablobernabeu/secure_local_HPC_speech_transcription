"""Tests for the timestamped-timeline repair.

The contract has four parts: pathological timings are made physically
consistent, the *fewest possible* words are touched in the process, healthy
timings pass through with every count at zero, and the counts say what was
done. The decisive test drives a pathological result through
``write_timestamped_outputs`` and then scores the emitted JSON with the
same ``timestamp_metrics`` the case study uses, because that scorer is the
instrument that reported the defect in the first place.

The minimality property is the one the first implementation lacked: it
raised every word after a forward-glitched one up to the glitch time, so a
single bad timestamp distorted dozens of healthy neighbours. The repair now
trusts a longest ordered run of start times and retimes only the words
outside it, and the cascade test pins exactly that difference.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.benchmark_podcast import timestamp_metrics
from transcription import (
    _repair_segment_timeline,
    write_timestamped_outputs,
)


def _segment(start, end, words):
    return {
        "start": start, "end": end,
        "text": " ".join(w["word"] for w in words),
        "words": words,
    }


def _word(text, start, end):
    return {"word": text, "start": start, "end": end}


def _flat_words(segments):
    return [w for s in segments for w in s.get("words") or []]


def _assert_scores_clean(segments):
    metrics = timestamp_metrics({"segments": segments})
    assert metrics["monotonicity_violations"] == 0
    assert metrics["n_overlaps"] == 0


def test_clean_timeline_is_untouched():
    """Zero counts on healthy input is the certificate the payload makes."""
    segments = [
        _segment(0.0, 1.0, [_word("a", 0.0, 0.4), _word("b", 0.5, 1.0)]),
        _segment(1.2, 2.0, [_word("c", 1.2, 1.6), _word("d", 1.7, 2.0)]),
    ]
    before = json.dumps(segments)
    counts = _repair_segment_timeline(segments)
    assert all(count == 0 for count in counts.values())
    assert json.dumps(segments) == before


def test_word_ending_before_it_starts_is_clamped():
    segments = [_segment(0.0, 1.0, [_word("a", 0.5, 0.2)])]
    counts = _repair_segment_timeline(segments)
    assert counts["word_end_clamped"] == 1
    assert segments[0]["words"][0]["end"] == 0.5


def test_backwards_word_is_retimed_minimally():
    """One out-of-order word means one retime, whichever side is chosen."""
    segments = [
        _segment(0.0, 1.0, [_word("a", 0.8, 1.0)]),
        _segment(1.0, 2.0, [_word("b", 0.3, 1.5)]),   # jumps backwards
    ]
    counts = _repair_segment_timeline(segments)
    assert counts["word_retimed"] == 1
    starts = [w["start"] for w in _flat_words(segments)]
    assert starts == sorted(starts)
    _assert_scores_clean(segments)


def test_forward_glitch_does_not_drag_its_neighbours():
    """The minimality property: one glitched word means one repair.

    The first implementation raised every later word to the glitch time,
    so this fixture would have counted four repairs and put four healthy
    words at 60 seconds. Only the glitch itself may move.
    """
    segments = [_segment(1.0, 5.0, [
        _word("a", 1.0, 1.5),
        _word("glitch", 60.0, 60.5),   # timed far ahead of its position
        _word("b", 2.0, 2.5),
        _word("c", 3.0, 3.5),
        _word("d", 4.0, 4.5),
    ])]
    counts = _repair_segment_timeline(segments)
    assert counts["word_retimed"] == 1
    words = segments[0]["words"]
    # The healthy neighbours kept their own timings.
    assert [w["start"] for w in words if w["word"] != "glitch"] == \
        [1.0, 2.0, 3.0, 4.0]
    # The glitch was moved into the interval its neighbours define.
    glitch = next(w for w in words if w["word"] == "glitch")
    assert 1.0 <= glitch["start"] <= 2.0
    assert glitch["start"] <= glitch["end"] <= 2.0
    _assert_scores_clean(segments)


def test_swallowed_segment_is_merged_not_collapsed():
    """A cue inside its predecessor merges into it; no zero-length cues.

    The first implementation stacked such cues at the predecessor's end
    with zero duration. The review layer computes no speech rate for a
    cue of zero length, so no flag could point a reader at one. Merging
    keeps the text and words and leaves nothing degenerate to stumble on.
    """
    segments = [
        _segment(0.0, 100.0, [_word("a", 0.0, 100.0)]),
        _segment(5.0, 6.0, [_word("b", 5.0, 6.0)]),     # inside the previous
    ]
    counts = _repair_segment_timeline(segments)
    assert counts["segment_merged"] == 1
    assert len(segments) == 1
    merged = segments[0]
    assert merged["text"] == "a b"
    assert len(merged["words"]) == 2                    # nothing lost
    assert all(merged["start"] <= w["start"] <= merged["end"]
               for w in merged["words"])
    assert merged["end"] > merged["start"]              # no degenerate cue
    _assert_scores_clean(segments)


def test_partial_overlap_is_clamped_and_words_carried():
    segments = [
        _segment(0.0, 10.0, [_word("a", 0.0, 10.0)]),
        _segment(5.0, 12.0, [_word("b", 5.0, 12.0)]),   # extends beyond
    ]
    counts = _repair_segment_timeline(segments)
    assert counts["segment_overlap_clamped"] == 1
    clamped = segments[1]
    assert clamped["start"] == 10.0
    assert clamped["words"][0]["start"] >= clamped["start"]
    _assert_scores_clean(segments)


def test_overlapping_segments_are_clamped_and_gaps_kept():
    segments = [
        _segment(0.0, 2.0, []),
        _segment(1.5, 3.0, []),     # overlaps its predecessor, not swallowed
        _segment(4.0, 5.0, []),     # a genuine gap, which must survive
    ]
    counts = _repair_segment_timeline(segments)
    assert counts["segment_overlap_clamped"] == 1
    assert segments[1]["start"] == 2.0
    assert segments[2]["start"] == 4.0      # the pause was not touched


def test_segment_bounds_follow_repaired_words():
    """After word repair, a segment's cue spans its own words again."""
    segments = [_segment(0.0, 9.9, [_word("a", 1.0, 0.2),
                                    _word("b", 1.4, 1.9)])]
    _repair_segment_timeline(segments)
    assert segments[0]["start"] == 1.0
    assert segments[0]["end"] == 1.9


def test_words_without_timings_are_skipped():
    segments = [_segment(0.0, 1.0, [{"word": "a"},
                                    _word("b", 0.2, 0.6)])]
    counts = _repair_segment_timeline(segments)
    assert all(count == 0 for count in counts.values())


def test_repair_is_idempotent_in_data_and_counts():
    """A second pass over repaired output must find nothing left to do."""
    segments = [
        _segment(0.0, 10.0, [_word("a", 0.0, 10.0)]),
        _segment(2.0, 3.0, [_word("b", 2.0, 3.0)]),
        _segment(2.5, 4.0, [_word("c", 2.5, 1.0)]),
    ]
    _repair_segment_timeline(segments)
    snapshot = json.dumps(segments)
    second = _repair_segment_timeline(segments)
    assert all(count == 0 for count in second.values())
    assert json.dumps(segments) == snapshot


def test_subtolerance_jitter_is_clamped_but_not_counted():
    """Wobble below the benchmark's own 1e-6 tolerance is not a defect:
    it is exactified silently, so the data is strictly ordered while the
    counts stay comparable to violations a reader would measure."""
    # The cue matches its word envelope, as the production builder makes
    # it, so the only candidate change is the jitter itself.
    segments = [_segment(1.0, 1.5, [_word("a", 1.0, 1.5),
                                    _word("b", 1.0 - 1e-9, 1.5)])]
    counts = _repair_segment_timeline(segments)
    assert all(count == 0 for count in counts.values())     # not material
    assert segments[0]["words"][1]["start"] == 1.0          # but exact
    # And at a fixpoint: a second pass finds nothing at all to do.
    snapshot = json.dumps(segments)
    second = _repair_segment_timeline(segments)
    assert all(count == 0 for count in second.values())
    assert json.dumps(segments) == snapshot
    _assert_scores_clean(segments)


def test_nan_timings_are_normalised_and_not_poisonous():
    """NaN becomes None (untimed), and must not disable the repair of its
    neighbours nor reach the JSON, where NaN is invalid."""
    segments = [_segment(0.0, 12.0, [
        _word("a", 10.0, 11.0),
        _word("b", float("nan"), float("nan")),
        _word("c", 0.5, 1.0),                          # genuinely backwards
    ])]
    counts = _repair_segment_timeline(segments)
    assert segments[0]["words"][1]["start"] is None
    assert segments[0]["words"][1]["end"] is None
    assert counts["word_retimed"] == 1
    timed = [w for w in segments[0]["words"] if w["start"] is not None]
    starts = [w["start"] for w in timed]
    assert starts == sorted(starts)
    # The payload this feeds must be strict JSON.
    json.dumps(segments, allow_nan=False)


def test_merge_preserves_every_word_and_all_text():
    """Merging may reshape cues but must never lose content."""
    segments = [
        _segment(0.0, 50.0, [_word("one", 0.0, 50.0)]),
        _segment(10.0, 11.0, [_word("two", 10.0, 11.0)]),
        _segment(20.0, 21.0, [_word("three", 20.0, 21.0)]),
    ]
    _repair_segment_timeline(segments)
    words = [w["word"] for w in _flat_words(segments)]
    assert words == ["one", "two", "three"]
    joined = " ".join(s["text"] for s in segments)
    assert joined.split() == ["one", "two", "three"]
    _assert_scores_clean(segments)


def test_emitted_json_scores_clean_after_repair(tmp_path):
    """End to end: a pathological result must leave a clean artefact.

    The fixture reproduces the defect classes the case study measured, and
    the emitted JSON is scored with the same ``timestamp_metrics`` that
    reported them, so this test fails if either defect survives to the file
    a reader receives.
    """
    result = {
        "text": "one two three four",
        "chunks": [
            {"text": "one", "timestamp": (0.0, 0.5)},
            {"text": "two", "timestamp": (0.9, 0.6)},     # ends before start
            {"text": "three", "timestamp": (0.4, 1.4)},   # starts backwards
            {"text": "four", "timestamp": (5.0, 5.5)},    # after a gap
        ],
    }
    written = write_timestamped_outputs(result, str(tmp_path), "demo",
                                        "demo.wav", model="m",
                                        language="english")
    payload = json.loads(Path(written["json"]).read_text(encoding="utf-8"))

    metrics = timestamp_metrics(payload)
    assert metrics["monotonicity_violations"] == 0
    assert metrics["n_overlaps"] == 0

    # The payload discloses the surgery rather than hiding it.
    repairs = payload["timeline_repairs"]
    assert repairs["word_retimed"] >= 1


# ---------------------------------------------------------------------------
# Which repair moved a word
#
# `word_retimed` and `word_order_enforced` shared one counter until
# 2026-08-11. That made a real question unanswerable: when the case-study
# episode reported 63 retimed words and the minimal retiming was expected
# to have reduced it, the payload could not say whether the count came
# from the retiming or from the safety net behind it. It came from the
# retiming, and 63 was already the minimum. These tests keep the two
# distinguishable, and pin the minimality claim the docstring makes.
# ---------------------------------------------------------------------------

def _longest_non_decreasing_run(values):
    """Length of the longest non-decreasing subsequence, computed naively."""
    if not values:
        return 0
    best = [1] * len(values)
    for i in range(len(values)):
        for j in range(i):
            if values[j] <= values[i]:
                best[i] = max(best[i], best[j] + 1)
    return max(best)


class TestRepairAttribution:
    def test_the_safety_net_reports_under_its_own_counter(self, transcription_module):
        """Called directly, on input the earlier passes never saw."""
        m = transcription_module
        segments = [{"start": 0.0, "end": 5.0, "words": [
            {"word": "a", "start": 3.0, "end": 3.5},
            {"word": "b", "start": 1.0, "end": 1.5},   # goes backwards
        ]}]
        counts = {"word_retimed": 0, "word_order_enforced": 0,
                  "word_end_clamped": 0}
        assert m._enforce_flat_word_order(segments, counts) is True
        assert counts["word_order_enforced"] == 1
        assert counts["word_retimed"] == 0

    def test_a_full_repair_leaves_the_safety_net_nothing_to_do(self, transcription_module):
        """The net is a structural guarantee, not an active repair.

        Randomised documents with backward jumps, inverted words and
        overlapping cues: the minimal retiming and the cue passes settle
        all of it, so the net never fires. A future change that makes it
        fire is a regression in one of those passes.
        """
        import random
        m = transcription_module
        rng = random.Random(20260811)
        moved = enforced = 0
        for _ in range(300):
            segments, t = [], 0.0
            for _ in range(rng.randint(1, 5)):
                words, wt = [], t
                for _ in range(rng.randint(1, 7)):
                    dur = rng.choice([0.1, 0.3, 0.7])
                    start = wt - rng.choice([0.5, 2.0, 9.0]) if rng.random() < 0.3 else wt
                    end = start - 0.4 if rng.random() < 0.1 else start + dur
                    words.append({"word": "w", "start": start, "end": end})
                    wt += dur
                segments.append({"start": t, "end": wt, "text": "w " * len(words),
                                 "words": words})
                t = wt + rng.choice([0.0, 0.2, -0.6])
            counts = m._repair_segment_timeline(segments)
            moved += counts["word_retimed"]
            enforced += counts["word_order_enforced"]
        assert moved > 0, "the fixture stopped exercising the retiming"
        assert enforced == 0, (
            f"the safety net fired {enforced} times; an earlier pass has a gap")

    def test_retiming_moves_only_words_outside_the_longest_run(self, transcription_module):
        """The minimality claim, asserted rather than asserted-in-prose."""
        m = transcription_module
        starts = [0.0, 5.0, 1.0, 2.0, 3.0, 0.5, 4.0]
        segments = [{"start": 0.0, "end": 9.0, "text": "w " * len(starts),
                     "words": [{"word": "w", "start": s, "end": s + 0.1}
                               for s in starts]}]
        counts = m._repair_segment_timeline(segments)
        expected = len(starts) - _longest_non_decreasing_run(starts)
        assert counts["word_retimed"] == expected

    def test_a_clean_timeline_reports_nothing(self, transcription_module):
        m = transcription_module
        segments = [{"start": 0.0, "end": 2.0, "text": "a b",
                     "words": [{"word": "a", "start": 0.0, "end": 0.5},
                               {"word": "b", "start": 0.6, "end": 1.0}]}]
        counts = m._repair_segment_timeline(segments)
        assert counts["word_retimed"] == 0
        assert counts["word_order_enforced"] == 0

    def test_both_counters_are_always_present_in_the_payload(self, transcription_module):
        """Consumers read these keys; absence must not be a silent zero."""
        m = transcription_module
        counts = m._repair_segment_timeline([])
        assert "word_retimed" in counts
        assert "word_order_enforced" in counts
