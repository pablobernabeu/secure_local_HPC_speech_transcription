"""Diarisation loading on the pinned pyannote 3.x behaviour.

Audit findings T2-03, T2-04, T2-11 and T2-12. pyannote 3.x
``Pipeline.from_pretrained`` takes ``use_auth_token`` (no ``token``, no
``local_files_only``), returns ``None`` for a gated model it cannot open,
and loads a local pipeline only from a config file. A fake ``pyannote.audio``
is injected so the tests run without the library.

DEPS-04: the Hub snapshots a load used are read back from pyannote's cache,
laid out here as ``hf_hub_download`` leaves it, without pinning the load.
"""

from __future__ import annotations

import contextlib
import io
import sys
import types
from pathlib import Path

import numpy as np
import pytest


class _Annotation:
    def __init__(self, tracks=()):
        self._tracks = list(tracks)

    def itertracks(self, yield_label=True):
        for start, end, label in self._tracks:
            yield types.SimpleNamespace(start=start, end=end), None, label


class _FakePipeline:
    calls = []

    def __init__(self, source):
        self.source = source
        self.inputs = []

    def to(self, device):
        return self

    def __call__(self, audio, **kwargs):
        self.inputs.append(audio)
        return _Annotation([(0.0, 1.0, 'SPEAKER_00')])


def _install(monkeypatch, from_pretrained):
    pipeline_cls = type("Pipeline", (), {
        "from_pretrained": staticmethod(from_pretrained)})
    audio = types.ModuleType("pyannote.audio")
    audio.Pipeline = pipeline_cls
    root = types.ModuleType("pyannote")
    root.audio = audio
    monkeypatch.setitem(sys.modules, "pyannote", root)
    monkeypatch.setitem(sys.modules, "pyannote.audio", audio)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACE_TOKEN", raising=False)


def _diarise(m, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return m.perform_speaker_diarization("does_not_exist.wav", **kwargs)


def test_gated_model_returning_none_is_reported(transcription_module,
                                                monkeypatch):
    m = transcription_module
    seen = []

    def from_pretrained_3x(checkpoint_path, hparams_file=None,
                           use_auth_token=None, cache_dir=None):
        seen.append(use_auth_token)
        return None

    _install(monkeypatch, from_pretrained_3x)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
    segments, info = _diarise(m)
    assert segments is None
    assert info['source'] == 'unavailable'
    assert "terms of service" in info['error']
    assert "gated model" in info['error']
    assert len(seen) == 1


def test_3x_signature_gets_use_auth_token_only(transcription_module,
                                               monkeypatch):
    m = transcription_module
    seen = {}

    def from_pretrained_3x(checkpoint_path, hparams_file=None,
                           use_auth_token=None, cache_dir=None):
        seen['token'] = use_auth_token
        return _FakePipeline(checkpoint_path)

    _install(monkeypatch, from_pretrained_3x)
    monkeypatch.setenv("HF_TOKEN", "hf_x")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    segments, info = _diarise(m)
    assert segments == [{'start': 0.0, 'end': 1.0, 'speaker': 'SPEAKER_00'}]
    assert info['source'] == 'hf_loader_offline'
    assert seen == {'token': 'hf_x'}


@pytest.mark.parametrize("offline", [False, True])
def test_load_kwargs_follow_the_signature(transcription_module, offline):
    m = transcription_module

    def v3(checkpoint_path, hparams_file=None, use_auth_token=None,
           cache_dir=None):
        pass

    def v4(checkpoint, revision=None, token=None, cache_dir=None):
        pass

    def v_new(checkpoint, token=None, local_files_only=False):
        pass

    def open_kwargs(checkpoint, **kwargs):
        pass

    assert m._pipeline_load_kwargs(v3, "t", offline) == {'use_auth_token': "t"}
    assert m._pipeline_load_kwargs(v4, "t", offline) == {'token': "t"}
    extra = {'local_files_only': True} if offline else {}
    assert m._pipeline_load_kwargs(v_new, "t", offline) == {'token': "t", **extra}
    assert m._pipeline_load_kwargs(open_kwargs, "t", offline) == \
        {'token': "t", **extra}


def test_directory_model_path_loads_its_config(transcription_module,
                                               monkeypatch, tmp_path):
    m = transcription_module
    seen = []

    def from_pretrained(checkpoint_path, hparams_file=None,
                        use_auth_token=None, cache_dir=None):
        seen.append(checkpoint_path)
        return _FakePipeline(checkpoint_path)

    _install(monkeypatch, from_pretrained)
    (tmp_path / "config.yaml").write_text("pipeline: {}\n", encoding="utf-8")
    segments, info = _diarise(m, model_path=str(tmp_path))
    assert info['source'] == 'local_path'
    assert seen == [str(tmp_path / "config.yaml")]


@pytest.mark.parametrize("returns_none", [False, True])
def test_failed_local_pipeline_does_not_fall_back_to_hub(
        transcription_module, monkeypatch, tmp_path, returns_none):
    m = transcription_module
    seen = []

    def from_pretrained(checkpoint_path, hparams_file=None,
                        use_auth_token=None, cache_dir=None):
        seen.append(checkpoint_path)
        return None

    _install(monkeypatch, from_pretrained)
    if returns_none:
        (tmp_path / "config.yaml").write_text("x: 1\n", encoding="utf-8")
    segments, info = _diarise(m, model_path=str(tmp_path))
    assert segments is None
    assert info['source'] == 'unavailable'
    assert "Not falling back" in info['error']
    assert m.DEFAULT_DIARIZATION_MODEL not in seen
    assert len(seen) == (1 if returns_none else 0)


def test_inference_failure_is_not_retried(transcription_module, monkeypatch):
    m = transcription_module
    pipelines = []

    class _Failing(_FakePipeline):
        def __call__(self, audio, **kwargs):
            self.inputs.append(audio)
            raise RuntimeError("CUDA out of memory")

    def from_pretrained(checkpoint_path, hparams_file=None,
                        use_auth_token=None, cache_dir=None):
        pipelines.append(_Failing(checkpoint_path))
        return pipelines[-1]

    _install(monkeypatch, from_pretrained)
    monkeypatch.setattr(m, "_HAS_AUDIO_IO", True)
    monkeypatch.setattr(m, "np", np)
    monkeypatch.setattr(m, "load_audio",
                        lambda *_a, **_k: (np.zeros(1600, dtype=np.float32),
                                           16000), raising=False)
    segments, info = _diarise(m)
    assert segments is None
    assert info['error'] == "diarisation runtime failure: CUDA out of memory"
    assert len(pipelines[0].inputs) == 1
    assert isinstance(pipelines[0].inputs[0], dict)


def test_decode_failure_falls_back_to_the_path(transcription_module,
                                               monkeypatch):
    m = transcription_module
    pipelines = []

    def from_pretrained(checkpoint_path, hparams_file=None,
                        use_auth_token=None, cache_dir=None):
        pipelines.append(_FakePipeline(checkpoint_path))
        return pipelines[-1]

    def bad_decode(*_a, **_k):
        raise RuntimeError("no decoder")

    _install(monkeypatch, from_pretrained)
    monkeypatch.setattr(m, "_HAS_AUDIO_IO", True)
    monkeypatch.setattr(m, "load_audio", bad_decode, raising=False)
    segments, _ = _diarise(m)
    assert segments is not None
    assert pipelines[0].inputs == ["does_not_exist.wav"]


def _isolate_token_sources(monkeypatch, tmp_path):
    """Hide every token source outside *tmp_path* from the shared lookup.

    Clears the token and Hub-home variables, points ``Path.home`` and
    preflight's repository root at empty directories under *tmp_path*, and
    changes into another empty one, so only what the test writes is found.

    Returns:
        ``(repo, work)``: the stand-in repository root and working directory.
    """
    import preflight

    for var in ("HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGING_FACE_HUB_TOKEN",
                "HF_TOKEN_PATH", "HF_HOME", "XDG_CACHE_HOME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(Path, "home",
                        classmethod(lambda cls: tmp_path / "home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(preflight, "_REPO_ROOT", repo)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    return repo, work


@pytest.mark.parametrize("source", [
    "HF_HOME", "HF_TOKEN_PATH", "HUGGING_FACE_HUB_TOKEN", "repo", "cwd"])
def test_pipeline_reads_the_token_preflight_finds(transcription_module,
                                                  monkeypatch, tmp_path,
                                                  source):
    """The token preflight reports is the one the diarisation loader gets.

    Audit findings PIPE-02 and INTEG-04: the pipeline delegates its lookup
    to preflight so that both see a ``huggingface-cli login`` token
    (``<HF_HOME>/token`` or ``$HF_TOKEN_PATH``) and
    ``HUGGING_FACE_HUB_TOKEN``. Only an end-to-end check catches a
    reverted delegation, since ``HF_TOKEN`` is read either way. The
    ``hf_token.txt`` cases keep the repository-root and working-directory
    files covered through the same path.
    """
    import preflight
    from evaluation import ami_meetings

    m = transcription_module
    seen = {}

    def from_pretrained_3x(checkpoint_path, hparams_file=None,
                           use_auth_token=None, cache_dir=None):
        seen['token'] = use_auth_token
        return _FakePipeline(checkpoint_path)

    _install(monkeypatch, from_pretrained_3x)
    repo, work = _isolate_token_sources(monkeypatch, tmp_path)
    hf_home = tmp_path / "hfhome"
    hf_home.mkdir()
    token_file = {"HF_HOME": hf_home / "token",
                  "HF_TOKEN_PATH": hf_home / "token",
                  "repo": repo / "hf_token.txt",
                  "cwd": work / "hf_token.txt"}.get(source)
    if token_file is not None:
        token_file.write_text("hf_found\n", encoding="utf-8")
    if source == "HF_HOME":
        monkeypatch.setenv("HF_HOME", str(hf_home))
    elif source == "HF_TOKEN_PATH":
        monkeypatch.setenv("HF_TOKEN_PATH", str(token_file))
    elif source == "HUGGING_FACE_HUB_TOKEN":
        monkeypatch.setenv("HUGGING_FACE_HUB_TOKEN", "hf_found")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")

    segments, info = _diarise(m)
    assert info['source'] == 'hf_loader_offline'
    assert seen == {'token': 'hf_found'}
    assert (m._resolve_hf_token() == ami_meetings.load_hf_token()
            == preflight.resolve_hf_token()[0] == 'hf_found')


def test_pipeline_passes_no_token_when_none_is_configured(
        transcription_module, monkeypatch, tmp_path):
    m = transcription_module
    seen = {}

    def from_pretrained_3x(checkpoint_path, hparams_file=None,
                           use_auth_token=None, cache_dir=None):
        seen['token'] = use_auth_token
        return _FakePipeline(checkpoint_path)

    _install(monkeypatch, from_pretrained_3x)
    _isolate_token_sources(monkeypatch, tmp_path)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    _diarise(m)
    assert seen == {'token': None}


# ---------------------------------------------------------------------------
# DEPS-04: the snapshots a load used
# ---------------------------------------------------------------------------

PIPELINE = "pyannote/speaker-diarization-3.1"
SEGMENTATION = "pyannote/segmentation-3.0"
EMBEDDING = "pyannote/wespeaker-voxceleb-resnet34-LM"
# The 3.1 pipeline's config.yaml, as the ARC cache holds it, less the
# hyperparameters.
CONFIG = (
    "version: 3.1.0\n"
    "pipeline:\n"
    "  name: pyannote.audio.pipelines.SpeakerDiarization\n"
    "  params:\n"
    "    clustering: AgglomerativeClustering\n"
    f"    embedding: {EMBEDDING}\n"
    "    embedding_batch_size: 32\n"
    f"    segmentation: {SEGMENTATION}\n"
)


def _snapshot(cache, repo, commit, files, ref="main"):
    """Lay out one snapshot of *repo* in *cache* as hf_hub_download leaves it.

    With *ref*, ``refs/<ref>`` names *commit*, as a load of that branch
    records it.
    """
    root = cache / ("models--" + repo.replace("/", "--"))
    snapshot = root / "snapshots" / commit
    snapshot.mkdir(parents=True)
    for name, text in files.items():
        (snapshot / name).write_text(text, encoding="utf-8")
    if ref:
        (root / "refs").mkdir(exist_ok=True)
        (root / "refs" / ref).write_text(commit, encoding="utf-8")
    return snapshot


def _point_pyannote_at(monkeypatch, cache):
    """Make preflight.pyannote_cache_dir() return *cache*.

    It reads CACHE_DIR from an imported pyannote.audio.core.model, the
    constant the real loaders default to, so a stand-in module carries it.
    """
    model = types.ModuleType("pyannote.audio.core.model")
    model.CACHE_DIR = str(cache)
    monkeypatch.setitem(sys.modules, "pyannote.audio.core.model", model)


@pytest.fixture()
def pyannote_cache(tmp_path, monkeypatch):
    """A pyannote cache holding the pipeline and the two models it names."""
    pytest.importorskip("huggingface_hub")
    pytest.importorskip("yaml")
    cache = tmp_path / "pyannote_cache"
    _point_pyannote_at(monkeypatch, cache)
    _snapshot(cache, PIPELINE, "a" * 40, {"config.yaml": CONFIG})
    _snapshot(cache, SEGMENTATION, "b" * 40, {"pytorch_model.bin": "w"})
    _snapshot(cache, EMBEDDING, "c" * 40, {"pytorch_model.bin": "w"})
    return cache


def _loads(monkeypatch):
    """Install a pyannote whose loader succeeds, offline, and record its calls."""
    seen = []

    def from_pretrained(checkpoint_path, hparams_file=None,
                        use_auth_token=None, cache_dir=None):
        seen.append(checkpoint_path)
        return _FakePipeline(checkpoint_path)

    _install(monkeypatch, from_pretrained)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    return seen


def test_the_hub_load_records_the_snapshots_it_used(
        transcription_module, monkeypatch, pyannote_cache):
    seen = _loads(monkeypatch)
    segments, info = _diarise(transcription_module)
    assert segments and info['source'] == 'hf_loader_offline'
    # The load itself is not pinned.
    assert seen == [PIPELINE]
    assert info['model_revision'] == "a" * 40
    assert info['sub_model_revisions'] == {SEGMENTATION: "b" * 40,
                                           EMBEDDING: "c" * 40}
    # Sorted, although the config names the embedding model first.
    assert list(info['sub_model_revisions']) == [SEGMENTATION, EMBEDDING]


def test_the_snapshot_main_names_is_the_one_recorded(
        transcription_module, monkeypatch, pyannote_cache):
    """Two cached snapshots: the one refs/main names is the one loaded. A
    model the config names with a revision is read at that revision."""
    pinned = SEGMENTATION + "@" + "e" * 40
    _snapshot(pyannote_cache, PIPELINE, "d" * 40,
              {"config.yaml": CONFIG.replace(SEGMENTATION, pinned)})
    _snapshot(pyannote_cache, SEGMENTATION, "e" * 40,
              {"pytorch_model.bin": "w2"}, ref=None)
    _loads(monkeypatch)
    _, info = _diarise(transcription_module)
    assert info['model_revision'] == "d" * 40
    assert info['sub_model_revisions'] == {SEGMENTATION: "e" * 40,
                                           EMBEDDING: "c" * 40}


def test_a_checkpoint_with_a_revision_records_that_revision(
        transcription_module, monkeypatch, pyannote_cache):
    _snapshot(pyannote_cache, PIPELINE, "d" * 40, {"config.yaml": CONFIG})
    _loads(monkeypatch)
    _, info = _diarise(transcription_module,
                       model_id=PIPELINE + "@" + "a" * 40)
    assert info['model_revision'] == "a" * 40


def test_an_unresolvable_snapshot_is_recorded_as_none(
        transcription_module, monkeypatch, tmp_path, pyannote_cache):
    """A cache that does not hold the pipeline, and no huggingface_hub."""
    _loads(monkeypatch)
    _point_pyannote_at(monkeypatch, tmp_path / "empty")
    _, info = _diarise(transcription_module)
    assert info['source'] == 'hf_loader_offline' and info['error'] is None
    assert (info['model_revision'], info['sub_model_revisions']) == (None, None)

    _point_pyannote_at(monkeypatch, pyannote_cache)
    monkeypatch.setitem(sys.modules, "huggingface_hub", None)
    _, info = _diarise(transcription_module)
    assert (info['model_revision'], info['sub_model_revisions']) == (None, None)


def test_a_local_pipeline_records_the_cached_models_it_names(
        transcription_module, monkeypatch, tmp_path, pyannote_cache):
    """A local config is no Hub snapshot, but the models it names by Hub id
    come from the cache; checkpoints on disk are not Hub models."""
    _loads(monkeypatch)
    local = tmp_path / "local"
    local.mkdir()
    config = local / "config.yaml"
    config.write_text(CONFIG, encoding="utf-8")
    _, info = _diarise(transcription_module, diarization_config=str(config))
    assert info['source'] == 'local_config'
    assert info['model_revision'] is None
    assert info['sub_model_revisions'] == {SEGMENTATION: "b" * 40,
                                           EMBEDDING: "c" * 40}

    for name in ("segmentation.ckpt", "embedding.ckpt"):
        (local / name).write_bytes(b"weights")
    config.write_text(CONFIG.replace(SEGMENTATION, (local / "segmentation.ckpt").as_posix())
                      .replace(EMBEDDING, (local / "embedding.ckpt").as_posix()),
                      encoding="utf-8")
    _, info = _diarise(transcription_module, model_path=str(local))
    assert info['source'] == 'local_path'
    assert (info['model_revision'], info['sub_model_revisions']) == (None, {})


def test_an_unreadable_config_names_no_revisions(transcription_module, tmp_path):
    pytest.importorskip("yaml")
    bad = tmp_path / "config.yaml"
    bad.write_text("pipeline: [not, a, mapping]\n", encoding="utf-8")
    assert transcription_module._sub_model_revisions(bad) is None
    assert transcription_module._sub_model_revisions(tmp_path / "absent.yaml") is None


def test_an_offline_cache_miss_names_the_cache_pyannote_reads(
        transcription_module, monkeypatch, tmp_path):
    """The message used to name the hub cache under HF_HOME, which
    pyannote 3.x never reads, so filling it did not help (CORE-R3)."""
    def from_pretrained(checkpoint_path, hparams_file=None,
                        use_auth_token=None, cache_dir=None):
        raise OSError("not in the local cache")

    _install(monkeypatch, from_pretrained)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    hf_home = tmp_path / "hf_home"
    monkeypatch.setenv("HF_HOME", str(hf_home))
    cache = tmp_path / "pyannote_cache"
    _point_pyannote_at(monkeypatch, cache)
    segments, info = _diarise(transcription_module)
    assert segments is None and info['source'] == 'unavailable'
    expected = str(cache / "models--pyannote--speaker-diarization-3.1")
    assert f"'{expected}'" in info['error']
    assert str(hf_home) not in info['error']
    assert "Underlying error: OSError: not in the local cache" in info['error']


def test_a_load_failure_names_the_exception_type(transcription_module,
                                                 monkeypatch, tmp_path):
    """The audit wave's case study logged only "Underlying error: 'name'":
    a KeyError raised reading a pipeline config without a name (a test had
    overwritten the cached one). The record now carries the type."""
    def from_pretrained(checkpoint_path, hparams_file=None,
                        use_auth_token=None, cache_dir=None):
        config = {"pipeline": {"params": {}}}
        return config["pipeline"]["name"]

    _install(monkeypatch, from_pretrained)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
    segments, info = _diarise(transcription_module)
    assert segments is None
    assert info['error'].endswith("Underlying error: KeyError: 'name'")

    config = tmp_path / "config.yaml"
    config.write_text("pipeline: {}\n", encoding="utf-8")
    _, info = _diarise(transcription_module, diarization_config=str(config))
    assert "Last error: local config failed: KeyError: 'name'" in info['error']


# What the ARC test runs wrote over the cached pipeline config (NEW-INC-01):
# no pipeline.name.
_STUB_CONFIG = (f"pipeline:\n  params:\n    embedding: {EMBEDDING}\n"
                f"    segmentation: {SEGMENTATION}\n")


def _fails_on_name(monkeypatch):
    """Install a pyannote whose Hub load fails as it did on the stub."""
    def from_pretrained(checkpoint_path, hparams_file=None,
                        use_auth_token=None, cache_dir=None):
        config = {"pipeline": {"params": {}}}
        return config["pipeline"]["name"]

    _install(monkeypatch, from_pretrained)


def _damaged_cache(monkeypatch, tmp_path):
    """Point pyannote's cache at one whose pipeline config is the stub.

    Returns the stub's path.
    """
    cache = tmp_path / "pyannote_cache"
    _point_pyannote_at(monkeypatch, cache)
    return _snapshot(cache, PIPELINE, "a" * 40, {"config.yaml": _STUB_CONFIG}) / "config.yaml"


@pytest.mark.parametrize("offline", [False, True])
def test_a_damaged_cached_config_is_named_in_place_of_the_token_advice(
        transcription_module, monkeypatch, tmp_path, offline):
    """The audit wave's case study was told to check its token. The cause
    was the damaged cached config, which neither a token nor a download
    repairs, and the error now says so."""
    _fails_on_name(monkeypatch)
    for var in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
        monkeypatch.delenv(var, raising=False)
    if offline:
        monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("HF_TOKEN", "hf_x")
    config = _damaged_cache(monkeypatch, tmp_path)
    segments, info = _diarise(transcription_module)
    assert segments is None and info['source'] == 'unavailable'
    error = info['error']
    assert (f"The cached pipeline config is damaged: {config} has no "
            "pipeline.name") in error
    assert "Neither a token nor a new download repairs it." in error
    assert f"Fix: delete {config}, then fetch it again" in error
    assert "Ensure a HuggingFace token" not in error
    assert "pre-populated" not in error
    assert "No HuggingFace token was found" not in error
    assert error.endswith("Underlying error: KeyError: 'name'")


def test_a_damaged_cached_config_still_names_a_missing_token(
        transcription_module, monkeypatch, tmp_path):
    """Fetching the file again needs a token, so its absence is named too."""
    _fails_on_name(monkeypatch)
    for var in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
        monkeypatch.delenv(var, raising=False)
    _isolate_token_sources(monkeypatch, tmp_path)
    _damaged_cache(monkeypatch, tmp_path)
    _, info = _diarise(transcription_module)
    assert "The cached pipeline config is damaged" in info['error']
    assert "No HuggingFace token was found either" in info['error']


def test_only_the_pipeline_preflight_checks_is_reported_damaged(
        transcription_module, monkeypatch, tmp_path):
    _fails_on_name(monkeypatch)
    for var in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HF_TOKEN", "hf_x")
    _damaged_cache(monkeypatch, tmp_path)
    # Another checkpoint: the damaged 3.1 config says nothing about it.
    _, info = _diarise(transcription_module,
                       model_id="pyannote/speaker-diarization-community-1")
    assert "damaged" not in info['error']
    assert "Ensure a HuggingFace token" in info['error']
    # The same pipeline at a revision is the one preflight checks.
    _, info = _diarise(transcription_module, model_id=PIPELINE + "@" + "a" * 40)
    assert "The cached pipeline config is damaged" in info['error']


@pytest.mark.parametrize("offline", [False, True])
def test_a_failing_damage_check_leaves_the_usual_message(
        transcription_module, monkeypatch, tmp_path, offline):
    """Only the message depends on the damage check, so a check that raises
    leaves the load error as it would be without the check, here even over a
    damaged cache."""
    import preflight

    def unreadable(*_args, **_kwargs):
        raise OSError("unreadable")

    _fails_on_name(monkeypatch)
    for var in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
        monkeypatch.delenv(var, raising=False)
    if offline:
        monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("HF_TOKEN", "hf_x")
    _damaged_cache(monkeypatch, tmp_path)
    monkeypatch.setattr(preflight, "damaged_pipeline_configs", unreadable)
    assert transcription_module._damaged_pipeline_cache(PIPELINE) is None
    segments, info = _diarise(transcription_module)
    assert segments is None and info['source'] == 'unavailable'
    error = info['error']
    assert "is damaged" not in error
    assert "Neither a token nor a new download" not in error
    if offline:
        assert "Expected the model to be pre-populated under" in error
    else:
        assert "Ensure a HuggingFace token is available" in error
    assert error.endswith("Underlying error: KeyError: 'name'")


def test_the_expected_cache_path_drops_a_revision_and_survives_no_home(
        transcription_module, monkeypatch, tmp_path):
    import preflight

    _point_pyannote_at(monkeypatch, tmp_path)
    assert transcription_module._expected_pipeline_cache_path(
        PIPELINE + "@" + "a" * 40) == str(
            tmp_path / "models--pyannote--speaker-diarization-3.1")
    monkeypatch.setattr(preflight, "pyannote_cache_dir", lambda: None)
    assert transcription_module._expected_pipeline_cache_path(PIPELINE) == (
        "$PYANNOTE_CACHE (or ~/.cache/torch/pyannote)/"
        "models--pyannote--speaker-diarization-3.1")


def test_the_example_generator_records_what_the_loader_records(
        transcription_module, monkeypatch, pyannote_cache):
    """The examples' stand-in source record must not drift from the real one."""
    from tools import generate_example_variants as gen

    _loads(monkeypatch)
    _, real = _diarise(transcription_module)
    _, stand_in = gen._diarisation(transcription_module)("example.wav")
    assert set(stand_in) == set(real)
