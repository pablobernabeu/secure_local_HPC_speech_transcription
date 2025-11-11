#!/bin/bash

# Auto-submit transcription jobs - automatically detects number of audio files
# Usage: ./submit_transcription.sh [transcription_options...]
# 
# Batch mode (default):
#   ./submit_transcription.sh --language english --mask-personal-names
#
# Single file mode:
#   ./submit_transcription.sh --single-file audio_input/myfile.wav --language english --mask-personal-names
#   ./submit_transcription.sh --single-file audio_input/myfile.wav --output-name "interview_2024" --mask-personal-names
#
# Options:
#   --single-file <path>     Specify exact file to transcribe
#   --output-name <name>     Custom name for output files (without extension)

echo "🎤 AUTO-SUBMIT TRANSCRIPTION JOBS"
echo "================================="

# Create logs directory if it doesn't exist
LOGS_DIR="$HOME/speech_transcription/logs"
if [ ! -d "$LOGS_DIR" ]; then
    mkdir -p "$LOGS_DIR"
    echo "📁 Created logs directory: $LOGS_DIR"
fi

# Define valid arguments
VALID_ARGS=(
    "--single-file"
    "--output-name"
    "--time-limit"
    "--memory"
    "--model"
    "--language"
    "--enhance-audio"
    "--mask-personal-names"
    "--fix-spurious-repetitions"
    "--save-name-masking-logs"
    "--save-enhanced-audio"
    "--use-facebook-names-for-masking"
    "--use-facebook-surnames-for-masking"
    "--languages-for-name-masking"
    "--exclude-common-english-words-from-name-masking"
    "--exclude-names-from-masking"
    "--exclude-names-file"
    "--speaker-attribution"
    "-h"
    "--help"
)

# Function to check if argument is valid
is_valid_arg() {
    local arg="$1"
    # Extract just the flag part (before any =)
    local flag="${arg%%=*}"
    
    for valid in "${VALID_ARGS[@]}"; do
        if [[ "$flag" == "$valid" ]]; then
            return 0
        fi
    done
    return 1
}

# Parse arguments for single-file mode
SINGLE_FILE=""
OUTPUT_NAME=""
TIME_LIMIT=""
MEMORY=""
TRANSCRIPTION_ARGS=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --single-file)
            SINGLE_FILE="$2"
            shift 2
            ;;
        --output-name)
            OUTPUT_NAME="$2"
            shift 2
            ;;
        --time-limit)
            TIME_LIMIT="$2"
            shift 2
            ;;
        --memory)
            MEMORY="$2"
            shift 2
            ;;
        -h|--help)
            shift 2
            ;;
        -h|--help)
            echo "Usage: ./submit_transcription.sh [options]"
            echo ""
            echo "HPC-specific options:"
            echo "  --single-file <path>       Specify exact file to transcribe"
            echo "  --output-name <name>       Custom name for output files"
            echo "  --time-limit HH:MM:SS      Maximum time per audio file (default: 2h GPU, 8h CPU)"
            echo "  --memory <size>            Memory allocation per job (default: 16G GPU, 32G CPU)"
            echo "                             Examples: 16G, 32G, 64G, 128G"
            echo ""
            echo "Transcription options:"
            echo "  --model <model>                    HuggingFace model ID"
            echo "  --language <lang>                  Transcription language (english, spanish, etc.)"
            echo "  --enhance-audio                    Enable audio enhancement"
            echo "  --mask-personal-names              Enable name masking"
            echo "  --fix-spurious-repetitions         Remove repetitive patterns"
            echo "  --save-name-masking-logs           Save detailed masking logs"
            echo "  --save-enhanced-audio              Save enhanced audio files"
            echo "  --speaker-attribution              Enable speaker diarization"
            echo "  --exclude-names-from-masking <names>  Comma-separated names to exclude"
            echo "  --exclude-names-file <file>        File with names to exclude"
            echo "  --languages-for-name-masking <langs>  Languages for name database"
            echo "  --use-facebook-names-for-masking   Use Facebook first names database"
            echo "  --use-facebook-surnames-for-masking  Use Facebook surnames database"
            echo ""
            echo "Examples:"
            echo "  ./submit_transcription.sh --mask-personal-names --language english"
            echo "  ./submit_transcription.sh --single-file audio_input/file.wav --time-limit 04:00:00 --memory 64G"
            exit 0
            ;;
        --*)
            # Check if this is a valid argument
            if ! is_valid_arg "$1"; then
                echo "❌ ERROR: Unknown argument: $1"
                echo ""
                echo "Valid arguments are:"
                for arg in "${VALID_ARGS[@]}"; do
                    echo "  $arg"
                done
                echo ""
                echo "Run './hpc/submit_transcription.sh --help' for usage information."
                exit 1
            fi
            TRANSCRIPTION_ARGS="$TRANSCRIPTION_ARGS $1"
            shift
            ;;
        *)
            # Non-flag argument (likely a value for a previous flag)
            TRANSCRIPTION_ARGS="$TRANSCRIPTION_ARGS $1"
            shift
            ;;
    esac
done

# Check for single-file mode
if [ -n "$SINGLE_FILE" ]; then
    echo "📄 SINGLE FILE MODE"
    echo "=================="
    
    # Validate the specified file exists
    if [ ! -f "$SINGLE_FILE" ]; then
        echo "❌ ERROR: Specified file not found: $SINGLE_FILE"
        exit 1
    fi
    
    # Check if it's a supported audio format
    case "${SINGLE_FILE,,}" in
        *.wav|*.mp3|*.m4a|*.flac|*.ogg|*.aac)
            echo "✅ File found: $(basename "$SINGLE_FILE")"
            echo "   Format: $(echo "$SINGLE_FILE" | sed 's/.*\.//' | tr '[:lower:]' '[:upper:]')"
            echo "   Size: $(ls -lh "$SINGLE_FILE" | awk '{print $5}')"
            ;;
        *)
            echo "❌ ERROR: Unsupported audio format: $SINGLE_FILE"
            echo "Supported formats: WAV, MP3, M4A, FLAC, OGG, AAC"
            exit 1
            ;;
    esac
    
    # Set up single file processing
    AUDIO_COUNT=1
    BATCH_MODE=false
    
    # Add custom arguments for single file mode
    if [ -n "$OUTPUT_NAME" ]; then
        TRANSCRIPTION_ARGS="$TRANSCRIPTION_ARGS --output-name \"$OUTPUT_NAME\""
        echo "📝 Custom output name: $OUTPUT_NAME"
    fi
    
    # Pass single-file to batch script (but batch script won't pass it to Python)
    TRANSCRIPTION_ARGS="$TRANSCRIPTION_ARGS --single-file \"$SINGLE_FILE\""
    
else
    echo "📁 BATCH MODE"
    echo "============"
    BATCH_MODE=true

    # Define audio input directory (relative to current working directory)
    AUDIO_INPUT_DIR="./audio_input"
    
    # Check if audio directory exists
    if [ ! -d "$AUDIO_INPUT_DIR" ]; then
        echo "❌ ERROR: Audio input directory not found: $AUDIO_INPUT_DIR"
        echo "Make sure your audio files are in the correct location."
        echo "Expected: $(pwd)/audio_input"
        exit 1
    fi
    
    # Count audio files
    echo "📁 Scanning for audio files..."
    AUDIO_COUNT=$(find "$AUDIO_INPUT_DIR" -type f \( -iname "*.wav" -o -iname "*.mp3" -o -iname "*.m4a" -o -iname "*.flac" -o -iname "*.ogg" -o -iname "*.aac" \) | wc -l)
    
    if [ "$AUDIO_COUNT" -eq 0 ]; then
        echo "❌ ERROR: No audio files found in $AUDIO_INPUT_DIR"
        echo "Supported formats: WAV, MP3, M4A, FLAC, OGG, AAC"
        exit 1
    fi
    
    echo "✅ Found $AUDIO_COUNT audio files"
    
    # List the files that will be processed (with proper space handling)
    echo ""
    echo "📄 Files to be processed:"
    find "$AUDIO_INPUT_DIR" -type f \( -iname "*.wav" -o -iname "*.mp3" -o -iname "*.m4a" -o -iname "*.flac" -o -iname "*.ogg" -o -iname "*.aac" \) -print0 | sort -z | tr '\0' '\n' | nl
fi

echo ""
if [ "$BATCH_MODE" = true ]; then
    echo "⚙️  Batch Job Configuration:"
    echo "   Files: $AUDIO_COUNT"
    echo "   Array range: 1-$AUDIO_COUNT"
else
    echo "⚙️  Single File Job Configuration:"
    echo "   File: $(basename \"$SINGLE_FILE\")"
    if [ -n "$OUTPUT_NAME" ]; then
        echo "   Output name: $OUTPUT_NAME"
    fi
fi
echo "   Time limit: 2 hours per task"
echo "   Memory: 16GB per task"
echo "   GPU: 1 per task"
if [ -n "$TRANSCRIPTION_ARGS" ]; then
    echo "   Options: $TRANSCRIPTION_ARGS"
    # Check if name masking is enabled
    if [[ "$TRANSCRIPTION_ARGS" == *"--mask-personal-names"* ]]; then
        echo "   🎭 Enhanced name masking: Will install global names database (730K+ names)"
    fi
else
    echo "   Options: None (basic transcription)"
fi

echo ""
echo "🚀 Submitting job..."

# Set time limits based on user input or defaults
if [ -n "$TIME_LIMIT" ]; then
    GPU_TIME="$TIME_LIMIT"
    CPU_TIME="$TIME_LIMIT"
    echo "⏱️  Using custom time limit: $TIME_LIMIT (applies to both GPU and CPU modes)"
else
    GPU_TIME="02:00:00"
    CPU_TIME="08:00:00"
fi

# Set memory based on user input or defaults
if [ -n "$MEMORY" ]; then
    GPU_MEMORY="$MEMORY"
    CPU_MEMORY="$MEMORY"
    echo "💾 Using custom memory: $MEMORY (applies to both GPU and CPU modes)"
else
    GPU_MEMORY="16G"
    CPU_MEMORY="32G"
fi
# Check GPU availability first
echo "Checking GPU availability..."
GPU_AVAILABLE=$(sinfo -N -o "%N %G" 2>/dev/null | grep -c "gpu" || echo "0")
echo "   DEBUG: GPU check returned: '$GPU_AVAILABLE'"

if [ "$GPU_AVAILABLE" -gt 0 ] 2>/dev/null; then
    echo "✅ Found $GPU_AVAILABLE GPU nodes available"
    echo "Attempting GPU job submission..."
    
    # Submit job based on mode
    if [ "$BATCH_MODE" = true ]; then
        # Batch mode: submit job array
        eval "JOB_ID=\$(sbatch \
            --array=1-$AUDIO_COUNT \
            --time=$GPU_TIME \
            --mem=$GPU_MEMORY \
            --parsable \
            hpc/batch_transcription.sh \
            $TRANSCRIPTION_ARGS 2>&1)"
    else
        # Single file mode: submit single job (no array)
        eval "JOB_ID=\$(sbatch \
            --time=$GPU_TIME \
            --mem=$GPU_MEMORY \
            --parsable \
            hpc/batch_transcription.sh \
            $TRANSCRIPTION_ARGS 2>&1)"
    fi
    
    if [[ $JOB_ID =~ ^[0-9]+$ ]]; then
        echo "✅ GPU job submitted successfully!"
        GPU_MODE=true
    else
        echo "⚠️  GPU job submission failed: $JOB_ID"
        echo "Falling back to CPU-only mode..."
        
        # Fallback CPU submission
        if [ "$BATCH_MODE" = true ]; then
            eval "JOB_ID=\$(sbatch \
                --array=1-$AUDIO_COUNT \
                --time=$CPU_TIME \
                --mem=$CPU_MEMORY \
                --parsable \
                hpc/batch_transcription.sh \
                $TRANSCRIPTION_ARGS)"
        else
            eval "JOB_ID=\$(sbatch \
                --time=$CPU_TIME \
                --mem=$CPU_MEMORY \
                --parsable \
                hpc/batch_transcription.sh \
                $TRANSCRIPTION_ARGS)"
        fi
        GPU_MODE=false
    fi
else
    echo "⚠️  No GPU nodes available, using CPU-only mode"
    if [ "$BATCH_MODE" = true ]; then
        echo "   Note: This will be significantly slower for large batches"
        echo "   Submitting array job for $AUDIO_COUNT files..."
        eval "JOB_ID=\$(sbatch \
            --array=1-$AUDIO_COUNT \
            --time=$CPU_TIME \
            --mem=$CPU_MEMORY \
            --parsable \
            hpc/batch_transcription.sh \
            $TRANSCRIPTION_ARGS 2>&1)"
    else
        echo "   Submitting single file job..."
        eval "JOB_ID=\$(sbatch \
            --time=$CPU_TIME \
            --mem=$CPU_MEMORY \
            --parsable \
            hpc/batch_transcription.sh \
            $TRANSCRIPTION_ARGS 2>&1)"
    fi
    GPU_MODE=false
fi

# Check if job was submitted successfully
echo ""
echo "📊 Submission result: '$JOB_ID'"

# Extract just the numeric job ID (parsable format is "jobid;cluster")
JOB_ID_NUM=$(echo "$JOB_ID" | cut -d';' -f1)

if [[ ! $JOB_ID_NUM =~ ^[0-9]+$ ]]; then
    echo "❌ Failed to submit job"
    echo "   Error details: $JOB_ID"
    echo ""
    echo "💡 Troubleshooting:"
    echo "   - Check logs directory exists: ls -la ~/speech_transcription/logs/"
    echo "   - Check SLURM configuration: sacctmgr show qos"
    echo "   - Try manual submission: sbatch hpc/batch_transcription.sh --language english"
    exit 1
fi

if [ $? -eq 0 ] && [[ $JOB_ID_NUM =~ ^[0-9]+$ ]]; then
    if [ "$BATCH_MODE" = true ]; then
        echo "✅ Job array submitted successfully!"
        echo "   Job ID: $JOB_ID_NUM"
        echo "   Tasks: $AUDIO_COUNT (1-$AUDIO_COUNT)"
        LOG_FILES="transcription_${JOB_ID_NUM}_*.out"
    else
        echo "✅ Single job submitted successfully!"
        echo "   Job ID: $JOB_ID_NUM"
        echo "   File: $(basename \"$SINGLE_FILE\")"
        if [ -n "$OUTPUT_NAME" ]; then
            echo "   Output name: $OUTPUT_NAME"
        fi
        LOG_FILES="transcription_${JOB_ID_NUM}.out"
    fi
    
    if [ "$GPU_MODE" = true ]; then
        echo "   Mode: GPU-accelerated 🚀"
        if [ -n "$TIME_LIMIT" ]; then
            echo "   Time: $TIME_LIMIT per task (custom)"
        else
            echo "   Time: 2 hours per task (default)"
        fi
        if [ -n "$MEMORY" ]; then
            echo "   Memory: $MEMORY per task (custom)"
        else
            echo "   Memory: 16G per task (default)"
        fi
    else
        echo "   Mode: CPU-only ⚠️  (slower but functional)"
        if [ -n "$TIME_LIMIT" ]; then
            echo "   Time: $TIME_LIMIT per task (custom)"
        else
            echo "   Time: 8 hours per task (default)"
        fi
        if [ -n "$MEMORY" ]; then
            echo "   Memory: $MEMORY per task (custom)"
        else
            echo "   Memory: 32G per task (default)"
        fi
    fi
    echo ""
    echo "📊 Monitor your job(s):"
    echo "   squeue -u \$USER -j $JOB_ID_NUM"
    echo "   tail -f ~/speech_transcription/logs/$LOG_FILES"
    echo ""
    echo "📁 Results will be saved to:"
    if [ -n "$OUTPUT_NAME" ]; then
        echo "   output/transcripts/${OUTPUT_NAME}_transcript.txt"
        echo "   output/transcripts/${OUTPUT_NAME}_transcript.docx"
    else
        echo "   output/transcripts/{filename}_transcript.txt"
        echo "   output/transcripts/{filename}_transcript.docx"
    fi
else
    echo "❌ Failed to submit job"
    exit 1
fi
