"""setup/setup_pyannote.py installs what requirements.txt pins, in one pip call.

The wizard used to install ``pyannote.audio>=3.1.0`` with no upper bound,
unpinned torch and torchaudio in separate pip calls, and speechbrain, which
audit finding DEPS-11 removed; requirements.txt caps pyannote.audio below 4
(DEPS-10). It now reads the specifiers from requirements.txt. No test here
runs pip: subprocess.run is replaced by a recorder.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import types
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def wizard():
    spec = importlib.util.spec_from_file_location(
        "_setup_pyannote_requirements", PROJECT_ROOT / "setup" / "setup_pyannote.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _requirement_lines() -> dict[str, str]:
    lines = {}
    for raw in (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            lines[line.split(">")[0].split("=")[0].split("<")[0].lower()] = line
    return lines


def test_the_wizard_takes_its_specifiers_from_requirements_txt(wizard):
    expected = _requirement_lines()
    assert wizard.pyannote_requirements() == [
        expected["torch"], expected["torchaudio"], expected["pyannote.audio"]]
    assert "<4" in wizard.pyannote_requirements()[2]


def test_the_wizard_installs_in_one_call_without_speechbrain(wizard, monkeypatch):
    calls = []

    def record(command, **kwargs):
        calls.append(command)
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", record)
    monkeypatch.setenv("VIRTUAL_ENV", str(PROJECT_ROOT))

    assert wizard.install_pyannote() is True
    installs = [c for c in calls if c[1:4] == ["-m", "pip", "install"]]
    assert installs == [[sys.executable, "-m", "pip", "install",
                         *wizard.pyannote_requirements()]]
    assert not any("speechbrain" in part for call in calls for part in call)


def test_a_failed_install_is_reported_as_failed(wizard, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: types.SimpleNamespace(
        returncode=1, stdout="", stderr="no matching distribution"))
    monkeypatch.setenv("VIRTUAL_ENV", str(PROJECT_ROOT))
    assert wizard.install_pyannote() is False


def test_a_package_missing_from_the_file_is_an_error(wizard, tmp_path):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("torch>=2.0.0\n# pyannote.audio>=3.1.0,<4\n", encoding="utf-8")
    with pytest.raises(ValueError, match="torchaudio, pyannote.audio"):
        wizard.pyannote_requirements(requirements)


def test_names_match_as_pip_compares_them(wizard, tmp_path):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(
        "Torch>=2.0.0  # inline comment\ntorchaudio>=2.0.0\npyannote-audio>=3.1.0,<4\n",
        encoding="utf-8")
    assert wizard.pyannote_requirements(requirements) == [
        "Torch>=2.0.0", "torchaudio>=2.0.0", "pyannote-audio>=3.1.0,<4"]
