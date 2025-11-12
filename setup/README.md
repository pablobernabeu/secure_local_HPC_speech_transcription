# Setup Scripts

This directory contains installation and configuration scripts for the transcription system.

## Scripts

### Installation and Setup

- **`install_requirements.py`** - Installs Python dependencies for the transcription system
  - Creates virtual environment
  - Installs PyTorch, Transformers, and other required packages
  - Sets up proper cache directories
  - **Usage**: `python setup/install_requirements.py`

- **`setup_environment.sh`** - One-time environment setup script for local/development
  - Creates virtual environment
  - Installs all dependencies
  - Pre-caches models (optional)
  - **Usage**: `chmod +x setup/setup_environment.sh && ./setup/setup_environment.sh`

- **`setup_pyannote.py`** - Interactive setup wizard for speaker attribution (diarization)
  - Configures HuggingFace token
  - Downloads pyannote models
  - Verifies installation
  - **Usage**: `python setup/setup_pyannote.py`
  - See [PYANNOTE_SETUP_GUIDE.md](../PYANNOTE_SETUP_GUIDE.md) for detailed instructions

- **`download_model.py`** - Pre-downloads transcription models to avoid network timeouts
  - Caches Whisper models locally
  - Optionally downloads pyannote models
  - Should be run on login node before batch processing
  - **Usage**: `python setup/download_model.py`
  - **With custom model**: `python setup/download_model.py --model "openai/whisper-medium"`

### Docker/Container Deployment

- **`Dockerfile`** - Docker container definition for containerized deployment
  - Based on NVIDIA CUDA images
  - Includes all dependencies
  - GPU acceleration support
  - **Usage**: `docker build -t speech-transcription .`

- **`docker-entrypoint.sh`** - Container entry point script
  - Handles container initialization
  - Sets up environment variables
  - Manages audio file processing

## Main Entry Points

The main scripts are in the project root:
- **`transcription.py`** - Main CLI for transcription
- **`setup.py`** - Python package setup and configuration
- **`activate_project_env.sh`** - Activates project environment (HPC use)

## Quick Reference

```bash
# Initial setup (local)
./setup/setup_environment.sh

# Initial setup (HPC)
source activate_project_env.sh
python setup/install_requirements.py

# Setup speaker attribution
python setup/setup_pyannote.py

# Pre-download models (HPC recommended)
python setup/download_model.py
```

