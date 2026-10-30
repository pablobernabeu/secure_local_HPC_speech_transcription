#!/bin/bash
# =============================================================================
# submit_der_sweep.sh  —  diarisation hyperparameter sweep on the AMI dev split
#
# Scores a grid of pyannote hyperparameters against the AMI development split,
# reusing one loaded pipeline and one reconstruction cache across the whole
# grid.  The development split is used deliberately: choosing a configuration
# on the test split and then reporting that split's DER would report the best
# of n draws as though it were a single measurement.
#
# Requires the reconstruction cache, so run hpc/submit_ami_cache.sh first.
#
# Usage (from the repository root on ARC):
#
# Account: pass your own project account with --account. With more than
# one, choose by current load, which changes: see the BALANCE note in
# .hpc-plan.yaml.
#
#   sbatch --account='<your-project>' hpc/submit_der_sweep.sh
#
#   # Custom grid
#   THRESHOLDS="0.5 0.6 0.7 0.8" \
#   MIN_DURATIONS_OFF="0.0 0.5" \
#     sbatch --account='<your-project>' hpc/submit_der_sweep.sh
#
# The default grid reproduces neither committed sweep. The two grids that
# produced der_sweep_* and der_sweep2_*, with job IDs, are in
# hpc/runs/der_sweep.env and hpc/runs/der_sweep2.env.
#
# Overrides (set before sbatch): THRESHOLDS, MIN_CLUSTER_SIZES (12),
# MIN_DURATIONS_OFF, SPLIT (validation), CACHE_DIR ($DATA/ami_cache),
# REPORT_DIR (default $DATA/speech_transcription_env/output/evaluation),
# OUTPUT_PREFIX (der_sweep; set e.g. der_sweep2 so a second grid in the same
# REPORT_DIR does not overwrite the first). The committed der_sweep2_* files
# come from a job that set OUTPUT_PREFIX=der_sweep2 (see
# hpc/runs/der_sweep2.env).

# SPLIT and REPORT_DIR are generic names and sbatch passes them through from
# the submitting shell, so check the echoed values at the top of the log.
#
# Outputs in $REPORT_DIR:
#   <prefix>.csv              — one row per (configuration, meeting)
#   <prefix>_summary.csv      — one row per configuration
#   <prefix>_selection.json   — the development-set winner
# =============================================================================

#SBATCH --job-name=der_sweep
#SBATCH --partition=short
#SBATCH --clusters=htc
#SBATCH --time=12:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --gres=gpu:1
#SBATCH --output=logs/der_sweep_%j.out
#SBATCH --error=logs/der_sweep_%j.err

set -euo pipefail

echo "DIARISATION HYPERPARAMETER SWEEP"
echo "================================"
echo "Started: $(date)   Job: ${SLURM_JOB_ID:-n/a}   Node: $(hostname)"

# Environment, GPU gate and token (hpc/common/arc_common.sh). The job used to
# print torch.cuda.is_available() and carry on without a GPU; a preflight
# failure now stops it with exit 2 (audit finding SHELL-05).
REPO_DIR="${SLURM_SUBMIT_DIR:-$HOME/paper_speech_transcription}"
# shellcheck source=common/arc_common.sh
source "$REPO_DIR/hpc/common/arc_common.sh" || exit 1
arc_activate "$REPO_DIR" --cuda || exit 1
arc_require_gpu --diarisation-required || exit 2
# pyannote/speaker-diarization-3.1 is gated.
arc_load_hf_token "$REPO_DIR" || exit 1

CACHE_DIR="${CACHE_DIR:-${DATA}/ami_cache}"
REPORT_DIR="${REPORT_DIR:-${DATA}/speech_transcription_env/output/evaluation}"
SPLIT="${SPLIT:-validation}"
OUTPUT_PREFIX="${OUTPUT_PREFIX:-der_sweep}"
mkdir -p "$REPORT_DIR" logs

# The default grid brackets the shipped clustering threshold (0.705) on both
# sides and pairs it with a short minimum pause, the two parameters that act
# on speaker confusion and on missed speech respectively.
THRESHOLDS="${THRESHOLDS:-0.50 0.60 0.70 0.80 0.90}"
MIN_CLUSTER_SIZES="${MIN_CLUSTER_SIZES:-12}"
MIN_DURATIONS_OFF="${MIN_DURATIONS_OFF:-0.0 0.5}"

echo ""
echo "Split:              $SPLIT"
echo "Cache:              $CACHE_DIR"
echo "Thresholds:         $THRESHOLDS"
echo "Min cluster sizes:  $MIN_CLUSTER_SIZES"
echo "Min durations off:  $MIN_DURATIONS_OFF"
echo "Report dir:         $REPORT_DIR"
echo "Output prefix:      $OUTPUT_PREFIX"
echo ""

# Record the software and GPU this run used beside its results.
arc_record_env "$REPORT_DIR"                      \
    "SPLIT=${SPLIT}"                              \
    "CACHE_DIR=${CACHE_DIR}"                      \
    "THRESHOLDS=${THRESHOLDS}"                    \
    "MIN_CLUSTER_SIZES=${MIN_CLUSTER_SIZES}"      \
    "MIN_DURATIONS_OFF=${MIN_DURATIONS_OFF}"      \
    "REPORT_DIR=${REPORT_DIR}"                    \
    "OUTPUT_PREFIX=${OUTPUT_PREFIX}"

# The three grid variables are space-separated lists, split into one
# argument per value on purpose.
# shellcheck disable=SC2086
python -m evaluation.sweep_der                       \
    --split "$SPLIT"                                 \
    --cache-dir "$CACHE_DIR"                         \
    --output-dir "$REPORT_DIR"                       \
    --output-prefix "$OUTPUT_PREFIX"                 \
    --clustering-threshold $THRESHOLDS               \
    --min-cluster-size $MIN_CLUSTER_SIZES            \
    --min-duration-off $MIN_DURATIONS_OFF

echo ""
echo "Finished: $(date)"
ls -lh "$REPORT_DIR"/"$OUTPUT_PREFIX"* 2>/dev/null || echo "  (no sweep output found)"
