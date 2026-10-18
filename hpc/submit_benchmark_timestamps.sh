#!/bin/bash
# =============================================================================
# submit_benchmark_timestamps.sh  —  Whisper timestamp alignment benchmark
#
# Streams the AMI IHM test split and, for each utterance, runs Whisper with
# segment-level return_timestamps=True to measure how accurately the first and
# last predicted segment boundaries align with the known utterance boundaries
# (0.0 s start, true duration end).  Results are written to REPORT_DIR as
# timestamp_report.csv, timestamp_skipped.csv and timestamp_summary.json.
#
# The default model is openai/whisper-large-v3; this can be overridden with
# the MODEL environment variable.  The job runs on a single GPU node. The
# committed 500-utterance runs took about 25 minutes on a Tesla P100 (jobs
# 7737896 and 7746221) and about 9 on an H100 80GB HBM3 (jobs 8917980 and
# 8917981). The job asks for any GPU, and the card can move a boundary, so
# hpc/runs/timestamps.env names the one the committed run used.
#
# When VAD_REFINE=1 is set, Silero VAD is loaded alongside Whisper and used
# to refine each utterance’s predicted end boundary.  The VAD locates the last
# voiced frame in the clip, and the predicted end becomes the later of the
# VAD end and Whisper's own (max, since bb32915): Whisper's gross errors are
# early truncations, so only a later VAD end can correct one.  Silero VAD
# (the tag snakers4/silero-vad:v6.2.1) is downloaded once to the torch hub
# cache, as the tag's whole repository (about 35 MB unpacked, for a 2.3 MB
# model); later runs use the cached copy.
#
# Usage (submit from the repository root on ARC):
#
#   sbatch hpc/submit_benchmark_timestamps.sh
#
#   # With Silero VAD end-boundary refinement
#   VAD_REFINE=1 sbatch hpc/submit_benchmark_timestamps.sh
#
#   # Score only the first 200 utterances (fast pilot)
#   LIMIT=200 sbatch hpc/submit_benchmark_timestamps.sh
#
#   # Use a different model
#   MODEL=distil-whisper/distil-large-v3 sbatch hpc/submit_benchmark_timestamps.sh
#
# Overrides (set before sbatch): MODEL, LIMIT (500), VAD_REFINE (0),
# REPORT_DIR. These are generic names that sbatch passes through from the
# submitting shell; the effective values are echoed at the top of the log.
#
# Outputs written to REPORT_DIR (default
# $DATA/speech_transcription_env/output/evaluation/):
#   timestamp_report.csv     one row per scored utterance
#   timestamp_skipped.csv    one row per utterance not scored, with the reason
#   timestamp_summary.json   the summary statistics, the sample and the decode
#   environment/             the job's record of its software, GPU and commit
#
# The settings behind the committed results are recorded in
# hpc/runs/timestamps.env and hpc/runs/timestamps_vad.env, which send a
# reproduction to a directory of its own.
#
# Reference: https://arc-user-guide.readthedocs.io/en/latest/arc-script-basics.html
# =============================================================================

#SBATCH --job-name=benchmark_timestamps
#SBATCH --partition=short
#SBATCH --clusters=htc
#SBATCH --time=04:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --gres=gpu:1
#SBATCH --output=logs/benchmark_timestamps_%j.out
#SBATCH --error=logs/benchmark_timestamps_%j.err

set -euo pipefail

echo "⏱  ARC TIMESTAMP ALIGNMENT BENCHMARK"
echo "======================================"
echo "Job started at: $(date)"
echo "Node:           ${SLURM_NODENAME:-local}"
echo "Job ID:         ${SLURM_JOB_ID:-n/a}"
echo "Cluster:        ${SLURM_CLUSTER_NAME:-n/a}"

# -----------------------------------------------------------------------------
# Environment and GPU gate (hpc/common/arc_common.sh). This job used to
# pip-install datasets, soundfile and transformers>=4.37 when an import
# failed, reinstall torch from the cu121 index when CUDA looked missing, and
# then continue on the CPU if CUDA was still missing. It now installs
# nothing and stops with exit 2 when the preflight fails (audit findings
# DEPS-03, SHELL-01, SHELL-05, DEPS-10).
# -----------------------------------------------------------------------------
REPO_DIR="${SLURM_SUBMIT_DIR:-$HOME/paper_speech_transcription}"
# shellcheck source=common/arc_common.sh
source "$REPO_DIR/hpc/common/arc_common.sh" || exit 1
arc_activate "$REPO_DIR" --cuda || exit 1
arc_require_gpu || exit 2

# Silero VAD is needed only when VAD_REFINE=1. It is a small model
# (2.3 MB) that runs offline once torch.hub has fetched it; no audio data
# is sent to any remote service. The pre-warm goes through the benchmark's
# own loader, so it fetches the same pinned tag
# (snakers4/silero-vad:v6.2.1) the run will use; the old pre-warm fetched
# the untagged repository, which is whatever its default branch holds.
if [[ "${VAD_REFINE:-0}" == "1" ]]; then
    python -c "from evaluation.benchmark_timestamps import _load_silero_vad; _load_silero_vad()" 2>/dev/null \
        || echo "  ⚠  Silero VAD pre-warm failed; torch.hub download will happen at runtime." >&2
fi

# -----------------------------------------------------------------------------
# Output directory
# -----------------------------------------------------------------------------
# The default is the ARC evaluation directory, from which a result is
# copied into the repository's output/evaluation/ to be committed. A run
# left at the default writes over the files there, as job 7746137 did on
# 31 May 2026, so the records in hpc/runs/ set REPORT_DIR to a directory of
# their own.
REPORT_DIR="${REPORT_DIR:-${DATA}/speech_transcription_env/output/evaluation}"
mkdir -p "$REPORT_DIR" logs

echo ""
echo "Output directory: $REPORT_DIR"
echo ""

# -----------------------------------------------------------------------------
# Parameters
# -----------------------------------------------------------------------------
MODEL="${MODEL:-openai/whisper-large-v3}"
LIMIT="${LIMIT:-500}"
VAD_REFINE="${VAD_REFINE:-0}"

echo "Model: $MODEL"
echo "Utterance limit: $LIMIT"
echo "VAD end-boundary refinement: ${VAD_REFINE}"
echo ""

# Record the software and GPU this run used beside its results.
arc_record_env "$REPORT_DIR"       \
    "MODEL=${MODEL}"               \
    "LIMIT=${LIMIT}"               \
    "VAD_REFINE=${VAD_REFINE}"     \
    "REPORT_DIR=${REPORT_DIR}"

# -----------------------------------------------------------------------------
# Run benchmark
# -----------------------------------------------------------------------------
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Timestamp benchmark  |  AMI IHM test split  |  model: ${MODEL}"
echo "  Started: $(date)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Build the argument list so that --vad-refine is optional.
ARGS=(
    --output-dir "$REPORT_DIR"
    --model      "$MODEL"
    --limit      "$LIMIT"
)
if [[ "${VAD_REFINE}" == "1" ]]; then
    ARGS+=(--vad-refine)
fi

python -m evaluation.benchmark_timestamps "${ARGS[@]}"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅  Timestamp benchmark complete at $(date)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Output files:"
ls -lh "$REPORT_DIR"/timestamp_*.{csv,json} 2>/dev/null || echo "  (no output files found)"
echo ""
echo "Job finished at: $(date)"
