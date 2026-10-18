#!/bin/bash
# =============================================================================
# submit_sweep.sh  —  Full cross-suite × cross-condition WER benchmark sweep
#
# Submits a SLURM array job where each task runs one suite against all
# selected conditions for a single ASR model, using
# evaluation/sweep.py.  Conditions are scored in a single audio pass per
# suite, so adding conditions costs no extra transcription time.
#
# Suite indices (--array=0-4):
#
#   0  librispeech_clean    librispeech_asr clean/test           ~2,620 utts
#   1  ami                  edinburghcstr/ami ihm/test           ~12,600 utts
#   2  fleurs               google/fleurs en_us/test                 647 utts
#   3  librispeech_other    librispeech_asr other/test           ~2,939 utts
#   4  voxpopuli_accented   facebook/voxpopuli en_accented/test  ~9,000 utts
#
# (Indices 1-4 follow the alphabetical order used by evaluation/sweep.py,
# which calls challenge_suites.list_suites() — sorted by name.  Check
# the current index table with:
#   python -m evaluation.sweep --list-suites)
#
# Default conditions: evaluation.conditions.default_sweep_conditions(), which
# builds the list from transcription.CLEAN_TEXT_STAGES, so every suite
# yields one summary per default condition per model. The list is not
# repeated here because a copy drifts; the registry of every available
# condition is printed by
#   python -m evaluation.sweep --list-conditions
#
# Override examples (set before sbatch):
#
#   SWEEP_MODEL=openai/whisper-medium       sbatch hpc/submit_sweep.sh
#   SWEEP_CONDITIONS=raw,whisper_norm       sbatch hpc/submit_sweep.sh
#   SWEEP_LIMIT=500                         sbatch hpc/submit_sweep.sh
#   DUMP_HYPOTHESES=1                       sbatch hpc/submit_sweep.sh
#   SWEEP_OUTPUT_DIR=$DATA/.../preflight    sbatch hpc/submit_sweep.sh
#   sbatch --array=0     hpc/submit_sweep.sh   # LibriSpeech only
#   sbatch --array=1-4   hpc/submit_sweep.sh   # challenge suites only
#   sbatch --array=4     hpc/submit_sweep.sh   # voxpopuli_accented only
#
# GPU type: the #SBATCH line below takes any GPU. The committed matrix ran
# Large v3 on Tesla V100-PCIE-32GB (8917985) and Medium and distil-large-v3
# on NVIDIA L40S (8917986, 8917987), as the summaries record, the same
# cards as the post-fix sweep before it (8688725, 8708134, 8708135). To repeat a
# model on the same card, name it on the command line, which overrides the
# #SBATCH line:
#   SWEEP_OUTPUT_DIR=... sbatch --gres=gpu:v100:1 hpc/submit_sweep.sh
#   SWEEP_OUTPUT_DIR=... SWEEP_MODEL=openai/whisper-medium \
#     sbatch --gres=gpu:l40s:1 hpc/submit_sweep.sh
#
# Outputs are written to $SWEEP_OUTPUT_DIR, by default
#   $DATA/speech_transcription_env/output/evaluation/
# under names qualified by suite and model slug for every cell, so no cell
# writes the bare wer_report.csv or wer_summary.json (evaluation/sweep.py's
# --legacy-primary-paths restores those for Large v3 on LibriSpeech clean;
# this script never passes it). A pre-flight still writes exactly the names
# of a full run, so a task with SWEEP_LIMIT set refuses to start (exit 3)
# unless SWEEP_OUTPUT_DIR is set too, and a ten-utterance check cannot
# overwrite a finished sweep (audit finding XREF-01).
#
# The environment is checked, never repaired: a task whose preflight fails
# (no CUDA device, a floor unmet, a package loaded from outside the
# environment) exits 2 before any decoding.
#
# After all tasks complete, aggregate the same directory:
#   SWEEP_DIR=<the SWEEP_OUTPUT_DIR used> sbatch hpc/aggregate_sweep.sh
#
# Or aggregate with dependency on this job:
#   JID=$(SWEEP_OUTPUT_DIR=$OUT sbatch --parsable hpc/submit_sweep.sh)
#   SWEEP_DIR=$OUT sbatch --dependency=afterok:${JID%%;*} hpc/aggregate_sweep.sh
#
# Usage (submit from the repository root on ARC):
#   sbatch hpc/submit_sweep.sh
# =============================================================================

#SBATCH --job-name=wer_sweep
#SBATCH --array=0-4
#SBATCH --partition=short
#SBATCH --clusters=htc
#SBATCH --time=12:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --gres=gpu:1
#SBATCH --output=logs/wer_sweep_%A_%a.out
#SBATCH --error=logs/wer_sweep_%A_%a.err

set -euo pipefail

# ---------------------------------------------------------------------------
# Environment and GPU gate (hpc/common/arc_common.sh). A preflight failure
# stops the task with exit 2; nothing is installed or reinstalled here.
# ---------------------------------------------------------------------------
REPO_DIR="${SLURM_SUBMIT_DIR:-$HOME/paper_speech_transcription}"
# shellcheck source=common/arc_common.sh
source "$REPO_DIR/hpc/common/arc_common.sh" || exit 1
arc_activate "$REPO_DIR" --cuda || exit 1
arc_require_gpu || exit 2

# ---------------------------------------------------------------------------
# Sweep parameters
# ---------------------------------------------------------------------------
# SWEEP_OUTPUT_DIR redirects the run somewhere other than the canonical
# results directory.  A pre-flight writes to the same filenames as a real
# run, so without this a ten-utterance check silently overwrites a
# completed sweep; and a re-run after a pipeline change wants to sit
# beside its predecessor rather than on top of it, so the two can be
# compared instead of one being taken on trust.
REPORT_DIR="${SWEEP_OUTPUT_DIR:-${DATA}/speech_transcription_env/output/evaluation}"
if [[ -n "${SWEEP_LIMIT:-}" && -z "${SWEEP_OUTPUT_DIR:-}" ]]; then
    echo "❌ SWEEP_LIMIT=${SWEEP_LIMIT} without SWEEP_OUTPUT_DIR would write a partial" >&2
    echo "   sweep over the full-run files in ${REPORT_DIR}." >&2
    echo "   Set SWEEP_OUTPUT_DIR to a directory of its own." >&2
    exit 3
fi
mkdir -p "$REPORT_DIR" logs

MODEL="${SWEEP_MODEL:-openai/whisper-large-v3}"

# An explicit SWEEP_CONDITIONS value overrides the per-suite defaults
# baked into evaluation/sweep.py.  Leave unset to use those defaults.
CONDITIONS_ARG=()
if [[ -n "${SWEEP_CONDITIONS:-}" ]]; then
    CONDITIONS_ARG=(--conditions "$SWEEP_CONDITIONS")
fi

LIMIT_ARG=()
if [[ -n "${SWEEP_LIMIT:-}" ]]; then
    LIMIT_ARG=(--limit "$SWEEP_LIMIT")
fi

# DUMP_HYPOTHESES=1 also writes the reference and the raw and transformed
# hypothesis for every (utterance, condition) pair.  The decode is the part
# that needs a GPU; a condition is a pure function of the text it produces.
# Dumping once therefore makes every later rescoring a processor job, which
# is what a change to any post-processing stage requires.  Off by default,
# because the dump holds transcript text.
DUMP_ARG=()
if [[ -n "${DUMP_HYPOTHESES:-}" ]]; then
    DUMP_ARG=(--dump-hypotheses)
fi

# Record the software and GPU this task ran on beside its results.
arc_record_env "$REPORT_DIR"                             \
    "SWEEP_MODEL=${MODEL}"                                 \
    "SUITE_INDEX=${SLURM_ARRAY_TASK_ID:-}"                 \
    "SWEEP_CONDITIONS=${SWEEP_CONDITIONS:-(sweep.py defaults)}" \
    "SWEEP_LIMIT=${SWEEP_LIMIT:-(full split)}"             \
    "DUMP_HYPOTHESES=${DUMP_HYPOTHESES:-}"                 \
    "REPORT_DIR=${REPORT_DIR}"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  WER sweep  |  array task ${SLURM_ARRAY_TASK_ID}  |  model: ${MODEL}"
echo "  Output dir: ${REPORT_DIR}"
echo "  Started:    $(date)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

python -m evaluation.sweep \
    --suite-index "${SLURM_ARRAY_TASK_ID}" \
    --model       "${MODEL}"               \
    --output-dir  "${REPORT_DIR}"          \
    --seed        42                       \
    "${CONDITIONS_ARG[@]}"                 \
    "${LIMIT_ARG[@]}"                      \
    "${DUMP_ARG[@]}"

echo ""
echo "✅ Task ${SLURM_ARRAY_TASK_ID} complete at $(date)"
echo "   Outputs: ${REPORT_DIR}"
