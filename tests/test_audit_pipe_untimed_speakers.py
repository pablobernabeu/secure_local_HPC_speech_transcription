"""Untimed words do not crash speaker stamping.

Audit finding T3-08: the timeline repair turns NaN timings into None, and
speaker stamping then compared None with a float, raising TypeError and
losing every timestamped artefact of a --speaker-attribution run.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path


def test_nan_word_with_diarisation(transcription_module, tmp_path):
    m = transcription_module
    result = {
        'text': 'hello there friend.',
        'chunks': [
            {'text': 'hello', 'timestamp': (0.0, 0.5)},
            {'text': 'there', 'timestamp': (float('nan'), float('nan'))},
            {'text': 'friend.', 'timestamp': (0.6, 0.9)},
        ],
    }
    diar = [{'start': 0.0, 'end': 2.0, 'speaker': 'SPEAKER_00'}]
    with contextlib.redirect_stdout(io.StringIO()):
        written = m.write_timestamped_outputs(
            result, output_dir=str(tmp_path), base_name='rec',
            audio_path='rec.wav', diarization_segments=diar)
    payload = json.loads(Path(written['json']).read_text(encoding='utf-8'))
    words = [w for s in payload['segments'] for w in s['words']]
    assert [w['word'] for w in words] == ['hello', 'there', 'friend.']
    assert {w['speaker'] for w in words} == {'SPEAKER_00'}
    assert words[1]['start'] is None
    assert Path(written['vtt']).exists()
