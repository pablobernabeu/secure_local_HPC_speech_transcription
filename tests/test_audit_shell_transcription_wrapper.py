"""Tests for the HPC transcription wrapper and worker (audit group SHELL).

hpc/submit_transcription.sh and hpc/batch_transcription.sh run on Oxford
ARC, so these tests exercise them locally with stub ``sbatch``, ``module``
and ``python`` executables on PATH. They check the behaviour the audit found
broken: the option list drifting from transcription.py, ``--help`` looping
forever, argument values being split or given literal quotes, a successful
cluster-qualified job ID triggering a second submission, and array tasks
indexing a directory listing that can change after submission.

The option-list test needs only Python. The execution tests need a POSIX
bash with GNU find/sort (Git Bash on Windows) and are skipped without one.
"""

from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SUBMIT = REPO / "hpc" / "submit_transcription.sh"
WORKER = REPO / "hpc" / "batch_transcription.sh"

# Options the wrapper consumes itself and never forwards to transcription.py.
HPC_ONLY = {"--single-file", "--output-name", "--time-limit", "--memory"}


def _array_items(script: str, name: str) -> list[str]:
    """Return the quoted items of the bash array literal ``name=( ... )``."""
    match = re.search(rf"^{name}=\((.*?)^\)", script, re.S | re.M)
    assert match, f"{name} array not found"
    return re.findall(r'"(-[^"]*)"', match.group(1))


def _transcription_option_strings() -> set[str]:
    """Every option string transcription.py's parser accepts.

    Taken from the add_argument calls, plus the ``--no-`` form argparse
    generates for each ``action=argparse.BooleanOptionalAction`` option.
    """
    tree = ast.parse((REPO / "transcription.py").read_text(encoding="utf-8"))
    options: set[str] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"):
            negatable = any(
                kw.arg == "action" and isinstance(kw.value, ast.Attribute)
                and kw.value.attr == "BooleanOptionalAction"
                for kw in node.keywords)
            for arg in node.args:
                if (isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                        and arg.value.startswith("-")):
                    options.add(arg.value)
                    if negatable and arg.value.startswith("--"):
                        options.add("--no-" + arg.value[2:])
    return options


def test_valid_args_match_transcription_argparse() -> None:
    """The wrapper accepts exactly the options transcription.py defines."""
    script = SUBMIT.read_text(encoding="utf-8")
    valid = set(_array_items(script, "VALID_ARGS")) | set(
        _array_items(script, "HPC_ARGS"))
    python_opts = _transcription_option_strings()
    assert python_opts, "no add_argument calls found in transcription.py"

    missing = python_opts - valid
    assert not missing, f"transcription.py options the wrapper rejects: {sorted(missing)}"

    stale = valid - python_opts - HPC_ONLY - {"-h", "--help"}
    assert not stale, f"wrapper accepts options transcription.py lacks: {sorted(stale)}"


# ---------------------------------------------------------------------------
# Execution tests
# ---------------------------------------------------------------------------

def _find_bash() -> str | None:
    """A bash with mapfile -d and GNU find/sort, or None."""
    candidates = []
    if sys.platform == "win32":
        # Windows environment names are case-insensitive, and os.environ
        # stores them upper-cased there, so the capitalised forms find
        # %ProgramFiles% and %ProgramW6432%.
        for base in (os.environ.get("LOCALAPPDATA", ""),
                     os.environ.get("PROGRAMFILES", ""),
                     os.environ.get("PROGRAMW6432", "")):
            if base:
                candidates += [Path(base) / "Programs" / "Git" / "usr" / "bin" / "bash.exe",
                               Path(base) / "Git" / "usr" / "bin" / "bash.exe",
                               Path(base) / "Git" / "bin" / "bash.exe"]
    found = shutil.which("bash")
    # WSL's launcher in System32 has different path semantics; skip it.
    if found and "system32" not in found.lower():
        candidates.append(Path(found))
    for cand in candidates:
        if not Path(cand).is_file():
            continue
        try:
            probe = subprocess.run(
                [str(cand), "-c",
                 'export PATH="/usr/bin:/bin:$PATH"; '
                 'mapfile -d "" -t a < <(printf "x\\0y\\0" | sort -z); '
                 'find . -maxdepth 0 -iname . >/dev/null && echo "${#a[@]}"'],
                capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if probe.returncode == 0 and probe.stdout.strip() == "2":
            return str(cand)
    return None


BASH = _find_bash()
needs_bash = pytest.mark.skipif(BASH is None, reason="no POSIX bash with GNU tools")


def _posix(path: Path) -> str:
    return str(path).replace("\\", "/")


def _copy_lf(src: Path, dest: Path) -> None:
    """Copy a script with LF endings (a Windows checkout has CRLF)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(src.read_bytes().replace(b"\r\n", b"\n"))


def _write_stub(path: Path, body: str) -> None:
    path.write_bytes(("#!/bin/bash\n" + body).encode())
    path.chmod(0o755)


def _run(script: Path, args: list[str], stub_dir: Path, env_extra: dict,
         cwd: Path, timeout: int = 300) -> subprocess.CompletedProcess:
    """Run *script* with bash, the stub directory first on PATH.

    The timeout only stops a hung script. The slowest job script takes
    about 25 s alone, but six went past an earlier 60 s on a loaded
    machine during a full run (10 October 2026), so the limit is generous.
    """
    env = dict(os.environ)
    env.update(env_extra)
    env["STUB_DIR_NATIVE"] = _posix(stub_dir)
    quoted = " ".join("'" + a.replace("'", "'\\''") + "'" for a in args)
    command = (
        'STUB="$(cd "$STUB_DIR_NATIVE" && pwd)"; '
        'export PATH="$STUB:/usr/bin:/bin:$PATH"; '
        f"exec bash '{_posix(script)}' {quoted}"
    )
    return subprocess.run([BASH, "-c", command], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace")


def _read_nul_args(path: Path) -> list[str]:
    raw = path.read_bytes().decode("utf-8")
    return raw.split("\0")[:-1] if raw else []


@pytest.fixture()
def fake_repo(tmp_path: Path) -> dict:
    """A repository copy holding the two scripts, plus stub commands."""
    repo = tmp_path / "repo"
    _copy_lf(SUBMIT, repo / "hpc" / "submit_transcription.sh")
    _copy_lf(WORKER, repo / "hpc" / "batch_transcription.sh")
    # The worker sources the shared job helper (hpc/common/arc_common.sh).
    _copy_lf(REPO / "hpc" / "common" / "arc_common.sh",
             repo / "hpc" / "common" / "arc_common.sh")
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    calls = tmp_path / "calls"
    calls.mkdir()
    # sbatch: record its arguments NUL-separated, one file per call, and
    # answer as ARC does for a job with --clusters=htc.
    _write_stub(stubs / "sbatch",
                f'n=$(ls "{_posix(calls)}" | wc -l)\n'
                f'printf "%s\\0" "$@" > "{_posix(calls)}/sbatch_$n"\n'
                'echo "8781999;htc"\n')
    return {"repo": repo, "stubs": stubs, "calls": calls, "tmp": tmp_path}


@needs_bash
def test_help_returns_at_once(fake_repo: dict) -> None:
    """--help prints usage and exits 0 instead of looping on `shift 2`."""
    result = _run(fake_repo["repo"] / "hpc" / "submit_transcription.sh",
                  ["--help"], fake_repo["stubs"], {}, fake_repo["tmp"], timeout=20)
    assert result.returncode == 0, result.stderr
    assert "Usage:" in result.stdout
    assert not list(fake_repo["calls"].iterdir()), "--help must not submit"


@needs_bash
def test_single_file_values_survive_and_submit_once(fake_repo: dict) -> None:
    """Values reach sbatch as single, unquoted arguments; one submission."""
    audio = fake_repo["tmp"] / "in dir" / "a.wav"
    audio.parent.mkdir()
    audio.write_bytes(b"RIFF")
    result = _run(
        fake_repo["repo"] / "hpc" / "submit_transcription.sh",
        ["--single-file", _posix(audio), "--output-name", "interview_2024",
         "--exclude-names-from-masking", "Anna, Bob",
         "--speaker-attribution", "--num-speakers", "2"],
        fake_repo["stubs"], {}, fake_repo["tmp"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "8781999" in result.stdout

    calls = sorted(fake_repo["calls"].iterdir())
    assert len(calls) == 1, "a successful '<id>;htc' reply must not trigger a resubmission"
    args = _read_nul_args(calls[0])
    assert "--array" not in " ".join(args)
    worker_at = args.index("hpc/batch_transcription.sh")
    forwarded = args[worker_at + 1:]
    assert forwarded[forwarded.index("--output-name") + 1] == "interview_2024"
    assert forwarded[forwarded.index("--exclude-names-from-masking") + 1] == "Anna, Bob"
    assert forwarded[forwarded.index("--num-speakers") + 1] == "2"
    single = forwarded[forwarded.index("--single-file") + 1]
    assert single.endswith("/in dir/a.wav")


@needs_bash
def test_unknown_option_rejected(fake_repo: dict) -> None:
    result = _run(fake_repo["repo"] / "hpc" / "submit_transcription.sh",
                  ["--no-such-flag"], fake_repo["stubs"], {}, fake_repo["tmp"])
    assert result.returncode == 1
    assert "Unknown argument: --no-such-flag" in result.stderr
    assert not list(fake_repo["calls"].iterdir())


@needs_bash
def test_batch_mode_freezes_a_case_insensitive_list(fake_repo: dict) -> None:
    """The array is sized from, and the worker is given, one frozen list."""
    audio_dir = fake_repo["tmp"] / "audio"
    audio_dir.mkdir()
    for name in ("b.wav", "A.Wav", "notes.txt", "c.M4A"):
        (audio_dir / name).write_bytes(b"x")
    result = _run(fake_repo["repo"] / "hpc" / "submit_transcription.sh",
                  ["--language", "english"], fake_repo["stubs"],
                  {"TRANSCRIPTION_AUDIO_DIR": _posix(audio_dir)}, fake_repo["tmp"])
    assert result.returncode == 0, result.stdout + result.stderr

    calls = sorted(fake_repo["calls"].iterdir())
    assert len(calls) == 1
    args = _read_nul_args(calls[0])
    assert "--array=1-3" in args
    forwarded = args[args.index("hpc/batch_transcription.sh") + 1:]
    list_file = forwarded[forwarded.index("--file-list") + 1]
    assert forwarded[-2:] == ["--language", "english"]

    # The list is written with a POSIX path; map it back for Python.
    listed = [p for p in (fake_repo["repo"] / "logs").iterdir()
              if p.name.startswith("filelist_")]
    assert len(listed) == 1 and list_file.endswith(listed[0].name)
    entries = _read_nul_args(listed[0])
    assert [Path(e).name for e in entries] == ["A.Wav", "b.wav", "c.M4A"]

    # The list names every recording, so it must stay out of commits and be
    # readable by its owner only (SHELL-R1).
    git = shutil.which("git")
    if git:
        ignored = subprocess.run(
            [git, "check-ignore", "-q", "--no-index", f"logs/{listed[0].name}"],
            cwd=REPO, capture_output=True)
        assert ignored.returncode == 0, "the frozen list is not git-ignored"
    if sys.platform != "win32":
        assert listed[0].stat().st_mode & 0o077 == 0


@needs_bash
def test_output_name_without_single_file_rejected(fake_repo: dict) -> None:
    audio_dir = fake_repo["tmp"] / "audio"
    audio_dir.mkdir()
    (audio_dir / "a.wav").write_bytes(b"x")
    result = _run(fake_repo["repo"] / "hpc" / "submit_transcription.sh",
                  ["--output-name", "x"], fake_repo["stubs"],
                  {"TRANSCRIPTION_AUDIO_DIR": _posix(audio_dir)}, fake_repo["tmp"])
    assert result.returncode == 1
    assert not list(fake_repo["calls"].iterdir())


@needs_bash
def test_output_name_equals_form_is_checked_too(fake_repo: dict) -> None:
    """--output-name=x must meet the same batch-mode check (SHELL-R3)."""
    audio_dir = fake_repo["tmp"] / "audio"
    audio_dir.mkdir()
    for name in ("a.wav", "b.wav"):
        (audio_dir / name).write_bytes(b"x")
    result = _run(fake_repo["repo"] / "hpc" / "submit_transcription.sh",
                  ["--output-name=interviews", "--mask-personal-names"],
                  fake_repo["stubs"],
                  {"TRANSCRIPTION_AUDIO_DIR": _posix(audio_dir)}, fake_repo["tmp"])
    assert result.returncode == 1
    assert "--output-name applies to one file" in result.stderr
    assert not list(fake_repo["calls"].iterdir())


@needs_bash
def test_hpc_options_in_equals_form_reach_sbatch(fake_repo: dict) -> None:
    """--memory=64G and --time-limit=... set the allocation (SHELL-R3)."""
    audio = fake_repo["tmp"] / "a.wav"
    audio.write_bytes(b"RIFF")
    result = _run(fake_repo["repo"] / "hpc" / "submit_transcription.sh",
                  [f"--single-file={_posix(audio)}", "--output-name=interview_2024",
                   "--memory=64G", "--time-limit=04:00:00", "--timestamps"],
                  fake_repo["stubs"], {}, fake_repo["tmp"])
    assert result.returncode == 0, result.stdout + result.stderr
    args = _read_nul_args(sorted(fake_repo["calls"].iterdir())[0])
    assert "--mem=64G" in args and "--time=04:00:00" in args
    assert "--array" not in " ".join(args)
    forwarded = args[args.index("hpc/batch_transcription.sh") + 1:]
    assert not any(a.startswith(("--memory", "--time-limit")) for a in forwarded)
    assert forwarded[forwarded.index("--output-name") + 1] == "interview_2024"
    assert forwarded[forwarded.index("--single-file") + 1].endswith("/a.wav")


@needs_bash
def test_equals_form_without_a_value_is_rejected(fake_repo: dict) -> None:
    result = _run(fake_repo["repo"] / "hpc" / "submit_transcription.sh",
                  ["--single-file="], fake_repo["stubs"], {}, fake_repo["tmp"])
    assert result.returncode == 1
    assert "needs a value" in result.stderr
    assert not list(fake_repo["calls"].iterdir())


def _worker_setup(fake_repo: dict, exit_code: int = 0) -> tuple[Path, Path]:
    """Prepare the fake repository and stubs for running the worker.

    The python stub records the arguments of the transcription call and
    exits with *exit_code*. The worker's preflight (``python -m
    preflight``) is answered separately, with ``$STUB_RC_preflight``
    (default 0), and is not recorded, so *record* holds the transcription
    call alone.
    """
    repo = fake_repo["repo"]
    (repo / "transcription.py").write_text("# stub\n")
    (repo / "activate_project_env_arc.sh").write_bytes(b"# no-op activation\n")
    record = fake_repo["tmp"] / "python_args"
    _write_stub(fake_repo["stubs"] / "module", "exit 0\n")
    _write_stub(fake_repo["stubs"] / "python",
                'if [[ "$1" == "--version" ]]; then echo "Python 3.12"; exit 0; fi\n'
                'if [[ "${1:-} ${2:-}" == "-m preflight" ]]; then exit "${STUB_RC_preflight:-0}"; fi\n'
                f'printf "%s\\0" "$@" > "{_posix(record)}"\n'
                f"exit {exit_code}\n")
    return repo, record


@needs_bash
def test_worker_takes_its_entry_from_the_frozen_list(fake_repo: dict) -> None:
    repo, record = _worker_setup(fake_repo)
    first = fake_repo["tmp"] / "one.wav"
    second = fake_repo["tmp"] / "two words.wav"
    for f in (first, second):
        f.write_bytes(b"x")
    list_file = fake_repo["tmp"] / "list.txt"
    list_file.write_bytes(f"{_posix(first)}\0{_posix(second)}\0".encode())

    result = _run(repo / "hpc" / "batch_transcription.sh",
                  ["--file-list", _posix(list_file), "--output-name", "interview_2024",
                   "--exclude-names-from-masking", "Anna, Bob"],
                  fake_repo["stubs"],
                  {"SLURM_SUBMIT_DIR": _posix(repo), "SLURM_ARRAY_TASK_ID": "2",
                   "SLURM_ARRAY_TASK_COUNT": "2", "DATA": _posix(fake_repo["tmp"])},
                  fake_repo["tmp"])
    assert result.returncode == 0, result.stdout + result.stderr
    args = _read_nul_args(record)
    assert args[0] == "-u" and args[1] == "transcription.py"
    assert args[2].endswith("two words.wav")
    assert args[args.index("--output-name") + 1] == "interview_2024"
    assert args[args.index("--exclude-names-from-masking") + 1] == "Anna, Bob"


@needs_bash
def test_worker_rejects_a_list_that_does_not_match_the_array(fake_repo: dict) -> None:
    repo, record = _worker_setup(fake_repo)
    only = fake_repo["tmp"] / "one.wav"
    only.write_bytes(b"x")
    list_file = fake_repo["tmp"] / "list.txt"
    list_file.write_bytes(f"{_posix(only)}\0".encode())
    result = _run(repo / "hpc" / "batch_transcription.sh",
                  ["--file-list", _posix(list_file)], fake_repo["stubs"],
                  {"SLURM_SUBMIT_DIR": _posix(repo), "SLURM_ARRAY_TASK_ID": "1",
                   "SLURM_ARRAY_TASK_COUNT": "3", "SLURM_ARRAY_TASK_MAX": "3",
                   "DATA": _posix(fake_repo["tmp"])},
                  fake_repo["tmp"])
    assert result.returncode == 1
    assert not record.exists(), "no transcription may start on a mismatched list"


@needs_bash
def test_worker_retries_a_subset_of_the_frozen_list(fake_repo: dict) -> None:
    """sbatch --array=4 against a five-entry list runs entry 4 (SHELL-R2)."""
    repo, record = _worker_setup(fake_repo)
    files = [fake_repo["tmp"] / f"f{i}.wav" for i in range(1, 6)]
    for f in files:
        f.write_bytes(b"x")
    list_file = fake_repo["tmp"] / "list.txt"
    list_file.write_bytes("".join(f"{_posix(f)}\0" for f in files).encode())
    result = _run(repo / "hpc" / "batch_transcription.sh",
                  ["--file-list", _posix(list_file)], fake_repo["stubs"],
                  {"SLURM_SUBMIT_DIR": _posix(repo), "SLURM_ARRAY_TASK_ID": "4",
                   "SLURM_ARRAY_TASK_COUNT": "1", "SLURM_ARRAY_TASK_MAX": "4",
                   "DATA": _posix(fake_repo["tmp"])},
                  fake_repo["tmp"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert _read_nul_args(record)[2].endswith("/f4.wav")


@needs_bash
def test_worker_splits_equals_form_options(fake_repo: dict) -> None:
    repo, record = _worker_setup(fake_repo)
    audio = fake_repo["tmp"] / "a.wav"
    audio.write_bytes(b"x")
    result = _run(repo / "hpc" / "batch_transcription.sh",
                  [f"--single-file={_posix(audio)}", "--output-name=interview_2024"],
                  fake_repo["stubs"],
                  {"SLURM_SUBMIT_DIR": _posix(repo), "DATA": _posix(fake_repo["tmp"])},
                  fake_repo["tmp"])
    assert result.returncode == 0, result.stdout + result.stderr
    args = _read_nul_args(record)
    assert args[2].endswith("/a.wav")
    assert args[args.index("--output-name") + 1] == "interview_2024"
    assert not any(a.startswith("--single-file") for a in args)


@needs_bash
def test_worker_propagates_the_python_exit_code(fake_repo: dict) -> None:
    repo, _ = _worker_setup(fake_repo, exit_code=3)
    audio = fake_repo["tmp"] / "a.wav"
    audio.write_bytes(b"x")
    result = _run(repo / "hpc" / "batch_transcription.sh",
                  ["--single-file", _posix(audio)], fake_repo["stubs"],
                  {"SLURM_SUBMIT_DIR": _posix(repo), "DATA": _posix(fake_repo["tmp"])},
                  fake_repo["tmp"])
    assert result.returncode == 3
    assert "FAILURE" in result.stdout


@needs_bash
def test_worker_stops_before_transcribing_when_preflight_fails(fake_repo: dict) -> None:
    """The CPU preflight gates the transcription (DOCS-03): exit 2, no run."""
    repo, record = _worker_setup(fake_repo)
    audio = fake_repo["tmp"] / "a.wav"
    audio.write_bytes(b"x")
    result = _run(repo / "hpc" / "batch_transcription.sh",
                  ["--single-file", _posix(audio)], fake_repo["stubs"],
                  {"SLURM_SUBMIT_DIR": _posix(repo), "DATA": _posix(fake_repo["tmp"]),
                   "STUB_RC_preflight": "1"},
                  fake_repo["tmp"])
    assert result.returncode == 2, result.stdout + result.stderr
    assert not record.exists(), "transcription.py must not start after a failed preflight"
    assert "Preflight failed" in result.stderr
