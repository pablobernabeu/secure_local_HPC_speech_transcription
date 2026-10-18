#!/bin/bash
# =============================================================================
# submit_pilot_benchmark.sh  —  Pilot WER benchmark for new post-processing
#                                conditions
#
# Runs a single-GPU pilot benchmark of the four conditions registered in
# Phase 1b (filler_strip, dedup_window, punct_strip, case_fold) against the
# raw baseline and the canonical whisper_norm condition, on a 200-utterance
# slice of LibriSpeech test-clean with openai/whisper-large-v3.  The audio
# is transcribed once per utterance and every condition is scored on the
# same hypotheses, so adding conditions to the list costs no extra audio
# passes.  This satisfies acceptance check 3 ("pilot benchmark") of the
# protocol described in docs/conditions_audit.md without disturbing the
# canonical wer_report.csv / wer_summary.json that the manuscript reads.
#
# PROVENANCE: this is the script behind ARC job 7721017
# (pilot_benchmark_wer), cited in docs/conditions_audit.md and priced in
# output/evaluation/footprint_report.csv under the "WER (pilot)" category.
# Kept for that reason; new condition checks go through submit_sweep.sh.
#
# Outputs are written under
#   $DATA/speech_transcription_env/output/evaluation/pilot/
# with the stems
#   wer_report_pilot.csv / wer_summary_pilot.json                  (raw)
#   wer_report_pilot_filler_strip.{csv,json}
#   wer_report_pilot_dedup_window.{csv,json}
#   wer_report_pilot_punct_strip.{csv,json}
#   wer_report_pilot_case_fold.{csv,json}
#   wer_report_pilot_whisper_norm.{csv,json}
#
# Usage (submit from the repository root on ARC):
#
#   sbatch hpc/submit_pilot_benchmark.sh
#
# Overrides:
#
#   PILOT_LIMIT=500     sbatch hpc/submit_pilot_benchmark.sh
#   PILOT_MODEL=openai/whisper-medium sbatch hpc/submit_pilot_benchmark.sh
#   PILOT_CONDITIONS=raw,case_fold    sbatch hpc/submit_pilot_benchmark.sh
# =============================================================================

#SBATCH --job-name=pilot_benchmark_wer
#SBATCH --partition=short
#SBATCH --clusters=htc
#SBATCH --time=02:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --gres=gpu:1
#SBATCH --output=logs/pilot_benchmark_wer_%j.out
#SBATCH --error=logs/pilot_benchmark_wer_%j.err

set -euo pipefail

# -----------------------------------------------------------------------------
# Environment and GPU gate (hpc/common/arc_common.sh). Job 7721017 ran the
# earlier version, which pip-installed datasets on a failed import and
# reinstalled torch from the cu121 index when CUDA looked missing; this one
# installs nothing and exits 2 when the preflight fails.
# -----------------------------------------------------------------------------
REPO_DIR="${SLURM_SUBMIT_DIR:-$HOME/paper_speech_transcription}"
# shellcheck source=common/arc_common.sh
source "$REPO_DIR/hpc/common/arc_common.sh" || exit 1
arc_activate "$REPO_DIR" --cuda || exit 1
arc_require_gpu || exit 2

# -----------------------------------------------------------------------------
# Pilot parameters
# -----------------------------------------------------------------------------
MODEL="${PILOT_MODEL:-openai/whisper-large-v3}"
LIMIT="${PILOT_LIMIT:-200}"
DATASET="${PILOT_DATASET:-librispeech_asr}"
CONFIG="${PILOT_CONFIG:-clean}"
SPLIT="${PILOT_SPLIT:-test}"
CONDITIONS="${PILOT_CONDITIONS:-raw,filler_strip,dedup_window,punct_strip,case_fold,whisper_norm}"

REPORT_DIR="${DATA}/speech_transcription_env/output/evaluation/pilot"
mkdir -p "$REPORT_DIR" logs

# Record the software and GPU this run used beside its results.
arc_record_env "$REPORT_DIR"               \
    "PILOT_MODEL=${MODEL}"                 \
    "PILOT_LIMIT=${LIMIT}"                 \
    "PILOT_DATASET=${DATASET}"             \
    "PILOT_CONFIG=${CONFIG}"               \
    "PILOT_SPLIT=${SPLIT}"                 \
    "PILOT_CONDITIONS=${CONDITIONS}"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Pilot benchmark"
echo "  Model:      ${MODEL}"
echo "  Corpus:     ${DATASET} (${CONFIG}/${SPLIT}), first ${LIMIT} utterances"
echo "  Conditions: ${CONDITIONS}"
echo "  Output dir: ${REPORT_DIR}"
echo "  Started:    $(date)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

python -m evaluation.benchmark_wer            \
    --model      "$MODEL"                      \
    --dataset    "$DATASET"                    \
    --config     "$CONFIG"                     \
    --split      "$SPLIT"                      \
    --report     "$REPORT_DIR/wer_report_pilot.csv"   \
    --summary    "$REPORT_DIR/wer_summary_pilot.json" \
    --conditions "$CONDITIONS"                 \
    --seed       42                            \
    --limit      "$LIMIT"

echo ""
echo "✅ Pilot benchmark complete at $(date)"
echo "   Reports under: $REPORT_DIR"
