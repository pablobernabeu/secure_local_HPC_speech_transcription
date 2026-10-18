#!/bin/bash
# =============================================================================
# docker-entrypoint.sh  -  entry point of the image built from setup/Dockerfile
#
# With no arguments, transcribes every recording in /app/audio_input (WAV,
# MP3, M4A, FLAC, OGG and AAC, any letter case) with name masking and English
# as the language. With arguments, runs `transcription.py <arguments>` once.
#
# Exits non-zero if any transcription fails, if there is nothing to
# transcribe, or if the provenance, review-flag or audio modules cannot be
# imported. transcription.py only prints a warning when those imports fail
# and then succeeds without writing the run manifest or review flags, so the
# check here is what makes a broken image fail loudly.
# =============================================================================

set -uo pipefail

echo "Speech Transcription Container Starting..."
printf 'Arguments passed:'
printf ' %q' "$@"
printf '\n'

if ! python3 -c "import audio_io, confidence, provenance" ; then
    echo "ERROR: audio_io, confidence or provenance cannot be imported; the image" >&2
    echo "       would transcribe without run manifests or review flags. Rebuild it" >&2
    echo "       from setup/Dockerfile, which copies these modules." >&2
    exit 3
fi

# Check if output directory is mounted
if [ ! -w "/app/output" ]; then
    echo "Output will be saved inside container at /app/output"
    echo "   Mount output directory with: -v /path/to/output:/app/output"
fi

# Recordings are mounted at /app/audio_input. AUDIO_INPUT_DIR overrides that,
# which lets the tests run this script outside a container.
AUDIO_DIR="${AUDIO_INPUT_DIR:-/app/audio_input}"

rc=0
if [ $# -eq 0 ]; then
    shopt -s nullglob nocaseglob
    audio_files=("$AUDIO_DIR"/*.{wav,mp3,m4a,flac,ogg,aac})
    shopt -u nullglob nocaseglob
    if [ ${#audio_files[@]} -eq 0 ]; then
        echo "No audio files found in $AUDIO_DIR" >&2
        echo "   Mount your audio directory with: -v /path/to/audio:/app/audio_input" >&2
        echo "   Supported formats: WAV, MP3, M4A, FLAC, OGG, AAC" >&2
        exit 2
    fi
    echo "Processing ${#audio_files[@]} audio files in $AUDIO_DIR..."
    failed=0
    for audio_file in "${audio_files[@]}"; do
        echo "Processing: $(basename "$audio_file")"
        if ! python3 transcription.py "$audio_file" --mask-personal-names --language english; then
            echo "FAILED: $audio_file" >&2
            failed=$((failed + 1))
            rc=1
        fi
    done
    echo "Processed ${#audio_files[@]} files, $failed failed."
else
    printf 'Running: python3 transcription.py'
    printf ' %q' "$@"
    printf '\n'
    python3 transcription.py "$@" || rc=$?
fi

if [ "$rc" -eq 0 ]; then
    echo "Processing complete!"
else
    echo "Processing finished with failures (exit $rc)." >&2
fi
exit "$rc"
