"""Named segmentation and chunking constants, and a reported repair bound.

Audit findings T2-13 and T3-23: the ASR windows and caption thresholds were
unexplained literals, and the four-pass timeline repair could run out
without saying so. Values must be unchanged.
"""

from __future__ import annotations

import contextlib
import inspect
import io


def test_values_are_unchanged(transcription_module):
    m = transcription_module
    assert (m.ASR_CHUNK_S_TIMESTAMPED, m.ASR_STRIDE_S_TIMESTAMPED) == (30, 5)
    assert (m.ASR_CHUNK_S_PLAIN, m.ASR_STRIDE_S_PLAIN) == (15, 2)
    params = inspect.signature(m._build_segments_from_chunks).parameters
    assert params['max_gap'].default == 1.0
    assert params['max_chars'].default == 180
    assert m._WORD_CHUNK_MAX_S == 2.5


def _segments():
    return [{'start': 0.0, 'end': 1.0, 'text': 'a',
             'words': [{'word': 'a', 'start': 0.0, 'end': 1.0}]}]


def test_ordinary_payload_has_no_converged_key(transcription_module):
    counts = transcription_module._repair_segment_timeline(_segments())
    assert 'converged' not in counts


def test_exhausted_bound_is_reported(transcription_module, monkeypatch):
    m = transcription_module
    monkeypatch.setattr(m, "_repair_segment_cues", lambda segs, counts: True)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        counts = m._repair_segment_timeline(_segments())
    assert counts['converged'] is False
    assert "did not reach a fixpoint" in out.getvalue()


def test_change_on_the_last_pass_only_is_not_flagged(transcription_module,
                                                     monkeypatch):
    m = transcription_module
    calls = []

    def fake(segs, counts):
        calls.append(1)
        return len(calls) <= 4    # changes on passes 1-4, then settles

    monkeypatch.setattr(m, "_repair_segment_cues", fake)
    counts = m._repair_segment_timeline(_segments())
    assert 'converged' not in counts
    assert len(calls) == 5
