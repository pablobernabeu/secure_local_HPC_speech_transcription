"""Stage-1 fix DEPS-10 in benchmark_anonymisation: the pyannote token keyword.

pyannote.audio 3.x takes ``use_auth_token``; 4.x takes ``token`` and
rejects the old name. The loaders here passed ``use_auth_token``
unconditionally. They now choose the keyword from the signature, and load
the diarisation pipeline at the revision evaluation/revisions.py pins.
pyannote and torch are replaced by stand-ins, so nothing is downloaded.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation import benchmark_anonymisation as ba  # noqa: E402
from evaluation.revisions import revision_for  # noqa: E402

PINNED = revision_for(ba.DIARISATION_PIPELINE)


class TestTokenKeyword:
    def test_pyannote_3_takes_use_auth_token(self):
        def from_pretrained(checkpoint, hparams_file=None, use_auth_token=None,
                            cache_dir=None):
            pass
        assert ba._token_kwargs(from_pretrained, "t") == {"use_auth_token": "t"}

    def test_pyannote_4_takes_token(self):
        def from_pretrained(checkpoint, revision=None, token=None):
            pass
        assert ba._token_kwargs(from_pretrained, "t") == {"token": "t"}

    def test_both_spellings_prefer_token(self):
        def loader(checkpoint, token=None, use_auth_token=None):
            pass
        assert ba._token_kwargs(loader, "t") == {"token": "t"}

    def test_open_keywords_get_token(self):
        def loader(checkpoint, **kwargs):
            pass
        assert ba._token_kwargs(loader, "t") == {"token": "t"}

    def test_a_loader_without_either_gets_nothing(self):
        def loader(checkpoint):
            pass
        assert ba._token_kwargs(loader, "t") == {}

    def test_an_unreadable_signature_gets_nothing(self):
        # Some builtins expose no signature; inspect raises ValueError.
        assert ba._token_kwargs(max, "t") == {}


class TestPinnedCheckpoint:
    def test_pyannote_3_pins_through_the_checkpoint_name(self):
        def from_pretrained(checkpoint, use_auth_token=None):
            pass
        assert PINNED is not None
        assert ba._pinned_checkpoint(from_pretrained, ba.DIARISATION_PIPELINE) == (
            f"{ba.DIARISATION_PIPELINE}@{PINNED}", {})

    def test_a_revision_keyword_is_used_when_there_is_one(self):
        def from_pretrained(checkpoint, revision=None, token=None):
            pass
        assert ba._pinned_checkpoint(from_pretrained, ba.DIARISATION_PIPELINE) == (
            ba.DIARISATION_PIPELINE, {"revision": PINNED})

    def test_an_unpinned_repository_loads_as_before(self):
        def from_pretrained(checkpoint, revision=None):
            pass
        assert ba._pinned_checkpoint(from_pretrained, "not/pinned") == (
            "not/pinned", {})


def _install_fakes(monkeypatch, pipeline_cls, embedding_fn):
    """Put stand-in torch and pyannote modules in sys.modules."""
    torch = types.ModuleType("torch")
    torch.device = lambda name: name
    torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    torch.Tensor = type("Tensor", (), {})      # probed by scipy's array API
    pyannote = types.ModuleType("pyannote")
    audio = types.ModuleType("pyannote.audio")
    audio.Pipeline = pipeline_cls
    pipelines = types.ModuleType("pyannote.audio.pipelines")
    verification = types.ModuleType("pyannote.audio.pipelines.speaker_verification")
    verification.PretrainedSpeakerEmbedding = embedding_fn
    for name, module in {"torch": torch, "pyannote": pyannote,
                         "pyannote.audio": audio,
                         "pyannote.audio.pipelines": pipelines,
                         "pyannote.audio.pipelines.speaker_verification":
                             verification}.items():
        monkeypatch.setitem(sys.modules, name, module)


class _Loaded:
    """A loaded pipeline carrying an embedding model, as 3.1 does."""

    _embedding = staticmethod(lambda tensor: tensor)
    embedding = "pyannote/wespeaker-voxceleb-resnet34-LM"

    def to(self, device):
        return self


def test_the_pyannote_3_pipeline_gets_the_old_keyword_and_the_pin(monkeypatch):
    seen = {}

    class Pipeline:
        @classmethod
        def from_pretrained(cls, checkpoint, hparams_file=None,
                            use_auth_token=None, cache_dir=None):
            seen.update(checkpoint=checkpoint, use_auth_token=use_auth_token)
            return _Loaded()

    _install_fakes(monkeypatch, Pipeline, lambda *a, **k: pytest.fail("fallback"))
    _, source = ba._load_embedder("tok")
    assert seen == {"checkpoint": f"{ba.DIARISATION_PIPELINE}@{PINNED}",
                    "use_auth_token": "tok"}
    assert "via the diarisation pipeline" in source


def test_the_pyannote_4_pipeline_gets_token_and_revision(monkeypatch):
    seen = {}

    class Pipeline:
        @classmethod
        def from_pretrained(cls, checkpoint, revision=None, hparams_file=None,
                            token=None, cache_dir=None):
            seen.update(checkpoint=checkpoint, revision=revision, token=token)
            return _Loaded()

    _install_fakes(monkeypatch, Pipeline, lambda *a, **k: pytest.fail("fallback"))
    ba._load_embedder("tok")
    assert seen == {"checkpoint": ba.DIARISATION_PIPELINE, "revision": PINNED,
                    "token": "tok"}


def test_the_fallback_embedding_gets_the_keyword_its_signature_names(monkeypatch):
    seen = {}

    class Pipeline:
        @classmethod
        def from_pretrained(cls, checkpoint, token=None):
            raise RuntimeError("gated")

    def PretrainedSpeakerEmbedding(embedding, device=None, token=None):  # noqa: N802
        seen.update(embedding=embedding, token=token)
        return lambda tensor: tensor

    _install_fakes(monkeypatch, Pipeline, PretrainedSpeakerEmbedding)
    _, source = ba._load_embedder("tok")
    assert seen == {"embedding": "pyannote/wespeaker-voxceleb-resnet34-LM",
                    "token": "tok"}
    assert source == "pyannote/wespeaker-voxceleb-resnet34-LM"


# ---------------------------------------------------------------------------
# Why a fallback happened is recorded, not only printed
# ---------------------------------------------------------------------------

WESPEAKER = "pyannote/wespeaker-voxceleb-resnet34-LM"


def _pipeline_returning(result=None, error=None):
    """A pyannote 3.x Pipeline whose loader returns *result* or raises *error*."""

    class Pipeline:
        @classmethod
        def from_pretrained(cls, checkpoint, hparams_file=None,
                            use_auth_token=None, cache_dir=None):
            if error is not None:
                raise error
            return result

    return Pipeline


def _embedding_loading(*failing):
    """PretrainedSpeakerEmbedding that fails for the names in *failing*."""
    def PretrainedSpeakerEmbedding(embedding, device=None, use_auth_token=None):  # noqa: N802
        if embedding in failing:
            raise OSError(f"{embedding} is not cached")
        return lambda tensor: tensor
    return PretrainedSpeakerEmbedding


def test_a_loaded_pipeline_records_no_failure(monkeypatch):
    _install_fakes(monkeypatch, _pipeline_returning(_Loaded()),
                   lambda *a, **k: pytest.fail("fallback"))
    failures = {}
    ba._load_embedder("tok", failures=failures)
    assert failures == {}


@pytest.mark.parametrize("pipeline, reason", [
    (_pipeline_returning(error=RuntimeError("gated")), "RuntimeError: gated"),
    (_pipeline_returning(None), "pyannote returned no pipeline"),
    (_pipeline_returning(types.SimpleNamespace(to=lambda device: None)),
     "no embedding model"),
], ids=["raises", "returns-none", "no-embedding"])
def test_why_the_pipeline_was_not_reused_is_recorded(monkeypatch, capsys,
                                                      pipeline, reason):
    """Each way the pipeline can fail, including the two that raised nothing
    and so were not reported at all."""
    _install_fakes(monkeypatch, pipeline, _embedding_loading())
    failures = {}
    _, source = ba._load_embedder("tok", failures=failures)
    assert source == WESPEAKER
    assert list(failures) == [ba.DIARISATION_PIPELINE]
    assert reason in failures[ba.DIARISATION_PIPELINE]
    assert "could not reuse the diarisation pipeline" in capsys.readouterr().err


def test_a_failed_fallback_model_is_recorded_too(monkeypatch):
    _install_fakes(monkeypatch, _pipeline_returning(error=RuntimeError("gated")),
                   _embedding_loading(WESPEAKER))
    failures = {}
    _, source = ba._load_embedder("tok", failures=failures)
    assert source == "pyannote/embedding"
    assert failures == {ba.DIARISATION_PIPELINE: "RuntimeError: gated",
                        WESPEAKER: f"OSError: {WESPEAKER} is not cached"}


def test_when_nothing_loads_every_reason_is_given(monkeypatch):
    _install_fakes(monkeypatch, _pipeline_returning(error=RuntimeError("gated")),
                   _embedding_loading(WESPEAKER, "pyannote/embedding"))
    with pytest.raises(SystemExit) as exit_:
        ba._load_embedder("tok")
    message = str(exit_.value)
    assert "RuntimeError: gated" in message
    assert f"{WESPEAKER}: OSError" in message
    assert "pyannote/embedding: OSError" in message
