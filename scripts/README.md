# Utility Scripts

This directory contains setup and utility scripts for the transcription project.

## Setup Scripts

- **`install_requirements.py`** - Install Python dependencies
- **`setup_pyannote.py`** - Set up PyAnnote for speaker diarization
- **`download_model.py`** - Download Whisper models
- **`setup_environment.sh`** - General environment setup
- **`setup_arc_structure.sh`** - Set up ARC directory structure
- **`verify_arc_upload.sh`** - Verify files uploaded to ARC

## Usage

Most scripts can be run directly:

```bash
# Install requirements
python scripts/install_requirements.py

# Setup PyAnnote
python scripts/setup_pyannote.py

# Download models
python scripts/download_model.py
```

## Main Entry Points

The main scripts remain in the project root:
- `../transcription.py` - Main CLI for transcription
- `../setup.py` - Python package setup
- `../activate_project_env_arc.sh` - Activate conda environment (used by SLURM)
