"""Stage-1 ENV tests for the container and the pyannote pre-cache.

* setup/Dockerfile pins its base image by digest, installs Python 3.12 and
  the lock (DEPS-14). The image itself is unbuilt; these checks are static.
* setup/cache_pyannote_arc.py downloads into the directory pyannote.audio
  3.x reads, at the revision the loaders ask for, and says when the Hub has
  moved away from the pinned one (REV-01).

Only Python is needed; nothing is downloaded, and the stand-in downloader
writes only inside each test's tmp_path.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# setup/Dockerfile (static: no container runtime is available)
# ---------------------------------------------------------------------------

def test_dockerfile_pins_base_python_and_packages():
    text = (REPO / "setup" / "Dockerfile").read_text(encoding="utf-8")
    base = re.search(r"^FROM (\S+)$", text, re.M)
    assert base and re.fullmatch(
        r"nvidia/cuda:12\.1\.1-devel-ubuntu22\.04@sha256:[0-9a-f]{64}", base.group(1))
    assert "python3.12 -m venv" in text
    assert re.search(r"pip install --no-cache-dir -r requirements-lock\.txt\s*\\\s*"
                     r"--extra-index-url https://download\.pytorch\.org/whl/cu121", text)
    assert "-r requirements.txt" not in text
    assert "python -m preflight --lock requirements-lock.txt" in text
    assert "UNBUILT AND UNVERIFIED" in text


def test_dockerfile_copies_the_files_transcription_reads_beside_it():
    """The image had no versions.csv, so it stamped "Unknown" as the version.

    The same files setup.py's RuntimeDataBuild puts beside the modules in a
    wheel, the dictionary and the release record, must be in the image.
    """
    text = (REPO / "setup" / "Dockerfile").read_text(encoding="utf-8")
    text = re.sub(r"\\\r?\n\s*", " ", text)       # join continued lines
    copied = set()
    for line in re.findall(r"^COPY (.+?)\s*$", text, re.M):
        # Every token but the last is a source; the last is the destination.
        copied.update(part.rstrip("/") for part in line.split()[:-1])
    setup_py = (REPO / "setup.py").read_text(encoding="utf-8")
    runtime = re.search(r"^_RUNTIME_DATA = \(([^)]*)\)", setup_py, re.M)
    assert runtime
    for relative in re.findall(r'"([^"]+)"', runtime.group(1)):
        top = relative.split("/")[0]
        assert relative in copied or top in copied, relative
    # And the top-level modules setup.py installs: the test used to check the
    # data files alone, so a module added to py_modules but not to the COPY
    # line would have built an image without it.
    modules = _setup_py_modules(setup_py)
    assert "transcription" in modules
    missing = [m for m in modules if f"{m}.py" not in copied]
    assert not missing, f"py_modules not copied into the image: {missing}"


def _setup_py_modules(setup_py: str) -> list[str]:
    """The ``py_modules`` list of the ``setup()`` call in setup.py's text."""
    import ast

    for node in ast.walk(ast.parse(setup_py)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "setup"):
            for keyword in node.keywords:
                if keyword.arg == "py_modules":
                    return [ast.literal_eval(element) for element in keyword.value.elts]
    raise AssertionError("setup.py's setup() call has no py_modules")


def test_setup_environment_installs_the_lock():
    text = (REPO / "setup" / "setup_environment.sh").read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert '-r "$REPO_DIR/requirements-lock.txt"' in code
    assert "--extra-index-url https://download.pytorch.org/whl/cu121" in code
    assert "preflight --lock requirements-lock.txt" in code
    # No unpinned torch from the CUDA index any more (CORE-21).
    assert not re.search(r"pip install torch", code)


# ---------------------------------------------------------------------------
# setup/cache_pyannote_arc.py (REV-01)
# ---------------------------------------------------------------------------

def _load_cache_module():
    spec = importlib.util.spec_from_file_location(
        "_s1_cache_pyannote_arc", REPO / "setup" / "cache_pyannote_arc.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# A pipeline config.yaml pyannote could load: pipeline.name, and the two
# models cache_pyannote_arc.py follows from it. The stub this replaced had
# no pipeline.name, and it is what jobs 8913985 and 8917186 wrote into the
# real cache.
_PIPELINE_CONFIG = (
    "pipeline:\n"
    "  name: pyannote.audio.pipelines.SpeakerDiarization\n"
    "  params:\n"
    "    embedding: pyannote/wespeaker-voxceleb-resnet34-LM\n"
    "    segmentation: pyannote/segmentation-3.0\n")


class _FakeHub:
    """snapshot_download stand-in: records calls, lays out a snapshot.

    It raises AssertionError instead of writing outside *root*, the calling
    test's tmp_path, or through a symlink. In ARC jobs 8913985 and 8917186
    an earlier version was handed the real pyannote cache and wrote through
    the snapshot's config.yaml link into the cached pipeline config (blob
    5402e3ca), replacing it with a stub that every diarisation job failed to
    load until the blob was restored (incident NEW-INC-01).
    """

    def __init__(self, root: Path, main_commits: dict[str, str],
                 config_text: str = _PIPELINE_CONFIG):
        self.root = Path(root).resolve()
        self.main_commits = main_commits
        self.config_text = config_text
        self.calls: list[dict] = []

    def _refuse_outside_root(self, path: Path, asked: str) -> None:
        # resolve() follows any link on the way, so a directory that links
        # out of tmp_path is refused before anything is created through it.
        if not Path(path).resolve().is_relative_to(self.root):
            raise AssertionError(
                f"_FakeHub refuses to write to {asked}: it is outside the "
                f"test's tmp_path {self.root}")

    def __call__(self, *, repo_id, token, cache_dir, revision):
        self._refuse_outside_root(Path(cache_dir), str(cache_dir))
        self.calls.append({"repo": repo_id, "cache_dir": cache_dir, "revision": revision})
        commit =self.main_commits[repo_id] if revision == "main" else revision
        snap = Path(cache_dir) / ("models--" + repo_id.replace("/", "--")) / "snapshots" / commit
        self._refuse_outside_root(snap, str(snap))
        snap.mkdir(parents=True, exist_ok=True)
        if repo_id == "pyannote/speaker-diarization-3.1":
            config = snap / "config.yaml"
            if config.is_symlink():
                raise AssertionError(
                    f"_FakeHub refuses to write through the symlink {config}, "
                    f"which points to {os.readlink(config)}")
            config.write_text(self.config_text, encoding="utf-8")
        return str(snap)


def _pins():
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from evaluation.revisions import revision_for
    return {repo: revision_for(repo) for repo in (
        "pyannote/speaker-diarization-3.1", "pyannote/segmentation-3.0",
        "pyannote/wespeaker-voxceleb-resnet34-LM")}


def test_cache_all_downloads_main_and_matches_the_pins(tmp_path):
    cache = _load_cache_module()
    pins = _pins()
    hub = _FakeHub(tmp_path, {repo: pin or "a" * 40 for repo, pin in pins.items()})
    moved = cache.cache_all(tmp_path, "hf_x", hub)
    assert moved == []
    assert {c["repo"] for c in hub.calls} == set(pins)
    assert all(c["revision"] == "main" and c["cache_dir"] == str(tmp_path)
               for c in hub.calls)


def test_cache_all_fetches_the_pin_too_when_main_has_moved(tmp_path):
    cache = _load_cache_module()
    pins = _pins()
    commits = {repo: pin or "a" * 40 for repo, pin in pins.items()}
    commits["pyannote/segmentation-3.0"] = "b" * 40
    hub = _FakeHub(tmp_path, commits)
    moved = cache.cache_all(tmp_path, "hf_x", hub)
    assert len(moved) == 1 and "pyannote/segmentation-3.0" in moved[0]
    seg = [c["revision"] for c in hub.calls if c["repo"] == "pyannote/segmentation-3.0"]
    assert seg == ["main", pins["pyannote/segmentation-3.0"]]


def test_main_downloads_where_pyannote_reads_not_into_the_hub_cache(tmp_path, monkeypatch):
    cache = _load_cache_module()
    pins = _pins()
    hub = _FakeHub(tmp_path, {repo: pin or "a" * 40 for repo, pin in pins.items()})
    monkeypatch.setitem(sys.modules, "huggingface_hub",
                        types.SimpleNamespace(snapshot_download=hub))
    monkeypatch.setattr(cache, "resolve_hf_token", lambda: ("hf_secret_1234", "test"))
    # Where pyannote is installed and already imported (on ARC), its
    # CACHE_DIR was fixed at import time and rightly takes precedence in
    # preflight.pyannote_cache_dir(); hide it so the environment rule this
    # test sets is the one applied. conftest.py points that CACHE_DIR at the
    # session's temporary cache, and _FakeHub refuses anything outside
    # tmp_path, so even without this line the test could no longer reach
    # the real cache as it did in jobs 8913985 and 8917186.
    monkeypatch.delitem(sys.modules, "pyannote.audio.core.model", raising=False)
    monkeypatch.setenv("PYANNOTE_CACHE", str(tmp_path / "pyannote"))
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    assert cache.main(["--no-save-token"]) == 0
    assert {c["cache_dir"] for c in hub.calls} == {str(tmp_path / "pyannote")}
    assert not (tmp_path / "hf" / "hub").exists()


def test_main_does_not_report_success_over_a_config_that_cannot_load(
        tmp_path, monkeypatch, capsys):
    # A real download keeps a file already in the cache, so the stub jobs
    # 8913985 and 8917186 left would survive a re-run; the script must say
    # so (NEW-INC-01).
    cache = _load_cache_module()
    pins = _pins()
    stub = ("pipeline:\n  params:\n    embedding: pyannote/wespeaker-voxceleb-resnet34-LM\n"
            "    segmentation: pyannote/segmentation-3.0\n")
    hub = _FakeHub(tmp_path, {repo: pin or "a" * 40 for repo, pin in pins.items()},
                   config_text=stub)
    monkeypatch.setitem(sys.modules, "huggingface_hub",
                        types.SimpleNamespace(snapshot_download=hub))
    monkeypatch.setattr(cache, "resolve_hf_token", lambda: ("hf_secret_1234", "test"))
    monkeypatch.delitem(sys.modules, "pyannote.audio.core.model", raising=False)
    monkeypatch.setenv("PYANNOTE_CACHE", str(tmp_path / "pyannote"))
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    assert cache.main(["--no-save-token"]) == 3
    out, err = capsys.readouterr()
    config = (tmp_path / "pyannote" / "models--pyannote--speaker-diarization-3.1"
              / "snapshots" / pins["pyannote/speaker-diarization-3.1"] / "config.yaml")
    assert "ERROR: the cached pipeline config is damaged:" in err
    assert f"{config} has no pipeline.name" in err
    assert "setup/cache_pyannote_arc.py" in err
    assert "All pyannote weights cached" not in out


def test_main_does_not_report_success_over_a_damaged_blob(tmp_path, monkeypatch, capsys):
    """A damaged blob no config links to: a real download would link it
    again instead of fetching the file, so the script fails on it too."""
    cache = _load_cache_module()
    pins = _pins()
    hub = _FakeHub(tmp_path, {repo: pin or "a" * 40 for repo, pin in pins.items()})
    monkeypatch.setitem(sys.modules, "huggingface_hub",
                        types.SimpleNamespace(snapshot_download=hub))
    monkeypatch.setattr(cache, "resolve_hf_token", lambda: ("hf_secret_1234", "test"))
    monkeypatch.delitem(sys.modules, "pyannote.audio.core.model", raising=False)
    monkeypatch.setenv("PYANNOTE_CACHE", str(tmp_path / "pyannote"))
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    # Named after the real config's git blob id, holding something else.
    blob = (tmp_path / "pyannote" / "models--pyannote--speaker-diarization-3.1" / "blobs"
            / "5402e3ca79b6cfa5b0ec283eed920cafe45ee39b")
    blob.parent.mkdir(parents=True)
    blob.write_text("pipeline:\n  params: {}\n", encoding="utf-8")
    assert cache.main(["--no-save-token"]) == 3
    out, err = capsys.readouterr()
    assert "ERROR: the pipeline's cache is damaged:" in err
    assert f"{blob} differs from the file the Hub served" in err
    assert f"Fix: delete {blob}, then fetch it again" in err
    assert "All pyannote weights cached" not in out


def test_main_says_which_loads_a_moved_main_changes(tmp_path, monkeypatch, capsys):
    """The warning used to say that the loaders read main. The DER and
    anonymisation benchmarks load the pipeline, and the fine-tuning script
    the segmentation model, at the pin, which the script caches as well.
    What reads main is transcription.py's pipeline load and the models the
    pipeline's config names without a revision."""
    cache = _load_cache_module()
    pins = _pins()
    commits = {repo: pin or "a" * 40 for repo, pin in pins.items()}
    commits["pyannote/segmentation-3.0"] = "b" * 40
    hub = _FakeHub(tmp_path, commits)
    monkeypatch.setitem(sys.modules, "huggingface_hub",
                        types.SimpleNamespace(snapshot_download=hub))
    monkeypatch.setattr(cache, "resolve_hf_token", lambda: ("hf_secret_1234", "test"))
    monkeypatch.delitem(sys.modules, "pyannote.audio.core.model", raising=False)
    monkeypatch.setenv("PYANNOTE_CACHE", str(tmp_path / "pyannote"))
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    assert cache.main(["--no-save-token"]) == 2
    out, err = capsys.readouterr()
    seg = pins["pyannote/segmentation-3.0"]
    assert f"pyannote/segmentation-3.0: main is {'b' * 40}, pinned {seg}" in err
    assert "The loaders read main" not in err
    assert "Loads at a pinned revision find the pinned snapshot, now cached" in err
    assert "transcription.py loads the pipeline at main" in err
    assert "it loads its segmentation and embedding models at main" in err
    assert "All pyannote weights cached" not in out


def test_the_stand_in_hub_writes_nowhere_but_the_test_directory(tmp_path):
    outside = tmp_path / "a_real_cache"
    hub = _FakeHub(tmp_path / "test", {"pyannote/speaker-diarization-3.1": "a" * 40})
    with pytest.raises(AssertionError, match="refuses to write"):
        hub(repo_id="pyannote/speaker-diarization-3.1", token="hf_x",
            cache_dir=str(outside), revision="main")
    assert not outside.exists()


def test_main_without_a_token_fails(monkeypatch):
    cache = _load_cache_module()
    monkeypatch.setattr(cache, "resolve_hf_token", lambda: (None, None))
    assert cache.main(["--no-save-token"]) == 1


@pytest.mark.parametrize("repo", ["pyannote/speaker-diarization-3.1",
                                  "pyannote/segmentation-3.0"])
def test_the_pipeline_and_segmentation_are_pinned(repo):
    assert _pins()[repo]
