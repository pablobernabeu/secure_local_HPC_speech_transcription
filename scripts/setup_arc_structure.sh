#!/bin/bash
# setup_arc_structure.sh
# One-time setup to create proper directory structure on Oxford ARC
# 
# Architecture:
#   Personal space (~):  Scripts, code, configs (memory-limited)
#   Project space ($DATA): Large files, models, cache, data (more space)

set -e  # Exit on error

echo "==================================="
echo "Oxford ARC Directory Setup"
echo "==================================="
echo ""

# Check environment
if [ -z "$DATA" ]; then
    echo "❌ ERROR: \$DATA environment variable not set"
    echo "   This should be set by ARC automatically"
    exit 1
fi

echo "✓ Environment variables:"
echo "  HOME: $HOME"
echo "  DATA: $DATA"
echo ""

# Define directories
PERSONAL_DIR="$HOME/speech_transcription"
PROJECT_DIR="$DATA/speech_transcription_env"

echo "==================================="
echo "Creating Directory Structure"
echo "==================================="
echo ""

# Personal space structure (lightweight files)
echo "1. Setting up personal space: $PERSONAL_DIR"
mkdir -p "$PERSONAL_DIR"
mkdir -p "$PERSONAL_DIR/scripts"
mkdir -p "$PERSONAL_DIR/configs"
mkdir -p "$PERSONAL_DIR/data"  # For small CSV files like curated_names.csv
mkdir -p "$PERSONAL_DIR/logs"  # For job logs and small output files
echo "   ✅ Personal directories created"
echo ""

# Project space structure (heavy files)
echo "2. Setting up project space: $PROJECT_DIR"
mkdir -p "$PROJECT_DIR"
mkdir -p "$PROJECT_DIR/venv"  # Virtual environment (can be large)
mkdir -p "$PROJECT_DIR/.python_user"
mkdir -p "$PROJECT_DIR/.pip_cache"
mkdir -p "$PROJECT_DIR/.huggingface_cache"  # Model files (2-3GB each)
mkdir -p "$PROJECT_DIR/.torch_cache"
mkdir -p "$PROJECT_DIR/audio_input"  # Input audio files
mkdir -p "$PROJECT_DIR/transcription_output"  # Output transcriptions
mkdir -p "$PROJECT_DIR/models"  # Downloaded model files
echo "   ✅ Project directories created"
echo ""

# Check disk usage
echo "==================================="
echo "Disk Usage Check"
echo "==================================="
echo ""
echo "Personal space quota:"
quota -s 2>/dev/null || du -sh "$HOME" 2>/dev/null || echo "  (quota command not available)"
echo ""
echo "Project space usage:"
du -sh "$PROJECT_DIR" 2>/dev/null || echo "  (directory empty or not accessible)"
echo ""

# Create a README in each location
echo "3. Creating README files..."
cat > "$PERSONAL_DIR/README.md" << 'EOF'
# Personal Space - Speech Transcription

This directory contains lightweight files that fit within home directory quota limits.

## Structure

- `scripts/`: Shell scripts (.sh), Python scripts (.py)
- `configs/`: Configuration files, requirements.txt
- `data/`: Small data files (CSV, JSON, etc.)
- `logs/`: Job logs and small output files

## Large Files

Large files (models, audio, cache) are stored in `$DATA/speech_transcription_env/`

## Usage

Activate environment:
```bash
source ~/speech_transcription/activate_project_env_arc.sh
```
EOF

cat > "$PROJECT_DIR/README.md" << 'EOF'
# Project Space - Speech Transcription Environment

This directory contains large files that require more storage space.

## Structure

- `venv/`: Python virtual environment and packages
- `.huggingface_cache/`: Cached model files (2-3GB per model)
- `.torch_cache/`: PyTorch cached files
- `.python_user/`: User-installed Python packages
- `audio_input/`: Input audio files for transcription
- `transcription_output/`: Generated transcription files
- `models/`: Downloaded model files

## Scripts and Code

Scripts and configuration files are stored in `~/speech_transcription/`
EOF

echo "   ✅ README files created"
echo ""

# Create a symlink for convenience
echo "4. Creating convenience symlink..."
if [ ! -L "$PERSONAL_DIR/data_storage" ]; then
    ln -s "$PROJECT_DIR" "$PERSONAL_DIR/data_storage"
    echo "   ✅ Symlink created: ~/speech_transcription/data_storage -> $DATA/speech_transcription_env"
else
    echo "   ℹ️  Symlink already exists"
fi
echo ""

# Summary
echo "==================================="
echo "Setup Complete!"
echo "==================================="
echo ""
echo "Directory structure created:"
echo ""
echo "📁 Personal space (~): $PERSONAL_DIR"
echo "   ├── scripts/          (Shell and Python scripts)"
echo "   ├── configs/          (Configuration files)"
echo "   ├── data/             (Small CSV/JSON files)"
echo "   ├── logs/             (Job logs)"
echo "   └── data_storage/     (→ symlink to \$DATA)"
echo ""
echo "📁 Project space (\$DATA): $PROJECT_DIR"
echo "   ├── venv/                    (Virtual environment)"
echo "   ├── .huggingface_cache/      (Model cache)"
echo "   ├── .torch_cache/            (PyTorch cache)"
echo "   ├── audio_input/             (Input audio files)"
echo "   └── transcription_output/    (Output files)"
echo ""
echo "Next steps:"
echo "1. Copy your scripts to: $PERSONAL_DIR/scripts/"
echo "2. Copy your data files to: $PERSONAL_DIR/data/"
echo "3. Run: source $PERSONAL_DIR/activate_project_env_arc.sh"
echo "4. Install packages: pip install -r requirements.txt"
echo ""
