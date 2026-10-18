"""Stage-1 ENV tests for the job scripts and their shared helper.

The job scripts run on Oxford ARC, so they are exercised here under bash with
stub ``module``, ``python`` and ``pip`` executables that log every call. The
checks are the behaviour the ENV fixes introduced:

* no job installs, upgrades or reinstalls a package (DEPS-03, SHELL-01,
  SHELL-06, TESTS-02, CORE-21);
* every job activates through hpc/common/arc_common.sh and gates on the
  preflight, GPU jobs with --gpu-required and the diarisation jobs with
  --diarisation-required as well, and a failed preflight stops the job
  before any work (SHELL-10, SHELL-05);
* the module versions are pinned;
* the sweep, aggregation, WER-scoring, determinism and test-suite scripts
  keep their outputs where they belong (SHELL-02, REV-02, XREF-01,
  SHELL-09, NEW-02, SHELL-08, TESTS-02);
* the retired WER scripts refuse to run.

Needs a POSIX bash with GNU tools (Git Bash on Windows); skipped otherwise.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from test_audit_shell_job_exit_status import _PYTHON_STUB  # noqa: I001
from test_audit_shell_transcription_wrapper import (
    REPO, _copy_lf, _posix, _run, _write_stub, needs_bash,
)

HPC = REPO / "hpc"
# The wrapper runs on the login node and only submits; it activates nothing.
_SUBMITTERS = {"submit_transcription.sh"}

GPU_SCRIPTS = {
    # script: (extra preflight flag, exit status on a failed preflight)
    "submit_anonymisation.sh": ("--diarisation-required", 2),
    "submit_sweep.sh": ("", 2),
    "submit_benchmark_der.sh": ("--diarisation-required", 2),
    "submit_der_sweep.sh": ("--diarisation-required", 2),
    "submit_benchmark_timestamps.sh": ("", 2),
    "submit_benchmark_wer_multilingual.sh": ("", 2),
    "submit_determinism.sh": ("", 2),
    "submit_disfluency.sh": ("", 2),
    "submit_finetune_pyannote.sh": ("--diarisation-required", 2),
    "submit_pilot_benchmark.sh": ("", 2),
    "submit_case_study.sh": ("--diarisation-required", 4),
}
CPU_SCRIPTS = ("aggregate_sweep.sh", "submit_ami_cache.sh", "evaluate_wer.sh",
               "run_tests.sh", "submit_determinism_cpu.sh")


def _live_scripts() -> list[Path]:
    return sorted(p for p in HPC.glob("*.sh") if p.name not in _SUBMITTERS)


def _code_lines(path: Path) -> str:
    """The script without its comment lines, so prose about pip is ignored."""
    return "\n".join(line for line in path.read_text(encoding="utf-8").splitlines()
                     if not line.lstrip().startswith("#"))


# ---------------------------------------------------------------------------
# Static checks: these need no bash.
# ---------------------------------------------------------------------------

_INSTALL = re.compile(r"\bpip3?\s+(install|uninstall)\b|-m\s+pip\s+(install|uninstall)\b"
                      r"|--force-reinstall")


def test_no_live_job_or_helper_installs_packages():
    files = [*_live_scripts(), HPC / "submit_transcription.sh",
             HPC / "common" / "arc_common.sh", REPO / "activate_project_env_arc.sh",
             REPO / "setup" / "docker-entrypoint.sh"]
    offenders = [f.name for f in files if _INSTALL.search(_code_lines(f))]
    assert not offenders, f"in-job package installs remain in {offenders}"


def test_every_job_script_is_classified():
    assert {p.name for p in _live_scripts()} == set(GPU_SCRIPTS) | set(CPU_SCRIPTS) \
        | {"batch_transcription.sh"}


@pytest.mark.parametrize("name", sorted(GPU_SCRIPTS))
def test_gpu_jobs_use_the_shared_gpu_gate(name):
    code = _code_lines(HPC / name)
    assert "#SBATCH --gres=gpu" in (HPC / name).read_text(encoding="utf-8")
    assert 'source "$REPO_DIR/hpc/common/arc_common.sh"' in code
    assert re.search(r'arc_activate "\$REPO_DIR" --cuda \|\| exit 1', code)
    flag, status = GPU_SCRIPTS[name]
    gate = re.search(r"arc_require_gpu(.*?)\|\| exit (\d)", code)
    assert gate, "no arc_require_gpu gate"
    assert gate.group(1).strip() == flag and int(gate.group(2)) == status
    assert "module load" not in code and "python -m preflight" not in code


@pytest.mark.parametrize("name", CPU_SCRIPTS + ("batch_transcription.sh",))
def test_cpu_jobs_use_the_shared_cpu_gate(name):
    text = (HPC / name).read_text(encoding="utf-8")
    code = _code_lines(HPC / name)
    assert "#SBATCH --gres=gpu" not in text
    assert 'source "$REPO_DIR/hpc/common/arc_common.sh"' in code
    assert "--cuda" not in code and "arc_require_gpu" not in code
    assert re.search(r"arc_preflight.*\|\| exit 2", code)


def test_legacy_scripts_live_apart_with_a_readme():
    legacy = HPC / "legacy"
    assert (legacy / "README.md").is_file()
    assert sorted(p.name for p in legacy.glob("*.sh")) == [
        "submit_benchmark_wer.sh", "submit_benchmark_wer_gpu.sh"]
    assert not (HPC / "submit_benchmark_wer.sh").exists()
    assert not (HPC / "submit_benchmark_wer_gpu.sh").exists()


# ---------------------------------------------------------------------------
# Behaviour under bash
# ---------------------------------------------------------------------------

@pytest.fixture()
def job(tmp_path: Path) -> dict:
    """A repository holding the helper, a logging activation and stubs."""
    repo = tmp_path / "repo"
    (repo / "hpc" / "common").mkdir(parents=True)
    _copy_lf(HPC / "common" / "arc_common.sh", repo / "hpc" / "common" / "arc_common.sh")
    log = tmp_path / "calls.log"
    (repo / "activate_project_env_arc.sh").write_bytes(
        b'printf "activate\\n" >> "$STUB_LOG"\n'
        b'export PROJECT_DIR="$DATA/speech_transcription_env"\n')
    (repo / "transcription.py").write_text("# stub\n")
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    _write_stub(stubs / "module", 'printf "module %s\\n" "$*" >> "$STUB_LOG"\n')
    _write_stub(stubs / "pip", 'printf "pip %s\\n" "$*" >> "$STUB_LOG"\n')
    _write_stub(stubs / "python", _PYTHON_STUB)
    _write_stub(stubs / "python3", _PYTHON_STUB)
    data = tmp_path / "data"
    data.mkdir()
    env = {"SLURM_SUBMIT_DIR": _posix(repo), "DATA": _posix(data),
           "STUB_LOG": _posix(log), "SLURM_JOB_ID": "42", "HF_TOKEN": "x"}
    return {"repo": repo, "stubs": stubs, "log": log, "data": data, "env": env,
            "tmp": tmp_path}


def _calls(job: dict) -> list[str]:
    return job["log"].read_text().splitlines() if job["log"].exists() else []


def _installs(calls: list[str]) -> list[str]:
    """Logged pip calls that change the environment. arc_record_env's
    read-only `python -m pip list` is allowed."""
    return [c for c in calls
            if re.match(r"(pip3?|-m pip) (install|uninstall|download)\b", c)]


def _submit(job: dict, name: str, args=(), source: Path | None = None, **env):
    script = job["repo"] / "hpc" / name
    _copy_lf(source or HPC / name, script)
    return _run(script, list(args), job["stubs"], dict(job["env"], **env), job["repo"])


def _gpu_env(job: dict, name: str) -> dict:
    """The minimum each GPU script needs to reach its preflight.

    A script not named here needs only the fixture's environment: the
    anonymisation job, for instance, builds its default REPORT_DIR from DATA
    and SLURM_JOB_ID, and creates it only after the gate.
    """
    extra = {"SLURM_ARRAY_TASK_ID": "0"}
    if name == "submit_benchmark_wer_multilingual.sh":
        extra["WER_ML_OUTPUT_DIR"] = _posix(job["tmp"] / "ml")
    if name == "submit_determinism.sh":
        extra["REPORT_DIR"] = _posix(job["tmp"] / "det")
    if name == "submit_case_study.sh":
        audio = job["tmp"] / "ep.wav"
        audio.write_bytes(b"RIFF")
        extra.update(CASE_AUDIO=_posix(audio), CASE_NAME="ep")
    return extra


@needs_bash
@pytest.mark.parametrize("name", sorted(GPU_SCRIPTS))
def test_gpu_job_stops_at_a_failed_preflight(job, name):
    flag, status = GPU_SCRIPTS[name]
    result = _submit(job, name, STUB_RC_preflight="1", **_gpu_env(job, name))
    assert result.returncode == status, result.stdout + result.stderr
    calls = _calls(job)
    preflight = [c for c in calls if c.startswith("-m preflight")]
    assert preflight == [f"-m preflight --gpu-required {flag}".strip()]
    # Nothing ran after the gate, and nothing was installed before it.
    assert not any(c.startswith(("-m evaluation", "transcription.py")) for c in calls)
    assert not _installs(calls)
    assert "module load Anaconda3/2025.06-1" in calls
    assert "module load CUDA/13.0.2" in calls
    # Modules first, then the environment, as before the refactor.
    assert calls.index("module purge") < calls.index("module load CUDA/13.0.2") \
        < calls.index("activate")


@needs_bash
@pytest.mark.parametrize("name", CPU_SCRIPTS)
def test_cpu_job_stops_at_a_failed_preflight(job, name):
    args = []
    if name == "evaluate_wer.sh":
        args = [_posix(job["tmp"]), _posix(job["tmp"])]
    result = _submit(job, name, args, STUB_RC_preflight="1")
    assert result.returncode == 2, result.stdout + result.stderr
    calls = _calls(job)
    preflight = [c for c in calls if c.startswith("-m preflight")]
    assert len(preflight) == 1 and "--gpu-required" not in preflight[0]
    assert not any(c.startswith(("-m evaluation", "-m pytest")) for c in calls)
    assert not any("CUDA" in c for c in calls if c.startswith("module"))
    assert not _installs(calls)


@needs_bash
def test_timestamps_job_runs_after_the_gate_without_installing(job):
    """The old script pip-installed transformers>=4.37 when the import
    failed and reinstalled torch when CUDA looked missing; now the preflight
    alone decides whether it runs."""
    result = _submit(job, "submit_benchmark_timestamps.sh",
                     REPORT_DIR=_posix(job["tmp"] / "ts"))
    assert result.returncode == 0, result.stdout + result.stderr
    calls = _calls(job)
    assert not _installs(calls)
    assert calls.index("-m preflight --gpu-required") < next(
        i for i, c in enumerate(calls) if c.startswith("-m evaluation.benchmark_timestamps"))


@needs_bash
def test_der_job_runs_after_the_gate_and_loads_the_token_file(job):
    (job["repo"] / "hf_token.txt").write_text(" hf_file \n")
    result = _submit(job, "submit_benchmark_der.sh",
                     REPORT_DIR=_posix(job["tmp"] / "der"))
    assert result.returncode == 0, result.stdout + result.stderr
    calls = _calls(job)
    assert calls.index("-m preflight --gpu-required --diarisation-required") < \
        next(i for i, c in enumerate(calls) if c.startswith("-m evaluation.benchmark_der"))
    assert "from" in result.stdout and "hf_file" not in result.stdout


# ---------------------------------------------------------------------------
# Script-specific behaviour
# ---------------------------------------------------------------------------

@needs_bash
def test_sweep_limit_needs_its_own_output_dir(job):
    result = _submit(job, "submit_sweep.sh", SLURM_ARRAY_TASK_ID="0", SWEEP_LIMIT="10")
    assert result.returncode == 3
    assert not any(c.startswith("-m evaluation.sweep") for c in _calls(job))

    job["log"].unlink()
    out = job["tmp"] / "preflight_sweep"
    result = _submit(job, "submit_sweep.sh", SLURM_ARRAY_TASK_ID="0",
                     SWEEP_LIMIT="10", SWEEP_OUTPUT_DIR=_posix(out))
    assert result.returncode == 0, result.stdout + result.stderr
    sweep = [c for c in _calls(job) if c.startswith("-m evaluation.sweep")]
    assert len(sweep) == 1 and f"--output-dir {_posix(out)}" in sweep[0]
    assert "--limit 10" in sweep[0]
    assert "--legacy-primary-paths" not in sweep[0]


@needs_bash
def test_aggregate_defaults_to_the_committed_sweep(job):
    # Its summaries record their commit, so no fallback label is passed.
    sweep_dir = (job["data"] / "speech_transcription_env" / "output" / "evaluation"
                 / "audit2026" / "sweep")
    sweep_dir.mkdir(parents=True)
    result = _submit(job, "aggregate_sweep.sh")
    assert result.returncode == 0, result.stdout + result.stderr
    agg = [c for c in _calls(job) if c.startswith("-m evaluation.sweep_aggregate")]
    assert len(agg) == 1
    assert f"--sweep-dir {_posix(sweep_dir)}" in agg[0]
    assert f"--out {_posix(sweep_dir)}/sweep_aggregate.csv" in agg[0]
    assert "--pipeline-version" not in agg[0]


@needs_bash
def test_aggregate_of_a_named_sweep_takes_versions_from_the_summaries(job):
    other = job["tmp"] / "new_sweep"
    other.mkdir()
    result = _submit(job, "aggregate_sweep.sh", SWEEP_DIR=_posix(other))
    assert result.returncode == 0, result.stdout + result.stderr
    agg = [c for c in _calls(job) if c.startswith("-m evaluation.sweep_aggregate")]
    assert f"--sweep-dir {_posix(other)}" in agg[0]
    assert "--pipeline-version" not in agg[0]

    job["log"].unlink()
    result = _submit(job, "aggregate_sweep.sh", SWEEP_DIR=_posix(other),
                     PIPELINE_VERSION="v9")
    assert "--pipeline-version v9" in [c for c in _calls(job)
                                       if "sweep_aggregate" in c][0]


@needs_bash
def test_aggregate_of_a_missing_directory_fails(job):
    result = _submit(job, "aggregate_sweep.sh", SWEEP_DIR=_posix(job["tmp"] / "none"))
    assert result.returncode == 1
    assert not any("sweep_aggregate" in c for c in _calls(job))


def _evaluate(job, *args, **env):
    refs = job["data"] / "speech_transcription_env" / "reference_transcripts"
    refs.mkdir(parents=True, exist_ok=True)
    return _submit(job, "evaluate_wer.sh", args, **env)


@needs_bash
def test_evaluate_wer_reads_the_worker_output_and_writes_its_own_names(job):
    transcripts = job["repo"] / "output" / "transcripts"
    transcripts.mkdir(parents=True)
    result = _evaluate(job)
    assert result.returncode == 4           # nothing to score yet (NEW-02)
    assert not any(c.startswith("-m evaluation.wer") for c in _calls(job))

    (transcripts / "interview_transcript.txt").write_text("hello")
    job["log"].unlink()
    result = _evaluate(job)
    assert result.returncode == 0, result.stdout + result.stderr
    wer = [c for c in _calls(job) if c.startswith("-m evaluation.wer")][0]
    inhouse = f"{_posix(job['data'])}/speech_transcription_env/output/evaluation/inhouse"
    assert f"--hypothesis {_posix(job['repo'])}/output/transcripts" in wer
    assert f"--report {inhouse}/wer_report_transcripts.csv" in wer
    assert f"--summary {inhouse}/wer_summary_transcripts.json" in wer
    assert "wer_summary.json" not in wer and "wer_report.csv" not in wer


@needs_bash
def test_evaluate_wer_refuses_to_overwrite_a_summary(job):
    hyp = job["tmp"] / "hyp"
    hyp.mkdir()
    (hyp / "a.txt").write_text("x")
    out = job["tmp"] / "out"
    out.mkdir()
    (out / "wer_summary_transcripts.json").write_text("{}")
    refs = job["tmp"] / "refs"
    refs.mkdir()
    result = _evaluate(job, _posix(hyp), _posix(refs), _posix(out))
    assert result.returncode == 3
    job["log"].unlink()
    result = _evaluate(job, _posix(hyp), _posix(refs), _posix(out), OVERWRITE="1")
    assert result.returncode == 0, result.stdout + result.stderr


@needs_bash
def test_determinism_repeats_only_the_first_seed(job):
    report = job["tmp"] / "det"
    result = _submit(job, "submit_determinism.sh", REPORT_DIR=_posix(report),
                     DET_SEEDS="0 1", DET_REPEATS="2")
    assert result.returncode == 0, result.stdout + result.stderr
    decodes = [re.search(r"--dump-hypotheses \S+/(seed\d+_run\d+)\.csv", c).group(1)
               for c in _calls(job) if c.startswith("-m evaluation.benchmark_wer")]
    assert decodes == ["seed0_run1", "seed0_run2", "seed1_run1"]
    compared = [c for c in _calls(job) if c.startswith("-m evaluation.determinism")]
    assert "seed0_run1.csv" in compared[0] and "seed0_run2.csv" in compared[0]
    assert "seed0_run1.csv" in compared[1] and "seed1_run1.csv" in compared[1]


def _evaluation_calls(job: dict, out: Path) -> list[str]:
    """The job's decode and comparison commands, with its output directory
    written as <OUT> so two jobs' commands can be compared."""
    return [c.replace(_posix(out), "<OUT>") for c in _calls(job)
            if c.startswith("-m evaluation.")]


@needs_bash
def test_determinism_cpu_runs_the_gpu_jobs_decodes_on_the_processor(job):
    """The CPU arm must differ from the GPU job in device and precision only,
    or a disagreement between the two could not be put down to them."""
    gpu_report = job["tmp"] / "gpu"
    result = _submit(job, "submit_determinism.sh", REPORT_DIR=_posix(gpu_report),
                     DET_SEEDS="0 1", DET_REPEATS="2")
    assert result.returncode == 0, result.stdout + result.stderr
    gpu = _evaluation_calls(job, gpu_report / "determinism")
    job["log"].unlink()

    # The CPU arm's defaults are the GPU runs' recorded values.
    cpu_report = job["tmp"] / "cpu"
    result = _submit(job, "submit_determinism_cpu.sh", REPORT_DIR=_posix(cpu_report))
    assert result.returncode == 0, result.stdout + result.stderr
    cpu = _evaluation_calls(job, cpu_report / "determinism_cpu")

    decodes = [c for c in cpu if c.startswith("-m evaluation.benchmark_wer")]
    assert len(decodes) == 3
    assert all(" --device cpu --dtype float32 " in c for c in decodes)
    assert [c.replace(" --device cpu --dtype float32", "") for c in cpu] == gpu
    assert not any("--device" in c or "--dtype" in c for c in gpu)


@needs_bash
def test_determinism_cpu_hides_any_gpu_and_fixes_the_thread_count(job):
    _write_stub(job["stubs"] / "python",
                'printf \'%s CVD=[%s] OMP=[%s]\\n\' "$*" '
                '"${CUDA_VISIBLE_DEVICES-unset}" "${OMP_NUM_THREADS-unset}" '
                '>> "$STUB_LOG"\n'
                'if [[ "${1:-}" == "-" ]]; then cat > /dev/null; fi\n')
    result = _submit(job, "submit_determinism_cpu.sh",
                     REPORT_DIR=_posix(job["tmp"] / "cpu"),
                     SLURM_CPUS_PER_TASK="8", CUDA_VISIBLE_DEVICES="0")
    assert result.returncode == 0, result.stdout + result.stderr
    decodes = [c for c in _calls(job) if c.startswith("-m evaluation.benchmark_wer")]
    assert decodes and all(c.endswith(" CVD=[] OMP=[8]") for c in decodes)
    assert not any("CUDA" in c for c in _calls(job) if c.startswith("module"))


@needs_bash
def test_determinism_cpu_keeps_to_its_own_directory(job):
    # By default it writes beside a GPU run's determinism/, never into it.
    evaluation = job["data"] / "speech_transcription_env" / "output" / "evaluation"
    (evaluation / "determinism").mkdir(parents=True)
    (evaluation / "determinism" / "determinism_repeat.json").write_text("{}")
    result = _submit(job, "submit_determinism_cpu.sh")
    assert result.returncode == 0, result.stdout + result.stderr
    out = evaluation / "determinism_cpu"
    dumps = [c for c in _calls(job) if c.startswith("-m evaluation.benchmark_wer")]
    assert all(f"--dump-hypotheses {_posix(out)}/seed" in c for c in dumps)
    assert (out / "cpu.txt").read_text().strip()
    assert (evaluation / "determinism" / "determinism_repeat.json").read_text() == "{}"

    # And, like the GPU job, it will not write over an earlier run.
    (out / "determinism_repeat.json").write_text("{}")
    job["log"].unlink()
    result = _submit(job, "submit_determinism_cpu.sh")
    assert result.returncode == 3
    assert not any(c.startswith("-m evaluation") for c in _calls(job))
    result = _submit(job, "submit_determinism_cpu.sh", OVERWRITE="1")
    assert result.returncode == 0, result.stdout + result.stderr


@needs_bash
def test_determinism_gpu_passes_a_dtype_only_when_asked(job):
    result = _submit(job, "submit_determinism.sh", REPORT_DIR=_posix(job["tmp"] / "a"),
                     DET_SEEDS="0", DET_REPEATS="2", DET_DTYPE="float32")
    assert result.returncode == 0, result.stdout + result.stderr
    decodes = [c for c in _calls(job) if c.startswith("-m evaluation.benchmark_wer")]
    assert len(decodes) == 2 and all(" --dtype float32 " in c for c in decodes)
    assert not any("--device" in c for c in decodes)


@needs_bash
def test_determinism_v100_record_changes_only_the_card(tmp_path):
    """The V100 run is there to compare card models under the L40S run's
    seed, so its record must ask for a V100 and otherwise run determinism.env's
    decodes, into a directory of its own."""
    from test_audit_shell_review_fixes import _sourced  # noqa: PLC0415
    names = ["DET_SUITE", "DET_LIMIT", "DET_SEEDS", "DET_REPEATS", "DET_DTYPE",
             "MODEL", "SBATCH_GRES", "REPORT_DIR"]
    gpu = _sourced(tmp_path, HPC / "runs" / "determinism.env", names)
    v100 = _sourced(tmp_path, HPC / "runs" / "determinism_v100.env", names)
    assert v100["SBATCH_GRES"] == "gpu:v100:1" and gpu["SBATCH_GRES"] == ""
    assert v100["REPORT_DIR"] != gpu["REPORT_DIR"]
    decodes = [n for n in names if n not in ("SBATCH_GRES", "REPORT_DIR")]
    assert {n: v100[n] for n in decodes} == {n: gpu[n] for n in decodes}
    # No dtype: the card's decode is the one every committed GPU run made.
    assert v100["DET_DTYPE"] == ""


def test_determinism_cpu_asks_for_a_processor_node_and_checks_the_lock():
    text = (HPC / "submit_determinism_cpu.sh").read_text(encoding="utf-8")
    code = _code_lines(HPC / "submit_determinism_cpu.sh")
    assert "#SBATCH --constraint=cpu" in text
    assert "#SBATCH --gres" not in text
    # The comparison with the GPU runs assumes their software, so a job on a
    # drifted environment stops at the gate.
    assert re.search(r'arc_preflight --lock "\$REPO_DIR/requirements-lock.txt" \|\| exit 2',
                     code)
    assert 'export CUDA_VISIBLE_DEVICES=""' in code


@needs_bash
def test_run_tests_checks_the_lock_instead_of_installing(job):
    result = _submit(job, "run_tests.sh")
    assert result.returncode == 0, result.stdout + result.stderr
    calls = _calls(job)
    lock = f"-m preflight --lock {_posix(job['repo'])}/requirements-lock.txt"
    assert calls.index(lock) < next(i for i, c in enumerate(calls)
                                    if c.startswith("-m pytest"))
    assert not _installs(calls)


@needs_bash
def test_ami_cache_audits_each_full_timeline_split(job):
    report = job["tmp"] / "eval"
    cache = job["tmp"] / "cache"
    result = _submit(job, "submit_ami_cache.sh", REPORT_DIR=_posix(report),
                     CACHE_DIR=_posix(cache))
    assert result.returncode == 0, result.stdout + result.stderr
    audits = [c for c in _calls(job) if c.startswith("-m evaluation.audit_reconstruction")]
    assert audits == [
        f"-m evaluation.audit_reconstruction {_posix(cache)}/{split}_timeline_full "
        f"--json {_posix(report)}/reconstruction_audit_{split}.json"
        for split in ("validation", "test")]


@needs_bash
def test_ami_cache_fails_when_an_audit_finds_a_displacement(job):
    result = _submit(job, "submit_ami_cache.sh", REPORT_DIR=_posix(job["tmp"] / "eval"),
                     CACHE_DIR=_posix(job["tmp"] / "cache"),
                     STUB_RC_evaluation_audit_reconstruction="1")
    assert result.returncode == 1
    # Both splits are audited before the job reports the failure.
    assert len([c for c in _calls(job) if "audit_reconstruction" in c]) == 2


@needs_bash
def test_ami_cache_skips_the_audit_for_a_truncated_cache(job):
    result = _submit(job, "submit_ami_cache.sh", REPORT_DIR=_posix(job["tmp"] / "eval"),
                     CACHE_DIR=_posix(job["tmp"] / "cache"), MAX_MINUTES="10")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not any("audit_reconstruction" in c for c in _calls(job))
    assert "Reconstruction audit skipped" in result.stdout


@needs_bash
def test_finetune_scores_from_the_baseline_cache(job):
    result = _submit(job, "submit_finetune_pyannote.sh")
    assert result.returncode == 0, result.stdout + result.stderr
    run = [c for c in _calls(job)
           if c.startswith("-m evaluation.finetune_pyannote_segmentation")]
    assert f"--eval-cache-dir {_posix(job['data'])}/ami_cache" in run[0]


@needs_bash
def test_timestamps_prewarm_uses_the_pinned_silero_loader(job):
    result = _submit(job, "submit_benchmark_timestamps.sh",
                     REPORT_DIR=_posix(job["tmp"] / "ts"), VAD_REFINE="1")
    assert result.returncode == 0, result.stdout + result.stderr
    calls = _calls(job)
    assert ("-c from evaluation.benchmark_timestamps import _load_silero_vad; "
            "_load_silero_vad()") in calls
    assert not any("torch.hub.load" in c for c in calls)


@needs_bash
@pytest.mark.parametrize("name", ["submit_benchmark_wer.sh", "submit_benchmark_wer_gpu.sh"])
def test_retired_scripts_refuse_to_run(job, name):
    result = _submit(job, name, source=HPC / "legacy" / name, SLURM_ARRAY_TASK_ID="0")
    assert result.returncode == 1
    assert "retired" in result.stderr
    assert _calls(job) == []


# ---------------------------------------------------------------------------
# The helper's own functions
# ---------------------------------------------------------------------------

def _helper(job: dict, body: str, **env):
    driver = job["tmp"] / "driver.sh"
    driver.write_bytes(("set -euo pipefail\n"
                        f'source "{_posix(job["repo"])}/hpc/common/arc_common.sh"\n'
                        + body).encode())
    return _run(driver, [], job["stubs"], dict(job["env"], **env), job["tmp"])


@needs_bash
def test_token_file_wins_over_the_environment_and_is_stripped(job):
    (job["repo"] / "hf_token.txt").write_bytes(b"hf_file\r\n")
    result = _helper(job, f'arc_load_hf_token "{_posix(job["repo"])}"\n'
                          'printf "TOKEN=%s\\n" "$HF_TOKEN"\n', HF_TOKEN="hf_env")
    assert result.returncode == 0, result.stderr
    assert "TOKEN=hf_file" in result.stdout


@needs_bash
def test_an_empty_token_file_falls_back_to_the_environment(job):
    (job["repo"] / "hf_token.txt").write_text("  \n")
    result = _helper(job, f'arc_load_hf_token "{_posix(job["repo"])}"\n'
                          'printf "TOKEN=%s\\n" "$HF_TOKEN"\n', HF_TOKEN="hf_env")
    assert result.returncode == 0 and "TOKEN=hf_env" in result.stdout


@needs_bash
def test_no_token_anywhere_fails(job):
    result = _helper(job, f'arc_load_hf_token "{_posix(job["repo"])}" || exit 7\n',
                     HF_TOKEN="")
    assert result.returncode == 7
    assert "No HuggingFace token" in result.stderr


@needs_bash
def test_activation_missing_fails_and_extra_modules_load_before_it(job):
    result = _helper(job, f'arc_activate "{_posix(job["tmp"])}/nowhere" || exit 5\n')
    assert result.returncode == 5
    assert "Activation script not found" in result.stderr

    job["log"].unlink()
    result = _helper(job, f'arc_activate "{_posix(job["repo"])}" --module FFmpeg\n'
                          'printf "PWD=%s\\n" "$PWD"\n'
                          'printf "TC=%s\\n" "${TRANSFORMERS_CACHE:-unset}"\n',
                     TRANSFORMERS_CACHE="/old")
    assert result.returncode == 0, result.stderr
    calls = _calls(job)
    assert calls == ["module purge", "module load Anaconda3/2025.06-1",
                     "module load FFmpeg", "activate"]
    lines = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    assert lines["PWD"].endswith("/repo")
    assert lines["TC"] == "unset"


@needs_bash
def test_module_pins_can_be_overridden_for_another_cluster(job):
    result = _helper(job, f'arc_activate "{_posix(job["repo"])}" --cuda\n',
                     ARC_ANACONDA_MODULE="Miniconda3/24", ARC_CUDA_MODULE="cuda/12.1")
    assert result.returncode == 0, result.stderr
    assert _calls(job)[:3] == ["module purge", "module load Miniconda3/24",
                               "module load cuda/12.1"]
