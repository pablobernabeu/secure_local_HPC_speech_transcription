#!/bin/bash

# Simple batch submission script for speech transcription workflow
# Usage: ./submit_batch.sh [--mask-names] [--force-english] [--model MODEL_NAME]

# Navigate to project directory
cd YOUR_PROJECT_DIRECTORY

# Count audio files dynamically
AUDIO_COUNT=$(find audio_input \( -name "*.wav" -o -name "*.WAV" \) -type f | wc -l)

if [ $AUDIO_COUNT -eq 0 ]; then
    echo "Error: No audio files found in audio_input/ directory"
    echo "Please place .wav or .WAV files in the audio_input/ directory"
    exit 1
fi

echo "Found $AUDIO_COUNT audio files for processing"
echo "Submitting SLURM job array with size 1-$AUDIO_COUNT"

# Submit the batch job with all arguments passed through
sbatch --array=1-$AUDIO_COUNT HPC_scripts/batch_transcription.sh "$@"

echo "Job submitted successfully!"
echo "Monitor progress with: squeue --me"
echo "Check logs: tail -f transcription_<job_id>_<task_id>.out"
