"""Stage-1 ENV tests for the preflight checks the job gate relies on.

Covers the lock comparison that replaced the installs in hpc/run_tests.sh
(TESTS-02, SHELL-06), the isolation check behind PYTHONNOUSERSITE (DEPS-02),
the CUDA remedy that no longer sends a working CUDA build to be reinstalled
(CORE-21), and the version floors kept in step across files (DEPS-10).
Everything environment-dependent is injected, so the tests hold on any
machine.
"""

from __future__ import annotations

import re
import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import preflight
from preflight import FAIL, OK, WARN


# ---------------------------------------------------------------------------
# --lock (TESTS-02, SHELL-06)
# ---------------------------------------------------------------------------

def _fake_versions(monkeypatch, versions: dict[str, str]) -> None:
    from importlib import metadata

    def version(name: str) -> str:
        try:
            return versions[name]
        except KeyError:
            raise metadata.PackageNotFoundError(name) from None

    monkeypatch.setattr(metadata, "version", version)


def test_lock_passes_when_every_pin_matches(tmp_path, monkeypatch):
    lock = tmp_path / "lock.txt"
    lock.write_text("# header\n\njiwer==4.0.0\ntorch==2.5.1+cu121\n", encoding="utf-8")
    _fake_versions(monkeypatch, {"jiwer": "4.0.0", "torch": "2.5.1+cu121"})
    result = preflight.check_lock(lock)
    assert result.status == OK and "2 pins" in result.detail


def test_lock_fails_on_a_different_or_missing_version(tmp_path, monkeypatch):
    lock = tmp_path / "lock.txt"
    lock.write_text("jiwer==4.0.0\npyannote.audio==3.4.0\ntorch==2.5.1+cu121\n",
                    encoding="utf-8")
    # The ~/.local shadow on ARC: right name, CPU build.
    _fake_versions(monkeypatch, {"jiwer": "4.0.0", "torch": "2.8.0+cpu"})
    result = preflight.check_lock(lock)
    assert result.status == FAIL
    assert "torch 2.8.0+cpu (lock 2.5.1+cu121)" in result.detail
    assert "pyannote.audio missing (lock 3.4.0)" in result.detail
    assert "never install from a job" in result.remedy


def test_lock_that_cannot_be_read_or_holds_no_pins_fails(tmp_path):
    assert preflight.check_lock(tmp_path / "absent.txt").status == FAIL
    empty = tmp_path / "empty.txt"
    empty.write_text("# only a comment\n", encoding="utf-8")
    assert preflight.check_lock(empty).status == FAIL


def test_the_committed_lock_parses_into_pins():
    pins, skipped = preflight._read_lock(PROJECT_ROOT / "requirements-lock.txt")
    assert pins["torch"] == "2.5.1+cu121"
    assert pins["transformers"] == "4.57.1"
    assert pins["pyannote.audio"] == "3.4.0"
    assert not skipped


def test_main_passes_lock_to_run_checks(monkeypatch, tmp_path):
    seen = {}

    def fake_run_checks(**kwargs):
        seen.update(kwargs)
        return [preflight.CheckResult("lock", OK, "fine")]

    monkeypatch.setattr(preflight, "run_checks", fake_run_checks)
    assert preflight.main(["--lock", str(tmp_path / "l.txt")]) == 0
    assert seen["lock"] == tmp_path / "l.txt"


def test_run_checks_adds_the_lock_check_only_when_asked(monkeypatch, tmp_path):
    # Every real check is replaced, so nothing heavy is imported here.
    for short in ("python", "numpy", "audio", "transformers", "isolation"):
        monkeypatch.setattr(preflight, f"check_{short}",
                            lambda n=short: preflight.CheckResult(n, OK, "stub"))
    monkeypatch.setattr(preflight, "check_torch",
                        lambda **_: preflight.CheckResult("torch", OK, "stub"))
    monkeypatch.setattr(preflight, "check_diarisation",
                        lambda **_: preflight.CheckResult("diarisation", OK, "stub"))
    monkeypatch.setattr(preflight, "check_optional",
                        lambda: [preflight.CheckResult("optional", OK, "stub")])
    monkeypatch.setattr(preflight, "check_lock",
                        lambda path: preflight.CheckResult("lock", FAIL, str(path), "x"))
    assert "lock" not in [r.name for r in preflight.run_checks()]
    names = [r.name for r in preflight.run_checks(lock=tmp_path / "l.txt")]
    assert "isolation" in names and "lock" in names
    assert names[-1] == "optional"


# ---------------------------------------------------------------------------
# isolation (DEPS-02)
# ---------------------------------------------------------------------------

def _fake_module(path: Path) -> types.ModuleType:
    module = types.ModuleType("fake")
    module.__file__ = str(path)
    return module


def _isolate(monkeypatch, prefix: Path, torch_file: Path) -> None:
    monkeypatch.setattr(sys, "prefix", str(prefix))
    monkeypatch.setitem(sys.modules, "torch", _fake_module(torch_file))
    monkeypatch.setitem(sys.modules, "transformers",
                        _fake_module(prefix / "lib" / "transformers" / "__init__.py"))
    monkeypatch.setitem(sys.modules, "pyannote.audio",
                        _fake_module(prefix / "lib" / "pyannote" / "audio" / "__init__.py"))


def test_isolation_ok_when_everything_loads_from_the_environment(tmp_path, monkeypatch):
    env = tmp_path / "env"
    _isolate(monkeypatch, env, env / "lib" / "torch" / "__init__.py")
    assert preflight.check_isolation().status == OK


def test_isolation_fails_in_an_activated_environment(tmp_path, monkeypatch):
    env, user_site = tmp_path / "env", tmp_path / "home" / ".local"
    _isolate(monkeypatch, env, user_site / "torch" / "__init__.py")
    monkeypatch.setenv("VIRTUAL_ENV", str(env))
    monkeypatch.delenv("CONDA_PREFIX", raising=False)
    result = preflight.check_isolation()
    assert result.status == FAIL
    assert "torch from" in result.detail and ".local" in result.detail
    assert "PYTHONNOUSERSITE" in result.remedy


def test_isolation_only_warns_without_an_activated_environment(tmp_path, monkeypatch):
    env, user_site = tmp_path / "env", tmp_path / "home" / ".local"
    _isolate(monkeypatch, env, user_site / "torch" / "__init__.py")
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.delenv("CONDA_PREFIX", raising=False)
    result = preflight.check_isolation()
    assert result.status == WARN and result.remedy


def test_isolation_skips_stand_ins_without_a_file(monkeypatch):
    # The fakes other tests put in sys.modules have no __file__ or __spec__.
    monkeypatch.setitem(sys.modules, "torch", object())
    assert preflight._module_origin("torch") is None


# ---------------------------------------------------------------------------
# CUDA remedy (CORE-21)
# ---------------------------------------------------------------------------

def _torch(cuda_build):
    return types.SimpleNamespace(
        __version__="2.5.1+cu121" if cuda_build else "2.5.1+cpu",
        version=types.SimpleNamespace(cuda=cuda_build),
        cuda=types.SimpleNamespace(is_available=lambda: False))


def test_a_cuda_build_without_a_device_is_not_sent_to_reinstall(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", _torch("12.1"))
    result = preflight.check_torch(gpu_required=True)
    assert result.status == FAIL
    assert "CUDA 12.1 build" in result.detail
    assert "pip install" not in result.remedy and "do not reinstall" in result.remedy


def test_a_cpu_build_gets_the_matching_reinstall_from_a_login_node(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", _torch(None))
    result = preflight.check_torch(gpu_required=True)
    assert result.status == FAIL
    assert "torch==2.5.1" in result.remedy and "cu121" in result.remedy
    assert "never from inside a job" in result.remedy


# ---------------------------------------------------------------------------
# Floors and caps (DEPS-10)
# ---------------------------------------------------------------------------

def test_transformers_floor_is_the_dtype_floor_everywhere():
    assert preflight._TRANSFORMERS_FLOOR == (4, 56)
    req = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert re.search(r"^transformers\[torch\]>=4\.56\.0$", req, re.M)
    timestamps = (PROJECT_ROOT / "evaluation" / "benchmark_timestamps.py").read_text(
        encoding="utf-8")
    floor = re.search(r"_TRANSFORMERS_DTYPE_FLOOR = \((\d+), (\d+)\)", timestamps)
    assert floor and (int(floor.group(1)), int(floor.group(2))) <= preflight._TRANSFORMERS_FLOOR


def test_requirements_cap_bibtexparser_and_pin_openai_whisper():
    req = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert re.search(r"^bibtexparser>=1\.4,<2$", req, re.M)
    lock = (PROJECT_ROOT / "requirements-lock.txt").read_text(encoding="utf-8")
    whisper = re.search(r"^openai-whisper==(\S+)$", req, re.M)
    assert whisper and f"openai-whisper=={whisper.group(1)}" in lock
