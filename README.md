
# Secure and Scalable Speech Transcription for Local and HPC

Production-grade automated speech transcription system with audio enhancement, speaker identification and comprehensive text processing. Designed for high-performance computing (HPC) environments with GPU (Graphics Processing Unit) acceleration and SLURM (Simple Linux Utility for Resource Management) job scheduling.

## Overview

This system provides end-to-end speech processing capabilities including audio enhancement, machine learning-based transcription, text cleaning and privacy protection. The pipeline supports batch processing with parallel job execution for efficient processing of large audio datasets.

**Key Features:**
- OpenAI Whisper Large v3 transcription with GPU acceleration
- Automatic audio enhancement and noise reduction
- Multilingual personal name masking (1,793+ curated names, optional Facebook database with 730K+ names)
- Speaker attribution (diarisation) for multi-speaker recordings
- HPC batch processing with SLURM job scheduling
- Dual output formats (plain text and Microsoft Word)

## System Requirements

- **Python 3.12** (recommended for HPC environments)
  - Python 3.13 has limited package availability (avoid for production)
  - Python 3.11 supported but 3.12 preferred for stability
- **PyTorch 2.5.1+cpu** (stable, torchcodec-compatible)
  - Avoid PyTorch 2.7+ on CPU-only systems (ABI compatibility issues)
- CUDA-compatible GPU (recommended) or CPU-only mode
- 32GB RAM minimum for batch processing
- SLURM job scheduler (for HPC environments)

### Tested Package Versions (HPC Production)

```
Python: 3.12.x
PyTorch: 2.5.1+cpu
TorchVision: 0.20.1+cpu
TorchAudio: 2.5.1+cpu
Transformers: 4.45.0+
Pyannote.audio: 3.1.0-3.3.x (NOT 4.x - requires torch>=2.8)
```

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for known issues and version compatibility details.

## Installation

### Initial Setup (One-time)

**Local/Development:**

```bash
# Clone the repository
git clone https://github.com/pablobernabeu/secure_local_HPC_speech_transcription
cd secure_local_HPC_speech_transcription

# Run one-time setup (creates venv, installs packages, caches models)
chmod +x setup/setup_environment.sh
./setup/setup_environment.sh
```

**HPC:**

```bash
# Clone the repository
git clone https://github.com/pablobernabeu/secure_local_HPC_speech_transcription
cd secure_local_HPC_speech_transcription

# CRITICAL: Activate environment BEFORE running setup
# This ensures packages install to project space, not your personal quota
source activate_project_env.sh

# Now run setup
python setup/install_requirements.py
```

**⚠️ HPC:** Always activate `activate_project_env.sh` before any setup or package installation to ensure packages install to project space (typically ~200GB+), not personal quota (typically ~20GB).

The setup script will:
- Create a Python virtual environment
- Install all required packages with CUDA support
- Set up proper cache directories for models
- Optionally pre-cache Whisper models (~1.5GB download)
- Ask if you want to set up speaker attribution (optional)
- Verify all dependencies are working

**⏱️ Total setup time:** 15-30 minutes (including optional speaker attribution)

**📖 For detailed speaker attribution setup:** See [PYANNOTE_SETUP_GUIDE.md](PYANNOTE_SETUP_GUIDE.md)

### Environment Activation (Per Session)

After initial setup, activate the environment for each session:

```bash
source activate_project_env.sh
```

## Quick Start

### For HPC Production Use (Recommended)

```bash
# Multiple files (batch) - processes all files in audio_input/
./hpc/submit_transcription.sh --mask-personal-names

# Single file with custom name
./hpc/submit_transcription.sh --single-file audio_input/interview.wav --output-name "client_call" --mask-personal-names
```

### For Local Testing/Development

```bash
# Direct Python execution (runs immediately on current machine)
python transcription.py "audio_input/test.wav" --mask-personal-names

# With language specification
python transcription.py "audio_input/test.wav" --mask-personal-names --language spanish

# With audio enhancement (improves quality but takes longer)
python transcription.py "audio_input/test.wav" --mask-personal-names --enhance-audio
```

See [docs/hpc_usage.md](docs/hpc_usage.md) for comprehensive HPC usage examples and [docs/advanced_usage.md](docs/advanced_usage.md) for advanced features.

## Command Line Options

Both `transcription.py` and `hpc/submit_transcription.sh` support the same options:

| Option | Description |
|--------|-------------|
| `--model MODEL` | HuggingFace model ID (default: openai/whisper-large-v3) |
| `--output-name <name>` | Custom name for output files (without extension) |
| `--language LANG` | Specify transcription language (e.g., `english`, `spanish`, `french`). Default: auto-detect |
| `--time-limit HH:MM:SS` | **HPC only**: Set maximum time per audio file (default: 2h GPU, 8h CPU) |
| `--memory <size>` | **HPC only**: Memory allocation per job (e.g., `16G`, `32G`, `64G`) |
| `--enhance-audio` | Enable audio enhancement (disabled by default) |
| `--mask-personal-names` | Enable personal name masking (OFF by default) |
| `--fix-spurious-repetitions` | Remove spurious repetitions from Whisper (OFF by default) |
| `--save-name-masking-logs` | Save detailed name replacement logs (OFF by default) |
| `--save-enhanced-audio` | Save enhanced audio files (OFF by default) |
| `--use-facebook-names-for-masking` | Use Facebook first names database (~730K names, OFF by default) |
| `--use-facebook-surnames-for-masking` | Use Facebook surnames database (~980K surnames, OFF by default) |
| `--languages-for-name-masking LANG ...` | Select languages for name database (default: all 9 languages) |
| `--exclude-common-english-words-from-name-masking` | Exclude common English words from masking (auto-enabled for English) |
| `--exclude-names-from-masking "name1,name2"` | Comma-separated list of names to exclude |
| `--exclude-names-file path/to/file.txt` | File with names to exclude (one per line) |
| `--speaker-attribution` | Enable speaker diarisation (OFF by default, requires HuggingFace token) |
| `-h, --help` | Show help message |

**Note:** The `--single-file` option is only available for HPC scripts.

See [docs/advanced_usage.md](docs/advanced_usage.md) for detailed usage examples of advanced features.

## Output Structure

```
output/
├── transcripts/                              # Processed transcription files
│   ├── filename_transcript.txt               # Base transcript (always created)
│   ├── filename_transcript.docx              # Base Word document (always created)
│   ├── filename_transcript_with_speakers.txt # With speaker labels (if --speaker-attribution)
│   └── filename_transcript_with_speakers.docx# Speaker-attributed Word doc (if --speaker-attribution)
└── enhanced_audio/                           # Processed audio (if --save-enhanced-audio)
    └── filename_enhanced.wav
```

## Documentation

- **[docs/architecture.md](docs/architecture.md)** - System architecture and processing pipeline details
- **[docs/advanced_usage.md](docs/advanced_usage.md)** - Advanced features:
  - Speaker Attribution
  - Repetition Fixing
  - Multilingual Name Masking
  - Optional Output Features
- **[docs/hpc_usage.md](docs/hpc_usage.md)** - HPC cluster usage guide with SLURM job management
- **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** - Common errors, solutions and known issues
- **[PYANNOTE_SETUP_GUIDE.md](PYANNOTE_SETUP_GUIDE.md)** - Speaker attribution setup guide

## Licence

This project was developed by Dr Pablo Bernabeu at the Department of Education at the University of Oxford. It is licenced under the [Creative Commons Attribution 4.0 International licence](https://creativecommons.org/licenses/by/4.0/legalcode.en).

## Citation

If you use this workflow in your research, please cite:

```cff
cff-version: "1.2.0"
message: "If you use this software, please cite it as below."
title: "Secure and Scalable Speech Transcription for Local and HPC"
authors:
  - given-names: "Pablo"
    family-names: "Bernabeu"
    affiliation: "Department of Education, University of Oxford"
date-released: "2025-11-12"
version: "1.0.0"
url: "https://github.com/pablobernabeu/secure_local_HPC_speech_transcription"
abstract: "A production-ready local transcription workflow leveraging OpenAI's Whisper models that addresses the limitations of cloud-based solutions through complete data sovereignty, unlimited scale, reproducible processing and advanced quality control, while maintaining GDPR compliance."
preferred-citation: |
  @software{secure_local_HPC_speech_transcription,
    title={Secure and Scalable Speech Transcription for Local and HPC},
    author={Pablo Bernabeu},
    year={2025},
    url={https://github.com/pablobernabeu/secure_local_HPC_speech_transcription}
  }
```
