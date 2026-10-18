"""A zero-length word is attributed to the turn that contains it.

Audit finding T2-05: overlap with a point is zero for every segment, so a
word with no end time, or one the timeline repair clamped to its start,
always took the carried-forward speaker, even from inside another
speaker's turn.
"""

from __future__ import annotations

import pytest

A_THEN_B = [{'start': 0.0, 'end': 10.0, 'speaker': 'A'},
            {'start': 10.0, 'end': 20.0, 'speaker': 'B'}]


def _assign(m, segs, start, end, fallback):
    ss, st, me = m._speaker_lookup(segs)
    return m._assign_speaker_to_interval(start, end, ss, st, fallback,
                                         segment_max_ends=me)


@pytest.mark.parametrize("fallback", ['A', None])
def test_point_inside_another_turn(transcription_module, fallback):
    assert _assign(transcription_module, A_THEN_B, 15.0, 15.0, fallback) == 'B'


def test_point_with_missing_end(transcription_module):
    assert _assign(transcription_module, A_THEN_B, 15.0, None, 'A') == 'B'


def test_point_at_a_boundary_opens_the_next_turn(transcription_module):
    assert _assign(transcription_module, A_THEN_B, 10.0, 10.0, 'A') == 'B'


def test_point_inside_a_nested_interjection(transcription_module):
    segs = [{'start': 0.0, 'end': 20.0, 'speaker': 'A'},
            {'start': 5.0, 'end': 8.0, 'speaker': 'B'}]
    m = transcription_module
    assert _assign(m, segs, 6.0, 6.0, 'A') == 'B'
    assert _assign(m, segs, 12.0, 12.0, 'B') == 'A'


def test_point_in_silence_keeps_carry_forward(transcription_module):
    segs = [{'start': 0.0, 'end': 5.0, 'speaker': 'A'},
            {'start': 10.0, 'end': 20.0, 'speaker': 'B'}]
    m = transcription_module
    assert _assign(m, segs, 7.0, 7.0, 'A') == 'A'
    assert _assign(m, segs, 7.0, 7.0, None) == 'SPEAKER_UNKNOWN'


def test_intervals_with_duration_are_unchanged(transcription_module):
    m = transcription_module
    assert _assign(m, A_THEN_B, 15.0, 15.02, 'A') == 'B'
    assert _assign(m, A_THEN_B, 9.0, 10.5, 'B') == 'A'
    # Touching a boundary without overlap still falls back, as before.
    assert _assign(m, A_THEN_B, 20.0, 21.0, 'A') == 'A'


def test_chunk_attribution_uses_containment(transcription_module):
    m = transcription_module
    chunks = [{'text': 'hi', 'timestamp': (1.0, 2.0)},
              {'text': 'there', 'timestamp': (15.0, 15.0)}]
    attributed = m._attribute_chunks_to_speakers(chunks, A_THEN_B)
    assert [c['speaker'] for c in attributed] == ['A', 'B']
    assert m.apply_speaker_labels_to_transcript(
        'hi there', A_THEN_B, 20.0, chunks=chunks) == '[A] hi\n\n[B] there'
