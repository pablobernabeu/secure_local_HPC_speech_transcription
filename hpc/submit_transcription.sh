#!/bin/bash
# =============================================================================
# submit_transcription.sh  -  submit transcription jobs to Oxford ARC
#
# Counts the recordings to transcribe, freezes that list, and submits one
# array task per recording (or a single job for one file) running
# hpc/batch_transcription.sh. Run it on the login node; it only submits.
#
# Usage (from anywhere; the script finds the repository root itself):
#
#   # Batch mode: every recording in the input directory
#   hpc/submit_transcription.sh --language english --mask-personal-names
#
#   # Single file
#   hpc/submit_transcription.sh --single-file audio_input/myfile.wav \
#       --output-name "interview_2024" --mask-personal-names
#
# Input directory (batch mode): $TRANSCRIPTION_AUDIO_DIR if set, otherwise
# $DATA/speech_transcription_env/audio_input, which is where
# ARC_USAGE_GUIDE.md tells users to copy recordings and where the worker has
# always looked. The sorted file list is written to
# logs/filelist_<timestamp>_<pid>.txt at submission and each array task reads
# its entry from that frozen list, so adding or removing recordings while
# tasks are queued cannot shift which file a task transcribes. The list names
# every recording, which may identify participants, so it is written
# owner-only and .gitignore's logs/* rule keeps it out of commits.
#
# HPC-specific options:
#   --single-file <path>     transcribe exactly this file
#   --output-name <name>     base name for the output files
#   --time-limit HH:MM:SS    wall-clock limit per task (default 08:00:00)
#   --memory <size>          memory per task (default 32G)
#
# Every other option is passed to transcription.py unchanged, so it accepts
# the same options as `python transcription.py --help` (VALID_ARGS below;
# tests/test_audit_shell_transcription_wrapper.py keeps the two in step).
#
# The worker runs on CPU (it sets CUDA_VISIBLE_DEVICES="" for stability), so
# no GPU is requested. An earlier version probed sinfo for GPUs and printed
# "GPU-accelerated" without ever requesting one, and treated the
# cluster-qualified job ID ("<id>;htc") as a failure and submitted a second,
# duplicate array.
# =============================================================================

set -euo pipefail

echo "🎤 SUBMIT TRANSCRIPTION JOBS"
echo "============================"

# The repository root is the parent of this script's directory. sbatch is run
# from there, so SLURM_SUBMIT_DIR in the worker is the repository root and
# the worker's relative log paths (logs/...) resolve where this script
# creates them, whatever the clone directory is called.
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOGS_DIR="$REPO_DIR/logs"

# Options this wrapper accepts. The HPC-only ones are consumed here; every
# other one is forwarded to transcription.py, whose argparse defines them.
HPC_ARGS=(
    "--single-file"
    "--output-name"
    "--time-limit"
    "--memory"
)
VALID_ARGS=(
    "${HPC_ARGS[@]}"
    "--model"
    "--language"
    "--original-filename"
    "--enhance-audio"
    "--mask-personal-names"
    "--fix-spurious-repetitions"
    "--save-name-masking-logs"
    "--save-enhanced-audio"
    "--use-facebook-names-for-masking"
    "--use-facebook-surnames-for-masking"
    "--languages-for-name-masking"
    "--exclude-common-english-words-from-name-masking"
    "--no-exclude-common-english-words-from-name-masking"
    "--exclude-names-from-masking"
    "--exclude-names-file"
    "--speaker-attribution"
    "--diarization-model-path"
    "--diarisation-model-path"
    "--diarization-config"
    "--diarisation-config"
    "--vad-onset"
    "--vad-onset-threshold"
    "--vad-offset"
    "--vad-offset-threshold"
    "--num-speakers"
    "--min-speakers"
    "--max-speakers"
    "--timestamps"
    "--redacted-timestamps-only"
    "--source-audio"
    "--source-derivation"
    "--review-flag-zero-duration"
    "--review-repeated-passage-words"
    "--review-repeated-passage-window"
    "-h"
    "--help"
)

is_valid_arg() {
    local flag="${1%%=*}"   # accept --flag=value as well as --flag value
    local valid
    for valid in "${VALID_ARGS[@]}"; do
        if [[ "$flag" == "$valid" ]]; then
            return 0
        fi
    done
    return 1
}

usage() {
    cat <<'EOF'
Usage: hpc/submit_transcription.sh [options]

HPC-specific options:
  --single-file <path>       Transcribe exactly this file (otherwise: batch mode)
  --output-name <name>       Base name for output files (single-file mode)
  --time-limit HH:MM:SS      Wall-clock limit per task (default: 08:00:00)
  --memory <size>            Memory per task (default: 32G), e.g. 16G, 64G

Batch mode reads $TRANSCRIPTION_AUDIO_DIR, or by default
$DATA/speech_transcription_env/audio_input.

Every other option is passed to transcription.py unchanged; see
`python transcription.py --help`. Common ones:
  --model <model>                     HuggingFace model ID
  --language <lang>                   Transcription language (english, spanish, ...)
  --mask-personal-names               Enable name masking
  --speaker-attribution               Enable speaker diarisation
  --num-speakers N                    Exact speaker count, with --speaker-attribution
  --diarization-model-path <path>     Local pyannote pipeline (offline use)
  --timestamps                        Write timestamped .json/.vtt as well
  --exclude-names-from-masking "A, B" Names to leave unmasked

Examples:
  hpc/submit_transcription.sh --mask-personal-names --language english
  hpc/submit_transcription.sh --single-file audio_input/file.wav --time-limit 04:00:00 --memory 64G
EOF
}

# -----------------------------------------------------------------------------
# Parse arguments. Values are kept as separate array elements end to end, so
# a value containing spaces, commas or quotes reaches Python exactly as typed
# and is never re-parsed by the shell.
# -----------------------------------------------------------------------------
SINGLE_FILE=""
OUTPUT_NAME=""
TIME_LIMIT=""
MEMORY=""
TRANSCRIPTION_ARGS=()

need_value() {  # need_value <flag> <remaining arg count>
    if [[ "$2" -lt 2 ]]; then
        echo "❌ ERROR: $1 needs a value" >&2
        exit 1
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --single-file)
            need_value "$1" $#; SINGLE_FILE="$2"; shift 2 ;;
        --output-name)
            need_value "$1" $#; OUTPUT_NAME="$2"; shift 2 ;;
        --time-limit)
            need_value "$1" $#; TIME_LIMIT="$2"; shift 2 ;;
        --memory)
            need_value "$1" $#; MEMORY="$2"; shift 2 ;;
        -h|--help)
            usage
            exit 0
            ;;
        --single-file=*|--output-name=*|--time-limit=*|--memory=*)
            # Split --flag=value and re-read it. Without this the =-form fell
            # through to the forwarding arm below: it bypassed the batch-mode
            # --output-name check, so every array task wrote the same output
            # name, and --time-limit/--memory never reached sbatch.
            if [[ -z "${1#*=}" ]]; then
                echo "❌ ERROR: ${1%%=*} needs a value" >&2
                exit 1
            fi
            set -- "${1%%=*}" "${1#*=}" "${@:2}"
            continue
            ;;
        --*)
            if ! is_valid_arg "$1"; then
                echo "❌ ERROR: Unknown argument: $1" >&2
                echo "" >&2
                echo "Valid arguments are:" >&2
                printf '  %s\n' "${VALID_ARGS[@]}" >&2
                echo "" >&2
                echo "Run 'hpc/submit_transcription.sh --help' for usage information." >&2
                exit 1
            fi
            TRANSCRIPTION_ARGS+=("$1")
            shift
            ;;
        *)
            # A value for the preceding transcription.py option
            # (e.g. the 2 in --num-speakers 2).
            TRANSCRIPTION_ARGS+=("$1")
            shift
            ;;
    esac
done

mkdir -p "$LOGS_DIR"

# Arguments for the worker: the HPC-only ones it needs, then everything for
# transcription.py.
WORKER_ARGS=()
if [[ -n "$OUTPUT_NAME" ]]; then
    WORKER_ARGS+=(--output-name "$OUTPUT_NAME")
fi

# -----------------------------------------------------------------------------
# Decide what to transcribe
# -----------------------------------------------------------------------------
if [[ -n "$SINGLE_FILE" ]]; then
    echo "📄 SINGLE FILE MODE"
    if [[ ! -f "$SINGLE_FILE" ]]; then
        echo "❌ ERROR: Specified file not found: $SINGLE_FILE" >&2
        exit 1
    fi
    case "${SINGLE_FILE,,}" in
        *.wav|*.mp3|*.m4a|*.flac|*.ogg|*.aac) ;;
        *)
            echo "❌ ERROR: Unsupported audio format: $SINGLE_FILE" >&2
            echo "Supported formats: WAV, MP3, M4A, FLAC, OGG, AAC" >&2
            exit 1
            ;;
    esac
    # Resolved now, relative to where the user ran this, because the job
    # runs from the repository root.
    SINGLE_FILE="$(cd "$(dirname "$SINGLE_FILE")" && pwd)/$(basename "$SINGLE_FILE")"
    echo "✅ File: $SINGLE_FILE ($(du -h "$SINGLE_FILE" | cut -f1))"
    AUDIO_COUNT=1
    BATCH_MODE=false
    WORKER_ARGS+=(--single-file "$SINGLE_FILE")
else
    echo "📁 BATCH MODE"
    if [[ -n "$OUTPUT_NAME" ]]; then
        echo "❌ ERROR: --output-name applies to one file; use it with --single-file" >&2
        exit 1
    fi
    if [[ -n "${TRANSCRIPTION_AUDIO_DIR:-}" ]]; then
        AUDIO_INPUT_DIR="$TRANSCRIPTION_AUDIO_DIR"
    elif [[ -n "${DATA:-}" ]]; then
        AUDIO_INPUT_DIR="$DATA/speech_transcription_env/audio_input"
    else
        echo "❌ ERROR: \$DATA is not set, so there is no default input directory." >&2
        echo "   Set TRANSCRIPTION_AUDIO_DIR to the directory holding the recordings." >&2
        exit 1
    fi
    if [[ ! -d "$AUDIO_INPUT_DIR" ]]; then
        echo "❌ ERROR: Audio input directory not found: $AUDIO_INPUT_DIR" >&2
        echo "   Copy recordings there, or set TRANSCRIPTION_AUDIO_DIR." >&2
        exit 1
    fi
    AUDIO_INPUT_DIR="$(cd "$AUDIO_INPUT_DIR" && pwd)"

    # Freeze the list now. NUL-delimited, so any file name survives, and
    # case-insensitive, so Interview.Wav is counted and processed alike.
    # Owner-only (umask 077 in a subshell), because the recording names can
    # identify participants and logs/ is often group-readable.
    FILE_LIST="$LOGS_DIR/filelist_$(date +%Y%m%d_%H%M%S)_$$.txt"
    (
        umask 077
        find "$AUDIO_INPUT_DIR" -type f \( -iname "*.wav" -o -iname "*.mp3" \
            -o -iname "*.m4a" -o -iname "*.flac" -o -iname "*.ogg" -o -iname "*.aac" \) \
            -print0 | LC_ALL=C sort -z > "$FILE_LIST"
    )
    AUDIO_COUNT="$(tr -cd '\0' < "$FILE_LIST" | wc -c | tr -d ' ')"

    if [[ "$AUDIO_COUNT" -eq 0 ]]; then
        rm -f "$FILE_LIST"
        echo "❌ ERROR: No audio files found in $AUDIO_INPUT_DIR" >&2
        echo "Supported formats: WAV, MP3, M4A, FLAC, OGG, AAC" >&2
        exit 1
    fi
    echo "✅ Found $AUDIO_COUNT audio files in $AUDIO_INPUT_DIR"
    echo "   Frozen list: $FILE_LIST"
    echo ""
    echo "📄 Files to be processed (array task: file):"
    tr '\0' '\n' < "$FILE_LIST" | nl
    BATCH_MODE=true
    WORKER_ARGS+=(--file-list "$FILE_LIST")
fi

WORKER_ARGS+=("${TRANSCRIPTION_ARGS[@]}")

TIME="${TIME_LIMIT:-08:00:00}"
MEM="${MEMORY:-32G}"

echo ""
echo "⚙️  Job configuration:"
if [[ "$BATCH_MODE" == true ]]; then
    echo "   Array range: 1-$AUDIO_COUNT"
fi
echo "   Time limit:  $TIME per task"
echo "   Memory:      $MEM per task"
echo "   Device:      CPU (the worker does not use a GPU)"
if [[ ${#TRANSCRIPTION_ARGS[@]} -gt 0 ]]; then
    printf '   Options:    '
    printf ' [%s]' "${TRANSCRIPTION_ARGS[@]}"
    printf '\n'
else
    echo "   Options:     none (basic transcription)"
fi

# -----------------------------------------------------------------------------
# Submit. No eval: the argument array is passed to sbatch as is.
# -----------------------------------------------------------------------------
SBATCH_ARGS=(--time="$TIME" --mem="$MEM" --parsable)
if [[ "$BATCH_MODE" == true ]]; then
    SBATCH_ARGS+=(--array="1-$AUDIO_COUNT")
fi

echo ""
echo "🚀 Submitting..."
cd "$REPO_DIR"
SUBMIT_RC=0
SUBMIT_OUT="$(sbatch "${SBATCH_ARGS[@]}" hpc/batch_transcription.sh "${WORKER_ARGS[@]}" 2>&1)" \
    || SUBMIT_RC=$?

# --parsable prints "<jobid>" or, with --clusters, "<jobid>;<cluster>".
JOB_ID_NUM="${SUBMIT_OUT%%;*}"
if [[ $SUBMIT_RC -ne 0 || ! "$JOB_ID_NUM" =~ ^[0-9]+$ ]]; then
    echo "❌ Failed to submit job (sbatch exit $SUBMIT_RC)" >&2
    echo "   sbatch said: $SUBMIT_OUT" >&2
    echo "" >&2
    echo "💡 Troubleshooting:" >&2
    echo "   - Check SLURM configuration: sacctmgr show qos" >&2
    echo "   - Try manual submission: sbatch hpc/batch_transcription.sh --single-file <file>" >&2
    exit 1
fi

if [[ "$BATCH_MODE" == true ]]; then
    echo "✅ Job array submitted: $JOB_ID_NUM (tasks 1-$AUDIO_COUNT)"
else
    echo "✅ Job submitted: $JOB_ID_NUM ($(basename "$SINGLE_FILE"))"
fi
# The worker logs to logs/transcription_%A_%a.out; for a job that is not an
# array Slurm fills %a with a placeholder number, hence the wildcard.
LOG_FILES="transcription_${JOB_ID_NUM}_*.out"
echo ""
echo "📊 Monitor:"
echo "   squeue -M htc -u \$USER -j $JOB_ID_NUM"
echo "   tail -f $LOGS_DIR/$LOG_FILES"
echo ""
echo "📁 Results will be saved under $REPO_DIR/output/transcripts/ as"
if [[ -n "$OUTPUT_NAME" ]]; then
    echo "   ${OUTPUT_NAME}_transcript.txt / .docx"
else
    echo "   <recording name>_transcript.txt / .docx"
fi
