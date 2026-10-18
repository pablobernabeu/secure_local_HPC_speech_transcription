"""Regression tests for the review of the CORE audit fixes (CORE-R*).

Each test names the finding it pins. All are hermetic: files live under
tmp_path, environment variables and modules are replaced with monkeypatch,
and nothing touches the network.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_setup_module(name):
    spec = importlib.util.spec_from_file_location(
        f"_audit_review_{name}", PROJECT_ROOT / "setup" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# CORE-R1: download only what the pipeline loads
# ---------------------------------------------------------------------------

# The 21 files of openai/whisper-large-v3 as the Hub lists them.
_WHISPER_LARGE_V3_FILES = [
    ".gitattributes", "README.md", "added_tokens.json", "config.json",
    "flax_model.msgpack", "generation_config.json", "merges.txt",
    "model.fp32-00001-of-00002.safetensors",
    "model.fp32-00002-of-00002.safetensors", "model.safetensors",
    "model.safetensors.index.fp32.json", "normalizer.json",
    "preprocessor_config.json", "pytorch_model.bin",
    "pytorch_model.bin.index.fp32.json",
    "pytorch_model.fp32-00001-of-00002.bin",
    "pytorch_model.fp32-00002-of-00002.bin", "special_tokens_map.json",
    "tokenizer.json", "tokenizer_config.json", "vocab.json",
]


def test_core_r1_snapshot_is_restricted(monkeypatch, capsys):
    calls = {}

    def fake_snapshot_download(repo_id, **kwargs):
        calls["repo_id"] = repo_id
        calls.update(kwargs)
        return "/cache/snap"

    class _Transcriber:
        def __call__(self, inputs):
            return {"text": ""}

    loaded = {}

    def fake_pipeline(*args, **kwargs):
        loaded.update(kwargs)
        return _Transcriber()

    hub = types.ModuleType("huggingface_hub")
    hub.snapshot_download = fake_snapshot_download
    transformers = types.ModuleType("transformers")
    transformers.pipeline = fake_pipeline
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    monkeypatch.setitem(sys.modules, "transformers", transformers)

    downloader = _load_setup_module("download_model")
    assert downloader.download_model("openai/whisper-large-v3") is True
    assert calls["repo_id"] == "openai/whisper-large-v3"
    assert calls["allow_patterns"] == downloader.WEIGHT_PATTERNS
    # DEPS-16: both the download and the load check use the pinned snapshot.
    from evaluation.revisions import revision_for
    pinned = revision_for("openai/whisper-large-v3")
    assert pinned and calls["revision"] == pinned
    assert loaded["revision"] == pinned


def test_deps16_unlisted_model_downloads_the_branch_head(monkeypatch):
    calls = {}

    class _Transcriber:
        def __call__(self, inputs):
            return {"text": ""}

    hub = types.ModuleType("huggingface_hub")
    hub.snapshot_download = lambda repo_id, **kw: calls.update(kw) or "/cache/snap"
    transformers = types.ModuleType("transformers")
    transformers.pipeline = lambda *a, **k: _Transcriber()
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    monkeypatch.setitem(sys.modules, "transformers", transformers)

    downloader = _load_setup_module("download_model")
    assert downloader.download_model("someone/unlisted-whisper") is True
    assert calls["revision"] is None


def test_core_r1_patterns_select_only_the_loaded_files():
    hub_utils = pytest.importorskip("huggingface_hub.utils")
    downloader = _load_setup_module("download_model")
    chosen = set(hub_utils.filter_repo_objects(
        _WHISPER_LARGE_V3_FILES, allow_patterns=downloader.WEIGHT_PATTERNS))
    assert "model.safetensors" in chosen
    for needed in ("config.json", "generation_config.json",
                   "preprocessor_config.json", "tokenizer.json",
                   "tokenizer_config.json", "vocab.json", "merges.txt",
                   "normalizer.json", "added_tokens.json",
                   "special_tokens_map.json"):
        assert needed in chosen
    # No Flax, .bin or fp32 weights: those made the snapshot about 25 GB.
    assert not any(name.endswith((".msgpack", ".bin")) for name in chosen)
    assert not any("fp32" in name and name.endswith(".safetensors")
                   for name in chosen)
    # Sharded safetensors checkpoints are still covered.
    assert list(hub_utils.filter_repo_objects(
        ["model-00001-of-00002.safetensors"],
        allow_patterns=downloader.WEIGHT_PATTERNS))


# ---------------------------------------------------------------------------
# CORE-R3: the cached-pipeline check looks where pyannote 3.x loads from
# ---------------------------------------------------------------------------

@pytest.fixture
def no_token_anywhere(monkeypatch, tmp_path):
    """No token in the environment, the repository, the cwd or any HF home."""
    import preflight
    for var in ("HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGING_FACE_HUB_TOKEN",
                "HF_TOKEN_PATH", "HF_HOME", "XDG_CACHE_HOME", "HF_HUB_CACHE",
                "HUGGINGFACE_HUB_CACHE", "PYANNOTE_CACHE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    monkeypatch.setattr(preflight, "_REPO_ROOT", tmp_path / "repo")
    (tmp_path / "work").mkdir()
    monkeypatch.chdir(tmp_path / "work")
    fake = types.ModuleType("pyannote.audio")
    monkeypatch.setitem(sys.modules, "pyannote", types.ModuleType("pyannote"))
    monkeypatch.setitem(sys.modules, "pyannote.audio", fake)
    monkeypatch.delitem(sys.modules, "pyannote.audio.core.model", raising=False)
    return preflight


def _cache_every_repo(preflight, root: Path) -> None:
    for repo in preflight.PYANNOTE_PIPELINE_REPOS:
        (root / ("models--" + repo.replace("/", "--")) / "snapshots" / "rev").mkdir(
            parents=True)
    # The pipeline counts as cached only with a config.yaml pyannote can
    # load (NEW-INC-01).
    (root / "models--pyannote--speaker-diarization-3.1" / "snapshots" / "rev"
     / "config.yaml").write_text(
        "pipeline:\n  name: pyannote.audio.pipelines.SpeakerDiarization\n",
        encoding="utf-8")


def test_core_r3_hub_cache_alone_does_not_excuse_a_missing_token(
        no_token_anywhere, monkeypatch, tmp_path):
    preflight = no_token_anywhere
    hf_home = tmp_path / "hfhome"
    monkeypatch.setenv("HF_HOME", str(hf_home))
    # What setup/cache_pyannote_arc.py fills, and pyannote 3.x never reads.
    _cache_every_repo(preflight, hf_home / "hub")
    result = preflight.check_diarisation(diarisation_required=True)
    assert result.status == preflight.FAIL


def test_core_r3_default_pyannote_cache_is_under_torch(no_token_anywhere, tmp_path):
    preflight = no_token_anywhere
    default = tmp_path / "home" / ".cache" / "torch" / "pyannote"
    assert preflight.pyannote_cache_dir() == default
    _cache_every_repo(preflight, default)
    assert preflight.check_diarisation(diarisation_required=True).status == preflight.WARN


def test_core_r3_loaded_pyannote_constant_wins(no_token_anywhere, monkeypatch, tmp_path):
    preflight = no_token_anywhere
    monkeypatch.setenv("PYANNOTE_CACHE", str(tmp_path / "from_env"))
    model_module = types.ModuleType("pyannote.audio.core.model")
    model_module.CACHE_DIR = str(tmp_path / "from_module")
    monkeypatch.setitem(sys.modules, "pyannote.audio.core.model", model_module)
    assert preflight.pyannote_cache_dir() == tmp_path / "from_module"


# ---------------------------------------------------------------------------
# CORE-R4: files named after the run but not <stem>_* are reported again
# ---------------------------------------------------------------------------

def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_core_r4_unmasked_copies_beside_the_run_are_reported(tmp_path):
    from provenance import verify_manifest, write_run_manifest
    files = [_write(tmp_path / "P03_transcript.txt", "[NAME] said hi")]
    mpath = tmp_path / "P03_manifest.json"
    write_run_manifest(files, tmp_path, mpath)
    assert verify_manifest(mpath)["ok"] is True

    _write(tmp_path / "P03.txt", "Alice said hi")
    _write(tmp_path / "P03 (edited).docx", "Alice said hi")
    report = verify_manifest(mpath)
    assert report["ok"] is False
    assert report["unlisted"] == ["P03 (edited).docx", "P03.txt"]


def test_core_r4_input_audio_and_other_runs_are_not_reported(tmp_path):
    from provenance import verify_manifest, write_run_manifest
    audio = tmp_path / "P1.wav"
    audio.write_bytes(b"RIFFfake")
    p10 = [_write(tmp_path / "P10_transcript.txt", "p10")]
    write_run_manifest(p10, tmp_path, tmp_path / "P10_manifest.json")
    p1 = [_write(tmp_path / "P1_transcript.txt", "p1")]
    write_run_manifest(p1, tmp_path, tmp_path / "P1_manifest.json",
                       audio_path=audio)
    # A later P10 file belongs to P10's run, not P1's.
    _write(tmp_path / "P10_transcript_extra.txt", "p10 again")
    report = verify_manifest(tmp_path / "P1_manifest.json")
    assert report["ok"] is True and report["unlisted"] == []
    assert verify_manifest(tmp_path / "P10_manifest.json")["unlisted"] == [
        "P10_transcript_extra.txt"]


def test_core_r4_underscore_stems_do_not_claim_each_other(tmp_path):
    from provenance import verify_manifest, write_run_manifest
    write_run_manifest([_write(tmp_path / "ep05_v2_transcript.txt", "v2")],
                       tmp_path, tmp_path / "ep05_v2_manifest.json")
    write_run_manifest([_write(tmp_path / "ep05_transcript.txt", "v1")],
                       tmp_path, tmp_path / "ep05_manifest.json")
    assert verify_manifest(tmp_path / "ep05_manifest.json")["unlisted"] == []


# ---------------------------------------------------------------------------
# CORE-R5: the wizard's test WAV lives in a private, always-removed directory
# ---------------------------------------------------------------------------

def _fake_pyannote(monkeypatch, pipeline_factory):
    class Pipeline:
        @staticmethod
        def from_pretrained(*args, **kwargs):
            return pipeline_factory()
    audio = types.ModuleType("pyannote.audio")
    audio.Pipeline = Pipeline
    monkeypatch.setitem(sys.modules, "pyannote", types.ModuleType("pyannote"))
    monkeypatch.setitem(sys.modules, "pyannote.audio", audio)


@pytest.mark.parametrize("outcome", ["runs", "raises", "gated"])
def test_core_r5_test_wav_is_private_and_removed(monkeypatch, tmp_path, outcome):
    pytest.importorskip("soundfile")
    import tempfile
    shared = tmp_path / "shared_tmp"
    shared.mkdir()
    # Another user's leftover under the old fixed name must not matter.
    (shared / "test_pyannote.wav").write_bytes(b"not ours")
    monkeypatch.setattr(tempfile, "tempdir", str(shared))
    seen = {}

    class _Diarisation:
        def itertracks(self):
            return iter(())

    def _pipeline(path):
        seen["path"] = Path(path)
        assert seen["path"].is_file()
        if outcome == "raises":
            raise RuntimeError("CUDA went away")
        return _Diarisation()

    _fake_pyannote(monkeypatch, lambda: None if outcome == "gated" else _pipeline)
    wizard = _load_setup_module("setup_pyannote")
    assert wizard.test_pyannote_functionality("hf_x") is (outcome == "runs")
    # Only the other user's file is left in the shared directory.
    assert sorted(p.name for p in shared.iterdir()) == ["test_pyannote.wav"]
    if outcome != "gated":
        assert seen["path"].parent != shared and not seen["path"].exists()


# ---------------------------------------------------------------------------
# CORE-R6: setup_environment.sh finds preflight from any working directory
# ---------------------------------------------------------------------------

def _precache_block() -> str:
    """The Python that setup_environment.sh's optional STEP 5 runs."""
    import re
    script = (PROJECT_ROOT / "setup" / "setup_environment.sh").read_text(encoding="utf-8")
    match = re.search(r'REPO_DIR="\$REPO_DIR" python3 -c "\n(.*?)\n" \|\| echo ', script, re.S)
    assert match, "STEP 5 must pass REPO_DIR and tolerate its own failure"
    code = match.group(1)
    # Inside bash double quotes these would be expanded before Python sees them.
    assert "$" not in code and "`" not in code and '"' not in code
    return code


def _fake_packages(root: Path, pipeline_result: str) -> Path:
    files = {
        "transformers/__init__.py": "def pipeline(*a, **k):\n    return object()\n",
        "torch/__init__.py": "class cuda:\n    is_available = staticmethod(lambda: False)\n",
        "pyannote/__init__.py": "",
        "pyannote/audio/__init__.py": (
            "class Pipeline:\n"
            "    @staticmethod\n"
            "    def from_pretrained(*a, **k):\n"
            f"        return {pipeline_result}\n"),
    }
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


@pytest.mark.parametrize("pipeline_result, expected", [
    ("object()", "Diarisation model cached"),
    ("None", "Diarisation model NOT cached"),
])
def test_core_r6_precache_imports_preflight_outside_the_repo(tmp_path, pipeline_result,
                                                            expected):
    import os
    import subprocess
    env = dict(os.environ)
    env.update(REPO_DIR=str(PROJECT_ROOT), HF_TOKEN="hf_test",
               PYTHONPATH=str(_fake_packages(tmp_path / "pkgs", pipeline_result)))
    elsewhere = tmp_path / "speech_transcription_env"
    elsewhere.mkdir()
    # -S skips site processing. Where pyannote is really installed (ARC), its
    # wheels' *-nspkg.pth hooks register the site-packages 'pyannote'
    # namespace at start-up, before PYTHONPATH is searched, so the fake
    # package would never be imported (ARC job 8917459). Everything the block
    # imports is stdlib, faked here, or preflight.py.
    result = subprocess.run([sys.executable, "-S", "-c", _precache_block()], cwd=elsewhere,
                            env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert expected in result.stdout
    assert "Models ready!" in result.stdout


# ---------------------------------------------------------------------------
# INTEG-01: the regeneration gate is not fooled by the checkout's line endings
# ---------------------------------------------------------------------------

def _gate():
    spec = importlib.util.spec_from_file_location(
        "_audit_review_verify_regeneration", PROJECT_ROOT / "tools" / "verify_regeneration.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_integ01_text_artefacts_match_up_to_line_endings(tmp_path):
    gate = _gate()
    produced = tmp_path / "produced.csv"
    committed = tmp_path / "committed" / "footprint_report.csv"
    committed.parent.mkdir()
    produced.write_bytes(b"job,kwh\r\n1,0.5\r\n")        # csv writers emit CRLF
    committed.write_bytes(b"job,kwh\n1,0.5\n")            # an LF checkout
    assert gate.compare(produced, committed) == "up to line endings"
    committed.write_bytes(b"job,kwh\r\n1,0.5\r\n")        # a CRLF checkout
    assert gate.compare(produced, committed) == "byte for byte"
    committed.write_bytes(b"job,kwh\n1,0.6\n")            # a moved number
    assert gate.compare(produced, committed) is None


def test_integ01_other_files_must_match_byte_for_byte(tmp_path):
    gate = _gate()
    produced, committed = tmp_path / "a.png", tmp_path / "b.png"
    produced.write_bytes(b"\x89PNG\r\n\x1a\n")
    committed.write_bytes(b"\x89PNG\n\x1a\n")
    assert gate.compare(produced, committed) is None

# ---------------------------------------------------------------------------
# G5: a summary that embeds its run metadata still matches a regeneration
# ---------------------------------------------------------------------------

def test_g5_json_matches_apart_from_run_metadata(tmp_path):
    import json
    gate = _gate()
    produced, committed = tmp_path / "p.json", tmp_path / "c.json"
    body = {"overall": {"recall": 0.35}, "n": 1940}
    produced.write_text(json.dumps({**body, "run_metadata": {"git_commit": "a"},
                                    "generated": "2026-09-27"}))
    committed.write_text(json.dumps({**body, "run_metadata": {"git_commit": "b"}}))
    assert gate.compare(produced, committed) is None
    assert gate.same_but_volatile(produced, committed)
    committed.write_text(json.dumps({**body, "n": 1939, "run_metadata": {}}))
    assert not gate.same_but_volatile(produced, committed)
    committed.write_text("not json")
    assert not gate.same_but_volatile(produced, committed)


def test_g5_wer_ci_matches_up_to_the_path_separator(tmp_path):
    gate = _gate()
    produced, committed = tmp_path / "p.csv", tmp_path / "c.csv"
    produced.write_text("file,wer\noutput/evaluation/wer_report.csv,0.02\n")
    committed.write_text("file,wer\noutput\\evaluation\\wer_report.csv,0.02\n")
    assert gate._same_up_to_path_separator(produced, committed)
    committed.write_text("file,wer\noutput\\evaluation\\wer_report.csv,0.03\n")
    assert not gate._same_up_to_path_separator(produced, committed)
