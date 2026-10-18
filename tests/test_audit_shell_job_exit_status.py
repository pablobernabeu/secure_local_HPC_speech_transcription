"""Exit-status and output-path tests for job scripts (audit group SHELL).

Each script is run under bash with stub ``module`` and ``python``
executables, so nothing is transcribed or scored. The checks are the ones the
audit found broken: failures that ended in a success banner and exit 0
(case study, fine-tuning, container entrypoint), output written where the
committed layout does not keep it (case study), and a multilingual re-run
silently overwriting an earlier arm's files.

Needs a POSIX bash with GNU tools (Git Bash on Windows); skipped otherwise.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from test_audit_shell_transcription_wrapper import (  # noqa: I001
    REPO, _copy_lf, _posix, _run, _write_stub, needs_bash,
)

pytestmark = needs_bash

# A python stub that logs each call on one line and exits with the status
# configured for the module it was asked to run (STUB_RC_<module>, dots and
# dashes as underscores), 0 otherwise. `python -` (a heredoc) is drained.
_PYTHON_STUB = r'''
log="$STUB_LOG"
printf '%s\n' "$*" >> "$log"
if [[ "${1:-}" == "-" ]]; then cat > /dev/null; exit 0; fi
target=""
if [[ "${1:-}" == "-m" ]]; then target="$2"; elif [[ "${1:-}" == *.py ]]; then target="$1"; fi
key="STUB_RC_$(printf '%s' "$target" | tr '.-' '__')"
exit "${!key:-0}"
'''


@pytest.fixture()
def job_env(tmp_path: Path) -> dict:
    repo = tmp_path / "repo"
    (repo / "hpc" / "common").mkdir(parents=True)
    _copy_lf(REPO / "hpc" / "common" / "arc_common.sh",
             repo / "hpc" / "common" / "arc_common.sh")
    (repo / "activate_project_env_arc.sh").write_bytes(
        b'export PROJECT_DIR="$DATA/speech_transcription_env"\n')
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    _write_stub(stubs / "module", "exit 0\n")
    _write_stub(stubs / "python", _PYTHON_STUB)
    _write_stub(stubs / "python3", _PYTHON_STUB)
    log = tmp_path / "python_calls.log"
    data = tmp_path / "data"
    data.mkdir()
    env = {"SLURM_SUBMIT_DIR": _posix(repo), "DATA": _posix(data),
           "STUB_LOG": _posix(log), "SLURM_JOB_ID": "42", "HF_TOKEN": "x"}
    return {"repo": repo, "stubs": stubs, "log": log, "data": data,
            "env": env, "tmp": tmp_path}


def _calls(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


def _case_study_script(job_env: dict) -> Path:
    """Copy the job into the stand-in repository, with the corpus manifest
    that the repository commits beside it."""
    script = job_env["repo"] / "hpc" / "submit_case_study.sh"
    _copy_lf(REPO / "hpc" / "submit_case_study.sh", script)
    manifest = job_env["repo"] / "data" / "codex_mentis" / "manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text('{"episodes": []}')
    return script


def _case_study(job_env: dict, **rcs: str):
    script = _case_study_script(job_env)
    audio = job_env["tmp"] / "ep.wav"
    audio.write_bytes(b"RIFF")
    env = dict(job_env["env"], CASE_AUDIO=_posix(audio), CASE_NAME="ep")
    env.update(rcs)
    return _run(script, [], job_env["stubs"], env, job_env["repo"])


def test_case_study_writes_evaluation_outside_the_tracked_tree(job_env: dict) -> None:
    """The evaluation goes to project storage, not the tracked output/case_study/
    of the clone, which a run used to leave modified (REV-04)."""
    result = _case_study(job_env)
    assert result.returncode == 0, result.stdout + result.stderr
    podcast = [c for c in _calls(job_env["log"]) if "benchmark_podcast" in c]
    expected = f"--output-dir {_posix(job_env['data'])}/speech_transcription_env/output/case_study"
    assert podcast and expected in podcast[0]
    assert "--output-dir output/case_study" not in podcast[0]
    assert not (job_env["repo"] / "output" / "case_study").exists()
    assert "Case study complete" in result.stdout


def test_case_study_refuses_to_overwrite_an_earlier_result(job_env: dict) -> None:
    report = job_env["data"] / "speech_transcription_env" / "output" / "case_study"
    report.mkdir(parents=True)
    (report / "podcast_eval_summary.json").write_text("{}")
    result = _case_study(job_env)
    assert result.returncode == 6
    assert not any("transcription.py" in c for c in _calls(job_env["log"]))

    job_env["log"].unlink(missing_ok=True)
    result = _case_study(job_env, OVERWRITE="1")
    assert result.returncode == 0, result.stdout + result.stderr


def test_case_study_names_the_original_of_a_decoded_recording(job_env: dict) -> None:
    """A decoded .m4a reaches transcription.py with its source and the exact
    decode command, for the run manifest (CORE-04)."""
    original = job_env["tmp"] / "ep.m4a"
    original.write_bytes(b"m4a")
    (job_env["tmp"] / "ep_16k.wav").write_bytes(b"RIFF")   # an earlier decode
    # ... of this very recording, as the stamp beside it records (DEPS-15).
    (job_env["tmp"] / "ep_16k.wav.source.sha256").write_text(
        hashlib.sha256(b"m4a").hexdigest() + "\n")
    script = _case_study_script(job_env)
    env = dict(job_env["env"], CASE_AUDIO=_posix(original), CASE_NAME="ep")
    result = _run(script, [], job_env["stubs"], env, job_env["repo"])
    assert result.returncode == 0, result.stdout + result.stderr
    run = [c for c in _calls(job_env["log"]) if c.startswith("transcription.py")][0]
    assert run.startswith(f"transcription.py {_posix(job_env['tmp'])}/ep_16k.wav ")
    assert f"--source-audio {_posix(original)}" in run
    assert "--source-derivation cached output of an earlier run of: ffmpeg -nostdin" in run
    assert "-ac 1 -ar 16000 -c:a pcm_s16le" in run


@pytest.mark.parametrize("stamp", [None, "0" * 64])
def test_case_study_does_not_reuse_a_decode_of_another_recording(job_env: dict,
                                                                  stamp) -> None:
    """A cached decode with no stamp, or a stamp naming another recording, is
    decoded again rather than reused (DEPS-15). The stub environment has no
    ffmpeg, so the fresh decode stops the job with exit 3 before any
    transcription."""
    original = job_env["tmp"] / "ep.m4a"
    original.write_bytes(b"m4a")
    (job_env["tmp"] / "ep_16k.wav").write_bytes(b"RIFF")
    if stamp is not None:
        (job_env["tmp"] / "ep_16k.wav.source.sha256").write_text(stamp + "\n")
    script = _case_study_script(job_env)
    env = dict(job_env["env"], CASE_AUDIO=_posix(original), CASE_NAME="ep")
    result = _run(script, [], job_env["stubs"], env, job_env["repo"])
    assert result.returncode == 3, result.stdout + result.stderr
    assert "no matching source stamp" in result.stdout
    assert not any(c.startswith("transcription.py") for c in _calls(job_env["log"]))


def test_case_study_passes_no_source_for_an_undecoded_recording(job_env: dict) -> None:
    result = _case_study(job_env)
    assert result.returncode == 0, result.stdout + result.stderr
    run = [c for c in _calls(job_env["log"]) if c.startswith("transcription.py")][0]
    assert "--source-audio" not in run and "--source-derivation" not in run


def test_case_study_runs_the_optional_review_checks(job_env: dict) -> None:
    """The case study's review uses the two optional checks (NEW-12) at
    their suggested settings."""
    result = _case_study(job_env)
    assert result.returncode == 0, result.stdout + result.stderr
    run = [c for c in _calls(job_env["log"]) if c.startswith("transcription.py")][0]
    assert "--review-flag-zero-duration" in run
    assert "--review-repeated-passage-words 8" in run
    assert "--review-repeated-passage-window 60" in run


def test_case_study_stops_with_exit_4_when_preflight_fails(job_env: dict) -> None:
    result = _case_study(job_env, STUB_RC_preflight="1")
    assert result.returncode == 4
    calls = _calls(job_env["log"])
    assert any("-m preflight --gpu-required --diarisation-required" in c for c in calls)
    assert not any("transcription.py" in c for c in calls)


def test_case_study_fails_when_provenance_verification_fails(job_env: dict) -> None:
    result = _case_study(job_env, STUB_RC_provenance="1")
    assert result.returncode == 5
    assert "Case study complete" not in result.stdout
    assert "Provenance verification exit status: 1" in result.stdout


def test_case_study_runs_verification_after_a_failed_evaluation(job_env: dict) -> None:
    result = _case_study(job_env, STUB_RC_evaluation_benchmark_podcast="2")
    assert result.returncode == 5
    assert any("provenance verify" in c for c in _calls(job_env["log"]))


def _podcast_call(job_env: dict) -> str:
    calls = [c for c in _calls(job_env["log"]) if "benchmark_podcast" in c]
    assert len(calls) == 1, calls
    return calls[0]


def test_case_study_scores_against_the_committed_manifest(job_env: dict) -> None:
    """With no fetch manifest beside the audio, as on ARC, the evaluation reads
    the repository's own instead of a path that does not exist, which failed
    re-run 8978758 after it had transcribed (NEW-06)."""
    result = _case_study(job_env)
    assert result.returncode == 0, result.stdout + result.stderr
    committed = f"{_posix(job_env['repo'])}/data/codex_mentis/manifest.json"
    assert f"--manifest {committed} --output-dir " in _podcast_call(job_env)
    # The environment record names the manifest the evaluation read.
    report = job_env["data"] / "speech_transcription_env" / "output" / "case_study"
    records = list((report / "environment").glob("*_42.txt"))
    assert len(records) == 1, records
    assert f"CASE_MANIFEST={committed}" in records[0].read_text().splitlines()


def test_case_study_stops_before_transcribing_without_the_committed_manifest(
        job_env: dict) -> None:
    """With no override and no fetch manifest, a clone missing its committed
    manifest stops before transcribing, instead of failing afterwards as
    re-run 8978758 did (NEW-06)."""
    script = _case_study_script(job_env)
    committed = job_env["repo"] / "data" / "codex_mentis" / "manifest.json"
    committed.unlink()
    audio = job_env["tmp"] / "ep.wav"
    audio.write_bytes(b"RIFF")
    env = dict(job_env["env"], CASE_AUDIO=_posix(audio), CASE_NAME="ep")
    result = _run(script, [], job_env["stubs"], env, job_env["repo"])
    assert result.returncode == 2, result.stdout + result.stderr
    assert f"Corpus manifest not found: {_posix(committed)}" in result.stderr
    assert not any("transcription.py" in c for c in _calls(job_env["log"]))


def test_case_study_prefers_the_manifest_fetched_beside_the_audio(job_env: dict) -> None:
    fetched = job_env["data"] / "codex_mentis" / "manifest.json"
    fetched.parent.mkdir(parents=True)
    fetched.write_text('{"episodes": []}')
    result = _case_study(job_env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"--manifest {_posix(fetched)} --output-dir " in _podcast_call(job_env)


def test_case_study_takes_the_manifest_it_is_given(job_env: dict) -> None:
    """CASE_MANIFEST wins over both the fetch manifest and the committed one."""
    fetched = job_env["data"] / "codex_mentis" / "manifest.json"
    fetched.parent.mkdir(parents=True)
    fetched.write_text('{"episodes": []}')
    given = job_env["tmp"] / "other_manifest.json"
    given.write_text('{"episodes": []}')
    result = _case_study(job_env, CASE_MANIFEST=_posix(given))
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"--manifest {_posix(given)} --output-dir " in _podcast_call(job_env)


def test_case_study_stops_before_transcribing_without_a_manifest(job_env: dict) -> None:
    missing = job_env["tmp"] / "no_such_manifest.json"
    result = _case_study(job_env, CASE_MANIFEST=_posix(missing))
    assert result.returncode == 2
    assert f"Corpus manifest not found: {_posix(missing)}" in result.stderr
    assert not any("transcription.py" in c for c in _calls(job_env["log"]))


def test_finetune_reports_and_returns_the_python_exit_code(job_env: dict) -> None:
    script = job_env["repo"] / "hpc" / "submit_finetune_pyannote.sh"
    _copy_lf(REPO / "hpc" / "submit_finetune_pyannote.sh", script)
    env = dict(job_env["env"], STUB_RC_evaluation_finetune_pyannote_segmentation="7")
    result = _run(script, [], job_env["stubs"], env, job_env["repo"])
    assert result.returncode == 7, result.stdout + result.stderr
    assert "(exit code: 7)" in result.stdout


def _multilingual(job_env: dict, out_dir: Path, **extra: str):
    script = job_env["repo"] / "hpc" / "submit_benchmark_wer_multilingual.sh"
    _copy_lf(REPO / "hpc" / "submit_benchmark_wer_multilingual.sh", script)
    env = dict(job_env["env"], SLURM_ARRAY_TASK_ID="0",
               WER_ML_OUTPUT_DIR=_posix(out_dir), **extra)
    return _run(script, [], job_env["stubs"], env, job_env["repo"])


def test_multilingual_names_outputs_by_model(job_env: dict) -> None:
    out = job_env["tmp"] / "ml"
    result = _multilingual(job_env, out, WER_ML_MODEL="openai/whisper-Medium")
    assert result.returncode == 0, result.stdout + result.stderr
    bench = [c for c in _calls(job_env["log"]) if "evaluation.benchmark_wer" in c]
    assert len(bench) == 1
    assert "wer_summary_fleurs_fr_fr_whisper-medium.json" in bench[0]
    assert "wer_report_fleurs_fr_fr_whisper-medium.csv" in bench[0]


def test_multilingual_refuses_to_overwrite_a_summary(job_env: dict) -> None:
    out = job_env["tmp"] / "ml"
    out.mkdir()
    (out / "wer_summary_fleurs_fr_fr_whisper-large-v3.json").write_text("{}")
    result = _multilingual(job_env, out)
    assert result.returncode == 3
    assert not any("evaluation.benchmark_wer" in c for c in _calls(job_env["log"]))

    job_env["log"].unlink(missing_ok=True)
    result = _multilingual(job_env, out, OVERWRITE="1")
    assert result.returncode == 0, result.stdout + result.stderr


def _entrypoint(job_env: dict, args: list[str], **extra: str):
    script = job_env["tmp"] / "docker-entrypoint.sh"
    _copy_lf(REPO / "setup" / "docker-entrypoint.sh", script)
    env = dict(job_env["env"], **extra)
    return _run(script, args, job_env["stubs"], env, job_env["tmp"])


def test_entrypoint_batch_counts_failures_and_all_formats(job_env: dict) -> None:
    audio = job_env["tmp"] / "audio"
    audio.mkdir()
    for name in ("a.WAV", "b.m4a", "c.Mp3", "notes.txt"):
        (audio / name).write_bytes(b"x")
    result = _entrypoint(job_env, [], AUDIO_INPUT_DIR=_posix(audio),
                         STUB_RC_transcription_py="1")
    assert result.returncode == 1
    runs = [c for c in _calls(job_env["log"]) if c.startswith("transcription.py")]
    assert len(runs) == 3
    assert "3 files, 3 failed" in result.stdout


def test_entrypoint_returns_the_status_of_an_explicit_run(job_env: dict) -> None:
    result = _entrypoint(job_env, ["rec.wav", "--timestamps"],
                         STUB_RC_transcription_py="4")
    assert result.returncode == 4
    assert "Processing complete!" not in result.stdout


def test_entrypoint_refuses_an_image_missing_its_modules(job_env: dict) -> None:
    # `python3 -c "import ..."` has no module target, so key STUB_RC_ is used.
    result = _entrypoint(job_env, ["rec.wav"], STUB_RC_="1")
    assert result.returncode == 3
    assert not any(c.startswith("transcription.py") for c in _calls(job_env["log"]))


def test_entrypoint_with_no_recordings_fails(job_env: dict) -> None:
    empty = job_env["tmp"] / "empty"
    empty.mkdir()
    result = _entrypoint(job_env, [], AUDIO_INPUT_DIR=_posix(empty))
    assert result.returncode == 2


def _setup_environment(job_env: dict, **rcs: str):
    work = job_env["tmp"] / "work"
    work.mkdir()
    script = work / "setup_environment.sh"
    _copy_lf(REPO / "setup" / "setup_environment.sh", script)
    # python3 -m venv venv must leave an activate script behind.
    _write_stub(job_env["stubs"] / "python3",
                'if [[ "$1 $2" == "-m venv" ]]; then mkdir -p "$3/bin"; '
                'echo "export VIRTUAL_ENV=$PWD/$3" > "$3/bin/activate"; exit 0; fi\n'
                + _PYTHON_STUB)
    env = dict(job_env["env"], **rcs)
    return _run(script, [], job_env["stubs"], env, work)


def test_setup_environment_reports_success_only_when_every_step_passed(job_env: dict) -> None:
    ok = _setup_environment(job_env)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert "ENVIRONMENT SETUP COMPLETE" in ok.stdout


def test_setup_environment_stops_at_a_failed_install(job_env: dict) -> None:
    failed = _setup_environment(job_env, STUB_RC_pip="1")
    assert failed.returncode != 0
    assert "ENVIRONMENT SETUP COMPLETE" not in failed.stdout
