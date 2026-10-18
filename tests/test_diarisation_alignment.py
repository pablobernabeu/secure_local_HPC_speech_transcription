"""Tests for the chunk-based diarisation alignment helpers."""

from __future__ import annotations



def test_basic_overlap(transcription_module):
    m = transcription_module
    segs = [{'start': 0.0, 'end': 2.0, 'speaker': 'A'},
            {'start': 2.5, 'end': 5.0, 'speaker': 'B'}]
    starts = [s['start'] for s in segs]
    assert m._assign_speaker_to_interval(0.5, 1.5, segs, starts, None) == 'A'
    assert m._assign_speaker_to_interval(2.6, 4.0, segs, starts, None) == 'B'


def test_silent_gap_carries_forward(transcription_module):
    m = transcription_module
    segs = [{'start': 0.0, 'end': 2.0, 'speaker': 'A'},
            {'start': 3.0, 'end': 5.0, 'speaker': 'B'}]
    starts = [s['start'] for s in segs]
    # Word fully inside the gap [2.0, 3.0] — no overlap. Carry forward.
    assert m._assign_speaker_to_interval(2.3, 2.7, segs, starts, 'A') == 'A'


def test_no_fallback_returns_unknown(transcription_module):
    m = transcription_module
    segs = [{'start': 0.0, 'end': 2.0, 'speaker': 'A'}]
    starts = [s['start'] for s in segs]
    # Past the last segment and no prior speaker.
    assert m._assign_speaker_to_interval(10.0, 11.0, segs, starts, None) \
        == 'SPEAKER_UNKNOWN'


def test_greatest_overlap_wins(transcription_module):
    m = transcription_module
    # A=[0,2], B=[1.9, 5]: word [1.0, 4.0] overlaps A by 1.0s, B by 2.1s.
    segs = [{'start': 0.0, 'end': 2.0, 'speaker': 'A'},
            {'start': 1.9, 'end': 5.0, 'speaker': 'B'}]
    starts = [s['start'] for s in segs]
    assert m._assign_speaker_to_interval(1.0, 4.0, segs, starts, None) == 'B'


def test_empty_diarisation(transcription_module):
    m = transcription_module
    assert m._assign_speaker_to_interval(0.0, 1.0, [], [], None) \
        == 'SPEAKER_UNKNOWN'
    assert m._assign_speaker_to_interval(0.0, 1.0, [], [], 'X') == 'X'


def test_attribute_chunks_to_speakers(transcription_module):
    m = transcription_module
    chunks = [
        {'text': 'hello', 'timestamp': (0.1, 0.5)},
        {'text': 'world', 'timestamp': (0.6, 1.0)},
        {'text': 'bye', 'timestamp': (3.0, 3.5)},
    ]
    diar = [{'start': 0.0, 'end': 2.0, 'speaker': 'A'},
            {'start': 3.0, 'end': 4.0, 'speaker': 'B'}]
    out = m._attribute_chunks_to_speakers(chunks, diar)
    assert [c['speaker'] for c in out] == ['A', 'A', 'B']
    assert [c['text'] for c in out] == ['hello', 'world', 'bye']


def test_attribute_chunks_carry_forward_through_gap(transcription_module):
    m = transcription_module
    chunks = [
        {'text': 'first', 'timestamp': (0.1, 0.5)},
        {'text': 'gap', 'timestamp': (2.2, 2.7)},     # silent gap
        {'text': 'next', 'timestamp': (3.1, 3.5)},
    ]
    diar = [{'start': 0.0, 'end': 2.0, 'speaker': 'A'},
            {'start': 3.0, 'end': 4.0, 'speaker': 'B'}]
    out = m._attribute_chunks_to_speakers(chunks, diar)
    assert [c['speaker'] for c in out] == ['A', 'A', 'B']


def test_format_attributed_text_groups_consecutive_same_speaker(transcription_module):
    m = transcription_module
    attributed = [
        {'start': 0.0, 'end': 0.5, 'text': 'hello', 'speaker': 'A'},
        {'start': 0.6, 'end': 1.0, 'text': 'world', 'speaker': 'A'},
        {'start': 3.0, 'end': 3.5, 'text': 'bye', 'speaker': 'B'},
    ]
    out = m._format_attributed_text(attributed)
    assert out == "[A] hello world\n\n[B] bye"


def test_empty_chunks_returns_empty(transcription_module):
    m = transcription_module
    assert m._attribute_chunks_to_speakers([], [{'start': 0, 'end': 1, 'speaker': 'A'}]) == []
    assert m._format_attributed_text([]) == ""


def test_legacy_path_when_chunks_missing(transcription_module):
    m = transcription_module
    diar = [{'start': 0.0, 'end': 5.0, 'speaker': 'A'},
            {'start': 5.0, 'end': 10.0, 'speaker': 'B'}]
    text = "hello world goodbye now"
    out = m.apply_speaker_labels_to_transcript(
        text, diar, audio_duration=10.0, chunks=None)
    assert '[A]' in out or '[B]' in out


# ---------------------------------------------------------------------------
# Overlapping diarisation output
#
# pyannote emits one track per speaker, so simultaneous speech produces
# segments that overlap. Sorted by start time, their end times are then no
# longer monotonic: a long turn can enclose short interjections by others.
# The backward scan must therefore not stop at the first segment ending
# before the query.
# ---------------------------------------------------------------------------

def _lookup(m, segs):
    return m._speaker_lookup(segs)


def test_an_enclosing_turn_is_found_past_shorter_interjections(transcription_module):
    m = transcription_module
    segs = [{'start': 0.0, 'end': 100.0, 'speaker': 'A'},   # encloses both
            {'start': 50.0, 'end': 55.0, 'speaker': 'B'},
            {'start': 60.0, 'end': 65.0, 'speaker': 'C'}]
    sorted_segs, starts, max_ends = _lookup(m, segs)
    # [70, 80] lies inside A only; the scan must not stop at C, which ends
    # at 65, before reaching A.
    assert m._assign_speaker_to_interval(
        70.0, 80.0, sorted_segs, starts, None, max_ends) == 'A'


def test_the_enclosing_turn_is_found_without_the_precomputed_maxima(transcription_module):
    """Callers that pass only starts must stay correct, if slower."""
    m = transcription_module
    segs = [{'start': 0.0, 'end': 100.0, 'speaker': 'A'},
            {'start': 50.0, 'end': 55.0, 'speaker': 'B'}]
    starts = [s['start'] for s in segs]
    assert m._assign_speaker_to_interval(70.0, 80.0, segs, starts, None) == 'A'


def test_a_carry_forward_fallback_no_longer_masks_a_real_overlap(transcription_module):
    """The failure was invisible: it looked like sensible carry-forward."""
    m = transcription_module
    segs = [{'start': 0.0, 'end': 100.0, 'speaker': 'A'},
            {'start': 10.0, 'end': 12.0, 'speaker': 'B'}]
    sorted_segs, starts, max_ends = _lookup(m, segs)
    assert m._assign_speaker_to_interval(
        20.0, 21.0, sorted_segs, starts, 'B', max_ends) == 'A'


def test_the_greater_overlap_still_wins_among_overlapping_turns(transcription_module):
    m = transcription_module
    segs = [{'start': 0.0, 'end': 100.0, 'speaker': 'A'},
            {'start': 40.0, 'end': 90.0, 'speaker': 'B'}]
    sorted_segs, starts, max_ends = _lookup(m, segs)
    # [50, 60] falls inside both; A and B overlap it equally, so the first
    # strictly greater overlap encountered wins deterministically.
    assert m._assign_speaker_to_interval(
        50.0, 60.0, sorted_segs, starts, None, max_ends) in {'A', 'B'}
    # [92, 95] is inside A alone.
    assert m._assign_speaker_to_interval(
        92.0, 95.0, sorted_segs, starts, None, max_ends) == 'A'


def test_chunk_attribution_uses_the_enclosing_turn(transcription_module):
    m = transcription_module
    chunks = [{'text': 'inside', 'timestamp': (70.0, 71.0)}]
    diar = [{'start': 0.0, 'end': 100.0, 'speaker': 'A'},
            {'start': 60.0, 'end': 65.0, 'speaker': 'C'}]
    out = m._attribute_chunks_to_speakers(chunks, diar)
    assert [c['speaker'] for c in out] == ['A']


class TestSpeakerLookup:
    def test_sorts_segments_and_accumulates_a_running_maximum(self, transcription_module):
        m = transcription_module
        segs = [{'start': 60.0, 'end': 65.0, 'speaker': 'C'},
                {'start': 0.0, 'end': 100.0, 'speaker': 'A'},
                {'start': 50.0, 'end': 55.0, 'speaker': 'B'}]
        sorted_segs, starts, max_ends = m._speaker_lookup(segs)
        assert [s['speaker'] for s in sorted_segs] == ['A', 'B', 'C']
        assert starts == [0.0, 50.0, 60.0]
        assert max_ends == [100.0, 100.0, 100.0]

    def test_empty_input(self, transcription_module):
        m = transcription_module
        assert m._speaker_lookup([]) == ([], [], [])
        assert m._speaker_lookup(None) == ([], [], [])
