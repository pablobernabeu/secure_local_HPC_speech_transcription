#!/bin/bash
# RETIRED (audit findings XREF-01, SHELL-09): kept only as the record of how
# the May 2026 wer_report.csv and wer_summary.json were made (array job
# 7682561), a pair output/evaluation/pilot_may2026/ now keeps (audit finding
# OUTPUTS-03). Task 0 wrote those names, which the manuscript reads, and the
# other stems are the ones evaluation/sweep.py writes, so a re-run would mix
# code versions across the matrix; it refuses to run. Use
# hpc/submit_sweep.sh; see hpc/legacy/README.md. The body below is
# unmaintained: it still carries the in-job `pip install` and torch
# force-reinstall that the live scripts no longer have.
echo "hpc/legacy/submit_benchmark_wer_gpu.sh is retired; use hpc/submit_sweep.sh (hpc/legacy/README.md)." >&2
exit 1
# =============================================================================
# submit_benchmark_wer_gpu.sh  —  unified GPU WER benchmark  (array job)
#
# PROVENANCE (superseded by submit_sweep.sh, kept because it documents how
# the legacy canonical files were made): the May 2026 pair was committed as
# output/evaluation/wer_summary.json and wer_report.csv on 2026-05-19
# (cefaac0) and kept those names until OUTPUTS-03 gave them to the sweep's
# raw cell; output/evaluation/pilot_may2026/ keeps it. The only ARC logs
# matching this script's logs/benchmark_wer_%A_%a.out pattern around then
# are array job 7682561, tasks 0-2 (2026-05-18/19). That job is the most
# likely producer (hpc/legacy/README.md gives the evidence); the logs do
# not record the commit it ran.
#
# Submits one SLURM array task per model (--array=0-2).  Each task runs all
# corpora for its assigned model in sequence, so three tasks can execute in
# parallel on three GPUs.  Each task takes approximately 6–7 h on an L40S,
# well within the short partition's 12 h limit.
#
#   Task 0  openai/whisper-large-v3
#   Task 1  distil-whisper/distil-large-v3
#   Task 2  openai/whisper-medium
#
# Each task covers two sections, both driven by the --conditions flag of
# evaluation/benchmark_wer.py (see evaluation/conditions.py for the registry).
# The benchmark iterates over each corpus once and scores every condition
# in the list on the same hypotheses, so adding conditions costs no extra
# audio passes.
#
#   Section 1  LibriSpeech test-clean  (raw + repetition_fix + whisper_norm)
#
#     raw             unprocessed hypothesis vs. unprocessed reference.
#     repetition_fix  detect_and_fix_repetitions applied to the hypothesis
#                     to suppress Whisper hallucination loops.
#     whisper_norm    Whisper EnglishTextNormalizer({}) applied to both
#                     sides so contractions, punctuation, casing and
#                     numerals are normalised equally.
#
#   Section 2  Challenge suites  (raw + whisper_norm)
#
#     fleurs              647 utterances, diverse speakers
#                         (google/fleurs en_us; CC-BY-4.0)
#     voxpopuli_accented  ~29 h, 15 L2 accent varieties
#                         (facebook/voxpopuli en_accented; CC0)
#     ami                 ~12,600 utterances, spontaneous meetings
#                         (edinburghcstr/ami ihm; CC-BY-4.0)
#
#     repetition_fix is not scored here because hallucination loops are
#     dominated by the LibriSpeech read-speech regime characterised in
#     Section 1.
#
# Outputs written to $DATA/speech_transcription_env/output/evaluation/.  The
# first condition writes to the --report / --summary paths supplied; each
# subsequent condition appends _<condition> to the file stem.  Therefore:
#   wer_report.csv / wer_summary.json                                  task 0 raw (canonical)
#   wer_report_repetition_fix.{csv,json}                               task 0 LibriSpeech repetition_fix
#   wer_report_whisper_norm.{csv,json}                                 task 0 LibriSpeech whisper_norm
#   wer_report_librispeech_{slug}.{csv,json}                           tasks 1-2 LibriSpeech raw
#   wer_report_librispeech_{slug}_{repetition_fix,whisper_norm}.{csv,json}
#   wer_report_{suite}_{slug}.{csv,json}                               raw
#   wer_report_{suite}_{slug}_whisper_norm.{csv,json}                  whisper_norm
#
# Usage (submit from the repository root):
#
#   sbatch hpc/submit_benchmark_wer_gpu.sh                     # all three models in parallel
#   sbatch --array=0   hpc/submit_benchmark_wer_gpu.sh         # large-v3 only
#   sbatch --array=1-2 hpc/submit_benchmark_wer_gpu.sh         # distil + medium only
#   RUN_LIBRISPEECH=false sbatch hpc/submit_benchmark_wer_gpu.sh
#   RUN_CHALLENGE=false   sbatch hpc/submit_benchmark_wer_gpu.sh
#   CHALLENGE_SUITES=ami  sbatch hpc/submit_benchmark_wer_gpu.sh
#   BENCHMARK_LIMIT=200   sbatch hpc/submit_benchmark_wer_gpu.sh
#   LIBRISPEECH_CONDITIONS=raw,whisper_norm sbatch hpc/submit_benchmark_wer_gpu.sh
#   CHALLENGE_CONDITIONS=raw                sbatch hpc/submit_benchmark_wer_gpu.sh
# =============================================================================

#SBATCH --job-name=benchmark_wer
#SBATCH --array=0-2
#SBATCH --partition=short
#SBATCH --clusters=htc
#SBATCH --time=12:00:00
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --gres=gpu:1
#SBATCH --output=logs/benchmark_wer_%A_%a.out
#SBATCH --error=logs/benchmark_wer_%A_%a.err

set -euo pipefail

# -----------------------------------------------------------------------------
module purge
module load Anaconda3 || true
module load CUDA || true   # provides CUDA runtime; safe no-op if not present

REPO_DIR="${SLURM_SUBMIT_DIR:-$HOME/paper_speech_transcription}"
ACTIVATION_SCRIPT="$REPO_DIR/activate_project_env_arc.sh"
if [[ -f "$ACTIVATION_SCRIPT" ]]; then
    # shellcheck source=/dev/null
    source "$ACTIVATION_SCRIPT"
else
    echo "❌ Activation script not found at $ACTIVATION_SCRIPT" >&2
    exit 1
fi

cd "$REPO_DIR"
unset TRANSFORMERS_CACHE

# Print the GPU assigned by SLURM so the log is auditable.
echo "GPU: ${CUDA_VISIBLE_DEVICES:-not set by SLURM}"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || true

# -----------------------------------------------------------------------------
# Ensure required packages are available
# -----------------------------------------------------------------------------
python -c "import datasets" 2>/dev/null \
    || pip install --quiet "datasets>=2.14.0"

# Reinstall PyTorch with CUDA support if the Conda env ships a CPU-only build.
if ! python -c "import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)" 2>/dev/null; then
    echo "PyTorch CUDA not available — reinstalling with CUDA 12.1 wheels..." >&2
    pip uninstall -y torch torchvision torchaudio 2>&1 | tail -n 5 || true
    pip install --force-reinstall --no-cache-dir \
        torch --index-url https://download.pytorch.org/whl/cu121
fi
python -c "import torch; print('CUDA available:', torch.cuda.is_available(), '| device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'n/a', '| torch:', torch.__version__)"
python -c "import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)" || {
    echo "❌ CUDA still unavailable after reinstall; aborting before CPU fallback." >&2
    exit 2
}

# -----------------------------------------------------------------------------
# Shared parameters
# -----------------------------------------------------------------------------
REPORT_DIR="${DATA}/speech_transcription_env/output/evaluation"
mkdir -p "$REPORT_DIR" logs

# Optional utterance limit applied to every corpus when set.
LIMIT="${BENCHMARK_LIMIT:-}"
LIMIT_ARG=()
if [[ -n "$LIMIT" ]]; then
    LIMIT_ARG=(--limit "$LIMIT")
fi

declare -a MODELS=(
    "openai/whisper-large-v3"
    "distil-whisper/distil-large-v3"
    "openai/whisper-medium"
)
declare -a SLUGS=(
    "whisper-large-v3"
    "distil-large-v3"
    "whisper-medium"
)

MODEL="${MODELS[$SLURM_ARRAY_TASK_ID]}"
SLUG="${SLUGS[$SLURM_ARRAY_TASK_ID]}"

echo ""
echo "Array task ${SLURM_ARRAY_TASK_ID} / model: ${MODEL}"
echo ""

# =============================================================================
# Section 1 — LibriSpeech test-clean  (raw + repetition_fix + whisper_norm)
# =============================================================================
if [[ "${RUN_LIBRISPEECH:-true}" == "true" ]]; then

    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Section 1: LibriSpeech test-clean  |  model: ${MODEL}"
    echo "  Started: $(date)"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    DATASET="${BENCHMARK_DATASET:-librispeech_asr}"
    CONFIG="${BENCHMARK_CONFIG:-clean}"
    SPLIT="${BENCHMARK_SPLIT:-test}"
    LS_CONDITIONS="${LIBRISPEECH_CONDITIONS:-raw,repetition_fix,whisper_norm}"

    # Task 0 (whisper-large-v3) writes its primary (raw) output to the
    # canonical paths read by the Quarto manuscript.  All other tasks use
    # descriptive names.  The repetition_fix and whisper_norm artefacts are
    # derived automatically by appending _<condition> to the file stem.
    if [[ "$SLUG" == "whisper-large-v3" ]]; then
        PRIMARY_REPORT="$REPORT_DIR/wer_report.csv"
        PRIMARY_SUMMARY="$REPORT_DIR/wer_summary.json"
    else
        PRIMARY_REPORT="$REPORT_DIR/wer_report_librispeech_${SLUG}.csv"
        PRIMARY_SUMMARY="$REPORT_DIR/wer_summary_librispeech_${SLUG}.json"
    fi

    python -m evaluation.benchmark_wer         \
        --model      "$MODEL"                   \
        --dataset    "$DATASET"                 \
        --config     "$CONFIG"                  \
        --split      "$SPLIT"                   \
        --report     "$PRIMARY_REPORT"          \
        --summary    "$PRIMARY_SUMMARY"         \
        --conditions "$LS_CONDITIONS"           \
        --seed       42                         \
        "${LIMIT_ARG[@]}"

    echo "  ✅ Section 1 complete at $(date)"
    echo ""

fi

# =============================================================================
# Section 2 — Challenge suites  (raw + whisper_norm)
# =============================================================================
if [[ "${RUN_CHALLENGE:-true}" == "true" ]]; then

    IFS=' ' read -ra SUITES <<< "${CHALLENGE_SUITES:-fleurs voxpopuli_accented ami}"
    CHALLENGE_CONDITIONS="${CHALLENGE_CONDITIONS:-raw,whisper_norm}"

    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Section 2: Challenge suites  |  model: ${MODEL}"
    echo "  Suites:     ${SUITES[*]}"
    echo "  Conditions: ${CHALLENGE_CONDITIONS}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    for SUITE in "${SUITES[@]}"; do

        echo ""
        echo "  Suite: ${SUITE}  |  Started: $(date)"

        # Primary (raw) artefact stem: wer_{report,summary}_{suite}_{slug}.
        # The whisper_norm artefacts are auto-derived by appending
        # _whisper_norm to that stem.
        python -m evaluation.benchmark_wer              \
            --suite      "$SUITE"                        \
            --model      "$MODEL"                        \
            --report     "$REPORT_DIR/wer_report_${SUITE}_${SLUG}.csv"   \
            --summary    "$REPORT_DIR/wer_summary_${SUITE}_${SLUG}.json" \
            --conditions "$CHALLENGE_CONDITIONS"         \
            --seed       42                              \
            "${LIMIT_ARG[@]}"

        echo "  ✅ ${SUITE} complete at $(date)"
    done

    echo ""
    echo "  ✅ Section 2 complete at $(date)"
    echo ""

fi

echo "✅ Task ${SLURM_ARRAY_TASK_ID} (${MODEL}) complete at $(date)"
