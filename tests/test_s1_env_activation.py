"""Stage-1 ENV tests for activate_project_env_arc.sh.

The script turns the user site off and no longer puts a non-existent
python3.11 site-packages on PYTHONPATH (DEPS-02, SHELL-07). A venv loads the
one Python module it was built with instead of the first of several that
`module spider` listed, and an interpreter below the 3.11 floor is refused.

The real script is sourced under bash against a fake $DATA; the behaviour
tests need a POSIX bash (Git Bash on Windows) and are skipped without one.
"""

from __future__ import annotations

import re
from pathlib import Path

from test_audit_shell_transcription_wrapper import (
    REPO, _copy_lf, _posix, _run, _write_stub, needs_bash,
)


def _activate(tmp_path: Path, python_body: str | None, venv: bool = False):
    """Source the real activation script against a fake $DATA.

    Returns the completed process, the variables the driver prints and the
    log of `module` calls.
    """
    repo = tmp_path / "repo"
    _copy_lf(REPO / "activate_project_env_arc.sh", repo / "activate_project_env_arc.sh")
    data = tmp_path / "data"
    env_dir = data / "speech_transcription_env"
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    _write_stub(stubs / "module", 'printf "module %s\\n" "$*" >> "$STUB_LOG"\n')
    if python_body is not None:
        if venv:
            (env_dir / "venv" / "bin").mkdir(parents=True)
            _write_stub(env_dir / "venv" / "bin" / "python", python_body)
            # Located from its own path, so the PATH entry is in the shell's
            # own form (a "C:/..." entry would split at the colon).
            (env_dir / "venv" / "bin" / "activate").write_bytes(
                b'_bin="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
                b'export PATH="$_bin:$PATH"\n'
                b'export VIRTUAL_ENV="$(dirname "$_bin")"\n')
        else:
            (env_dir / "bin").mkdir(parents=True)
            (env_dir / "conda-meta").mkdir()
            _write_stub(env_dir / "bin" / "python", python_body)
    driver = tmp_path / "driver.sh"
    # The activation puts $DATA/.../bin on PATH, so under Git Bash $DATA must
    # be in the shell's /c/... form: a "C:/..." PATH entry splits at the colon.
    driver.write_bytes(
        b'if command -v cygpath >/dev/null 2>&1; then DATA="$(cygpath -u "$DATA")"; fi\n'
        b'export DATA\n'
        b'source "$1"; rc=$?\n'
        b'printf "rc=%s\\n" "$rc"\n'
        b'printf "NOUSERSITE=%s\\n" "${PYTHONNOUSERSITE:-}"\n'
        b'printf "PYTHONPATH=%s\\n" "${PYTHONPATH:-}"\n'
        b'printf "PYTHONUSERBASE=%s\\n" "${PYTHONUSERBASE:-}"\n')
    log = tmp_path / "calls.log"
    result = _run(driver, [_posix(repo / "activate_project_env_arc.sh")], stubs,
                  {"DATA": _posix(data), "STUB_LOG": _posix(log), "PYTHONPATH": ""},
                  tmp_path)
    values = dict(line.split("=", 1) for line in result.stdout.splitlines()
                  if re.match(r"^(rc|NOUSERSITE|PYTHONPATH|PYTHONUSERBASE)=", line))
    return result, values, log


_GOOD_PYTHON = ('if [[ "${1:-}" == "--version" ]]; then echo "Python 3.12.12"; exit 0; fi\n'
                'if [[ "${1:-}" == "-c" ]]; then exit 0; fi\n')


@needs_bash
def test_activation_turns_the_user_site_off(tmp_path):
    result, values, _ = _activate(tmp_path, _GOOD_PYTHON)
    assert values["rc"] == "0", result.stdout + result.stderr
    assert values["NOUSERSITE"] == "1"
    # The old python3.11 entry pointed at a directory that does not exist in
    # the Python 3.12 environment (SHELL-07).
    assert "python3.11" not in values["PYTHONPATH"]
    assert values["PYTHONUSERBASE"].endswith("/speech_transcription_env/.python_user")
    assert "sys.path:" in result.stdout


@needs_bash
def test_activation_refuses_python_below_the_floor(tmp_path):
    old = ('if [[ "${1:-}" == "--version" ]]; then echo "Python 3.10.12"; exit 0; fi\n'
           'if [[ "${1:-}" == "-c" ]]; then exit 1; fi\n')
    result, values, _ = _activate(tmp_path, old)
    assert values["rc"] == "1"
    assert "below the Python 3.11 floor" in result.stdout


@needs_bash
def test_activation_without_an_environment_fails(tmp_path):
    _, values, _ = _activate(tmp_path, None)
    assert values["rc"] == "1"


@needs_bash
def test_a_venv_loads_the_one_python_module_it_was_built_with(tmp_path):
    result, values, log = _activate(tmp_path, _GOOD_PYTHON, venv=True)
    assert values["rc"] == "0", result.stdout + result.stderr
    loads = [line for line in log.read_text().splitlines() if line.startswith("module load")]
    # No cascade over 3.12/3.11/3.10 any more: exactly one, fixed module.
    assert loads == ["module load Python/3.12.3-GCCcore-13.3.0"]


def test_activation_no_longer_names_python311_or_a_module_cascade():
    text = (REPO / "activate_project_env_arc.sh").read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert "python3.11" not in code
    assert "module spider" not in code
    assert "export PYTHONNOUSERSITE=1" in code
