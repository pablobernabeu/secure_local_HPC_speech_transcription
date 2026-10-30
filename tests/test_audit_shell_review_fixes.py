"""Regression tests for the review of the SHELL audit fixes (SHELL-R*).

The scripts run on Oxford ARC, so they are exercised here under bash with
stub ``python``, ``module`` and ``sbatch`` executables, in temporary git
repositories and directories. Needs a POSIX bash with GNU tools (Git Bash on
Windows) and, for the environment-record tests, git; skipped otherwise.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from test_audit_shell_job_exit_status import _PYTHON_STUB
from test_audit_shell_transcription_wrapper import (
    REPO, _copy_lf, _posix, _run, _write_stub, needs_bash,
)

pytestmark = needs_bash

GIT = shutil.which("git")
needs_git = pytest.mark.skipif(GIT is None, reason="git not on PATH")


@pytest.fixture()
def stubs(tmp_path: Path) -> dict:
    stub_dir = tmp_path / "stubs"
    stub_dir.mkdir()
    _write_stub(stub_dir / "module", "exit 0\n")
    _write_stub(stub_dir / "python", _PYTHON_STUB)
    _write_stub(stub_dir / "python3", _PYTHON_STUB)
    log = tmp_path / "python_calls.log"
    return {"dir": stub_dir, "log": log,
            "env": {"STUB_LOG": _posix(log), "HF_TOKEN": "x"}}


# ---------------------------------------------------------------------------
# SHELL-R4 / SHELL-R5: arc_record_env's git probe
# ---------------------------------------------------------------------------

def _git(repo: Path, *args: str) -> None:
    subprocess.run([GIT, "-C", str(repo), *args], check=True,
                   capture_output=True, text=True)


def _repo_with_history(tmp_path: Path) -> Path:
    repo = tmp_path / "clone"
    (repo / "output" / "case_study").mkdir(parents=True)
    (repo / "manuscript").mkdir()
    (repo / "code.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "output" / "case_study" / "summary.json").write_text("{}\n", encoding="utf-8")
    (repo / "manuscript" / "paper.qmd").write_text("text\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.org")
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "core.autocrlf", "false")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _record_env(tmp_path: Path, stubs: dict, workdir: Path) -> str:
    common = tmp_path / "arc_common.sh"
    _copy_lf(REPO / "hpc" / "common" / "arc_common.sh", common)
    driver = tmp_path / "driver.sh"
    driver.write_bytes(b'source "$1"\ncd "$2"\narc_record_env "$3" "PARAM=1"\n')
    dest = tmp_path / "results"
    result = _run(driver, [_posix(common), _posix(workdir), _posix(dest)],
                  stubs["dir"], stubs["env"], tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    records = list((dest / "environment").glob("*.txt"))
    assert len(records) == 1
    return records[0].read_text(encoding="utf-8", errors="replace")


@needs_git
def test_record_env_leaves_the_git_index_alone(tmp_path: Path, stubs: dict) -> None:
    repo = _repo_with_history(tmp_path)
    # Stale stat data with unchanged content: a plain `git status` would
    # refresh the index and rewrite .git/index under index.lock (SHELL-R5).
    past = time.time() - 300
    os.utime(repo / "code.py", (past, past))
    index = repo / ".git" / "index"
    before = index.stat().st_mtime_ns
    record = _record_env(tmp_path, stubs, repo)
    assert index.stat().st_mtime_ns == before
    assert "git_modified_tracked_files: 0" in record


@needs_git
def test_record_env_counts_code_not_tracked_results(tmp_path: Path, stubs: dict) -> None:
    repo = _repo_with_history(tmp_path)
    (repo / "output" / "case_study" / "summary.json").write_text('{"a": 1}\n',
                                                                encoding="utf-8")
    (repo / "manuscript" / "paper.qmd").write_text("edited\n", encoding="utf-8")
    record = _record_env(tmp_path, stubs, repo)
    # A re-run rewriting a tracked result is not modified code (SHELL-R4).
    assert "git_modified_tracked_files: 0" in record

    (repo / "code.py").write_text("x = 2\n", encoding="utf-8")
    record = _record_env(tmp_path, stubs, repo)
    assert "git_modified_tracked_files: 1" in record
    assert " M code.py" in record
    assert "summary.json" not in record


def test_record_env_outside_a_repository_says_unknown(tmp_path: Path, stubs: dict) -> None:
    outside = tmp_path / "not_a_repo"
    outside.mkdir()
    env_ceiling = dict(stubs["env"], GIT_CEILING_DIRECTORIES=_posix(tmp_path))
    record = _record_env(tmp_path, dict(stubs, env=env_ceiling), outside)
    assert "git_modified_tracked_files: unknown" in record


# ---------------------------------------------------------------------------
# SHELL-R6 / SHELL-R7: reproduction recipes never write over the originals
# ---------------------------------------------------------------------------

def _sourced(tmp_path: Path, env_file: Path, names: list[str]) -> dict[str, str]:
    """The values *env_file* sets, sourced as its recipe does, with DATA=/d."""
    copy = tmp_path / env_file.name
    _copy_lf(env_file, copy)
    driver = tmp_path / "print_env.sh"
    driver.write_bytes(("set -a; . \"$1\"; set +a\n" + "".join(
        f'printf "{n}=%s\\n" "${{{n}:-}}"\n' for n in names)).encode())
    result = _run(driver, [_posix(copy)], tmp_path, {"DATA": "/d"}, tmp_path)
    assert result.returncode == 0, result.stderr
    return dict(line.split("=", 1) for line in result.stdout.splitlines())


# The variable each job script takes its output directory from, where it is
# not REPORT_DIR: the script derives REPORT_DIR from it.
_OUTPUT_DIR_VARIABLES = {"submit_sweep.sh": "SWEEP_OUTPUT_DIR",
                         "submit_benchmark_wer_multilingual.sh": "WER_ML_OUTPUT_DIR",
                         "submit_case_study.sh": "CASE_REPORT_DIR"}


def test_every_recipe_writes_to_its_own_fresh_directory(tmp_path: Path) -> None:
    fresh = "/d/speech_transcription_env/output/evaluation/repro"
    names = ["REPORT_DIR", *_OUTPUT_DIR_VARIABLES.values()]
    seen = {}
    for env_file in sorted((REPO / "hpc" / "runs").glob("*.env")):
        values = _sourced(tmp_path, env_file, names)
        report_dir = next((values[n] for n in names if values[n]), "")
        assert report_dir.startswith(fresh), f"{env_file.name}: {report_dir}"
        seen[env_file.name] = report_dir
    # determinism.env's job adds its own determinism/ subdirectory.
    assert len(set(seen.values())) == len(seen)
    # Each of those scripts reads its variable, so a recipe that sets it
    # really does move the output.
    for script, variable in _OUTPUT_DIR_VARIABLES.items():
        text = (REPO / "hpc" / script).read_text(encoding="utf-8")
        assert f'REPORT_DIR="${{{variable}:-' in text, script


def test_no_recipe_reproduces_into_the_directory_its_original_wrote(
        tmp_path: Path) -> None:
    """A record notes where its run wrote as "# original: NAME=..." and
    sends a reproduction elsewhere. The determinism check's CPU arm and its
    V100 run, jobs 8978759 and 8978760, wrote into the directories their
    records named before they ran, so both records now name new ones."""
    checked = set()
    for env_file in sorted((REPO / "hpc" / "runs").glob("*.env")):
        originals = [line.removeprefix("# original: ")
                     for line in env_file.read_text(encoding="utf-8").splitlines()
                     if line.startswith("# original: ")]
        if not originals:
            continue
        names = [assignment.split("=", 1)[0] for assignment in originals]
        original = tmp_path / f"original_{env_file.name}"
        original.write_bytes("".join(f"{a}\n" for a in originals).encode())
        before = _sourced(tmp_path, original, names)
        now = _sourced(tmp_path, env_file, names)
        for name in names:
            assert before[name] and now[name] != before[name], (env_file.name, name)
        checked.add(env_file.name)
    assert {"determinism_cpu.env", "determinism_v100.env"} <= checked


def test_the_fleurs_recipe_scores_the_whole_split_whatever_the_shell_holds(
        tmp_path: Path, monkeypatch) -> None:
    """Job 8917984 ran every FLEURS split whole. The recipe sets the limit
    empty, which the script reads as no limit, so a WER_ML_LIMIT left in the
    calling shell does not shorten a reproduction."""
    monkeypatch.setenv("WER_ML_LIMIT", "5")
    values = _sourced(tmp_path, REPO / "hpc" / "runs" / "fleurs_ml.env",
                      ["WER_ML_LIMIT", "WER_ML_MODEL", "WER_ML_CONDITIONS"])
    assert values == {"WER_ML_LIMIT": "", "WER_ML_MODEL": "openai/whisper-large-v3",
                      "WER_ML_CONDITIONS": "raw,pipeline_full"}
    script = (REPO / "hpc" / "submit_benchmark_wer_multilingual.sh").read_text(
        encoding="utf-8")
    assert 'if [[ -n "${WER_ML_LIMIT:-}" ]]; then' in script


def _reproduce_commands(env_file: Path) -> str:
    """The commands of *env_file*'s "# Reproduce" paragraph, uncommented.

    The paragraph runs to the next empty comment line, and its commands are
    the lines indented under it, so prose between two groups of commands
    (sweep.env's "then ... aggregate") is skipped and both groups are kept.
    """
    lines = env_file.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("# Reproduce"))
    commands = []
    for line in lines[start + 1:]:
        if line.rstrip() == "#" or not line.startswith("#"):
            break
        if line.startswith("#   "):
            commands.append(line[4:])
    return "".join(f"{line}\n" for line in commands)


def test_the_fleurs_recipe_commands_submit_nothing_without_the_recipe(
        tmp_path: Path) -> None:
    """The recipe's header says to reproduce from a checkout of 6f9bf56,
    which predates the recipe. Bash goes on past a "." that cannot find its
    file, so a command without a guard would submit the script with its
    defaults, into the evaluation directory itself. Run as the header gives
    them, the commands submit nothing there, and once the recipe is copied
    in they submit one job per card type with its values."""
    recipe = REPO / "hpc" / "runs" / "fleurs_ml.env"
    stub_dir = tmp_path / "stubs"
    stub_dir.mkdir()
    log = tmp_path / "sbatch.log"
    _write_stub(stub_dir / "sbatch",
                'printf "%s|%s|%s\\n" "$*" "${WER_ML_OUTPUT_DIR-unset}" '
                '"${WER_ML_LIMIT-unset}" >> "$SBATCH_LOG"\n')
    commands = tmp_path / "reproduce.sh"
    commands.write_bytes(_reproduce_commands(recipe).encode())
    env = {"DATA": "/d", "SBATCH_LOG": _posix(log), "WER_ML_LIMIT": "5"}
    checkout = tmp_path / "checkout_of_6f9bf56"
    (checkout / "hpc" / "runs").mkdir(parents=True)

    result = _run(commands, [], stub_dir, env, checkout)
    assert result.returncode != 0
    assert "fleurs_ml.env" in result.stderr
    assert not log.exists(), log.read_text()

    _copy_lf(recipe, checkout / "hpc" / "runs" / "fleurs_ml.env")
    result = _run(commands, [], stub_dir, env, checkout)
    assert result.returncode == 0, result.stderr
    out = "/d/speech_transcription_env/output/evaluation/repro/fleurs_ml"
    script = "hpc/submit_benchmark_wer_multilingual.sh"
    assert log.read_text().splitlines() == [
        f"--account=educ-lift --array=0,3 --gres=gpu:h100:1 --constraint=nvlink {script}|{out}|",
        f"--account=educ-lift --array=1 --gres=gpu:a100:1 {script}|{out}|",
        f"--account=educ-lift --array=2,4,5 --gres=gpu:l40s:1 {script}|{out}|",
    ]


# The variables a reproduction's output directory can travel in, and the one
# each submitted script reads it from (REPORT_DIR for any other script).
# aggregate_sweep.sh reads the sweep's directory as SWEEP_DIR.
_SUBMITTED_OUTPUT_VARIABLES = {**_OUTPUT_DIR_VARIABLES, "aggregate_sweep.sh": "SWEEP_DIR"}
_LOGGED_VARIABLES = ("REPORT_DIR", *_OUTPUT_DIR_VARIABLES.values(), "SWEEP_DIR")


@pytest.mark.parametrize(
    "record", sorted(p.name for p in (REPO / "hpc" / "runs").glob("*.env")))
def test_every_recipe_submits_only_with_its_record(tmp_path: Path, record: str) -> None:
    """Bash goes on past a "." that cannot find its file, so a command
    without the "|| exit 1" guard submits the script with its own defaults,
    which for most scripts write into the evaluation directory itself
    (SHELL-08). Run as the record's header gives them, from a checkout
    without the record, the commands submit nothing. With the record, each
    sbatch in them runs once, and the script it submits finds the record's
    output directory in the variable it reads, sweep.env's aggregation
    included."""
    env_file = REPO / "hpc" / "runs" / record
    commands = tmp_path / "reproduce.sh"
    commands.write_bytes(_reproduce_commands(env_file).encode())
    n_submissions = commands.read_text().count("sbatch ")
    assert n_submissions, record
    values = _sourced(tmp_path, env_file, list(_OUTPUT_DIR_VARIABLES.values()) + ["REPORT_DIR"])
    out = next(v for v in values.values() if v)

    stub_dir = tmp_path / "stubs"
    stub_dir.mkdir()
    log = tmp_path / "sbatch.log"
    _write_stub(stub_dir / "sbatch",
                'printf "%s' + "".join(f"|{n}=%s" for n in _LOGGED_VARIABLES)
                + '\\n" "$*" ' + " ".join(f'"${{{n}-}}"' for n in _LOGGED_VARIABLES)
                + ' >> "$SBATCH_LOG"\n')
    # Nothing the calling shell holds can stand in for the record.
    env = {"DATA": "/d", "SBATCH_LOG": _posix(log), **dict.fromkeys(_LOGGED_VARIABLES, "")}
    checkout = tmp_path / "checkout"
    (checkout / "hpc" / "runs").mkdir(parents=True)

    result = _run(commands, [], stub_dir, env, checkout)
    assert result.returncode != 0
    assert record in result.stderr
    assert not log.exists(), log.read_text()

    _copy_lf(env_file, checkout / "hpc" / "runs" / record)
    result = _run(commands, [], stub_dir, env, checkout)
    assert result.returncode == 0, result.stderr
    calls = log.read_text().splitlines()
    assert len(calls) == n_submissions, calls
    for call in calls:
        args, *fields = call.split("|")
        given = dict(field.split("=", 1) for field in fields)
        script = Path(args.split()[-1]).name
        assert given[_SUBMITTED_OUTPUT_VARIABLES.get(script, "REPORT_DIR")] == out, call


def test_every_documented_recipe_command_is_guarded() -> None:
    """The records, the job scripts' headers and the READMEs show the same
    command; each copy sources its record with the guard."""
    sourcing = re.compile(r"\. hpc/runs/[\w.]+\.env\b(?! \|\| exit 1)")
    texts = [*(REPO / "hpc" / "runs").glob("*.env"), *(REPO / "hpc").glob("*.sh"),
             REPO / "hpc" / "README.md", REPO / "README.md"]
    unguarded = [f"{path.relative_to(REPO).as_posix()}: {line.strip()}"
                 for path in texts
                 for line in path.read_text(encoding="utf-8").splitlines()
                 if "set -a" in line and sourcing.search(line)]
    assert unguarded == []


@needs_git
def test_every_recipe_is_checked_out_with_lf_endings() -> None:
    """A recipe checked out with CRLF (Windows, core.autocrlf) and copied to
    ARC sets every value with a trailing carriage return there: ANON_PRESET
    becomes $'multi-meeting\\r', which submit_anonymisation.sh rejects."""
    recipes = sorted(p.relative_to(REPO).as_posix()
                     for p in (REPO / "hpc" / "runs").glob("*.env"))
    result = subprocess.run([GIT, "-C", str(REPO), "check-attr", "eol", "--", *recipes],
                            capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip(f"not a git checkout: {result.stderr.strip()}")
    assert result.stdout.splitlines() == [f"{r}: eol: lf" for r in recipes]


def test_der_sweep2_recipe_writes_the_committed_file_names(tmp_path: Path) -> None:
    """The August job predated --output-prefix and its files were renamed by
    hand; the recipe sets it, as the re-run, job 8976362, did (SHELL-R7)."""
    values = _sourced(tmp_path, REPO / "hpc" / "runs" / "der_sweep2.env",
                      ["OUTPUT_PREFIX"])
    assert values["OUTPUT_PREFIX"] == "der_sweep2"
    assert (REPO / "output" / "evaluation" / "der_sweep2_selection.json").is_file()
    header = (REPO / "hpc" / "submit_der_sweep.sh").read_text(encoding="utf-8")
    assert "which is how the committed der_sweep2_* files arose" not in header


# Every variable hpc/submit_benchmark_der.sh turns into an argument.
_DER_KNOBS = ("LIMIT_MEETINGS", "MAX_MINUTES", "UTT_PER_MEETING",
              "CLUSTERING_THRESHOLD", "MIN_CLUSTER_SIZE", "MIN_DURATION_OFF",
              "SEGMENTATION_MODEL", "ORACLE_NUM_SPEAKERS")
# record: (its summary under output/evaluation/, the knobs its job set, as
# the job's environment record lists them under EXTRA_ARGS)
_DER_RECORDS = {
    "der_default.env": ("der_summary.json", {}),
    "der_oracle.env": ("der_oracle/der_summary.json", {"ORACLE_NUM_SPEAKERS": "1"}),
    "der_tuned.env": ("der_tuned/der_summary.json",
                      {"CLUSTERING_THRESHOLD": "0.70", "MIN_DURATION_OFF": "0.0"}),
    "der_concat.env": ("der_concat/der_summary.json", {"UTT_PER_MEETING": "25"}),
}


@pytest.mark.parametrize("record", sorted(_DER_RECORDS))
def test_each_der_record_sets_what_its_committed_run_ran_with(
        tmp_path: Path, monkeypatch, record: str) -> None:
    """sbatch passes the submitting shell's variables through, so each record
    sets every argument variable, and a stray value cannot change the run.
    What it sets is what the committed summary says the run did."""
    names = ["SPLIT", "MIX_MODE", "CACHE_DIR", *_DER_KNOBS]
    for name in names:
        monkeypatch.setenv(name, "stray")
    values = _sourced(tmp_path, REPO / "hpc" / "runs" / record, names)
    summary_path, knobs = _DER_RECORDS[record]
    summary = json.loads((REPO / "output" / "evaluation" / summary_path)
                         .read_text(encoding="utf-8"))
    assert {k: values[k] for k in _DER_KNOBS} == {k: knobs.get(k, "") for k in _DER_KNOBS}
    assert (values["SPLIT"], values["MIX_MODE"]) == (summary["split"], summary["mix_mode"])
    assert (values["ORACLE_NUM_SPEAKERS"] == "1") is summary["oracle_num_speakers"]
    tuned = summary["hyperparameters"]
    if values["CLUSTERING_THRESHOLD"]:
        assert float(values["CLUSTERING_THRESHOLD"]) == tuned["clustering"]["threshold"]
        assert float(values["MIN_DURATION_OFF"]) == tuned["segmentation"]["min_duration_off"]
    # The timeline runs read the shared cache; the concatenation run built
    # its corpus in a directory of its own, and so does a reproduction.
    if summary["mix_mode"] == "timeline":
        assert values["CACHE_DIR"] == "/d/ami_cache"
    else:
        assert values["CACHE_DIR"].startswith(
            "/d/speech_transcription_env/output/evaluation/repro/")


@pytest.mark.parametrize("prefix", ["der_sweep", "der_sweep2"])
def test_each_der_sweep_record_sets_the_grid_its_selection_records(
        tmp_path: Path, monkeypatch, prefix: str) -> None:
    """The selection file keeps the argv of the job that wrote it."""
    names = ["SPLIT", "CACHE_DIR", "THRESHOLDS", "MIN_CLUSTER_SIZES",
             "MIN_DURATIONS_OFF", "OUTPUT_PREFIX"]
    for name in names:
        monkeypatch.setenv(name, "stray")
    values = _sourced(tmp_path, REPO / "hpc" / "runs" / f"{prefix}.env", names)
    argv = json.loads((REPO / "output" / "evaluation" / f"{prefix}_selection.json")
                      .read_text(encoding="utf-8"))["argv"]

    def given(flag: str) -> list[str]:
        start = argv.index(flag) + 1
        end = next((i for i in range(start, len(argv)) if argv[i].startswith("--")),
                   len(argv))
        return argv[start:end]

    assert given("--split") == [values["SPLIT"]] == ["validation"]
    assert given("--output-prefix") == [values["OUTPUT_PREFIX"]] == [prefix]
    assert given("--clustering-threshold") == values["THRESHOLDS"].split()
    assert given("--min-cluster-size") == values["MIN_CLUSTER_SIZES"].split()
    assert given("--min-duration-off") == values["MIN_DURATIONS_OFF"].split()
    assert given("--cache-dir")[0].endswith("/ami_cache")
    assert values["CACHE_DIR"] == "/d/ami_cache"


def _determinism(tmp_path: Path, stubs: dict, report_dir: Path, **extra: str):
    repo = tmp_path / "repo"
    (repo / "hpc" / "common").mkdir(parents=True, exist_ok=True)
    _copy_lf(REPO / "hpc" / "common" / "arc_common.sh",
             repo / "hpc" / "common" / "arc_common.sh")
    _copy_lf(REPO / "hpc" / "submit_determinism.sh", repo / "hpc" / "submit_determinism.sh")
    (repo / "activate_project_env_arc.sh").write_bytes(b"# no-op activation\n")
    env = dict(stubs["env"], SLURM_SUBMIT_DIR=_posix(repo), DATA=_posix(tmp_path),
               REPORT_DIR=_posix(report_dir), DET_SEEDS="0", DET_REPEATS="1", **extra)
    return _run(repo / "hpc" / "submit_determinism.sh", [], stubs["dir"], env, repo)


def _calls(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


def test_determinism_refuses_to_overwrite_a_run(tmp_path: Path, stubs: dict) -> None:
    report_dir = tmp_path / "evaluation"
    (report_dir / "determinism").mkdir(parents=True)
    (report_dir / "determinism" / "determinism_repeat.json").write_text("{}")
    result = _determinism(tmp_path, stubs, report_dir)
    assert result.returncode == 3
    assert not any("benchmark_wer" in c for c in _calls(stubs["log"]))
    assert (report_dir / "determinism" / "determinism_repeat.json").read_text() == "{}"

    result = _determinism(tmp_path, stubs, report_dir, OVERWRITE="1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert any("benchmark_wer" in c for c in _calls(stubs["log"]))


def test_determinism_runs_into_a_fresh_directory(tmp_path: Path, stubs: dict) -> None:
    result = _determinism(tmp_path, stubs, tmp_path / "fresh")
    assert result.returncode == 0, result.stdout + result.stderr
    assert any("evaluation.determinism" in c for c in _calls(stubs["log"]))
