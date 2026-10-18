#!/bin/bash
# =============================================================================
# submit_finetune_pyannote.sh  —  Fine-tune pyannote segmentation on Oxford ARC
#
# Fine-tunes pyannote/segmentation-3.0 on the AMI IHM training split, aiming
# at missed speech, which is the largest component of the released model's
# diarisation error on the held-out test split (see
# output/evaluation/der_summary.json for the figures) and the one that
# rises with how much of a meeting is spoken over. Clustering cannot recover
# speech that segmentation never emitted, so the segmentation model is where
# the lever is. Nothing here has produced a reported result; the improvement
# is a hypothesis until this is run and scored.
#
# The script executes three phases in sequence.
#
# Phase 1 — data preparation.  The AMI IHM train split is streamed from
# HuggingFace, each meeting is rebuilt on its original timeline exactly as
# the benchmark does, and saved as WAV and RTTM files under
# $FINETUNE_DIR.  The phase is NOT skipped automatically when the files
# already exist; set SKIP_DATA_PREP=1 to pass --skip-data-prep and reuse
# them (a rerun without it rebuilds every meeting).
#
# Phase 2 — fine-tuning.  pyannote/segmentation-3.0 is loaded from the
# local HuggingFace cache (or downloaded if absent) and fine-tuned for
# $EPOCHS epochs using PyTorch Lightning.  Checkpoints are written to
# $FINETUNE_DIR/checkpoints; the best one is copied to
# $FINETUNE_DIR/segmentation_model/segmentation-ami-best.ckpt, beside its
# finetune_provenance.json.
#
# Phase 3 — evaluation.  The full DER benchmark is re-run on the AMI IHM
# test set with the fine-tuned segmentation model substituted into the
# pyannote/speaker-diarization-3.1 pipeline.  Results are written to
# $FINETUNE_DIR/evaluation and compared against the committed baseline.
#
# Usage (submit from the repository root on ARC):
#
#   sbatch hpc/submit_finetune_pyannote.sh
#
#   # Pilot: 20 meetings, 3 epochs, skip evaluation
#   LIMIT_MEETINGS=20 EPOCHS=3 SKIP_EVAL=1 \
#     sbatch hpc/submit_finetune_pyannote.sh
#
#   # Re-run fine-tuning only (data already on disk)
#   SKIP_DATA_PREP=1 sbatch hpc/submit_finetune_pyannote.sh
#
# Environment variables (all optional, defaults shown):
#   LIMIT_MEETINGS   Maximum AMI train meetings to use   (default: 80)
#   EPOCHS           Number of fine-tuning epochs        (default: 10)
#   MAX_MINUTES      Truncate each meeting, for a pilot  (default: whole)
#   SKIP_DATA_PREP   Set to 1 to skip Phase 1            (default: unset)
#   SKIP_EVAL        Set to 1 to skip Phase 3            (default: unset)
#   CACHE_DIR        AMI reconstruction cache Phase 3 scores from
#                    (default: $DATA/ami_cache, the DER baseline's cache)
#
# Reference: https://arc-user-guide.readthedocs.io/en/latest/arc-script-basics.html
# =============================================================================

#SBATCH --job-name=finetune_pyannote
#SBATCH --partition=short
#SBATCH --clusters=htc
#SBATCH --time=12:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH --output=logs/finetune_pyannote_%j.out
#SBATCH --error=logs/finetune_pyannote_%j.err

set -euo pipefail

echo "🎙  ARC PYANNOTE FINE-TUNING"
echo "============================="
echo "Job started at: $(date)"
echo "Node:           ${SLURM_NODENAME:-local}"
echo "Job ID:         ${SLURM_JOB_ID:-n/a}"
echo "Cluster:        ${SLURM_CLUSTER_NAME:-n/a}"

# -----------------------------------------------------------------------------
# Environment, GPU gate and token (hpc/common/arc_common.sh). This job used
# to pip-install datasets, soundfile, pyannote.audio and pytorch-lightning
# when an import failed, and to uninstall torch, torchvision and torchaudio
# and reinstall torch and torchaudio from the cu121 index when CUDA or
# torchaudio looked broken. It now installs nothing: the preflight must pass
# (exit 2 otherwise), and pytorch-lightning, which only this job imports,
# must import (exit 2 otherwise).
# -----------------------------------------------------------------------------
REPO_DIR="${SLURM_SUBMIT_DIR:-$HOME/paper_speech_transcription}"
# shellcheck source=common/arc_common.sh
source "$REPO_DIR/hpc/common/arc_common.sh" || exit 1
arc_activate "$REPO_DIR" --cuda || exit 1
arc_require_gpu --diarisation-required || exit 2
if ! python -c "import pytorch_lightning as pl; print('pytorch-lightning:', pl.__version__)"; then
    echo "❌ pytorch-lightning is not importable; it is pinned in requirements-lock.txt." >&2
    exit 2
fi
# pyannote/segmentation-3.0 and pyannote/speaker-diarization-3.1 are gated.
arc_load_hf_token "$REPO_DIR" || exit 1

# -----------------------------------------------------------------------------
# Output directory — write to project space ($DATA) on ARC
# -----------------------------------------------------------------------------
# A pilot (MAX_MINUTES or LIMIT_MEETINGS set) gets its own directory, so its
# truncated WAV/RTTM files are never taken for a full run's data. The
# script's data_manifest.json refuses a mismatch either way (EDER-11); this
# keeps the two runs from blocking each other. The default path is unchanged.
FINETUNE_DIR="${PROJECT_DIR}/output/finetune${MAX_MINUTES:+_${MAX_MINUTES}min}${LIMIT_MEETINGS:+_${LIMIT_MEETINGS}m}"
mkdir -p "$FINETUNE_DIR"
mkdir -p "$REPO_DIR/logs"

echo ""
echo "Output directory: $FINETUNE_DIR"
echo "Limit meetings:   ${LIMIT_MEETINGS:-80}"
echo "Epochs:           ${EPOCHS:-10}"
echo "Max minutes:      ${MAX_MINUTES:-whole meetings}"

# Record the software and GPU this run used beside its outputs.
arc_record_env "$FINETUNE_DIR"                    \
    "EVAL_CACHE_DIR=${CACHE_DIR:-${DATA}/ami_cache}" \
    "LIMIT_MEETINGS=${LIMIT_MEETINGS:-80}"        \
    "EPOCHS=${EPOCHS:-10}"                        \
    "MAX_MINUTES=${MAX_MINUTES:-}"                \
    "SKIP_DATA_PREP=${SKIP_DATA_PREP:-0}"         \
    "SKIP_EVAL=${SKIP_EVAL:-0}"

# -----------------------------------------------------------------------------
# Build the argument list
# -----------------------------------------------------------------------------
# Phase 3 scores the AMI test meetings from the same 16-bit reconstruction
# cache the released model's baseline (der_summary.json) was scored on, so
# the two DERs differ only in the segmentation model (audit finding
# EDER-06). CACHE_DIR overrides it, as in the DER scripts.
EVAL_CACHE_DIR="${CACHE_DIR:-${DATA}/ami_cache}"
ARGS=(
    "--output-dir" "$FINETUNE_DIR"
    "--limit-meetings" "${LIMIT_MEETINGS:-80}"
    "--epochs" "${EPOCHS:-10}"
    "--eval-cache-dir" "$EVAL_CACHE_DIR"
)
if [[ -n "${MAX_MINUTES:-}" ]]; then
    ARGS+=("--max-minutes" "$MAX_MINUTES")
fi

if [[ "${SKIP_DATA_PREP:-0}" == "1" ]]; then
    ARGS+=("--skip-data-prep")
    echo "Phase 1 (data prep): skipped"
fi

if [[ "${SKIP_EVAL:-0}" == "1" ]]; then
    ARGS+=("--skip-eval")
    echo "Phase 3 (evaluation): skipped"
fi

# -----------------------------------------------------------------------------
# Run fine-tuning
# -----------------------------------------------------------------------------
echo ""
echo "Starting fine-tuning at: $(date)"
printf 'Command: python -m evaluation.finetune_pyannote_segmentation'
printf ' %q' "${ARGS[@]}"
printf '\n'
echo "----------------------------------------------------------------------"

# Capture the status instead of letting `set -e` end the script here, so a
# failed run still prints the report below and exits with Python's code.
EXIT_CODE=0
python -m evaluation.finetune_pyannote_segmentation "${ARGS[@]}" || EXIT_CODE=$?

echo ""
echo "----------------------------------------------------------------------"
echo "Fine-tuning finished at: $(date)  (exit code: $EXIT_CODE)"

if [[ $EXIT_CODE -eq 0 ]]; then
    # benchmark_der --segmentation-model takes the checkpoint file itself
    # (the name is _BEST_CHECKPOINT_NAME in finetune_pyannote_segmentation)
    # and refuses a directory.
    MODEL_DIR="$FINETUNE_DIR/segmentation_model"
    MODEL_PATH="$MODEL_DIR/segmentation-ami-best.ckpt"
    PROV_FILE="$MODEL_DIR/finetune_provenance.json"
    echo ""
    echo "Fine-tuned segmentation model: $MODEL_PATH"
    if [[ -f "$PROV_FILE" ]]; then
        echo "Provenance:"
        cat "$PROV_FILE"
    fi
    echo ""
    echo "To re-run the DER benchmark with the fine-tuned model:"
    printf '  SEGMENTATION_MODEL=%q sbatch hpc/submit_benchmark_der.sh\n' "$MODEL_PATH"
    echo ""
    echo "Or run directly:"
    printf '  python -m evaluation.benchmark_der --segmentation-model %q\n' "$MODEL_PATH"
fi

exit $EXIT_CODE
