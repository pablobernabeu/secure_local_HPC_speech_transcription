"""Regression tests for the CORE audit fixes.

Each test names the finding it pins. All are hermetic: files live under
tmp_path, environment variables are set with monkeypatch, and nothing
touches the network.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import re
import sys
from pathlib import Path

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import audio_io
import confidence
import preflight
import provenance
from provenance import (
    KeyFileError,
    load_key,
    verify_manifest,
    write_manifest,
    write_run_manifest,
)

_KEY = b"a-test-signing-key"


def _touch(path: Path, text: str = "x") -> Path:
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# CORE-01: exact artefact lists, escaped stem matching, no empty manifests
# ---------------------------------------------------------------------------

def test_core01_p1_manifest_ignores_p10_files(tmp_path):
    p10 = [_touch(tmp_path / "P10_transcript.txt", "p10"),
           _touch(tmp_path / "P10_transcript.docx", "p10")]
    write_run_manifest(p10, tmp_path, tmp_path / "P10_manifest.json")
    p1 = [_touch(tmp_path / "P1_transcript.txt", "p1")]
    m = write_run_manifest(p1, tmp_path, tmp_path / "P1_manifest.json")
    assert [e["path"] for e in m["artefacts"]] == ["P1_transcript.txt"]

    # Re-running P10 must not make P1 look tampered with.
    _touch(tmp_path / "P10_transcript.txt", "p10 again")
    report = verify_manifest(tmp_path / "P1_manifest.json")
    assert report["ok"] is True and report["unlisted"] == []


def test_core01_bracketed_stem_is_covered(tmp_path):
    stem = "Interview [P01]"
    files = [_touch(tmp_path / f"{stem}_transcript.txt", "hello")]
    mpath = tmp_path / f"{stem}_manifest.json"
    m = write_run_manifest(files, tmp_path, mpath)
    assert len(m["artefacts"]) == 1
    # Tampering is now detected, and an added file is reported.
    _touch(tmp_path / f"{stem}_transcript.txt", "tampered")
    _touch(tmp_path / f"{stem}_transcript_extra.txt", "added")
    report = verify_manifest(mpath)
    assert report["ok"] is False
    assert report["modified"] == [f"{stem}_transcript.txt"]
    assert report["unlisted"] == [f"{stem}_transcript_extra.txt"]


def test_core01_stale_rerun_files_are_not_swept_in(tmp_path):
    _touch(tmp_path / "ep_transcript_with_speakers.txt", "old run")
    files = [_touch(tmp_path / "ep_transcript.txt", "new run")]
    m = write_run_manifest(files, tmp_path, tmp_path / "ep_manifest.json")
    assert [e["path"] for e in m["artefacts"]] == ["ep_transcript.txt"]


def test_core01_zero_artefacts_is_refused(tmp_path):
    mpath = tmp_path / "x_manifest.json"
    with pytest.raises(ValueError):
        write_run_manifest([], tmp_path, mpath)
    with pytest.raises(ValueError):
        write_manifest([], tmp_path, mpath)       # the old entry point too
    assert not mpath.exists()


def test_core01_missing_or_outside_artefact_is_refused(tmp_path):
    inside = tmp_path / "run"
    inside.mkdir()
    with pytest.raises(ValueError):
        write_run_manifest([inside / "absent.txt"], inside,
                           inside / "r_manifest.json")
    outside = _touch(tmp_path / "elsewhere.txt")
    with pytest.raises(ValueError):
        write_run_manifest([outside], inside, inside / "r_manifest.json")


def test_core01_none_entries_are_skipped(tmp_path):
    files = [_touch(tmp_path / "a_transcript.txt"), None]
    m = write_run_manifest(files, tmp_path, tmp_path / "a_manifest.json")
    assert len(m["artefacts"]) == 1


# ---------------------------------------------------------------------------
# CORE-03: an explicit key file must be usable
# ---------------------------------------------------------------------------

def test_core03_missing_key_file_raises(tmp_path):
    with pytest.raises(KeyFileError):
        load_key(tmp_path / "no-such.key")


def test_core03_empty_key_file_raises(tmp_path):
    kf = _touch(tmp_path / "empty.key", "  \n")
    with pytest.raises(KeyFileError):
        load_key(kf)


def test_core03_env_branch_still_returns_none(monkeypatch):
    monkeypatch.delenv("TRANSCRIPTION_SIGNING_KEY", raising=False)
    assert load_key() is None


def test_core03_cli_exits_2_on_unreadable_key(tmp_path, capsys):
    files = [_touch(tmp_path / "s_transcript.txt")]
    mpath = tmp_path / "s_manifest.json"
    write_run_manifest(files, tmp_path, mpath, key=_KEY)
    rc = provenance.main(["verify", str(mpath), "--key-file",
                          str(tmp_path / "typo.key")])
    assert rc == 2


def test_core03_key_file_requires_a_signature(tmp_path):
    files = [_touch(tmp_path / "u_transcript.txt")]
    mpath = tmp_path / "u_manifest.json"
    write_run_manifest(files, tmp_path, mpath)             # unsigned
    kf = _touch(tmp_path / "k.key", _KEY.decode())
    assert provenance.main(["verify", str(mpath), "--key-file", str(kf)]) == 1


def test_core03_require_signature_without_key_fails(tmp_path, monkeypatch):
    monkeypatch.delenv("TRANSCRIPTION_SIGNING_KEY", raising=False)
    files = [_touch(tmp_path / "v_transcript.txt")]
    mpath = tmp_path / "v_manifest.json"
    write_run_manifest(files, tmp_path, mpath, key=_KEY)
    assert provenance.main(["verify", str(mpath)]) == 0     # integrity only
    assert provenance.main(["verify", str(mpath), "--require-signature"]) == 1
    kf = _touch(tmp_path / "k.key", _KEY.decode())
    assert provenance.main(["verify", str(mpath), "--key-file", str(kf)]) == 0


# ---------------------------------------------------------------------------
# CORE-02: preflight survives a broken numpy
# ---------------------------------------------------------------------------

def test_core02_run_checks_returns_without_numpy(monkeypatch):
    # Keep heavy libraries from being imported for the first time against a
    # broken numpy, which would leave them half-initialised for later tests.
    for heavy in ("torch", "transformers", "pyannote.audio"):
        monkeypatch.setitem(sys.modules, heavy, None)
    monkeypatch.setitem(sys.modules, "numpy", None)
    monkeypatch.delitem(sys.modules, "audio_io", raising=False)
    results = preflight.run_checks()
    by_name = {r.name: r for r in results}
    assert by_name["numpy"].status == preflight.FAIL
    assert by_name["audio"].status == preflight.FAIL
    assert "numpy" in by_name["audio"].detail


def test_core02_run_checks_converts_systemexit(monkeypatch):
    def _exits():
        raise SystemExit("boom")
    monkeypatch.setattr(preflight, "check_numpy", _exits)
    result = next(r for r in preflight.run_checks() if r.name == "numpy")
    assert result.status == preflight.FAIL and "SystemExit" in result.detail


def test_core02_audio_io_raises_importerror_without_numpy(monkeypatch):
    monkeypatch.setitem(sys.modules, "numpy", None)
    monkeypatch.delitem(sys.modules, "audio_io", raising=False)
    with pytest.raises(ImportError):
        importlib.import_module("audio_io")


# ---------------------------------------------------------------------------
# CORE-11 / CORE-13: shared token resolution
# ---------------------------------------------------------------------------

@pytest.fixture
def clean_token_env(monkeypatch, tmp_path):
    for var in ("HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGING_FACE_HUB_TOKEN",
                "HF_TOKEN_PATH", "HF_HOME", "XDG_CACHE_HOME", "HF_HUB_CACHE",
                "HUGGINGFACE_HUB_CACHE", "PYANNOTE_CACHE"):
        monkeypatch.delenv(var, raising=False)
    # A real pyannote imported by an earlier test would fix the cache path.
    monkeypatch.delitem(sys.modules, "pyannote.audio.core.model", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(preflight, "_REPO_ROOT", root)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    return root


def test_core11_hf_home_token_is_found(clean_token_env, monkeypatch, tmp_path):
    hf_home = tmp_path / "hfhome"
    hf_home.mkdir()
    _touch(hf_home / "token", "hf_fromhome\n")
    monkeypatch.setenv("HF_HOME", str(hf_home))
    token, source = preflight.resolve_hf_token()
    assert token == "hf_fromhome" and source == str(hf_home / "token")


def test_core11_repo_root_token_found_from_any_cwd(clean_token_env):
    _touch(clean_token_env / "hf_token.txt", "hf_root")
    assert preflight.resolve_hf_token() == (
        "hf_root", str(clean_token_env / "hf_token.txt"))


def test_core13_env_wins_and_hub_variable_is_read(clean_token_env, monkeypatch):
    _touch(clean_token_env / "hf_token.txt", "hf_root")
    monkeypatch.setenv("HUGGING_FACE_HUB_TOKEN", "hf_env")
    token, source = preflight.resolve_hf_token()
    assert token == "hf_env" and "HUGGING_FACE_HUB_TOKEN" in source


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "utf-16-be-bom"])
def test_a_token_file_with_a_byte_order_mark_is_read(clean_token_env, encoding):
    """A UTF-8 mark survived .strip() and became part of the token; a UTF-16
    file failed the UTF-8 decode and was skipped as if absent."""
    path = clean_token_env / "hf_token.txt"
    if encoding == "utf-16-be-bom":
        path.write_bytes(b"\xfe\xff" + "hf_marked\r\n".encode("utf-16-be"))
    else:
        path.write_bytes("hf_marked\r\n".encode(encoding))
    assert preflight.resolve_hf_token() == ("hf_marked", str(path))


def test_an_undecodable_token_file_is_still_skipped(clean_token_env, monkeypatch, tmp_path):
    (clean_token_env / "hf_token.txt").write_bytes(b"\xff\xfe\x00")   # odd length
    hf_home = tmp_path / "hfhome"
    hf_home.mkdir()
    _touch(hf_home / "token", "hf_fromhome")
    monkeypatch.setenv("HF_HOME", str(hf_home))
    assert preflight.resolve_hf_token() == ("hf_fromhome", str(hf_home / "token"))


def test_core13_nothing_found(clean_token_env):
    assert preflight.resolve_hf_token() == (None, None)


def test_core11_cached_pipeline_downgrades_missing_token(clean_token_env,
                                                         monkeypatch, tmp_path):
    class _Pyannote:
        pass
    monkeypatch.setitem(sys.modules, "pyannote", _Pyannote())
    monkeypatch.setitem(sys.modules, "pyannote.audio", _Pyannote())
    # pyannote.audio 3.x reads $PYANNOTE_CACHE, not the hub cache (CORE-R3).
    pyannote_cache = tmp_path / "pyannote_cache"
    monkeypatch.setenv("PYANNOTE_CACHE", str(pyannote_cache))
    strict = preflight.check_diarisation(diarisation_required=True)
    assert strict.status == preflight.FAIL           # nothing cached
    for repo in preflight.PYANNOTE_PIPELINE_REPOS:
        snap = pyannote_cache / ("models--" + repo.replace("/", "--")) / "snapshots" / "abc"
        snap.mkdir(parents=True)
    # The pipeline is cached only with a config.yaml pyannote can load
    # (NEW-INC-01); an empty snapshot is what an interrupted download leaves.
    assert preflight.check_diarisation(diarisation_required=True).status == preflight.FAIL
    _touch(pyannote_cache / "models--pyannote--speaker-diarization-3.1" / "snapshots"
           / "abc" / "config.yaml",
           "pipeline:\n  name: pyannote.audio.pipelines.SpeakerDiarization\n")
    strict = preflight.check_diarisation(diarisation_required=True)
    assert strict.status == preflight.WARN and strict.remedy


def test_xref16_both_spellings_of_the_flag(monkeypatch):
    seen = {}

    def fake_run_checks(**kwargs):
        seen.update(kwargs)
        return []
    monkeypatch.setattr(preflight, "run_checks", fake_run_checks)
    preflight.main(["--diarization-required"])
    assert seen["diarisation_required"] is True


# ---------------------------------------------------------------------------
# CORE-21 / CORE-22: remedies and floors derived, not retyped
# ---------------------------------------------------------------------------

def test_core21_remedy_matches_installed_torch(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda name, *a, **k: None)   # no torchvision
    remedy = preflight.cuda_reinstall_remedy("2.8.0+cpu")
    assert "torch==2.8.0" in remedy and "torchaudio==2.8.0" in remedy
    assert "cu126" in remedy and "cu121" not in remedy
    assert "torchvision" not in remedy
    assert "cu121" in preflight.cuda_reinstall_remedy("2.5.1+cu121")
    # An unknown series gets the constraint, not a guessed command.
    assert "pip install" not in preflight.cuda_reinstall_remedy("2.14.0")


def test_core22_floors_agree_with_setup_and_requirements():
    setup_text = (PROJECT_ROOT / "setup.py").read_text(encoding="utf-8")
    py = re.search(r'python_requires=">=(\d+)\.(\d+)"', setup_text)
    assert py and (int(py.group(1)), int(py.group(2))) == preflight._PYTHON_FLOOR
    req = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")
    tf = re.search(r"^transformers\[torch\]>=(\d+)\.(\d+)", req, re.M)
    assert tf and (int(tf.group(1)), int(tf.group(2))) == preflight._TRANSFORMERS_FLOOR


def test_core22_missing_transformers_remedy_uses_the_floor(monkeypatch):
    monkeypatch.setitem(sys.modules, "transformers", None)
    monkeypatch.setattr(preflight, "_TRANSFORMERS_FLOOR", (9, 99))
    assert ">=9.99" in preflight.check_transformers().remedy


# ---------------------------------------------------------------------------
# CORE-06 / CORE-07 / CORE-23: audio_io
# ---------------------------------------------------------------------------

sf = pytest.importorskip("soundfile")


def test_core06_ffmpeg_keeps_channel_layout_when_not_mono(tmp_path, monkeypatch):
    captured = {}

    class _Done:
        returncode = 1
        stdout = b""
        stderr = b"stop here"

    def fake_run(command, **kwargs):
        captured["command"] = command
        return _Done()
    monkeypatch.setattr(audio_io, "find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(audio_io.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError):
        audio_io.decode_with_ffmpeg(tmp_path / "x.m4a", mono=False)
    assert "-ac" not in captured["command"]
    with pytest.raises(RuntimeError):
        audio_io.decode_with_ffmpeg(tmp_path / "x.m4a", mono=True)
    assert captured["command"][captured["command"].index("-ac") + 1] == "1"


def test_core07_corrupt_wav_names_the_native_error(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_io, "find_ffmpeg", lambda: None)
    path = tmp_path / "broken.wav"
    path.write_bytes(b"RIFF\x00\x00\x00\x00WAVEjunk")
    with pytest.raises(RuntimeError) as excinfo:
        audio_io.load_audio(path)
    assert "soundfile failed" in str(excinfo.value)
    assert excinfo.value.__cause__ is not None


def test_core07_resample_errors_are_not_swallowed(tmp_path, monkeypatch):
    t = np.linspace(0, 1, 44100, endpoint=False, dtype=np.float32)
    path = tmp_path / "tone.wav"
    sf.write(str(path), 0.1 * np.sin(2 * np.pi * 440 * t), 44100)

    def boom(*a, **k):
        raise MemoryError("resampler blew up")
    monkeypatch.setattr(audio_io, "_resample", boom)
    monkeypatch.setattr(audio_io, "decode_with_ffmpeg",
                        lambda *a, **k: pytest.fail("fell back to ffmpeg"))
    with pytest.raises(MemoryError):
        audio_io.load_audio(path, sr=16000)


def test_core23_each_binary_gets_its_own_current_shim(tmp_path, monkeypatch):
    import shutil
    import tempfile

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    bin1, bin2 = tmp_path / "b1", tmp_path / "b2"
    bin1.mkdir()
    bin2.mkdir()
    fake1 = _touch(bin1 / "ffmpeg-v1", "one")
    fake2 = _touch(bin2 / "ffmpeg-v2", "two")
    for fake in (fake1, fake2):
        if os.name != "nt":
            fake.chmod(0o755)
        monkeypatch.setattr(audio_io, "find_ffmpeg", lambda f=fake: str(f))
        monkeypatch.setenv("PATH", str(fake.parent))
        monkeypatch.delenv("IMAGEIO_FFMPEG_EXE", raising=False)
        audio_io.ensure_ffmpeg_on_path()
        found = shutil.which("ffmpeg")
        assert found is not None
        if Path(found).suffix.lower() == ".bat":
            assert str(fake) in Path(found).read_text(encoding="utf-8")
        else:
            assert os.path.samefile(found, fake)
    # One directory per binary, so the two never share a shim.
    shim_parent = next((tmp_path / "tmp").iterdir())
    assert len(list(shim_parent.iterdir())) == 2


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="POSIX ownership check")
def test_core23_foreign_writable_dir_is_not_used(tmp_path, monkeypatch):
    import tempfile

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    parent = tmp_path / f"transcription_ffmpeg_shim-{os.getuid()}"
    parent.mkdir()
    parent.chmod(0o777)
    assert audio_io._private_shim_dir("/opt/ffmpeg-x") is None


# ---------------------------------------------------------------------------
# CORE-10: confidence report with a null end
# ---------------------------------------------------------------------------

def test_core10_print_report_handles_null_end(capsys):
    report = confidence.review_transcript(
        {"segments": [{"start": 612.0, "end": None, "text": ""}]})
    confidence.print_report(report)
    assert "n/a" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# CORE-16: GUI child process encoding
# ---------------------------------------------------------------------------

def test_core16_gui_child_runs_in_utf8():
    pytest.importorskip("tkinter")
    gui = importlib.import_module("local_app.gui")
    kwargs = gui.child_io_kwargs()
    assert kwargs["encoding"] == "utf-8" and kwargs["errors"] == "replace"
    assert kwargs["env"]["PYTHONIOENCODING"] == "utf-8"
    assert kwargs["env"]["PYTHONUTF8"] == "1"
    assert kwargs["env"] is not os.environ


# ---------------------------------------------------------------------------
# CORE-12 / CORE-14 / CORE-15 / CORE-18: setup scripts
# ---------------------------------------------------------------------------

def _load_setup_module(name):
    spec = importlib.util.spec_from_file_location(
        f"_audit_{name}", PROJECT_ROOT / "setup" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_core12_wizard_uses_the_repository_root():
    wizard = _load_setup_module("setup_pyannote")
    assert wizard.TOKEN_FILE == PROJECT_ROOT / "hf_token.txt"


def test_core14_token_save_is_private_and_does_not_clobber(tmp_path):
    cache = _load_setup_module("cache_pyannote_arc")    # no side effects
    assert cache.save_token(tmp_path, "hf_first") is True
    token_file = tmp_path / "token"
    if os.name != "nt":
        assert token_file.stat().st_mode & 0o077 == 0
    assert cache.save_token(tmp_path, "hf_second") is False
    assert token_file.read_text(encoding="utf-8") == "hf_first"
    assert cache.save_token(tmp_path, "hf_second", overwrite=True) is True
    assert token_file.read_text(encoding="utf-8") == "hf_second"
    assert "first" not in cache._masked("hf_first_token_abcd")


def test_core15_embedding_model_is_cached():
    assert "pyannote/wespeaker-voxceleb-resnet34-LM" in preflight.PYANNOTE_PIPELINE_REPOS


def test_core15_config_models_are_discovered(tmp_path):
    cache = _load_setup_module("cache_pyannote_arc")
    _touch(tmp_path / "config.yaml",
           "pipeline:\n  params:\n    embedding: pyannote/wespeaker-voxceleb-resnet34-LM\n"
           "    segmentation: pyannote/segmentation-3.0\n")
    assert cache.repos_named_in_config(tmp_path) == [
        "pyannote/segmentation-3.0", "pyannote/wespeaker-voxceleb-resnet34-LM"]


def test_core18_installer_points_at_the_real_wizard():
    text = (PROJECT_ROOT / "setup" / "install_requirements.py").read_text(encoding="utf-8")
    assert "'setup_pyannote.py']" not in text
    assert "python setup_pyannote.py" not in text


# ---------------------------------------------------------------------------
# CORE-17 / DEPS-11 / DEPS-13 / XREF-02: packaging
# ---------------------------------------------------------------------------

def test_core17_setup_lists_every_top_level_module():
    text = (PROJECT_ROOT / "setup.py").read_text(encoding="utf-8")
    for module in ("transcription", "audio_io", "audio_redaction", "confidence",
                   "ner_masking", "preflight", "provenance", "voice_anonymisation"):
        assert f'"{module}"' in text
        assert (PROJECT_ROOT / f"{module}.py").is_file()


def _requirement_names(path: Path) -> list[str]:
    """The lower-cased package names a requirements file lists, in order."""
    lines = (line.strip() for line in path.read_text(encoding="utf-8").splitlines())
    return [re.split(r"[<>=!~\[; ]", line)[0].lower() for line in lines
            if line and not line.startswith(("#", "-"))]


def test_deps11_runtime_requirements_exclude_dev_tools():
    names = _requirement_names(PROJECT_ROOT / "requirements.txt")
    # Read from requirements-dev.txt, not typed here: a hand-typed tuple
    # still named flake8 and black after ruff had replaced them (SC-22).
    dev_tools = _requirement_names(PROJECT_ROOT / "requirements-dev.txt")
    assert {"pytest", "ruff"} <= set(dev_tools)
    for dev in dev_tools:
        assert dev not in names
    assert len(names) == len(set(names)), "duplicate requirement"


def test_deps18_cli_mains_are_documented():
    assert preflight.main.__doc__ and "exit" in preflight.main.__doc__.lower()
    assert provenance.main.__doc__ and "2" in provenance.main.__doc__
