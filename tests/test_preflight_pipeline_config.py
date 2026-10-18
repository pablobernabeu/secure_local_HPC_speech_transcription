"""preflight catches a damaged cached pyannote pipeline config (NEW-INC-01).

On ARC, test-suite jobs 8913985 and 8917186 each wrote a 119-byte stub
without ``pipeline.name`` over the cached config.yaml of
pyannote/speaker-diarization-3.1 (blob 5402e3ca). Every
``Pipeline.from_pretrained`` until the blob was restored failed with
KeyError: 'name': case-study job 8918023 failed, and anonymisation jobs
8913992, 8917988 and 8917989 fell back to loading the embedding model
directly. All four had passed preflight with --diarisation-required,
because with a token it never looked at the cache.

Every cache layout here is built in tmp_path, and pyannote itself is
replaced by empty modules, so nothing depends on what this machine has
cached. The tests that need PyYAML's parser skip without it; the tests of
the linked layout skip where symlinks cannot be created.

The blobs of the pipeline are checked as well, linked or not: a damaged
blob whose snapshot link had been deleted left no config to check, so the
pipeline counted as not cached and a job with a token passed, and the
next download linked the damaged blob again.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import types
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import preflight  # noqa: E402
from evaluation.revisions import revision_for  # noqa: E402

_PIPELINE = "pyannote/speaker-diarization-3.1"
# config.yaml of pyannote/speaker-diarization-3.1 at its pinned revision, as
# restored in ARC's pyannote cache on 2026-10-04: 469 bytes, git blob id
# 5402e3ca, the name of the blob it is cached under.
PIPELINE_CONFIG = (
    b"version: 3.1.0\n"
    b"\n"
    b"pipeline:\n"
    b"  name: pyannote.audio.pipelines.SpeakerDiarization\n"
    b"  params:\n"
    b"    clustering: AgglomerativeClustering\n"
    b"    embedding: pyannote/wespeaker-voxceleb-resnet34-LM\n"
    b"    embedding_batch_size: 32\n"
    b"    embedding_exclude_overlap: true\n"
    b"    segmentation: pyannote/segmentation-3.0\n"
    b"    segmentation_batch_size: 32\n"
    b"\n"
    b"params:\n"
    b"  clustering:\n"
    b"    method: centroid\n"
    b"    min_cluster_size: 12\n"
    b"    threshold: 0.7045654963945799\n"
    b"  segmentation:\n"
    b"    min_duration_off: 0.0\n"
)
PIPELINE_CONFIG_BLOB = "5402e3ca79b6cfa5b0ec283eed920cafe45ee39b"
# What the test suite's stand-in downloader wrote over it in jobs 8913985
# and 8917186 (the copy kept on ARC as evidence is byte-identical).
INCIDENT_STUB = (
    b"pipeline:\n"
    b"  params:\n"
    b"    embedding: pyannote/wespeaker-voxceleb-resnet34-LM\n"
    b"    segmentation: pyannote/segmentation-3.0\n"
)


def test_the_fixtures_are_the_real_config_and_the_incident_stub():
    assert len(PIPELINE_CONFIG) == 469
    assert preflight._git_blob_id(PIPELINE_CONFIG) == PIPELINE_CONFIG_BLOB
    assert len(INCIDENT_STUB) == 119


# ---------------------------------------------------------------------------
# The config check itself
# ---------------------------------------------------------------------------

def test_the_real_config_loads_and_matches_its_blob():
    assert preflight._config_problem(PIPELINE_CONFIG) is None
    assert preflight._config_problem(PIPELINE_CONFIG, PIPELINE_CONFIG_BLOB) is None


def test_the_incident_stub_is_named_for_what_breaks_the_load():
    # The KeyError is named from PyYAML's parse; the text check used
    # without it cannot tell a missing key from an empty one.
    pytest.importorskip("yaml")
    problem = preflight._config_problem(INCIDENT_STUB)
    assert problem == ("has no pipeline.name, so Pipeline.from_pretrained "
                       "cannot load it (KeyError: 'name')")
    # Read through the blob it overwrote, it also no longer matches the
    # name, and both problems read as one phrase after the file's path.
    problem = preflight._config_problem(INCIDENT_STUB, PIPELINE_CONFIG_BLOB)
    assert problem == (
        "has no pipeline.name, so Pipeline.from_pretrained cannot load it "
        "(KeyError: 'name'), and differs from the file the Hub served "
        f"(git hash-object gives {preflight._git_blob_id(INCIDENT_STUB)[:8]}, "
        "not the blob's name 5402e3ca)")


def test_a_config_that_parses_but_differs_from_its_blob_is_reported():
    edited = PIPELINE_CONFIG.replace(b"threshold: 0.7045654963945799",
                                     b"threshold: 0.5")
    assert preflight._config_problem(edited) is None
    problem = preflight._config_problem(edited, PIPELINE_CONFIG_BLOB)
    # It still loads, with a threshold nobody chose, so the report must not
    # say it cannot.
    assert problem.startswith("differs from the file the Hub served")
    assert "cannot load" not in problem


@pytest.mark.parametrize("data, expected", [
    (b"", "is not a YAML mapping"),
    (b"- pipeline\n- name\n", "is not a YAML mapping"),
    (b"pipeline: [unclosed\n", "does not parse as YAML"),
    (b"pipeline: SpeakerDiarization\n", "has no pipeline mapping"),
    (b"pipeline:\n  name:\n", "has no pipeline.name"),
    (b"pipeline:\n  params:\n    name: nested\n", "has no pipeline.name"),
    (b"\xff\xfepipeline:\n", "is not UTF-8 text"),
])
def test_each_way_a_config_cannot_load_is_reported(data, expected):
    pytest.importorskip("yaml")
    assert preflight._config_problem(data).startswith(expected)


def test_without_pyyaml_the_text_check_reads_the_block_layout(monkeypatch):
    # A None entry makes `import yaml` raise ImportError.
    monkeypatch.setitem(sys.modules, "yaml", None)
    assert preflight._config_problem(PIPELINE_CONFIG) is None
    assert "has no pipeline.name" in preflight._config_problem(INCIDENT_STUB)
    read = preflight._pipeline_name_without_yaml
    assert read("pipeline:  # the class\n  # comment\n"
                "  name: 'pyannote.audio.pipelines.SpeakerDiarization'  # note\n"
                ) == "pyannote.audio.pipelines.SpeakerDiarization"
    # Only a key directly under the top-level pipeline counts.
    assert read("pipeline:\n  params:\n    name: nested\n") is None
    assert read("params:\n  name: elsewhere\n") is None
    assert read("pipeline:\n  name:\n") is None


# ---------------------------------------------------------------------------
# check_diarisation against cache layouts in tmp_path
# ---------------------------------------------------------------------------

@pytest.fixture
def cache(monkeypatch, tmp_path):
    """An empty pyannote cache in tmp_path, a stand-in pyannote and no token.

    Returns the cache directory. Tests that want a token set HF_TOKEN.
    """
    for var in ("HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGING_FACE_HUB_TOKEN",
                "HF_TOKEN_PATH", "HUGGINGFACE_HUB_CACHE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hf" / "hub"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    monkeypatch.setattr(preflight, "_REPO_ROOT", tmp_path / "repo")
    (tmp_path / "work").mkdir()
    monkeypatch.chdir(tmp_path / "work")
    monkeypatch.setitem(sys.modules, "pyannote", types.ModuleType("pyannote"))
    monkeypatch.setitem(sys.modules, "pyannote.audio", types.ModuleType("pyannote.audio"))
    # A real pyannote imported earlier would fix the cache directory.
    monkeypatch.delitem(sys.modules, "pyannote.audio.core.model", raising=False)
    root = tmp_path / "pyannote"
    monkeypatch.setenv("PYANNOTE_CACHE", str(root))
    return root


def _snapshot(root: Path, repo: str) -> Path:
    snapshot = (root / preflight._repo_folder(repo) / "snapshots"
                / (revision_for(repo) or "a" * 40))
    snapshot.mkdir(parents=True, exist_ok=True)
    return snapshot


def _cache_pipeline(root: Path, config: bytes | None) -> Path | None:
    """Give every repository a snapshot; the pipeline's holds *config*.

    Returns the pipeline's config.yaml, or None when *config* is None.
    """
    for repo in preflight.PYANNOTE_PIPELINE_REPOS:
        _snapshot(root, repo)
    if config is None:
        return None
    path = _snapshot(root, _PIPELINE) / "config.yaml"
    path.write_bytes(config)
    return path


def _link(target: Path, link: Path) -> None:
    """Link *link* to *target* as hf_hub_download does, or skip the test."""
    try:
        os.symlink(os.path.relpath(target, link.parent), link)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"cannot create a symlink here: {exc}")


def test_the_incident_fails_a_diarisation_job_even_with_a_token(cache, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_test")
    config = _cache_pipeline(cache, INCIDENT_STUB)
    result = preflight.check_diarisation(diarisation_required=True)
    assert result.status == preflight.FAIL
    assert str(config) in result.detail and "has no pipeline.name" in result.detail
    assert "setup/cache_pyannote_arc.py" in result.remedy
    assert f"delete {config}" in result.remedy


def test_other_jobs_are_warned_about_it(cache, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_test")
    config = _cache_pipeline(cache, INCIDENT_STUB)
    result = preflight.check_diarisation(diarisation_required=False)
    assert result.status == preflight.WARN
    assert str(config) in result.detail and result.remedy


def test_without_a_token_the_damaged_config_is_not_a_usable_cache(cache):
    _cache_pipeline(cache, INCIDENT_STUB)
    assert preflight.pyannote_pipeline_cached() is False
    result = preflight.check_diarisation(diarisation_required=True)
    assert result.status == preflight.FAIL and "has no pipeline.name" in result.detail


def test_an_intact_cache_still_passes(cache, monkeypatch):
    _cache_pipeline(cache, PIPELINE_CONFIG)
    assert preflight.damaged_pipeline_configs() == []
    assert preflight.pyannote_pipeline_cached() is True
    # No token: a fully cached pipeline downgrades that to a warning.
    assert preflight.check_diarisation(diarisation_required=True).status == preflight.WARN
    monkeypatch.setenv("HF_TOKEN", "hf_test")
    assert preflight.check_diarisation(diarisation_required=True).status == preflight.OK


def test_a_pipeline_snapshot_without_its_config_is_not_cached(cache):
    # What an interrupted download leaves: the snapshot directory, empty.
    _cache_pipeline(cache, None)
    assert preflight.damaged_pipeline_configs() == []
    assert preflight.pyannote_pipeline_cached() is False
    assert preflight.check_diarisation(diarisation_required=True).status == preflight.FAIL


def test_nothing_cached_with_a_token_is_left_to_the_download(cache, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_test")
    assert preflight.damaged_pipeline_configs() == []
    assert preflight.check_diarisation(diarisation_required=True).status == preflight.OK


def test_every_snapshot_is_checked(cache, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_test")
    _cache_pipeline(cache, PIPELINE_CONFIG)
    other = (cache / preflight._repo_folder(_PIPELINE) / "snapshots" / ("b" * 40)
             / "config.yaml")
    other.parent.mkdir(parents=True)
    other.write_bytes(INCIDENT_STUB)
    assert [path for path, _ in preflight.damaged_pipeline_configs()] == [other]
    assert preflight.check_diarisation(diarisation_required=True).status == preflight.FAIL


# ---------------------------------------------------------------------------
# The layout hf_hub_download writes on Linux: snapshot links into blobs/
# ---------------------------------------------------------------------------

def _linked_layout(root: Path, blob_content: bytes) -> tuple[Path, Path]:
    """The pipeline cached as on ARC: config.yaml links to blob 5402e3ca."""
    _cache_pipeline(root, None)
    blob = root / preflight._repo_folder(_PIPELINE) / "blobs" / PIPELINE_CONFIG_BLOB
    blob.parent.mkdir(parents=True)
    blob.write_bytes(blob_content)
    config = _snapshot(root, _PIPELINE) / "config.yaml"
    _link(blob, config)
    return config, blob


def test_a_damaged_blob_is_named_with_its_link(cache, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_test")
    config, blob = _linked_layout(cache, INCIDENT_STUB)
    # The blob is reported with its link, not a second time on its own.
    assert [path for path, _ in preflight.damaged_pipeline_configs()] == [config]
    result = preflight.check_diarisation(diarisation_required=True)
    assert result.status == preflight.FAIL
    assert f"the cached pipeline config is damaged: {config} has no" in result.detail
    assert "and differs from the file the Hub served" in result.detail
    assert f"delete {blob} and the link {config}" in result.remedy
    # No copy in the hub cache: the remedy says where one would be and
    # how to check it before use.
    assert f"git hash-object on that copy prints {PIPELINE_CONFIG_BLOB}" in result.remedy


def test_an_intact_copy_in_the_hub_cache_is_offered(cache, monkeypatch, tmp_path):
    monkeypatch.setenv("HF_TOKEN", "hf_test")
    _config, blob = _linked_layout(cache, INCIDENT_STUB)
    copy = (tmp_path / "hf" / "hub" / preflight._repo_folder(_PIPELINE) / "blobs"
            / PIPELINE_CONFIG_BLOB)
    copy.parent.mkdir(parents=True)
    copy.write_bytes(PIPELINE_CONFIG)
    remedy = preflight.check_diarisation(diarisation_required=True).remedy
    assert re.search(rf"copy {re.escape(str(copy))} over {re.escape(str(blob))}", remedy)
    # A copy that is itself damaged is not offered.
    copy.write_bytes(INCIDENT_STUB)
    remedy = preflight.check_diarisation(diarisation_required=True).remedy
    assert f"copy {copy} over" not in remedy


def test_an_intact_linked_blob_passes(cache, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_test")
    _linked_layout(cache, PIPELINE_CONFIG)
    assert preflight.damaged_pipeline_configs() == []
    assert preflight.check_diarisation(diarisation_required=True).status == preflight.OK


def test_an_edit_that_still_loads_fails_as_damaged_not_as_unloadable(cache, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_test")
    edited = PIPELINE_CONFIG.replace(b"threshold: 0.7045654963945799",
                                     b"threshold: 0.5")
    config, _blob = _linked_layout(cache, edited)
    result = preflight.check_diarisation(diarisation_required=True)
    assert result.status == preflight.FAIL
    assert (f"the cached pipeline config is damaged: {config} differs from the "
            "file the Hub served") in result.detail
    assert "cannot load" not in result.detail


# ---------------------------------------------------------------------------
# A config that is a file of its own: the layout where symlinks are
# unavailable, or a cache copied without them
# ---------------------------------------------------------------------------

def _hub_snapshot_config(tmp_path: Path) -> Path:
    """Where the hub cache keeps the pipeline config of the pinned snapshot."""
    snapshot = (tmp_path / "hf" / "hub" / preflight._repo_folder(_PIPELINE)
                / "snapshots" / (revision_for(_PIPELINE) or "a" * 40))
    snapshot.mkdir(parents=True)
    return snapshot / "config.yaml"


def test_an_unlinked_damaged_config_is_offered_a_verified_hub_copy(
        cache, monkeypatch, tmp_path):
    monkeypatch.setenv("HF_TOKEN", "hf_test")
    config = _cache_pipeline(cache, INCIDENT_STUB)
    copy = _hub_snapshot_config(tmp_path)
    hub_blob = copy.parents[2] / "blobs" / PIPELINE_CONFIG_BLOB
    hub_blob.parent.mkdir(parents=True)
    hub_blob.write_bytes(PIPELINE_CONFIG)
    _link(hub_blob, copy)
    remedy = preflight.check_diarisation(diarisation_required=True).remedy
    assert f"delete {config}, then fetch it again" in remedy
    assert f"Or copy {copy} over {config}" in remedy
    # Once the hub's blob is damaged too, the copy is no longer offered.
    hub_blob.write_bytes(INCIDENT_STUB)
    remedy = preflight.check_diarisation(diarisation_required=True).remedy
    assert f"copy {copy}" not in remedy


def test_an_unlinked_damaged_config_is_not_offered_a_copy_that_cannot_be_checked(
        cache, monkeypatch, tmp_path):
    # A hub copy that is a file of its own loads, but nothing says it is the
    # file the Hub served, so only the download is offered.
    monkeypatch.setenv("HF_TOKEN", "hf_test")
    config = _cache_pipeline(cache, INCIDENT_STUB)
    _hub_snapshot_config(tmp_path).write_bytes(PIPELINE_CONFIG)
    remedy = preflight.check_diarisation(diarisation_required=True).remedy
    assert remedy == (f"delete {config}, then fetch it again with python "
                      "setup/cache_pyannote_arc.py where there is network "
                      "access (on ARC, a login node)")


# ---------------------------------------------------------------------------
# The pipeline's blobs, whether or not a snapshot links to them
# ---------------------------------------------------------------------------

def _blob(root: Path, content: bytes, name: str = PIPELINE_CONFIG_BLOB) -> Path:
    """Put *content* in the blobs directory of the pipeline in *root*, as *name*."""
    blob = root / preflight._repo_folder(_PIPELINE) / "blobs" / name
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(content)
    return blob


def test_a_damaged_blob_whose_link_was_deleted_still_fails_a_diarisation_job(
        cache, monkeypatch):
    """The snapshot's config.yaml link deleted, the damaged blob kept.

    No config is left to check, so the pipeline counted as not cached and,
    with a token, the check passed. hf_hub_download links a blob the cache
    already holds instead of fetching the file, so the next download would
    have linked the damaged blob again.
    """
    monkeypatch.setenv("HF_TOKEN", "hf_test")
    _cache_pipeline(cache, None)
    blob = _blob(cache, INCIDENT_STUB)
    stub_id = preflight._git_blob_id(INCIDENT_STUB)[:8]
    assert preflight.damaged_pipeline_configs() == [(blob, (
        f"differs from the file the Hub served (git hash-object gives {stub_id}, "
        "not the blob's name 5402e3ca), and a download keeps it, since it finds "
        "the blob already cached"))]
    result = preflight.check_diarisation(diarisation_required=True)
    assert result.status == preflight.FAIL
    assert result.detail.startswith("pyannote.audio importable, but the pipeline's "
                                    f"cache is damaged: {blob} differs from the file")
    assert result.remedy.startswith(f"delete {blob}, then fetch it again with python "
                                    "setup/cache_pyannote_arc.py")
    # No copy in the hub cache: the remedy says where one would be and how
    # to check it before use.
    assert f"git hash-object on that copy prints {PIPELINE_CONFIG_BLOB}" in result.remedy
    assert preflight.check_diarisation(diarisation_required=False).status == preflight.WARN


def test_an_intact_blob_without_a_link_is_left_to_the_download(cache, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_test")
    _cache_pipeline(cache, None)
    _blob(cache, PIPELINE_CONFIG)
    # What an interrupted download leaves: not named after a digest, so not
    # compared with one.
    _blob(cache, b"partial", name=PIPELINE_CONFIG_BLOB + ".incomplete")
    assert preflight.damaged_pipeline_configs() == []
    assert preflight.check_diarisation(diarisation_required=True).status == preflight.OK


def test_a_damaged_blob_is_offered_an_intact_hub_copy(cache, monkeypatch, tmp_path):
    monkeypatch.setenv("HF_TOKEN", "hf_test")
    _cache_pipeline(cache, None)
    blob = _blob(cache, INCIDENT_STUB)
    copy = _blob(tmp_path / "hf" / "hub", PIPELINE_CONFIG)
    remedy = preflight.check_diarisation(diarisation_required=True).remedy
    assert (f"Or copy {copy} over {blob}: that copy in the Hugging Face hub cache "
            "still matches its name under git hash-object") in remedy
    # A copy that is itself damaged is not offered.
    copy.write_bytes(INCIDENT_STUB)
    remedy = preflight.check_diarisation(diarisation_required=True).remedy
    assert f"copy {copy} over" not in remedy


def test_an_lfs_blob_is_compared_with_its_sha256(cache, monkeypatch):
    """An LFS file's blob is named after the SHA-256 of its content."""
    monkeypatch.setenv("HF_TOKEN", "hf_test")
    _cache_pipeline(cache, PIPELINE_CONFIG)
    name = hashlib.sha256(b"weights").hexdigest()
    blob = _blob(cache, b"weights", name=name)
    assert preflight.damaged_pipeline_configs() == []
    assert preflight.pyannote_pipeline_cached() is True
    blob.write_bytes(b"other weights")
    actual = hashlib.sha256(b"other weights").hexdigest()
    (path, problem), = preflight.damaged_pipeline_configs()
    assert path == blob
    assert problem.startswith(f"differs from the file the Hub served (sha256sum gives "
                              f"{actual[:8]}, not the blob's name {name[:8]})")
    # The config is intact, but the pipeline's cache is not.
    assert preflight.pyannote_pipeline_cached() is False
    result = preflight.check_diarisation(diarisation_required=True)
    assert result.status == preflight.FAIL
    assert f"sha256sum on that copy prints {name}" in result.remedy


def test_a_blob_a_damaged_config_links_to_is_reported_once(cache, monkeypatch):
    """Reported with the config, not again on its own. The link is stood in
    for by patching _linked_blob, so this runs where symlinks cannot be made;
    test_a_damaged_blob_is_named_with_its_link covers a real one."""
    monkeypatch.setenv("HF_TOKEN", "hf_test")
    config = _cache_pipeline(cache, INCIDENT_STUB)
    blob = _blob(cache, INCIDENT_STUB)
    real = preflight._linked_blob
    monkeypatch.setattr(preflight, "_linked_blob",
                        lambda path: blob.resolve() if path == config else real(path))
    assert [path for path, _ in preflight.damaged_pipeline_configs()] == [config]
    result = preflight.check_diarisation(diarisation_required=True)
    assert result.detail.startswith("pyannote.audio importable, but the cached "
                                    f"pipeline config is damaged: {config} has no")
    assert f"delete {blob.resolve()} and the link {config} to it" in result.remedy
    assert result.remedy.count("delete ") == 1
