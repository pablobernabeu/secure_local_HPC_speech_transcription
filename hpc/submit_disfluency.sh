#!/bin/bash
# =============================================================================
# submit_disfluency.sh  —  filler-preservation benchmark on Oxford ARC
#
# Transcribes the AMI test split once, keeps the verbatim hypotheses, and
# scores how many non-lexical fillers each condition preserves.
#
# AMI is the corpus that can answer this. It is spontaneous meeting speech
# transcribed verbatim, so its references record the hesitations that read
# speech corpora either never contain or normalise away.
#
# The retention half of the measurement needs no audio at all and is
# available locally:
#
#   python -m evaluation.disfluency --audit-conditions
#
# What this job adds is the reference-anchored half: of the fillers a human
# transcriber recorded, how many reach the output, which depends on what the
# model actually heard and so needs a real pass over the audio.
#
# Usage (submit from the repository root on ARC):
#
# Account: either project account is valid; the examples use educ-intract.
# Choose by current load, which changes: see the BALANCE note in .hpc-plan.yaml.
#
#   sbatch --account=educ-intract hpc/submit_disfluency.sh
#
#   # A quick pilot over the first 200 utterances
#   WER_LIMIT=200 sbatch --account=educ-intract hpc/submit_disfluency.sh
#
# Overrides (set before sbatch): WER_LIMIT (unset = full split), MODEL
# (openai/whisper-large-v3), REPORT_DIR (default
# $DATA/speech_transcription_env/output/evaluation). MODEL and REPORT_DIR are
# generic names that sbatch passes through from the submitting shell; the
# effective values are echoed at the top of the log.
#
# Outputs in $REPORT_DIR:
#   wer_hypotheses_ami.csv      — one row per (utterance, condition)
#   disfluency_summary.json     — retention and reference recall per condition
#   disfluency_report.csv       — the same table
#
# The committed output/evaluation/disfluency_summary.json and
# disfluency_report.csv no longer come from this job (its last run, 8555165
# on 2026-08-12, decoded AMI separately). They score the AMI dump of the
# audit's Large v3 sweep, so that the filler figures share the sweep's
# decoding; the evaluation.disfluency docstring gives the command. This job
# still decodes a fresh dump for the same measurement. With the default
# REPORT_DIR it overwrites the August 2026 dump and summary on ARC, so set
# REPORT_DIR to a new directory to keep them.
# =============================================================================

#SBATCH --job-name=disfluency
#SBATCH --partition=short
#SBATCH --clusters=htc
#SBATCH --time=12:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --gres=gpu:1
#SBATCH --output=logs/disfluency_%j.out
#SBATCH --error=logs/disfluency_%j.err

set -euo pipefail

echo "FILLER-PRESERVATION BENCHMARK"
echo "============================="
echo "Started: $(date)   Job: ${SLURM_JOB_ID:-n/a}   Node: $(hostname)"

REPO_DIR="${SLURM_SUBMIT_DIR:-$HOME/paper_speech_transcription}"
# shellcheck source=common/arc_common.sh
source "$REPO_DIR/hpc/common/arc_common.sh" || exit 1
arc_activate "$REPO_DIR" --cuda || exit 1

# Fail before any decoding if the environment cannot do the work.
arc_require_gpu || exit 2

REPORT_DIR="${REPORT_DIR:-${DATA}/speech_transcription_env/output/evaluation}"
MODEL="${MODEL:-openai/whisper-large-v3}"
mkdir -p "$REPORT_DIR" logs

LIMIT_ARG=()
if [[ -n "${WER_LIMIT:-}" ]]; then
    LIMIT_ARG=(--limit "$WER_LIMIT")
    echo "Utterance limit: $WER_LIMIT"
fi

DUMP="$REPORT_DIR/wer_hypotheses_ami.csv"

echo ""
echo "Corpus:  AMI test (spontaneous, verbatim references)"
echo "Model:   $MODEL"
echo "Dump:    $DUMP"
echo "Report:  $REPORT_DIR"
echo ""

# Record the software and GPU this run used beside its results.
arc_record_env "$REPORT_DIR"                  \
    "MODEL=${MODEL}"                          \
    "WER_LIMIT=${WER_LIMIT:-(full split)}"    \
    "REPORT_DIR=${REPORT_DIR}"

# raw is the model's own output; pipeline_full is what the workflow ships;
# whisper_norm is the normaliser conventionally used for scoring, included
# because the claim is partly about what that normaliser discards.
python -m evaluation.benchmark_wer                      \
    --suite ami                                         \
    --model "$MODEL"                                    \
    --conditions raw,pipeline_full,whisper_norm         \
    --report  "$REPORT_DIR/wer_report_ami_disfluency.csv"   \
    --summary "$REPORT_DIR/wer_summary_ami_disfluency.json" \
    --dump-hypotheses "$DUMP"                           \
    "${LIMIT_ARG[@]}"

echo ""
echo "--- scoring filler preservation ---"
python -m evaluation.disfluency "$DUMP"                 \
    --json "$REPORT_DIR/disfluency_summary.json"        \
    --csv  "$REPORT_DIR/disfluency_report.csv"

echo ""
echo "Finished: $(date)"
ls -lh "$REPORT_DIR"/disfluency_* "$DUMP" 2>/dev/null || true
