"""No test may reach a real model cache (incident NEW-INC-01).

ARC test-suite jobs 8913985 (commit 76d9489) and 8917186 (commit 2e5e852)
each ran test_s1_env_setup.py's pre-cache test after another test had
imported pyannote.audio, so the test's stand-in downloader was handed the
real ~/.cache/torch/pyannote. It wrote its 119-byte stub config.yaml
through the snapshot's symlink into blob 5402e3ca of
pyannote/speaker-diarization-3.1, and every Pipeline.from_pretrained on the
cluster failed with KeyError: 'name' until the blob was restored.
tests/conftest.py now redirects every model cache into one temporary
directory for the session, and the stand-in refuses to write outside its
test's tmp_path or through a link. These tests pin both guards.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
import types
from pathlib import Path

import pytest

import conftest
import preflight
from test_s1_env_setup import _FakeHub

# Named here rather than read from conftest, so that dropping one there
# fails this test.
_REDIRECTED = ("PYANNOTE_CACHE", "HF_HOME", "HF_HUB_CACHE",
               "HUGGINGFACE_HUB_CACHE", "TORCH_HOME", "XDG_CACHE_HOME")
# Read ahead of those by transformers, datasets and huggingface_hub, so an
# inherited value would reach past the redirect; conftest removes them.
_OVERRIDING = ("TRANSFORMERS_CACHE", "PYTORCH_TRANSFORMERS_CACHE",
               "PYTORCH_PRETRAINED_BERT_CACHE", "HF_DATASETS_CACHE",
               "HF_DATASETS_DOWNLOADED_DATASETS_PATH",
               "HF_DATASETS_EXTRACTED_DATASETS_PATH", "HF_MODULES_CACHE",
               "HF_ASSETS_CACHE", "HUGGINGFACE_ASSETS_CACHE", "HF_XET_CACHE")
_PIPELINE = "pyannote/speaker-diarization-3.1"
_BLOB = "5402e3ca79b6cfa5b0ec283eed920cafe45ee39b"


def _inside(path, root: Path) -> bool:
    return Path(path).expanduser().resolve().is_relative_to(root.resolve())


def _commits() -> dict[str, str]:
    return {_PIPELINE: "a" * 40}


def _link(target: Path, link: Path) -> None:
    """Link *link* to *target* as hf_hub_download does, or skip the test."""
    try:
        os.symlink(os.path.relpath(target, link.parent), link,
                   target_is_directory=target.is_dir())
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"cannot create a symlink here: {exc}")


# ---------------------------------------------------------------------------
# conftest.py: the session's caches
# ---------------------------------------------------------------------------

def test_the_session_cache_is_a_temporary_directory(isolated_model_caches):
    assert isolated_model_caches.is_dir()
    assert isolated_model_caches.name.startswith("pytest-model-caches-")
    assert _inside(isolated_model_caches, Path(tempfile.gettempdir()))


def test_every_model_cache_variable_points_into_it(isolated_model_caches):
    for name in _REDIRECTED:
        assert _inside(os.environ[name], isolated_model_caches), (
            f"{name}={os.environ[name]} is outside {isolated_model_caches}")
    assert set(_OVERRIDING) <= set(conftest.OVERRIDING_CACHE_VARIABLES)
    assert [name for name in conftest.OVERRIDING_CACHE_VARIABLES
            if name in os.environ] == []


def test_preflight_finds_the_redirected_pyannote_cache(isolated_model_caches):
    cache = preflight.pyannote_cache_dir()
    assert cache is not None and _inside(cache, isolated_model_caches)
    home = Path.home().resolve()
    # The defaults of pyannote, the Hub and torch all live under ~/.cache.
    assert not _inside(cache, home / ".cache")
    # The session directory itself lies under the home directory only where
    # the system's temporary directory does (Windows keeps %TEMP% there).
    if not isolated_model_caches.resolve().is_relative_to(home):
        assert not _inside(cache, home)


def test_a_pyannote_imported_with_the_real_cache_is_redirected(
        monkeypatch, isolated_model_caches):
    real = str(Path.home() / ".cache" / "torch" / "pyannote")
    model = types.ModuleType("pyannote.audio.core.model")
    model.CACHE_DIR = real
    monkeypatch.setitem(sys.modules, "pyannote.audio.core.model", model)
    patch = pytest.MonkeyPatch()
    try:
        changed = conftest.redirect_loaded_pyannote_caches(patch)
        assert "pyannote.audio.core.model" in changed
        assert _inside(model.CACHE_DIR, isolated_model_caches)
        assert _inside(preflight.pyannote_cache_dir(), isolated_model_caches)
    finally:
        patch.undo()
    assert real == model.CACHE_DIR


# ---------------------------------------------------------------------------
# test_s1_env_setup._FakeHub: the stand-in that wrote through the link
# ---------------------------------------------------------------------------

def test_the_fake_hub_refuses_a_cache_outside_tmp_path(tmp_path):
    hub = _FakeHub(tmp_path / "inside", _commits())
    outside = tmp_path / "outside"
    with pytest.raises(AssertionError, match=re.escape(str(outside))):
        hub(repo_id=_PIPELINE, token="hf_x", cache_dir=str(outside), revision="main")
    assert not outside.exists() and hub.calls == []


def test_the_fake_hub_refuses_the_real_pyannote_cache(tmp_path):
    real = Path.home() / ".cache" / "torch" / "pyannote"
    existed = real.exists()
    hub = _FakeHub(tmp_path, _commits())
    with pytest.raises(AssertionError, match="outside the test's tmp_path"):
        hub(repo_id=_PIPELINE, token="hf_x", cache_dir=str(real), revision="main")
    assert real.exists() == existed


def test_the_fake_hub_never_writes_through_a_snapshot_link(tmp_path):
    # The layout hf_hub_download leaves, and that jobs 8913985 and 8917186
    # wrote through: the snapshot's config.yaml is a link to a blob.
    repo = tmp_path / "cache" / "models--pyannote--speaker-diarization-3.1"
    blob = repo / "blobs" / _BLOB
    blob.parent.mkdir(parents=True)
    blob.write_bytes(b"version: 3.1.0\n")
    snapshot = repo / "snapshots" / ("a" * 40)
    snapshot.mkdir(parents=True)
    _link(blob, snapshot / "config.yaml")
    hub = _FakeHub(tmp_path, _commits())
    with pytest.raises(AssertionError, match="through the symlink"):
        hub(repo_id=_PIPELINE, token="hf_x", cache_dir=str(tmp_path / "cache"),
            revision="main")
    assert blob.read_bytes() == b"version: 3.1.0\n"


def test_the_fake_hub_refuses_a_directory_that_links_out(tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    cache = tmp_path / "inside" / "cache"
    cache.mkdir(parents=True)
    _link(elsewhere, cache / "models--pyannote--speaker-diarization-3.1")
    hub = _FakeHub(tmp_path / "inside", _commits())
    with pytest.raises(AssertionError, match="outside the test's tmp_path"):
        hub(repo_id=_PIPELINE, token="hf_x", cache_dir=str(cache), revision="main")
    assert list(elsewhere.iterdir()) == []
