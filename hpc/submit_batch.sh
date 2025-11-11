#!/bin/bash

# Submit batch transcription jobs with automatic array sizing
# Adapted for Oxford ARC HPC cluster with GPU constraints
# Usage: ./submit_batch.sh [--mask-names] [--model "MODEL_NAME"] [--force-english]

# Default values
MASK_NAMES=""
MODEL_ARG=""
FORCE_ENGLISH=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --mask-names)
            MASK_NAMES="--mask-names"
            shift
            ;;
        --model)
            MODEL_ARG="--model $2"
            shift 2
            ;;
        --force-english)
            FORCE_ENGLISH="--force-english"
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: ./submit_batch.sh [--mask-names] [--model \"MODEL_NAME\"] [--force-english]"
            exit 1
            ;;
    esac
done

# Count audio files in the virtual environment (multiple formats supported)
AUDIO_INPUT_DIR="$DATA/speech_transcription_env/audio_input"
AUDIO_COUNT=$(find "$AUDIO_INPUT_DIR" \( -name "*.wav" -o -name "*.WAV" -o -name "*.mp3" -o -name "*.MP3" -o -name "*.m4a" -o -name "*.M4A" -o -name "*.flac" -o -name "*.FLAC" -o -name "*.ogg" -o -name "*.OGG" -o -name "*.aac" -o -name "*.AAC" \) -type f 2>/dev/null | wc -l)

if [ $AUDIO_COUNT -eq 0 ]; then
    echo "No audio files found in $AUDIO_INPUT_DIR"
    echo "Supported formats: WAV, MP3, M4A, FLAC, OGG, AAC"
    echo "Please copy your audio files to: $AUDIO_INPUT_DIR"
    exit 1
fi

echo "Supported audio formats: WAV, MP3, M4A, FLAC, OGG, AAC"

echo "Found $AUDIO_COUNT audio file(s)"
echo "Submitting batch job with parameters:"
echo "  Mask names: ${MASK_NAMES:-"disabled"}"
echo "  Model: ${MODEL_ARG:-"default (openai/whisper-large-v3)"}"
echo "  Force English: ${FORCE_ENGLISH:-"disabled"}"

# Build arguments string
ARGS="$MASK_NAMES $MODEL_ARG $FORCE_ENGLISH"

# Submit job to ARC HTC cluster with GPU constraints
# Using specific GPU constraints as documented in ARC user guide
echo "Submitting job array with $AUDIO_COUNT tasks..."

# First try with GPU on short partition (12 hour limit due to co-investment GPUs)
JOB_ID=$(sbatch --clusters=htc \
       --array=1-$AUDIO_COUNT \
       --partition=short \
       --time=12:00:00 \
       --mem=16G \
       --cpus-per-task=2 \
       --gres=gpu:1 \
       --output="transcription_%A_%a.out" \
       --error="transcription_%A_%a.err" \
       hpc/batch_transcription.sh $ARGS 2>&1 | grep "Submitted batch job" | awk '{print $NF}')

if [ -z "$JOB_ID" ]; then
    echo "❌ GPU job submission failed. Trying CPU-only on medium partition..."
    JOB_ID=$(sbatch --clusters=htc \
           --array=1-$AUDIO_COUNT \
           --partition=medium \
           --time=23:00:00 \
           --mem=32G \
           --cpus-per-task=4 \
           --output="transcription_%A_%a.out" \
           --error="transcription_%A_%a.err" \
           hpc/batch_transcription.sh $ARGS 2>&1 | grep "Submitted batch job" | awk '{print $NF}')
fi

if [ -n "$JOB_ID" ]; then
    echo "✅ Job submitted successfully to ARC HTC cluster!"
    echo "Job ID: $JOB_ID"
    echo "Resources requested:"
    echo "  - Partition: short (GPU, 12h max) or medium (CPU-only, 48h max)"
    echo "  - Time limit: 12h (GPU) or 23h (CPU-only)"
    echo "  - Memory: 16GB (GPU) or 32GB (CPU-only)"
    echo "  - CPUs: 2 (GPU) or 4 (CPU-only)"
    echo "  - GPU: 1 (if available, limited to 12h due to co-investment nodes)"
    echo "  - Cluster: htc"
    echo ""
    echo "⚠️  Note: Co-investment GPU nodes limited to 12 hours maximum runtime"
    echo ""
    echo "Output files will be named: transcription_${JOB_ID}_<task_id>.out"
    echo "Error files will be named: transcription_${JOB_ID}_<task_id>.err"
    echo ""
    echo "Monitor your job with:"
    echo "  squeue --me --clusters=htc"
    echo "  sacct -j $JOB_ID --format=JobID,JobName,State,ExitCode,Start,End,Elapsed"
    echo ""
    echo "Check logs with:"
    echo "  ls -la transcription_${JOB_ID}_*.out"
    echo "  tail -f transcription_${JOB_ID}_1.out"
else
    echo "❌ All job submission attempts failed!"
    echo "Please check:"
    echo "  1. Cluster access: sinfo --clusters=htc"
    echo "  2. Account permissions: sacctmgr show user $USER"
    echo "  3. Available resources: sinfo --clusters=htc --format='%P %a %l %D %T %N'"
fi
