"""The manifest and headers record what the run actually used.

Audit findings T3-09 and T3-10: an English default applied because
detection failed was recorded as if English had been chosen, and the
manifest omitted settings that change the output (masking languages and
lists, diarisation settings, software versions) while its 'timestamps'
field said false for a --speaker-attribution run that wrote JSON/VTT.
"""

from __future__ import annotations

import contextlib
import io
import json

import pytest


def _fake_result(*_args, **_kwargs):
    return {'text': 'hello there.',
            'chunks': [{'text': 'hello', 'timestamp': (0.0, 0.4)},
                       {'text': 'there.', 'timestamp': (0.5, 0.9)}]}


@pytest.fixture()
def run(transcription_module, tmp_path, monkeypatch):
    m = transcription_module
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(m, "AUDIO_LIBS_AVAILABLE", True)
    monkeypatch.setattr(m, "TRANSFORMERS_AVAILABLE", True)
    monkeypatch.setattr(m, "transcribe_audio_only", _fake_result)
    monkeypatch.setattr(
        m, "perform_speaker_diarization",
        lambda *_a, **_k: ([{'start': 0.0, 'end': 1.0, 'speaker': 'SPEAKER_00'}],
                           {'source': 'local_config', 'model_id': 'x',
                            'model_path': 'cfg.yaml', 'error': None}))
    (tmp_path / "rec.wav").write_bytes(b"RIFF0000WAVE")
    out = tmp_path / "output" / "transcripts"

    def _run(**kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            assert m.process_audio_file(str(tmp_path / "rec.wav"), **kwargs)
        manifest = json.loads((out / "rec_manifest.json").read_text("utf-8"))
        return manifest['provenance'], out

    return _run


def test_assumed_language_is_recorded_as_assumed(run):
    prov, out = run()
    assert prov['language'] == 'english'
    assert prov['language_requested'] is None
    assert prov['language_detected'] is None
    assert prov['language_assumed'] is True
    txt = (out / "rec_transcript.txt").read_text("utf-8")
    assert "Language: English (assumed for post-processing" in txt


def test_requested_language_is_not_assumed(run):
    prov, out = run(language="english", timestamps=True)
    assert prov['language_requested'] == 'english'
    assert prov['language_assumed'] is False
    payload = json.loads((out / "rec_transcript.json").read_text("utf-8"))
    assert payload['pipeline']['language_assumed'] is False
    assert payload['pipeline']['language_requested'] == 'english'


def test_settings_that_change_output_are_recorded(run):
    prov, _ = run(language="english", speaker_attribution=True,
                  mask_names=True, selected_languages=['english'],
                  excluded_names={'sarah', 'john'}, num_speakers=2,
                  diarization_config='cfg.yaml')
    assert prov['timestamps'] is False
    assert prov['timestamped_artefacts_written'] is True
    masking = prov['name_masking_settings']
    assert masking['languages'] == ['english']
    assert masking['exclude_common_words'] is True
    assert masking['excluded_names']['count'] == 2
    assert len(masking['excluded_names']['sha256']) == 64
    assert 'sarah' not in json.dumps(prov)
    diar = prov['diarization_settings']
    assert diar['source'] == 'local_config'
    assert diar['num_speakers'] == 2
    assert diar['config'] == 'cfg.yaml'
    software = prov['software']
    assert software['packages']['python']
    assert 'torch' in software['packages']
    assert 'git_commit' in software

def test_the_loaded_model_snapshot_is_recorded(run, transcription_module, monkeypatch):
    """The Hub commit transformers resolved reaches the manifest and the JSON
    (DEPS-04); the fake above sets none, so it is recorded as None there."""
    m = transcription_module
    rev = "06f233fe06e710322aca913c1bc4249a0d71fce1"
    monkeypatch.setattr(m, "transcribe_audio_only",
                        lambda *a, **k: dict(_fake_result(), model_revision=rev))
    prov, out = run(language="english", timestamps=True)
    assert prov['asr_model_revision'] == rev
    payload = json.loads((out / "rec_transcript.json").read_text("utf-8"))
    assert payload['pipeline']['asr_model_revision'] == rev


def test_the_diarisation_snapshots_are_recorded(run, transcription_module, monkeypatch):
    """The snapshots the loader read back (DEPS-04) reach the manifest's
    diarisation settings and the JSON pipeline block; a run without speaker
    attribution records no diarisation keys at all."""
    m = transcription_module
    rev = "84fd25912480287da0247647c3d2b4853cb3ee5d"
    sub = {"pyannote/segmentation-3.0": "e66f3d3b9eb0873085418a7b813d3b369bf160bb",
           "pyannote/wespeaker-voxceleb-resnet34-LM": None}
    monkeypatch.setattr(
        m, "perform_speaker_diarization",
        lambda *_a, **_k: ([{'start': 0.0, 'end': 1.0, 'speaker': 'SPEAKER_00'}],
                           {'source': 'hf_loader_offline',
                            'model_id': 'pyannote/speaker-diarization-3.1',
                            'model_path': None, 'model_revision': rev,
                            'sub_model_revisions': sub, 'error': None}))
    prov, out = run(language="english", speaker_attribution=True)
    assert prov['diarization_settings']['model_revision'] == rev
    assert prov['diarization_settings']['sub_model_revisions'] == sub
    payload = json.loads((out / "rec_transcript.json").read_text("utf-8"))
    assert payload['pipeline']['diarization_model_revision'] == rev
    assert payload['pipeline']['diarization_sub_model_revisions'] == sub

    prov, out = run(language="english", timestamps=True)
    assert prov['diarization_settings'] is None
    payload = json.loads((out / "rec_transcript.json").read_text("utf-8"))
    assert not any(key.startswith('diarization_') for key in payload['pipeline'])


def test_review_options_reach_the_review_and_the_manifest(run):
    """The optional checks (NEW-12) change the review whose digest the
    manifest records, so the manifest names them. A default run's manifest
    has no such key and its review no optional_checks block, so both are
    what they were before the checks existed."""
    options = {'flag_zero_duration': True, 'repeated_passage_words': 8,
               'repeated_passage_window_s': 30.0}
    prov, out = run(language="english", timestamps=True,
                    review_options=options)
    assert prov['review_settings'] == options
    review = json.loads((out / "rec_review.json").read_text("utf-8"))
    assert review['optional_checks'] == options

    prov, out = run(language="english", timestamps=True)
    assert 'review_settings' not in prov
    review = json.loads((out / "rec_review.json").read_text("utf-8"))
    assert 'optional_checks' not in review


def test_loaded_model_revision_reads_the_config_commit(transcription_module):
    m = transcription_module

    class _Config:
        _commit_hash = "abc123"

    class _Model:
        config = _Config()

    class _Transcriber:
        model = _Model()

    assert m._loaded_model_revision(_Transcriber()) == "abc123"
    assert m._loaded_model_revision(object()) is None
