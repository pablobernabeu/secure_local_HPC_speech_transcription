"""The review report carries no spoken names when masking is on.

Audit finding T3-01: the review file copied each flagged segment's raw
text, so under --redacted-timestamps-only it was the one artefact in the
output tree that still held the names the flag promises to suppress.
"""

from __future__ import annotations

import contextlib
import io
import json

import pytest


def _result():
    return {
        'text': 'Thanks, Sarah. Thanks, Sarah. John Smith.',
        'chunks': [
            {'text': 'Thanks,', 'timestamp': (0.0, 0.4)},
            {'text': 'Sarah.', 'timestamp': (0.4, 0.9)},
            {'text': 'Thanks,', 'timestamp': (1.0, 1.4)},
            {'text': 'Sarah.', 'timestamp': (1.4, 1.8)},
            {'text': 'John', 'timestamp': (5.0, 5.05)},
            {'text': 'Smith.', 'timestamp': (5.05, 5.1)},
        ],
    }


@pytest.fixture(scope="module")
def masker(transcription_module):
    with contextlib.redirect_stdout(io.StringIO()):
        mask, _ = transcription_module.create_enhanced_name_masker()
    return mask


def test_no_raw_name_anywhere_in_the_tree(transcription_module, masker,
                                           tmp_path):
    m = transcription_module
    with contextlib.redirect_stdout(io.StringIO()):
        written = m.write_timestamped_outputs(
            _result(), output_dir=str(tmp_path), base_name='rec',
            audio_path='rec.wav', mask_fn=masker, write_raw=False)
    review = m.write_review_file(
        written['segments'], str(tmp_path / 'rec_review.json'),
        mask_fn=masker)
    assert review['summary']['flagged'] >= 2
    assert review['redacted'] is True

    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == ['rec_review.json', 'rec_transcript_redacted.json',
                     'rec_transcript_redacted.vtt']
    for path in tmp_path.iterdir():
        text = path.read_text(encoding='utf-8')
        for name in ('Sarah', 'John', 'Smith'):
            assert name not in text, f"{name} leaked into {path.name}"


def test_flags_are_computed_on_the_raw_segments(transcription_module, masker,
                                                tmp_path):
    m = transcription_module
    with contextlib.redirect_stdout(io.StringIO()):
        written = m.write_timestamped_outputs(
            _result(), output_dir=str(tmp_path), base_name='rec',
            audio_path='rec.wav', mask_fn=masker)
    plain = m.write_review_file(written['segments'],
                                str(tmp_path / 'plain.json'))
    masked = m.write_review_file(written['segments'],
                                 str(tmp_path / 'masked.json'),
                                 mask_fn=masker)
    assert plain['redacted'] is False
    assert plain['summary'] == masked['summary']
    assert [r['flags'] for r in plain['flagged']] == \
        [r['flags'] for r in masked['flagged']]
    assert any('Sarah' in r['text'] for r in plain['flagged'])
    on_disk = json.loads((tmp_path / 'masked.json').read_text('utf-8'))
    assert on_disk == masked
