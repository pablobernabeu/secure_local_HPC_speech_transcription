#!/bin/bash
# =============================================================================
#  run_tests.sh — execute the pytest suite on Oxford ARC
#
#  Runs `python -m pytest tests/ -v -rs --tb=short` inside the project
#  environment so that the tests skipped on developer laptops actually
#  execute. The skips come from missing optional dependencies: jiwer (the
#  WER aggregation and normalisation modules), pyannote.core, .metrics and
#  .audio (DER scoring and offline diarisation), transformers (the
#  whisper_norm condition), bibtexparser, an ffmpeg binary (compressed-audio
#  decoding) and a POSIX bash (the hpc/ script tests); run `pytest -rs`
#  locally for the current list. -rs prints every skip that remains here with its reason,
#  so the log shows which tests did not run, not only how many passed.
#  No GPU is needed: these tests are CPU-only.
#
#  The tests run against the environment exactly as the result jobs see it,
#  and that environment is never changed from here. Before pytest starts,
#  `python -m preflight --lock requirements-lock.txt` compares every
#  installed version with the lock and stops the job (exit 2) on any
#  difference. The script used to upgrade pip and pip-install jiwer, an
#  unpinned pyannote.audio>=3.1 and bibtexparser<2 into the shared results
#  environment whenever an import failed (audit findings TESTS-02, SHELL-06).
#
#  Recorded runs on ARC, with their commits, pass counts and remaining skip,
#  are listed in hpc/README.md under "Checks run on ARC" (TESTS-01), with
#  what to record for the next one.
#
#  Submission:
#      sbatch hpc/run_tests.sh
#
#  Reference: https://arc-user-guide.readthedocs.io/en/latest/arc-script-basics.html
# =============================================================================

#SBATCH --job-name=pytest_suite
#SBATCH --output=logs/pytest_%j.out
#SBATCH --error=logs/pytest_%j.err
#SBATCH --clusters=htc
#SBATCH --partition=short
#SBATCH --time=00:30:00
#SBATCH --mem=8G
#SBATCH --cpus-per-task=2

set -euo pipefail

echo "🧪 ARC PYTEST RUN"
echo "================="
echo "Job started at: $(date)"
echo "Node:           ${SLURM_NODENAME:-local}"
echo "Job ID:         ${SLURM_JOB_ID:-n/a}"
echo "Cluster:        ${SLURM_CLUSTER_NAME:-n/a}"

# -----------------------------------------------------------------------------
# Environment (hpc/common/arc_common.sh), then the version gate: the job
# fails fast when the environment differs from requirements-lock.txt,
# instead of installing whatever is missing.
# -----------------------------------------------------------------------------
# SLURM_SUBMIT_DIR is set automatically to the directory where sbatch was called,
# so the script works regardless of the name used when cloning the repository.
REPO_DIR="${SLURM_SUBMIT_DIR:-$HOME/paper_speech_transcription}"
# shellcheck source=common/arc_common.sh
source "$REPO_DIR/hpc/common/arc_common.sh" || exit 1
arc_activate "$REPO_DIR" || exit 1
mkdir -p logs
arc_preflight --lock "$REPO_DIR/requirements-lock.txt" || exit 2

echo
echo "Python:        $(python --version)"
echo "Pytest:        $(python -m pytest --version | head -n 1)"
echo "Working dir:   $(pwd)"
echo "PYTHONPATH:    ${PYTHONPATH:-<unset>}"
echo

# Record the environment the tests ran against, so a pass count can be tied
# to the package versions that produced it.
arc_record_env "$REPO_DIR/logs"

# -----------------------------------------------------------------------------
# Run the suite
# -----------------------------------------------------------------------------
# The PYTHONPATH export makes the top-level packages (evaluation, tools,
# local_app, transcription) importable when pytest runs from the repository
# root, matching the developer-laptop invocation.
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

python -m pytest tests/ -v -rs --tb=short

echo "✅ Finished at $(date)"
