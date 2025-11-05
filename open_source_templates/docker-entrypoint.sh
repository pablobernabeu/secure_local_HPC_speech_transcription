#!/bin/bash

# Docker entrypoint script for speech transcription

echo "ÌæôÔ∏è  Speech Transcription Container Starting..."
echo "Arguments passed: $@"

# Check if audio_input directory has files
if [ -z "$(ls -A /app/audio_input 2>/dev/null)" ]; then
    echo "‚ö†Ô∏è  No audio files found in /app/audio_input"
    echo "   Mount your audio directory with: -v /path/to/audio:/app/audio_input"
    echo "   Supported formats: .wav, .WAV"
fi

# Check if output directory is mounted
if [ ! -w "/app/output" ]; then
    echo "‚ÑπÔ∏è  Output will be saved inside container at /app/output"
    echo "   Mount output directory with: -v /path/to/output:/app/output"
fi

# Default behavior: process all files in audio_input if no specific file given
if [ $# -eq 0 ]; then
    echo "Ì Processing all audio files in /app/audio_input..."
    for audio_file in /app/audio_input/*.[Ww][Aa][Vv]; do
        [ -f "$audio_file" ] || continue
        echo "¥ÑÌ Processing: $(basename "$audio_file")"
        python3 transcription.py "$audio_file" --mask-names --force-english
    done
else
    # Run with provided arguments
    echo "≥ÅÌ Running: python3 transcription.py $@"
    python3 transcription.py "$@"
fi

echo "∫Ä‚úÖ Processing complete!"
