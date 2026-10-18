#!/bin/bash
# =============================================================================
# submit_benchmark_wer_multilingual.sh
#   Multilingual FLEURS WER benchmark — the non-English counterpart to the
#   English-only sweep.  Each array task scores one FLEURS language split
#   under the raw and pipeline_full conditions, driving Whisper with the
#   matching --language so the decoder is prompted in the right language.
#
# Array index -> (FLEURS config, Whisper language):
#
#   0  fr_fr   french        3  it_it   italian
#   1  de_de   german        4  nl_nl   dutch
#   2  es_419  spanish        5  pl_pl   polish
#
# These six are space-delimited European languages for which word error
# rate is meaningful; CJK splits are deliberately excluded because they
# need character error rate rather than WER.
#
# Outputs (one pair per language, first condition writes the base stem;
# <slug> is the model name after its last "/", lower-cased):
#   $WER_ML_OUTPUT_DIR (default $DATA/speech_transcription_env/output/evaluation)/
#     wer_report_fleurs_<config>_<slug>.csv         (raw)
#     wer_summary_fleurs_<config>_<slug>.json        (raw, records benchmark.language)
#     wer_report_fleurs_<config>_<slug>_pipeline_full.csv
#     wer_summary_fleurs_<config>_<slug>_pipeline_full.json
# A task refuses to start if its summary already exists, unless OVERWRITE=1.
#
# ALWAYS pre-flight before the full array (cheap, one language, five utts),
# into its own directory so it cannot collide with a real run:
#   WER_ML_LIMIT=5 WER_ML_OUTPUT_DIR=$DATA/.../preflight_ml \
#     sbatch --array=0 hpc/submit_benchmark_wer_multilingual.sh
#
# Then the full run, throttled to two concurrent tasks to spare capacity.
# Six tasks is small, so a single account is fine; to share load across
# both project accounts, split the range (standard QoS, never priority):
#   sbatch --account=educ-lift    --array=0-2%2 hpc/submit_benchmark_wer_multilingual.sh
#   sbatch --account=educ-intract --array=3-5%2 hpc/submit_benchmark_wer_multilingual.sh
#
# Overrides (set before sbatch):
#   WER_ML_MODEL=openai/whisper-large-v3   (default)
#   WER_ML_CONDITIONS=raw,pipeline_full    (default)
#   WER_ML_LIMIT=200                       (omit for the full split)
#   WER_ML_OUTPUT_DIR=/path                (default: the evaluation directory)
#   OVERWRITE=1                            (replace an existing summary)
#
# Submit from the repository root on ARC.
# =============================================================================

#SBATCH --job-name=wer_fleurs_ml
#SBATCH --array=0-5%2
#SBATCH --partition=short
#SBATCH --clusters=htc
#SBATCH --time=12:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --gres=gpu:1
#SBATCH --output=logs/wer_fleurs_ml_%A_%a.out
#SBATCH --error=logs/wer_fleurs_ml_%A_%a.err

set -euo pipefail

# ---------------------------------------------------------------------------
# FLEURS config and Whisper language, keyed by array index.
# ---------------------------------------------------------------------------
CONFIGS=(fr_fr de_de es_419 it_it nl_nl pl_pl)
LANGS=(french german spanish italian dutch polish)

IDX="${SLURM_ARRAY_TASK_ID:-0}"
if (( IDX < 0 || IDX >= ${#CONFIGS[@]} )); then
    echo "❌ array index ${IDX} out of range 0-$(( ${#CONFIGS[@]} - 1 ))" >&2
    exit 2
fi
FLEURS_CONFIG="${CONFIGS[$IDX]}"
WHISPER_LANG="${LANGS[$IDX]}"

# ---------------------------------------------------------------------------
# Environment and GPU gate (hpc/common/arc_common.sh): one preflight covers
# torch+CUDA, transformers, audio and where the packages load from. A
# failure exits 2; nothing is installed (the old `pip install datasets` on
# a failed import is gone).
# ---------------------------------------------------------------------------
REPO_DIR="${SLURM_SUBMIT_DIR:-$HOME/paper_speech_transcription}"
# shellcheck source=common/arc_common.sh
source "$REPO_DIR/hpc/common/arc_common.sh" || exit 1
arc_activate "$REPO_DIR" --cuda || exit 1
arc_require_gpu || exit 2

# ---------------------------------------------------------------------------
# Parameters.
# ---------------------------------------------------------------------------
# WER_ML_OUTPUT_DIR keeps a pre-flight or a re-run after a post-processing
# change away from the finished outputs, for the same reason as
# SWEEP_OUTPUT_DIR in submit_sweep.sh: the comparison needs both runs.
REPORT_DIR="${WER_ML_OUTPUT_DIR:-${DATA}/speech_transcription_env/output/evaluation}"
mkdir -p "$REPORT_DIR" logs

MODEL="${WER_ML_MODEL:-openai/whisper-large-v3}"
CONDITIONS="${WER_ML_CONDITIONS:-raw,pipeline_full}"

# The model slug is part of the file names, as in evaluation/sweep.py
# (_model_slug: the last path component, lower-cased), so runs of different
# models never share a file. The three committed arms (see .hpc-plan.yaml)
# predate this and were written as wer_*_fleurs_<config>.* without a slug.
MODEL_SLUG="$(printf '%s' "${MODEL##*/}" | tr '[:upper:]' '[:lower:]')"
REPORT_CSV="${REPORT_DIR}/wer_report_fleurs_${FLEURS_CONFIG}_${MODEL_SLUG}.csv"
SUMMARY_JSON="${REPORT_DIR}/wer_summary_fleurs_${FLEURS_CONFIG}_${MODEL_SLUG}.json"

# Refuse to write over a finished result: an earlier arm's per-language files
# were overwritten in place this way, and only the hand-assembled
# fleurs_multilingual_summary.json kept the comparison.
if [[ -e "$SUMMARY_JSON" && "${OVERWRITE:-0}" != "1" ]]; then
    echo "❌ ${SUMMARY_JSON} already exists." >&2
    echo "   Set WER_ML_OUTPUT_DIR to a new directory, or OVERWRITE=1 to replace it." >&2
    exit 3
fi

LIMIT_ARG=()
if [[ -n "${WER_ML_LIMIT:-}" ]]; then
    LIMIT_ARG=(--limit "${WER_ML_LIMIT}")
fi

# Record the software and GPU this task ran on beside its results.
arc_record_env "$REPORT_DIR"                          \
    "FLEURS_CONFIG=${FLEURS_CONFIG}"                  \
    "WHISPER_LANG=${WHISPER_LANG}"                    \
    "WER_ML_MODEL=${MODEL}"                           \
    "WER_ML_CONDITIONS=${CONDITIONS}"                 \
    "WER_ML_LIMIT=${WER_ML_LIMIT:-(full split)}"      \
    "REPORT_DIR=${REPORT_DIR}"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Multilingual FLEURS  |  task ${IDX}  |  ${FLEURS_CONFIG} (${WHISPER_LANG})"
echo "  Model: ${MODEL}   Conditions: ${CONDITIONS}"
echo "  Output dir: ${REPORT_DIR}"
echo "  Started: $(date)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

python -m evaluation.benchmark_wer \
    --dataset    google/fleurs                                    \
    --config     "${FLEURS_CONFIG}"                               \
    --split      test                                            \
    --language   "${WHISPER_LANG}"                               \
    --ref-field  transcription                                   \
    --uid-field  id                                              \
    --model      "${MODEL}"                                      \
    --conditions "${CONDITIONS}"                                 \
    --seed       42                                              \
    --report     "${REPORT_CSV}"                                 \
    --summary    "${SUMMARY_JSON}"                               \
    "${LIMIT_ARG[@]}"

echo ""
echo "✅ Task ${IDX} (${FLEURS_CONFIG}/${WHISPER_LANG}) complete at $(date)"
echo "   Outputs: ${REPORT_DIR}"
