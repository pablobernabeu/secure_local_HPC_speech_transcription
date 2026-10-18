"""Tests for the preflight environment doctor.

What an environment happens to contain varies by machine, so these tests
avoid asserting on any real dependency's presence. They pin the parts that
must hold everywhere: version parsing, the convention that every non-OK
result carries a remedy, the exit-code contract, the GPU-required
escalation, and token discovery. The environment-dependent checks are
exercised through injected fakes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import preflight  # noqa: E402
from preflight import (  # noqa: E402
    FAIL,
    OK,
    WARN,
    CheckResult,
    _find_hf_token,
    _parse_version,
    check_python,
    run_checks,
)


def test_parse_version_handles_real_shapes():
    assert _parse_version("4.57.1") == (4, 57, 1)
    assert _parse_version("2.5.0+cu121") == (2, 5, 0)
    assert _parse_version("5.7.0.dev0") == (5, 7, 0)
    # Unparseable compares smaller than any floor, so floors fail loudly.
    assert _parse_version("garbage") == ()
    assert _parse_version("garbage") < (4, 45)


def test_current_python_passes():
    """The suite itself runs on a supported interpreter, so this is stable."""
    assert check_python().status == OK


def test_every_non_ok_result_names_a_remedy():
    """A warning without a fix is homework; the convention is load-bearing."""
    for result in run_checks():
        if result.status != OK:
            assert result.remedy, f"{result.name} is {result.status} " \
                                  f"without a remedy"


def test_gpu_required_escalates_a_missing_gpu(monkeypatch):
    """The same absent GPU is WARN on a laptop and FAIL in a GPU job."""
    class _FakeCuda:
        @staticmethod
        def is_available():
            return False

    class _FakeTorch:
        __version__ = "2.5.0"
        cuda = _FakeCuda()

    monkeypatch.setitem(sys.modules, "torch", _FakeTorch())
    relaxed = preflight.check_torch(gpu_required=False)
    strict = preflight.check_torch(gpu_required=True)
    assert relaxed.status == WARN
    assert strict.status == FAIL
    assert "cu121" in (strict.remedy or "")     # names the actual fix


def test_transformers_floor_and_trap_note(monkeypatch):
    class _FakeTransformers:
        __version__ = "4.44.0"

    monkeypatch.setitem(sys.modules, "transformers", _FakeTransformers())
    below = preflight.check_transformers()
    assert below.status == FAIL and "4.56" in below.remedy

    # 4.45-4.55 has detect_language but rejects pipeline(dtype=), which the
    # timestamp benchmark passes, so it must fail too (DEPS-10).
    _FakeTransformers.__version__ = "4.55.4"
    assert preflight.check_transformers().status == FAIL

    _FakeTransformers.__version__ = "4.57.1"
    trapped = preflight.check_transformers()
    assert trapped.status == OK
    # The 4.48-5.6 return_language trap is stated, with the reassurance.
    assert "return_language" in trapped.detail
    assert "detect_language" in trapped.detail

    _FakeTransformers.__version__ = "5.7.0"
    clean = preflight.check_transformers()
    assert clean.status == OK and "return_language" not in clean.detail


def test_find_hf_token_prefers_env_then_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Every source the shared lookup reads, not only the cwd and home: on
    # ARC the job environment exports HF_HOME (which holds a token) and the
    # clone holds hf_token.txt at the repository root (CORE-R2).
    for var in ("HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGING_FACE_HUB_TOKEN",
                "HF_TOKEN_PATH", "HF_HOME", "XDG_CACHE_HOME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(preflight, "_REPO_ROOT", tmp_path / "repo")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert _find_hf_token() is None

    (tmp_path / "hf_token.txt").write_text("hf_secret", encoding="utf-8")
    assert _find_hf_token() == "hf_token.txt"

    monkeypatch.setenv("HF_TOKEN", "hf_env")
    assert "HF_TOKEN" in _find_hf_token()      # env wins over the file


def test_exit_code_contract(monkeypatch, capsys, tmp_path):
    """Exit 1 exactly when something FAILs; warnings alone exit 0."""
    healthy = [CheckResult("a", OK, "fine"),
               CheckResult("b", WARN, "degraded", "pip install b")]
    broken = healthy + [CheckResult("c", FAIL, "absent", "pip install c")]

    monkeypatch.setattr(preflight, "run_checks", lambda **kwargs: healthy)
    assert preflight.main([]) == 0

    monkeypatch.setattr(preflight, "run_checks", lambda **kwargs: broken)
    out_path = tmp_path / "report.json"
    assert preflight.main(["--json", str(out_path)]) == 1

    # The JSON mirrors the printed report, for scripts that want structure.
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert [entry["name"] for entry in payload] == ["a", "b", "c"]
    printed = capsys.readouterr().out
    assert "NOT USABLE" in printed and "fix: pip install c" in printed


def test_diarisation_required_escalates(monkeypatch):
    """The same absent pyannote is WARN normally and FAIL when the job's
    point is speaker attribution."""
    # A None entry in sys.modules makes the import raise ImportError,
    # deterministically, whatever this machine has installed.
    monkeypatch.setitem(sys.modules, "pyannote.audio", None)
    relaxed = preflight.check_diarisation(diarisation_required=False)
    strict = preflight.check_diarisation(diarisation_required=True)
    assert relaxed.status == WARN
    assert strict.status == FAIL
    assert relaxed.remedy and strict.remedy


def test_a_crashing_check_becomes_a_fail_not_a_crash(monkeypatch):
    """The never-crash contract is structural, not a per-check promise."""
    def _explodes():
        raise RuntimeError("wired wrong")

    monkeypatch.setattr(preflight, "check_numpy", _explodes)
    results = run_checks()
    numpy_result = next(r for r in results if r.name == "numpy")
    assert numpy_result.status == FAIL
    assert "crashed" in numpy_result.detail
    assert "RuntimeError" in numpy_result.detail
    assert numpy_result.remedy      # even the crash names a next step
