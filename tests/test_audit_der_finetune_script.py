"""The fine-tuning job must print a model path the DER benchmark accepts (DER-2).

finetune_pyannote_segmentation exports a checkpoint file,
segmentation_model/segmentation-ami-best.ckpt, and benchmark_der refuses a
--segmentation-model that is not a file. The job script still printed the
directory, so the command it suggested failed after a GPU queue wait. The
script runs under bash with a python stub, as in
test_audit_shell_job_exit_status; skipped without a POSIX bash.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from test_audit_shell_transcription_wrapper import (
    REPO, _copy_lf, _posix, _run, _write_stub, needs_bash,
)

@needs_bash
@pytest.mark.parametrize("data_name", ["data", "data with spaces and 'quotes'"])
def test_the_suggested_commands_name_the_exported_checkpoint(tmp_path: Path, data_name: str):
    from evaluation.finetune_pyannote_segmentation import _BEST_CHECKPOINT_NAME

    repo = tmp_path / "repo"
    (repo / "hpc" / "common").mkdir(parents=True)
    _copy_lf(REPO / "hpc" / "common" / "arc_common.sh",
             repo / "hpc" / "common" / "arc_common.sh")
    script = repo / "hpc" / "submit_finetune_pyannote.sh"
    _copy_lf(REPO / "hpc" / "submit_finetune_pyannote.sh", script)
    (repo / "activate_project_env_arc.sh").write_bytes(
        b'export PROJECT_DIR="$DATA/speech_transcription_env"\n')
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    _write_stub(stubs / "module", "exit 0\n")
    _write_stub(stubs / "python", "exit 0\n")
    data = tmp_path / data_name
    data.mkdir()
    env = {"SLURM_SUBMIT_DIR": _posix(repo), "DATA": _posix(data),
           "SLURM_JOB_ID": "42", "HF_TOKEN": "x"}

    result = _run(script, [], stubs, env, repo)
    assert result.returncode == 0, result.stdout + result.stderr

    suggested = [shlex.split(line.strip()) for line in result.stdout.splitlines()
                 if line.strip().startswith("SEGMENTATION_MODEL=")]
    direct = [shlex.split(line.strip()) for line in result.stdout.splitlines()
              if line.strip().startswith("python -m evaluation.benchmark_der ")]
    expected = (f"{_posix(data)}/speech_transcription_env/output/finetune"
                f"/segmentation_model/{_BEST_CHECKPOINT_NAME}")
    assert suggested == [[f"SEGMENTATION_MODEL={expected}", "sbatch",
                          "hpc/submit_benchmark_der.sh"]]
    assert direct == [["python", "-m", "evaluation.benchmark_der", "--segmentation-model",
                       expected]]
    training = [shlex.split(line.removeprefix("Command: "))
                for line in result.stdout.splitlines() if line.startswith("Command: ")]
    assert len(training) == 1
    output_index = training[0].index("--output-dir")
    assert (training[0][output_index + 1]
            == f"{_posix(data)}/speech_transcription_env/output/finetune")


@pytest.mark.filterwarnings("ignore::RuntimeWarning")    # runpy re-executes the module
@pytest.mark.parametrize(("argv", "status"), [(["--help"], 0), (["--epochs", "x"], 2)])
def test_the_script_ends_through_exit_without_finalising(monkeypatch, capsys, argv, status):
    """SC-24: the script streams AMI like benchmark_der and sweep_der, so it
    must end as they do, or the streaming stack's abort at shutdown (status
    134) would fail a run that had saved its checkpoint."""
    import runpy
    import sys

    from evaluation import benchmark_der

    exits: list[int] = []
    monkeypatch.setattr(benchmark_der, "exit_without_finalising", exits.append)
    monkeypatch.setattr(sys, "argv", ["finetune_pyannote_segmentation", *argv])
    runpy.run_module("evaluation.finetune_pyannote_segmentation", run_name="__main__")
    assert exits == [status]
    assert ("error: 2" in capsys.readouterr().err) == (status == 2)


def test_python_suggested_command_preserves_a_checkpoint_path_with_spaces_and_quotes(
        tmp_path: Path, monkeypatch, capsys):
    from evaluation import finetune_pyannote_segmentation as finetune

    output = tmp_path / "run with spaces and 'quotes'"
    checkpoint = output / "segmentation_model" / finetune._BEST_CHECKPOINT_NAME
    monkeypatch.setattr(finetune, "load_hf_token", lambda: "test-token")
    monkeypatch.setattr(finetune, "_reload_from_disk", lambda *args, **kwargs: ([], []))
    monkeypatch.setattr(finetune, "_finetune", lambda **kwargs: checkpoint)
    finetune.main(["--output-dir", str(output), "--skip-data-prep", "--skip-eval"])
    commands = [shlex.split(line.strip()) for line in capsys.readouterr().out.splitlines()
                if line.strip().startswith("python -m evaluation.benchmark_der ")]
    assert commands == [["python", "-m", "evaluation.benchmark_der",
                         "--segmentation-model", checkpoint.as_posix()]]
