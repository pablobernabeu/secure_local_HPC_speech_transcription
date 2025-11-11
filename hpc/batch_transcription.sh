#!/bin/bash

# ARC-compatible batch transcription script with CPU processing
# Adapted for Oxford ARC HPC cluster environment
# Modified to use virtual environment directories in $DATA

#SBATCH --job-name=transcription
#SBATCH --output=logs/transcription_%A_%a.out
#SBATCH --error=logs/transcription_%A_%a.err
#SBATCH --clusters=htc
#SBATCH --partition=short
#SBATCH --time=10:00:00
#SBATCH --mem=40G
#SBATCH --cpus-per-task=4
# GPU disabled - using CPU-only PyTorch for stability
# #SBATCH --gres=gpu:1

echo "🎤 ARC SPEECH TRANSCRIPTION JOB"
echo "==============================="
echo "Job started at: $(date)"
echo "Running on node: $SLURM_NODENAME"
echo "Job ID: $SLURM_JOB_ID"
echo "Task ID: $SLURM_ARRAY_TASK_ID"
echo "Cluster: $SLURM_CLUSTER_NAME"
echo ""

# Check GPU availability
if nvidia-smi &> /dev/null; then
    echo "🚀 GPU Information:"
    nvidia-smi --query-gpu=name,memory.total,compute_cap --format=csv,noheader,nounits
    echo ""
else
    echo "⚠️  Warning: No GPU detected"
    echo ""
fi

# Parse command line arguments for options
MASK_NAMES=""
MODEL=""
FORCE_ENGLISH=""
FIX_REPETITIONS=""
SAVE_NAME_MASKING_LOGS=""
SAVE_ENHANCED_AUDIO=""
SINGLE_FILE=""
OUTPUT_NAME=""
TRANSCRIPTION_ARGS=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --mask-names|--mask-personal-names)
            MASK_NAMES="--mask-personal-names"
            TRANSCRIPTION_ARGS="$TRANSCRIPTION_ARGS --mask-personal-names"
            shift
            ;;
        --model)
            MODEL="--model $2"
            TRANSCRIPTION_ARGS="$TRANSCRIPTION_ARGS --model $2"
            shift 2
            ;;
        --force-english|--language)
            # Handle both --force-english (legacy) and --language arguments
            if [ "$1" = "--force-english" ]; then
                FORCE_ENGLISH="--language english"
                TRANSCRIPTION_ARGS="$TRANSCRIPTION_ARGS --language english"
                shift
            else
                FORCE_ENGLISH="--language $2"
                TRANSCRIPTION_ARGS="$TRANSCRIPTION_ARGS --language $2"
                shift 2
            fi
            ;;
        --fix-repetitions|--fix-spurious-repetitions)
            FIX_REPETITIONS="--fix-spurious-repetitions"
            TRANSCRIPTION_ARGS="$TRANSCRIPTION_ARGS --fix-spurious-repetitions"
            shift
            ;;
        --save-name-masking-logs)
            SAVE_NAME_MASKING_LOGS="--save-name-masking-logs"
            TRANSCRIPTION_ARGS="$TRANSCRIPTION_ARGS --save-name-masking-logs"
            shift
            ;;
        --save-enhanced-audio)
            SAVE_ENHANCED_AUDIO="--save-enhanced-audio"
            TRANSCRIPTION_ARGS="$TRANSCRIPTION_ARGS --save-enhanced-audio"
            shift
            ;;
        --single-file)
            SINGLE_FILE="$2"
            shift 2
            ;;
        --output-name)
            OUTPUT_NAME="$2"
            shift 2
            ;;
        *)
            TRANSCRIPTION_ARGS="$TRANSCRIPTION_ARGS $1"
            shift
            ;;
    esac
done

# Set default model if not specified
if [ -z "$MODEL" ]; then
    MODEL="--model openai/whisper-large-v3"
fi

echo "🎯 Processing configuration:"
echo "  Model: ${MODEL#--model }"
[ -n "$MASK_NAMES" ] && echo "  Mask names: enabled" || echo "  Mask names: disabled"
[ -n "$FORCE_ENGLISH" ] && echo "  Force English: enabled" || echo "  Force English: disabled"
[ -n "$FIX_REPETITIONS" ] && echo "  Fix repetitions: enabled"
[ -n "$SAVE_NAME_MASKING_LOGS" ] && echo "  Save masking logs: enabled"
[ -n "$SAVE_ENHANCED_AUDIO" ] && echo "  Save enhanced audio: enabled"
[ -n "$SINGLE_FILE" ] && echo "  Single file mode: $SINGLE_FILE"
[ -n "$OUTPUT_NAME" ] && echo "  Output name: $OUTPUT_NAME"
echo ""

# Environment Setup
echo "🔧 STEP 1: Setting up environment..."
module purge

# Load required modules
if module load Anaconda3 &> /dev/null; then
    echo "   ✅ Anaconda3 loaded"
fi

# DO NOT load CUDA - causes conflicts with CPU-only PyTorch
# if module load CUDA/11.8.0 &> /dev/null; then
#     echo "   🚀 CUDA 11.8.0 loaded"
# elif module load CUDA &> /dev/null; then
#     echo "   🚀 CUDA loaded"
# fi
echo "   ⚠️  CUDA not loaded (using CPU-only PyTorch)"

# Load FFmpeg for audio format support
if module load FFmpeg &> /dev/null; then
    echo "   🎵 FFmpeg loaded (for M4A, MP3, etc.)"
fi

echo "   📦 Modules loaded:"
module list 2>&1 | grep -E "(Anaconda|FFmpeg)" | sed 's/^/      /'

# Environment Activation and Directory Setup
echo ""
echo "📦 STEP 2: Activating environment and setting up directories..."

# Source the activation script from personal space
ACTIVATION_SCRIPT="$HOME/speech_transcription/activate_project_env_arc.sh"

if [ -f "$ACTIVATION_SCRIPT" ]; then
    source "$ACTIVATION_SCRIPT"
    echo "   ✅ Environment activated via $ACTIVATION_SCRIPT"
    echo "   🐍 Python version: $(python --version)"
else
    echo "   ❌ Error: Activation script not found at $ACTIVATION_SCRIPT"
    echo "   💡 Expected location: ~/speech_transcription/activate_project_env_arc.sh"
    exit 1
fi

# Define environment path (already set by activation script, but define for clarity)
CONDA_ENV_PATH="$DATA/speech_transcription_env"

# Set up directories within the virtual environment
AUDIO_INPUT_DIR="$CONDA_ENV_PATH/audio_input"
OUTPUT_BASE_DIR="$CONDA_ENV_PATH/output"
TRANSCRIPTIONS_DIR="$OUTPUT_BASE_DIR/transcriptions"
ENHANCED_AUDIO_DIR="$OUTPUT_BASE_DIR/enhanced_audio"
MODELS_CACHE_DIR="$CONDA_ENV_PATH/models_cache"

# Create directories if they don't exist
mkdir -p "$AUDIO_INPUT_DIR"
mkdir -p "$TRANSCRIPTIONS_DIR"
mkdir -p "$ENHANCED_AUDIO_DIR"
mkdir -p "$MODELS_CACHE_DIR"

echo "   📁 Working directories:"
echo "      • Audio input: $AUDIO_INPUT_DIR"
echo "      • Transcriptions: $TRANSCRIPTIONS_DIR"
echo "      • Enhanced audio: $ENHANCED_AUDIO_DIR"
echo "      • Models cache: $MODELS_CACHE_DIR"

# Verify directories were created successfully
for dir in "$AUDIO_INPUT_DIR" "$TRANSCRIPTIONS_DIR" "$ENHANCED_AUDIO_DIR" "$MODELS_CACHE_DIR"; do
    if [ ! -d "$dir" ]; then
        echo "   ❌ Failed to create directory: $dir"
        exit 1
    fi
done

# Set environment variables for the Python script
export MODELS_CACHE_DIR
export TRANSFORMERS_CACHE="$MODELS_CACHE_DIR"
export HF_HOME="$MODELS_CACHE_DIR"

# Change to the project directory (where transcription.py is located)
PROJECT_DIR="$HOME/speech_transcription"
if [ -d "$PROJECT_DIR" ]; then
    cd "$PROJECT_DIR"
    echo "   📂 Working directory: $PROJECT_DIR"
else
    echo "   ❌ Project directory not found: $PROJECT_DIR"
    echo "   💡 Expected location: ~/speech_transcription/"
    exit 1
fi

# Find audio files in the project space audio_input directory (multiple formats supported)
echo ""
echo "🔍 STEP 3: Finding audio files..."
mapfile -t audio_files < <(find "$AUDIO_INPUT_DIR" \( -name "*.wav" -o -name "*.WAV" -o -name "*.mp3" -o -name "*.MP3" -o -name "*.m4a" -o -name "*.M4A" -o -name "*.flac" -o -name "*.FLAC" -o -name "*.ogg" -o -name "*.OGG" -o -name "*.aac" -o -name "*.AAC" \) -type f | sort)

if [ ${#audio_files[@]} -eq 0 ]; then
    echo "   ❌ No audio files found in $AUDIO_INPUT_DIR"
    echo "   🎵 Supported formats: WAV, MP3, M4A, FLAC, OGG, AAC"
    echo "   💡 Please copy your audio files to: $AUDIO_INPUT_DIR"
    exit 1
fi

# Select file for this array task or use single file mode
if [ -n "$SINGLE_FILE" ]; then
    # Single file mode - construct proper path
    # If SINGLE_FILE is absolute, use it as-is
    # If relative, check both personal space and project space
    if [[ "$SINGLE_FILE" = /* ]]; then
        # Absolute path - use as-is
        AUDIO_FILE="$SINGLE_FILE"
    elif [ -f "$SINGLE_FILE" ]; then
        # Relative path exists in current directory (personal space)
        AUDIO_FILE="$(realpath "$SINGLE_FILE")"
    else
        # Try in project DATA audio_input directory
        AUDIO_FILE="$AUDIO_INPUT_DIR/$(basename "$SINGLE_FILE")"
    fi
    echo "   📁 Single file mode: $(basename "$AUDIO_FILE")"
    echo "   🎵 File format: ${AUDIO_FILE##*.}"
else
    # Array mode - select file based on task ID (SLURM_ARRAY_TASK_ID is 1-based)
    TASK_INDEX=$((SLURM_ARRAY_TASK_ID - 1))
    if [ $TASK_INDEX -ge ${#audio_files[@]} ]; then
        echo "   ❌ Task index $TASK_INDEX exceeds available files (${#audio_files[@]})"
        exit 1
    fi
    
    AUDIO_FILE="${audio_files[$TASK_INDEX]}"
    echo "   📁 Processing file $SLURM_ARRAY_TASK_ID/${#audio_files[@]}: $(basename "$AUDIO_FILE")"
    echo "   🎵 File format: ${AUDIO_FILE##*.}"
fi

# Verify file exists and is readable
if [ ! -f "$AUDIO_FILE" ]; then
    echo "   ❌ Audio file not found: $AUDIO_FILE"
    exit 1
fi

echo "   📊 File size: $(du -h "$AUDIO_FILE" | cut -f1)"

# Verify Python environment and packages
echo ""
echo "🔍 STEP 4: Verifying environment..."

# Quick version check - skip heavy imports that may hang
timeout 10 python --version
if [ $? -eq 0 ]; then
    echo "   ✅ Python accessible"
else
    echo "   ❌ Python not accessible"
    exit 1
fi

# Skip detailed package verification to avoid hanging
# The transcription script will fail fast if packages are missing
echo "   ⏭️  Skipping detailed package check (will verify during transcription)"

# Run transcription with modified paths
echo ""
echo "🎤 STEP 5: Running speech transcription..."

# Check if the main transcription script exists
TRANSCRIPTION_SCRIPT="transcription.py"
if [ ! -f "$TRANSCRIPTION_SCRIPT" ]; then
    echo "   ❌ Transcription script not found: $TRANSCRIPTION_SCRIPT"
    echo "   📂 Current directory: $(pwd)"
    echo "   📋 Available files:"
    ls -la *.py 2>/dev/null | head -5 || echo "      No Python files found"
    exit 1
fi

# Construct command with proper paths
echo "   📋 Running transcription..."
echo "   📁 Audio: $(basename "$AUDIO_FILE")"
echo "   📤 Output: ./output/transcripts/"

# Add output-name to transcription args if specified
if [ -n "$OUTPUT_NAME" ]; then
    TRANSCRIPTION_ARGS="$TRANSCRIPTION_ARGS --output-name \"$OUTPUT_NAME\""
fi

echo "   ⚙️  Options: $TRANSCRIPTION_ARGS"
echo ""

# Run with timeout to prevent jobs hanging (3 hours = 10800 seconds)
echo "🔄 Starting transcription (this may take a while)..."
echo "   🐛 Debug: Command to execute:"
echo "   python $TRANSCRIPTION_SCRIPT $AUDIO_FILE $TRANSCRIPTION_ARGS"
echo ""

# Force CPU-only mode - prevent ANY GPU/CUDA usage
export CUDA_VISIBLE_DEVICES=""
export PYTORCH_CUDA_ALLOC_CONF=""
export TORCH_DEVICE="cpu"

# Skip import test - just run transcription with unbuffered output
# The transcription script will fail fast if imports are broken
export PYTHONUNBUFFERED=1
echo "   ⚡ Starting Python script (strict CPU-only mode)..."
timeout 10800 python -u "$TRANSCRIPTION_SCRIPT" "$AUDIO_FILE" $TRANSCRIPTION_ARGS 2>&1
TRANSCRIPTION_EXIT_CODE=$?

echo ""
echo "   🐛 Debug: Python exit code: $TRANSCRIPTION_EXIT_CODE"

echo ""
echo "📊 TRANSCRIPTION RESULTS"
echo "========================"

if [ $TRANSCRIPTION_EXIT_CODE -eq 0 ]; then
    echo "✅ SUCCESS: Transcription completed"
    
    # Show output files (works with any input format)
    BASE_NAME=$(basename "$AUDIO_FILE")
    BASE_NAME="${BASE_NAME%.*}"  # Remove any extension
    
    echo "   📄 Output files created:"
    if [ -f "$TRANSCRIPTIONS_DIR/${BASE_NAME}_transcription.txt" ]; then
        echo "      • ${BASE_NAME}_transcription.txt ($(du -h "$TRANSCRIPTIONS_DIR/${BASE_NAME}_transcription.txt" | cut -f1))"
    fi
    if [ -f "$TRANSCRIPTIONS_DIR/${BASE_NAME}_transcription.docx" ]; then
        echo "      • ${BASE_NAME}_transcription.docx ($(du -h "$TRANSCRIPTIONS_DIR/${BASE_NAME}_transcription.docx" | cut -f1))"
    fi
    if [ -f "$ENHANCED_AUDIO_DIR/${BASE_NAME}_enhanced.wav" ]; then
        echo "      • ${BASE_NAME}_enhanced.wav ($(du -h "$ENHANCED_AUDIO_DIR/${BASE_NAME}_enhanced.wav" | cut -f1))"
    fi
    
elif [ $TRANSCRIPTION_EXIT_CODE -eq 124 ]; then
    echo "❌ TIMEOUT: Transcription exceeded 3 hour limit"
else
    echo "❌ FAILURE: Transcription failed with exit code $TRANSCRIPTION_EXIT_CODE"
fi

echo ""
echo "🏁 JOB SUMMARY"
echo "=============="
echo "Job completed at: $(date)"
echo "File processed: $(basename "$AUDIO_FILE")"
echo "Exit code: $TRANSCRIPTION_EXIT_CODE"
echo "Node: $SLURM_NODENAME"
echo "Job ID: $SLURM_JOB_ID"
echo "Task ID: $SLURM_ARRAY_TASK_ID"
echo "Working directory: $CONDA_ENV_PATH"

exit $TRANSCRIPTION_EXIT_CODE