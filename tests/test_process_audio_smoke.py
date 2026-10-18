"""End-to-end smoke test for ``write_timestamped_outputs``.

We do not need real audio or a real ASR pipeline to test the file-writing
contract: the function consumes a plain dict in the shape that
``transformers.pipeline('automatic-speech-recognition', ...)`` returns
when ``return_timestamps='word'`` is set. Building that dict by hand
lets us verify the JSON/VTT artefacts on any machine.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _fake_transcription_result():
    return {
        'text': 'hello world goodbye',
        'chunks': [
            {'text': 'hello', 'timestamp': (0.1, 0.5)},
            {'text': 'world', 'timestamp': (0.6, 1.0)},
            {'text': 'goodbye', 'timestamp': (3.0, 3.5)},
        ],
    }


def test_write_timestamped_outputs_without_diarisation(transcription_module, tmp_path):
    m = transcription_module
    res = m.write_timestamped_outputs(
        _fake_transcription_result(),
        output_dir=str(tmp_path),
        base_name='sample',
        audio_path='sample.wav',
        model='openai/whisper-large-v3',
        language='english',
    )
    json_path = Path(res['json'])
    vtt_path = Path(res['vtt'])
    assert json_path.exists() and vtt_path.exists()

    payload = json.loads(json_path.read_text(encoding='utf-8'))
    assert payload['audio_file'] == 'sample.wav'
    assert payload['pipeline']['asr_model'] == 'openai/whisper-large-v3'
    assert 'diarization_model_source' not in payload['pipeline']
    assert 'diarization_segments' not in payload
    # No <v ...> voice tags when diarisation is absent.
    vtt = vtt_path.read_text(encoding='utf-8')
    assert '<v ' not in vtt


def test_write_timestamped_outputs_with_diarisation(transcription_module, tmp_path):
    m = transcription_module
    diar = [
        {'start': 0.0, 'end': 2.0, 'speaker': 'SPEAKER_00'},
        {'start': 3.0, 'end': 4.0, 'speaker': 'SPEAKER_01'},
    ]
    source = {
        'source': 'local_path',
        'model_id': 'pyannote/speaker-diarization-3.1',
        'model_path': '/local/pyannote',
        'error': None,
    }
    res = m.write_timestamped_outputs(
        _fake_transcription_result(),
        output_dir=str(tmp_path),
        base_name='sample',
        audio_path='sample.wav',
        model='openai/whisper-large-v3',
        language='english',
        diarization_segments=diar,
        diarization_source=source,
    )
    payload = json.loads(Path(res['json']).read_text(encoding='utf-8'))
    # pipeline block records provenance.
    assert payload['pipeline']['diarization_model_source'] == 'local_path'
    assert payload['pipeline']['diarization_model_path'] == '/local/pyannote'
    # Raw segments preserved.
    assert payload['diarization_segments'] == diar
    # Every emitted segment received a speaker label.
    speakers = {s.get('speaker') for s in payload['segments']}
    assert speakers and speakers <= {'SPEAKER_00', 'SPEAKER_01'}
    # VTT cues use <v SPEAKER_xx> voice tags.
    vtt = Path(res['vtt']).read_text(encoding='utf-8')
    assert '<v SPEAKER_' in vtt


def test_perform_speaker_diarization_without_pyannote_returns_unavailable(
    transcription_module, monkeypatch
):
    """When ``pyannote.audio`` is not importable the function must fail
    gracefully and report ``source='unavailable'`` rather than raising."""
    m = transcription_module
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith('pyannote'):
            raise ImportError("pyannote not installed (simulated)")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', fake_import)
    segments, source = m.perform_speaker_diarization('does_not_exist.wav')
    assert segments is None
    assert source['source'] == 'unavailable'
    assert 'pyannote' in (source.get('error') or '').lower()


def test_perform_speaker_diarization_fails_cleanly_on_load_error(
    transcription_module, monkeypatch
):
    """When Pipeline.from_pretrained raises for any reason, fail gracefully."""
    m = transcription_module
    try:
        import pyannote.audio  # noqa: F401
    except Exception:
        pytest.skip("pyannote.audio not available")

    import pyannote.audio as pa
    original = pa.Pipeline.from_pretrained

    def boom(*args, **kwargs):
        raise OSError("simulated load failure")

    monkeypatch.setattr(pa.Pipeline, 'from_pretrained', boom)
    segments, source = m.perform_speaker_diarization(
        'does_not_exist.wav')
    assert segments is None
    assert source['source'] == 'unavailable'
    monkeypatch.setattr(pa.Pipeline, 'from_pretrained', original)
