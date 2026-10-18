#!/bin/bash
# =============================================================================
# batch_transcription.sh  -  one transcription task on Oxford ARC (CPU)
#
# Normally submitted by hpc/submit_transcription.sh, which freezes the list
# of recordings and passes it here. Each array task transcribes one entry of
# that list with transcription.py and writes to output/transcripts/ in the
# repository.
#
# Arguments (all others are passed to transcription.py unchanged):
#   --file-list <path>     NUL-delimited list written at submission; this task
#                          transcribes entry $SLURM_ARRAY_TASK_ID (1-based).
#                          Failed tasks can be retried against the same list,
#                          e.g. sbatch --array=7,23 hpc/batch_transcription.sh
#                          --file-list logs/filelist_<...>.txt <same options>
#   --single-file <path>   transcribe exactly this file
#   --output-name <name>   base name for the output files
#   --mask-names, --force-english, --fix-repetitions
#                          older spellings of --mask-personal-names,
#                          --language english and --fix-spurious-repetitions
#
# Submitted directly with neither --file-list nor --single-file, it falls back
# to listing $DATA/speech_transcription_env/audio_input at run time, which is
# not stable if files change while tasks are queued; prefer the wrapper.
#
# Submit from the repository root (the wrapper does this), so that
# SLURM_SUBMIT_DIR is the repository and the log paths below resolve there.
#
# The job runs on CPU: CUDA_VISIBLE_DEVICES is emptied before Python starts
# and no GPU is requested. Before transcribing it runs `python -m preflight`
# (without --gpu-required) and stops with exit 2 on a FAIL. Slurm's --time is
# the only time limit; there is no internal timeout. The time and memory
# below apply to a direct sbatch; the wrapper overrides them (default
# 08:00:00 and 32G).
# =============================================================================

#SBATCH --job-name=transcription
#SBATCH --output=logs/transcription_%A_%a.out
#SBATCH --error=logs/transcription_%A_%a.err
#SBATCH --clusters=htc
#SBATCH --partition=short
#SBATCH --time=10:00:00
#SBATCH --mem=40G
#SBATCH --cpus-per-task=4

set -euo pipefail

echo "🎤 ARC SPEECH TRANSCRIPTION JOB"
echo "==============================="
echo "Job started at: $(date)"
echo "Running on node: ${SLURM_NODENAME:-$(hostname)}"
echo "Job ID: ${SLURM_JOB_ID:-n/a}"
echo "Task ID: ${SLURM_ARRAY_TASK_ID:-n/a}"
echo "Cluster: ${SLURM_CLUSTER_NAME:-n/a}"
echo ""

# -----------------------------------------------------------------------------
# Arguments. Kept as an array so values with spaces or quotes reach Python
# exactly as given.
# -----------------------------------------------------------------------------
SINGLE_FILE=""
FILE_LIST=""
OUTPUT_NAME=""
TRANSCRIPTION_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --single-file=*|--file-list=*|--output-name=*)
            # Split --flag=value and re-read it, so the =-form is consumed
            # here instead of reaching transcription.py unexamined.
            set -- "${1%%=*}" "${1#*=}" "${@:2}"; continue ;;
        --single-file)  SINGLE_FILE="${2:?--single-file needs a value}"; shift 2 ;;
        --file-list)    FILE_LIST="${2:?--file-list needs a value}"; shift 2 ;;
        --output-name)  OUTPUT_NAME="${2:?--output-name needs a value}"; shift 2 ;;
        --mask-names)   TRANSCRIPTION_ARGS+=(--mask-personal-names); shift ;;
        --force-english) TRANSCRIPTION_ARGS+=(--language english); shift ;;
        --fix-repetitions) TRANSCRIPTION_ARGS+=(--fix-spurious-repetitions); shift ;;
        *)              TRANSCRIPTION_ARGS+=("$1"); shift ;;
    esac
done

echo "🎯 Processing configuration:"
[[ -n "$SINGLE_FILE" ]] && echo "  Single file: $SINGLE_FILE"
[[ -n "$FILE_LIST" ]] && echo "  File list:   $FILE_LIST"
[[ -n "$OUTPUT_NAME" ]] && echo "  Output name: $OUTPUT_NAME"
if [[ ${#TRANSCRIPTION_ARGS[@]} -gt 0 ]]; then
    printf '  Options:    '
    printf ' [%s]' "${TRANSCRIPTION_ARGS[@]}"
    printf '\n'
fi
echo ""

# -----------------------------------------------------------------------------
# Environment
# -----------------------------------------------------------------------------
echo "🔧 STEP 1: Setting up environment..."
# The repository is where sbatch was run from. The clone directory can have
# any name, so it is not hard-coded.
REPO_DIR="${SLURM_SUBMIT_DIR:-$(pwd)}"
if [[ ! -f "$REPO_DIR/transcription.py" ]]; then
    echo "   ❌ transcription.py not found in $REPO_DIR" >&2
    echo "   💡 Submit from the repository root (hpc/submit_transcription.sh does)." >&2
    exit 1
fi
# Modules, activation and the move into the repository are shared with every
# job (hpc/common/arc_common.sh). CUDA is deliberately not loaded: the job
# runs CPU-only. FFmpeg is loaded for M4A, MP3 and the other compressed
# formats. Model weights come from the HF_HOME the activation script sets;
# the helper unsets the deprecated TRANSFORMERS_CACHE, which would override it.
# shellcheck source=common/arc_common.sh
source "$REPO_DIR/hpc/common/arc_common.sh" || exit 1
arc_activate "$REPO_DIR" --module FFmpeg || exit 1
echo "   📂 Working directory: $REPO_DIR"
echo "   🐍 Python: $(python --version 2>&1)"

# -----------------------------------------------------------------------------
# Choose the recording
# -----------------------------------------------------------------------------
echo ""
echo "🔍 STEP 2: Selecting the recording..."
if [[ -n "$SINGLE_FILE" ]]; then
    AUDIO_FILE="$SINGLE_FILE"
else
    if [[ -z "${SLURM_ARRAY_TASK_ID:-}" ]]; then
        echo "   ❌ Neither --single-file nor an array task: nothing to select." >&2
        exit 1
    fi
    if [[ -n "$FILE_LIST" ]]; then
        if [[ ! -f "$FILE_LIST" ]]; then
            echo "   ❌ File list not found: $FILE_LIST" >&2
            exit 1
        fi
        mapfile -d '' -t audio_files < "$FILE_LIST"
        # The array was sized from this list at submission, so its highest
        # index can be no larger than the list; a larger one means the job
        # and the list do not belong together. The task count is not
        # compared: a retry of failed tasks against the same list
        # (sbatch --array=7,23 ... --file-list <same list>) has fewer tasks
        # but the same index-to-file mapping, which is why the list is kept
        # (audit finding SHELL-R2).
        if [[ "${SLURM_ARRAY_TASK_MAX:-}" =~ ^[0-9]+$ ]] \
              && (( SLURM_ARRAY_TASK_MAX > ${#audio_files[@]} )); then
            echo "   ❌ The array reaches task ${SLURM_ARRAY_TASK_MAX} but $FILE_LIST lists only ${#audio_files[@]} files." >&2
            exit 1
        fi
    else
        AUDIO_INPUT_DIR="${DATA:?DATA is not set}/speech_transcription_env/audio_input"
        echo "   ⚠️  No --file-list: listing $AUDIO_INPUT_DIR now, which is only safe if it does not change while tasks are queued."
        mapfile -d '' -t audio_files < <(find "$AUDIO_INPUT_DIR" -type f \( -iname "*.wav" \
            -o -iname "*.mp3" -o -iname "*.m4a" -o -iname "*.flac" -o -iname "*.ogg" \
            -o -iname "*.aac" \) -print0 | LC_ALL=C sort -z)
    fi
    TASK_INDEX=$((SLURM_ARRAY_TASK_ID - 1))
    if (( TASK_INDEX < 0 || TASK_INDEX >= ${#audio_files[@]} )); then
        echo "   ❌ Task $SLURM_ARRAY_TASK_ID is outside the ${#audio_files[@]} listed files" >&2
        exit 1
    fi
    AUDIO_FILE="${audio_files[$TASK_INDEX]}"
    echo "   📁 Task $SLURM_ARRAY_TASK_ID/${#audio_files[@]}"
fi

if [[ ! -f "$AUDIO_FILE" ]]; then
    echo "   ❌ Audio file not found: $AUDIO_FILE" >&2
    exit 1
fi
echo "   🎵 $(basename "$AUDIO_FILE") (${AUDIO_FILE##*.}, $(du -h "$AUDIO_FILE" | cut -f1))"

if [[ -n "$OUTPUT_NAME" ]]; then
    TRANSCRIPTION_ARGS+=(--output-name "$OUTPUT_NAME")
    BASE_NAME="$OUTPUT_NAME"
else
    BASE_NAME="$(basename "$AUDIO_FILE")"
    BASE_NAME="${BASE_NAME%.*}"
fi

# -----------------------------------------------------------------------------
# Transcribe
# -----------------------------------------------------------------------------
echo ""
echo "🎤 STEP 3: Running speech transcription (CPU)..."
printf '   Command: python -u transcription.py %q' "$AUDIO_FILE"
if [[ ${#TRANSCRIPTION_ARGS[@]} -gt 0 ]]; then
    printf ' %q' "${TRANSCRIPTION_ARGS[@]}"
fi
printf '\n\n'

# Keep Python off any GPU the node may have: the environment is used here
# with CPU PyTorch for stability.
export CUDA_VISIBLE_DEVICES=""
export PYTORCH_CUDA_ALLOC_CONF=""
export TORCH_DEVICE="cpu"
export PYTHONUNBUFFERED=1

# The CPU preflight, run with the GPU already hidden so it checks the job as
# it will run: a FAIL (no torch, transformers below its floor, a package
# loaded from outside the environment) stops the task with exit 2 in
# seconds instead of partway through a long recording. A missing GPU is only
# a warning here, since none is wanted.
arc_preflight || exit 2

# No in-script timeout: Slurm enforces the --time the task was granted and
# records TIMEOUT itself. A fixed timeout here used to cut 8-10 h allocations
# to 3 h.
TRANSCRIPTION_EXIT_CODE=0
python -u transcription.py "$AUDIO_FILE" "${TRANSCRIPTION_ARGS[@]}" 2>&1 \
    || TRANSCRIPTION_EXIT_CODE=$?

echo ""
echo "📊 TRANSCRIPTION RESULTS"
echo "========================"
if [[ $TRANSCRIPTION_EXIT_CODE -eq 0 ]]; then
    echo "✅ SUCCESS: Transcription completed"
    echo "   📄 Output files in $REPO_DIR/output/transcripts/:"
    shopt -s nullglob
    outputs=(output/transcripts/"${BASE_NAME}"_*)
    shopt -u nullglob
    if [[ ${#outputs[@]} -eq 0 ]]; then
        echo "      (none found for ${BASE_NAME}_*)"
    else
        for f in "${outputs[@]}"; do
            echo "      • $(basename "$f") ($(du -h "$f" | cut -f1))"
        done
    fi
else
    echo "❌ FAILURE: Transcription failed with exit code $TRANSCRIPTION_EXIT_CODE"
fi

echo ""
echo "🏁 JOB SUMMARY"
echo "=============="
echo "Job completed at: $(date)"
echo "File processed: $(basename "$AUDIO_FILE")"
echo "Exit code: $TRANSCRIPTION_EXIT_CODE"
echo "Job ID: ${SLURM_JOB_ID:-n/a}   Task ID: ${SLURM_ARRAY_TASK_ID:-n/a}"

exit "$TRANSCRIPTION_EXIT_CODE"
