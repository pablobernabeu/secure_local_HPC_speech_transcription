"""Tests for the offline-aware diarisation resolution policy.

These tests exercise the pure resolution helper ``_resolve_diarization_strategy``
and the offline-mode env-var detection in ``transcription.py``. They do not
require ``pyannote.audio`` and do not perform any network call.

The integration with the real pyannote loader is also exercised here through
a monkeypatched ``Pipeline.from_pretrained``, gated behind an
``importorskip("pyannote.audio")`` so the test is skipped in environments
that lack the optional dependency.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import transcription  # noqa: E402
from transcription import _is_offline_mode, _resolve_diarization_strategy  # noqa: E402


# ---------------------------------------------------------------------------
# _is_offline_mode
# ---------------------------------------------------------------------------

def test_offline_mode_unset_is_false():
    assert _is_offline_mode(env={}) is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", "  1  "])
def test_offline_mode_truthy_hf_hub_offline(value):
    assert _is_offline_mode(env={"HF_HUB_OFFLINE": value}) is True


@pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
def test_offline_mode_truthy_transformers_offline(value):
    assert _is_offline_mode(env={"TRANSFORMERS_OFFLINE": value}) is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
def test_offline_mode_falsy_values(value):
    assert _is_offline_mode(env={"HF_HUB_OFFLINE": value}) is False


def test_offline_mode_either_var_independently():
    # If TRANSFORMERS_OFFLINE is set but HF_HUB_OFFLINE is explicitly off,
    # offline mode is still active (either variable triggers it).
    env = {"HF_HUB_OFFLINE": "0", "TRANSFORMERS_OFFLINE": "1"}
    assert _is_offline_mode(env=env) is True


# ---------------------------------------------------------------------------
# _resolve_diarization_strategy
# ---------------------------------------------------------------------------

def test_strategy_default_only_hf_loader():
    plan = _resolve_diarization_strategy(env={})
    assert plan['offline_mode'] is False
    assert len(plan['attempts']) == 1
    only = plan['attempts'][0]
    assert only['kind'] == 'hf_loader'
    assert only['source_label'] == 'hf_loader'
    assert only['path'] == 'pyannote/speaker-diarization-3.1'


def test_strategy_offline_marks_hf_loader_label():
    plan = _resolve_diarization_strategy(env={"HF_HUB_OFFLINE": "1"})
    assert plan['offline_mode'] is True
    assert plan['attempts'][-1]['source_label'] == 'hf_loader_offline'


def test_strategy_local_path_precedes_hf_loader():
    plan = _resolve_diarization_strategy(model_path="/srv/models/diar", env={})
    kinds = [a['kind'] for a in plan['attempts']]
    assert kinds == ['local_path', 'hf_loader']
    assert plan['attempts'][0]['path'] == '/srv/models/diar'
    assert plan['attempts'][0]['source_label'] == 'local_path'


def test_strategy_local_config_precedes_local_path():
    plan = _resolve_diarization_strategy(
        model_path="/srv/models/diar",
        diarization_config="/srv/configs/diar.yaml",
        env={},
    )
    kinds = [a['kind'] for a in plan['attempts']]
    assert kinds == ['local_config', 'local_path', 'hf_loader']
    assert plan['attempts'][0]['source_label'] == 'local_config'


def test_strategy_offline_with_local_config_still_marks_hf_loader_offline():
    plan = _resolve_diarization_strategy(
        diarization_config="/srv/configs/diar.yaml",
        env={"TRANSFORMERS_OFFLINE": "1"},
    )
    assert plan['offline_mode'] is True
    # Local-config label is independent of offline mode.
    assert plan['attempts'][0]['source_label'] == 'local_config'
    assert plan['attempts'][-1]['source_label'] == 'hf_loader_offline'


def test_strategy_custom_model_id_threads_through():
    plan = _resolve_diarization_strategy(
        model_id="acme/speaker-diar-v2", env={},
    )
    assert plan['attempts'][-1]['path'] == 'acme/speaker-diar-v2'


# ---------------------------------------------------------------------------
# Integration with the real perform_speaker_diarization (mocked loader)
# ---------------------------------------------------------------------------

@pytest.fixture
def pyannote_audio():
    """Skip only the tests that need pyannote.audio.

    A module-level importorskip here skipped the whole module, including
    the pure tests above, on every machine without pyannote (TESTS-03).
    """
    return pytest.importorskip("pyannote.audio")


class _FakeDiarization:
    """Minimal stand-in for a pyannote ``Annotation`` object."""

    def itertracks(self, yield_label=True):
        yield from []


class _FakePipeline:
    """Mimics ``pyannote.audio.Pipeline`` for the resolution tests."""

    def __init__(self, source_path, **kwargs):
        self.source_path = source_path
        self.kwargs = kwargs

    def to(self, device):
        return self

    def __call__(self, audio_path):
        return _FakeDiarization()


def test_integration_hf_loader_offline_passes_local_files_only(monkeypatch, pyannote_audio):
    """In offline mode the HF loader call must request ``local_files_only=True``."""
    captured = {}

    def fake_from_pretrained(model_id_or_path, **kwargs):
        captured['model_id_or_path'] = model_id_or_path
        captured['kwargs'] = dict(kwargs)
        return _FakePipeline(model_id_or_path, **kwargs)

    monkeypatch.setattr(
        pyannote_audio.Pipeline, "from_pretrained",
        staticmethod(fake_from_pretrained),
    )
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)

    segments, source_info = transcription.perform_speaker_diarization(
        audio_path="dummy.wav",
    )
    assert segments == []
    assert source_info['source'] == 'hf_loader_offline'
    assert source_info['offline_mode'] is True
    assert source_info['error'] is None
    assert captured['kwargs'].get('local_files_only') is True


def test_integration_local_config_takes_precedence(monkeypatch, tmp_path, pyannote_audio):
    """``diarization_config`` short-circuits the HF loader."""
    calls = []

    def fake_from_pretrained(model_id_or_path, **kwargs):
        calls.append((model_id_or_path, dict(kwargs)))
        return _FakePipeline(model_id_or_path, **kwargs)

    monkeypatch.setattr(
        pyannote_audio.Pipeline, "from_pretrained",
        staticmethod(fake_from_pretrained),
    )
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)

    cfg = tmp_path / "diar.yaml"
    cfg.write_text("placeholder: true\n", encoding="utf-8")

    segments, source_info = transcription.perform_speaker_diarization(
        audio_path="dummy.wav",
        diarization_config=str(cfg),
    )
    assert segments == []
    assert source_info['source'] == 'local_config'
    assert source_info['model_path'] == str(cfg)
    # Only one call: the local_config attempt. HF loader must not be reached.
    assert len(calls) == 1
    assert calls[0][0] == str(cfg)


def test_integration_offline_cache_miss_returns_clear_error(monkeypatch, pyannote_audio):
    """When the HF loader fails in offline mode, the error names the cache path."""

    def failing_from_pretrained(model_id_or_path, **kwargs):
        raise OSError("model files not found in local cache")

    monkeypatch.setattr(
        pyannote_audio.Pipeline, "from_pretrained",
        staticmethod(failing_from_pretrained),
    )
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)

    segments, source_info = transcription.perform_speaker_diarization(
        audio_path="dummy.wav",
    )
    assert segments is None
    assert source_info['source'] == 'unavailable'
    assert source_info['offline_mode'] is True
    err = source_info['error']
    assert err is not None
    assert "offline mode" in err.lower()
    assert "models--pyannote--speaker-diarization-3.1" in err
    assert "--diarization-model-path" in err or "--diarization-config" in err
