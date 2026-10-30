#!/bin/bash
# =============================================================================
# submit_benchmark_der.sh  —  Diarisation Error Rate benchmark on Oxford ARC
#
# Reconstructs AMI meetings on their original timeline, runs
# pyannote/speaker-diarization-3.1 over each one, and scores the output against
# the corpus speaker labels.  The AMI IHM release ships one clip per speaker
# turn together with that turn's position in the meeting, so summing the
# headset channels at their true offsets rebuilds a signal close to the
# corpus's own headset mix, overlapping speech included.
#
# Run hpc/submit_ami_cache.sh first: with a reconstruction cache in place this
# job needs no network access and spends its GPU time on diarisation rather
# than on downloading the corpus again.
#
# Usage (from the repository root on ARC):
#
# Account: pass your own project account with --account. With more than
# one, choose by current load, which changes: see the BALANCE note in
# .hpc-plan.yaml.
#
#   # Held-out test split at the shipped defaults
#   sbatch --account='<your-project>' hpc/submit_benchmark_der.sh
#
#   # A configuration chosen on the development split
#   CLUSTERING_THRESHOLD=0.60 MIN_DURATION_OFF=0.5 \
#   REPORT_DIR=$DATA/.../evaluation/der_tuned \
#     sbatch --account='<your-project>' hpc/submit_benchmark_der.sh
#
#   # The utterance-concatenation arrangement used before, for comparison
#   MIX_MODE=concat UTT_PER_MEETING=25 sbatch --account='<your-project>' hpc/submit_benchmark_der.sh
#
# The committed DER artefacts (der_summary.json and the der_tuned/,
# der_oracle/ and der_concat/ directories) each came from one invocation;
# the overrides and job IDs are in hpc/runs/der_*.env.
#
# Every variable this script reads (set before sbatch, all optional):
#   SPLIT                 AMI split to score (default test)
#   MIX_MODE              timeline | concat (default timeline)
#   UTT_PER_MEETING       utterances per meeting, concat mode only
#   CLUSTERING_THRESHOLD  pyannote clustering threshold
#   MIN_CLUSTER_SIZE      pyannote minimum cluster size
#   MIN_DURATION_OFF      pyannote minimum pause, seconds
#   SEGMENTATION_MODEL    path to a replacement segmentation model
#   ORACLE_NUM_SPEAKERS   1 to give the pipeline the true speaker count
#   LIMIT_MEETINGS        score only the first N meetings
#   MAX_MINUTES           truncate each meeting, for a pilot
#   CACHE_DIR             reconstruction cache (default $DATA/ami_cache)
#   REPORT_DIR            output directory (default
#                         $DATA/speech_transcription_env/output/evaluation)
# SPLIT and REPORT_DIR are generic names that sbatch passes through from the
# submitting shell: a SPLIT=validation left over from a sweep session would
# score the development split here. The effective values are echoed at the
# top of the log and der_summary.json records the split.
#
# Outputs in $REPORT_DIR:
#   der_report.csv    — one row per meeting, with its overlap and silence
#   der_summary.json  — corpus-level DER, the hyperparameters, the corpus shape
#
# Reference: https://arc-user-guide.readthedocs.io/en/latest/arc-script-basics.html
# =============================================================================

#SBATCH --job-name=benchmark_der
#SBATCH --partition=short
#SBATCH --clusters=htc
#SBATCH --time=12:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --gres=gpu:1
#SBATCH --output=logs/benchmark_der_%j.out
#SBATCH --error=logs/benchmark_der_%j.err

set -euo pipefail

echo "ARC DER BENCHMARK"
echo "================="
echo "Started: $(date)   Job: ${SLURM_JOB_ID:-n/a}   Node: $(hostname)"

# -----------------------------------------------------------------------------
# Environment, GPU gate and token (hpc/common/arc_common.sh). The job used to
# print torch.cuda.is_available() and carry on, so a node without a usable
# GPU diarised on the CPU inside a GPU allocation; the preflight now stops it
# with exit 2, and --diarisation-required also stops it when pyannote cannot
# be imported or no token or cached pipeline is found (audit finding
# SHELL-05).
# -----------------------------------------------------------------------------
REPO_DIR="${SLURM_SUBMIT_DIR:-$HOME/paper_speech_transcription}"
# shellcheck source=common/arc_common.sh
source "$REPO_DIR/hpc/common/arc_common.sh" || exit 1
arc_activate "$REPO_DIR" --cuda || exit 1
arc_require_gpu --diarisation-required || exit 2
# pyannote/speaker-diarization-3.1 is gated.
arc_load_hf_token "$REPO_DIR" || exit 1

# -----------------------------------------------------------------------------
# Parameters
# -----------------------------------------------------------------------------
REPORT_DIR="${REPORT_DIR:-${DATA}/speech_transcription_env/output/evaluation}"
CACHE_DIR="${CACHE_DIR:-${DATA}/ami_cache}"
SPLIT="${SPLIT:-test}"
MIX_MODE="${MIX_MODE:-timeline}"
mkdir -p "$REPORT_DIR" logs

OPTIONAL_ARGS=()
# The explicit `return 0` matters: under `set -e` a function whose last
# command is a failing `[[ ... ]] && ...` returns non-zero, and an unset
# variable would abort the job before it started.
add_if_set() {  # add_if_set <flag> <value>
    if [[ -n "${2:-}" ]]; then
        OPTIONAL_ARGS+=("$1" "$2")
    fi
    return 0
}
add_if_set --limit-meetings         "${LIMIT_MEETINGS:-}"
add_if_set --max-minutes            "${MAX_MINUTES:-}"
add_if_set --utterances-per-meeting "${UTT_PER_MEETING:-}"
add_if_set --clustering-threshold   "${CLUSTERING_THRESHOLD:-}"
add_if_set --min-cluster-size       "${MIN_CLUSTER_SIZE:-}"
add_if_set --min-duration-off       "${MIN_DURATION_OFF:-}"
add_if_set --segmentation-model     "${SEGMENTATION_MODEL:-}"
if [[ "${ORACLE_NUM_SPEAKERS:-0}" == "1" ]]; then
    OPTIONAL_ARGS+=(--oracle-num-speakers)
fi

echo ""
echo "Split:      $SPLIT        Mix mode: $MIX_MODE"
echo "Cache:      $CACHE_DIR"
echo "Report dir: $REPORT_DIR"
echo "Extra args: ${OPTIONAL_ARGS[*]:-none}"
echo ""

# Record the software and GPU this run used beside its results.
arc_record_env "$REPORT_DIR"              \
    "SPLIT=${SPLIT}"                      \
    "MIX_MODE=${MIX_MODE}"                \
    "CACHE_DIR=${CACHE_DIR}"              \
    "REPORT_DIR=${REPORT_DIR}"            \
    "EXTRA_ARGS=${OPTIONAL_ARGS[*]:-none}"

# -----------------------------------------------------------------------------
# Run
# -----------------------------------------------------------------------------
python -m evaluation.benchmark_der    \
    --split "$SPLIT"                  \
    --mix-mode "$MIX_MODE"            \
    --cache-dir "$CACHE_DIR"          \
    --output-dir "$REPORT_DIR"        \
    "${OPTIONAL_ARGS[@]}"

echo ""
echo "DER benchmark complete at $(date)"
ls -lh "$REPORT_DIR"/der_report.csv "$REPORT_DIR"/der_summary.json 2>/dev/null \
    || echo "  (no output files found)"
