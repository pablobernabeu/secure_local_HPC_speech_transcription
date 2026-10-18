"""Speaker-labelled output: no lost words, and both transcripts written.

Audit finding T2-06: the legacy uniform-time labelling wrote "[None]" for
words before the first covered one and dropped everything when no word was
covered, and the plain/speaker dual output was gated on a librosa duration
probe that only the legacy path needs. The end-to-end run also checks the
turn breaks restored for T3-04.
"""

from __future__ import annotations

import contextlib
import io



def test_legacy_path_never_drops_or_mislabels(transcription_module):
    m = transcription_module
    with contextlib.redirect_stdout(io.StringIO()):
        none_covered = m.apply_speaker_labels_to_transcript(
            "hello world again",
            [{'start': 5.0, 'end': 6.0, 'speaker': 'SPEAKER_00'}], None)
        leading = m.apply_speaker_labels_to_transcript(
            "hello world again",
            [{'start': 5.0, 'end': 9.0, 'speaker': 'SPEAKER_00'}], 12.0)
    assert none_covered == "[SPEAKER_UNKNOWN] hello world again"
    assert leading == "[SPEAKER_UNKNOWN] hello world\n\n[SPEAKER_00] again"
    assert "[None]" not in leading


def _fake_result(*_args, **_kwargs):
    return {
        'text': ' Hello there. hi, how are you?',
        'chunks': [
            {'text': ' Hello', 'timestamp': (0.0, 0.4)},
            {'text': ' there.', 'timestamp': (0.5, 0.9)},
            {'text': ' hi,', 'timestamp': (3.0, 3.3)},
            {'text': ' how', 'timestamp': (3.4, 3.6)},
            {'text': ' are', 'timestamp': (3.7, 3.8)},
            {'text': ' you?', 'timestamp': (3.9, 4.2)},
        ],
    }


def test_dual_output_without_a_duration_probe(transcription_module, tmp_path,
                                              monkeypatch):
    m = transcription_module
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(m, "AUDIO_LIBS_AVAILABLE", True)
    monkeypatch.setattr(m, "TRANSFORMERS_AVAILABLE", True)
    monkeypatch.setattr(m, "transcribe_audio_only", _fake_result)
    monkeypatch.setattr(
        m, "perform_speaker_diarization",
        lambda *_a, **_k: ([{'start': 0.0, 'end': 2.0, 'speaker': 'SPEAKER_00'},
                            {'start': 2.5, 'end': 5.0, 'speaker': 'SPEAKER_01'}],
                           {'source': 'local_path', 'model_id': 'x',
                            'model_path': None, 'error': None}))
    (tmp_path / "rec.wav").write_bytes(b"RIFF0000WAVE")
    with contextlib.redirect_stdout(io.StringIO()):
        ok = m.process_audio_file(str(tmp_path / "rec.wav"),
                                  language="english", speaker_attribution=True)
    assert ok is True
    out = tmp_path / "output" / "transcripts"
    plain = (out / "rec_transcript.txt").read_text(encoding="utf-8")
    labelled = (out / "rec_transcript_with_speakers.txt").read_text(
        encoding="utf-8")
    assert "[SPEAKER_" not in plain
    assert "Speaker attribution: Enabled" not in plain
    assert ("[SPEAKER_00] Hello there.\n\n[SPEAKER_01] Hi, how are you?"
            in labelled)
