
# Secure and Scalable Speech Transcription for Local and HPC

Production-grade automated speech transcription system with audio enhancement, speaker identification and comprehensive text processing. Designed for high-performance computing environments with GPU acceleration and SLURM job scheduling.

## Overview

This system provides end-to-end speech processing capabilities including audio enhancement, machine learning-based transcription, text cleaning and privacy protection. The pipeline supports batch processing with parallel job execution for efficient processing of large audio datasets.

## System Architecture

### Core Components

1. **Audio Enhancement Pipeline**

   - Spectral noise reduction using first 0.5s as noise reference
   - Dynamic range compression (4:1 ratio above 0.1 threshold)
   - Signal amplification (3.61x gain)
   - 16kHz resampling for optimised speech recognition
   - Automatic gain control and normalization

2. **Transcription Engine**

   - Default: OpenAI Whisper Large v3 model
   - Optional: Custom HuggingFace models (e.g., other Whisper variants)
   - GPU-accelerated inference with automatic fallback to CPU
   - Automatic model caching and optimisation
   - Robust error handling and fallback mechanisms

3. **Text Processing Subsystem**

   - **Automatic Quality Improvements**: Intelligent detection and correction of transcription artifacts
     - Massive repetition removal (handles AI-generated artifacts like repeated sentences)
     - Punctuation spacing fixes (proper spacing before/after punctuation marks)
     - Enhanced name masking with context awareness to prevent false positives
   - Unicode artifact removal and emoji filtering
   - Repetitive pattern detection and correction
   - Comprehensive spelling correction database
   - **Enhanced personal name masking**: Curated multilingual database with 1,793 names across 9 languages (English, Chinese, French, German, Hindi, Spanish, Italian, Arabic, Polynesian)
     - Intelligent filtering prevents masking common English words (e.g., "The", "Okay", "Yeah", "Well", "But")
     - Case-insensitive name detection for comprehensive coverage
     - Surname-specific detection with [SURNAME] placeholder
     - Optional Facebook database (730K+ first names, 980K+ surnames) for comprehensive global coverage with higher false positive rate
   - Professional formatting and structure standardization

4. **Output Management**
   - Dual format generation (plain text and Microsoft Word documents)
   - Organized directory structure with preserved enhanced audio
   - Comprehensive processing metadata and timestamps

## Installation and Setup

### System Requirements

- **Python 3.12** (recommended for HPC environments)
  - Python 3.13 has limited package availability (avoid for production)
  - Python 3.11 supported but 3.12 preferred for stability
- **PyTorch 2.5.1+cpu** (stable, torchcodec-compatible)
  - Avoid PyTorch 2.7+ on CPU-only systems (ABI compatibility issues)
- CUDA-compatible GPU (recommended) or CPU-only mode
- 32GB RAM minimum for batch processing
- SLURM job scheduler (for HPC environments)

### Tested Package Versions (HPC Production)

The following versions are **verified working** in HPC environments:

```
Python: 3.12.x
PyTorch: 2.5.1+cpu
TorchVision: 0.20.1+cpu
TorchAudio: 2.5.1+cpu
Transformers: 4.45.0+
Pyannote.audio: 3.1.0-3.3.x (NOT 4.x - requires torch>=2.8)
```

**Why these specific versions?**
- **Python 3.12**: Full wheel availability, production-stable
- **PyTorch 2.5.1**: Last stable version before 2.7.x introduced breaking ABI changes
- **TorchCodec compatibility**: PyTorch 2.5.1 works with transformers audio backend
- **Pyannote 3.x**: Compatible with PyTorch 2.5.1 (v4.x requires torch>=2.8.0)

**Known Issues to Avoid:**
- ❌ Python 3.13 + PyTorch 2.5.1: No wheels available (torchvision 0.20.1 missing)
- ❌ PyTorch 2.7.1+cpu on GPU nodes: Symbol mismatch with torchcodec (`undefined symbol: _ZNK3c107SymBool...`)
- ❌ PyTorch 2.8.0+cpu: May have torchcodec compatibility issues on some systems
- ❌ Pyannote 4.0.1: Requires PyTorch 2.8.0+ (incompatible with stable 2.5.1)

### Initial Setup (One-time)

**Step 1: Install Core Dependencies**

**Local/Development:**

```bash
# Clone the repository
git clone <repository-url>
cd speech_transcription

# Run one-time setup (creates venv, installs packages, caches models)
chmod +x scripts/setup_environment.sh
./scripts/setup_environment.sh
```

**HPC (CRITICAL - Read Carefully!):**

```bash
# Clone the repository
git clone <repository-url>
cd speech_transcription

# CRITICAL: Activate environment BEFORE running setup
# This ensures packages install to project space, not your personal quota
# Note: $DATA is an environment variable set by your HPC system
source activate_project_env.sh

# Now run setup
python scripts/install_requirements.py
```

**⚠️ HPC IMPORTANT:** Always activate `activate_project_env.sh` before any setup or package installation. This ensures:
- Packages install to **project space** (`$DATA/speech_transcription_env/`, shared quota, typically ~200GB+)
- NOT to **personal space** (`~/.local/`, your limited quota, typically ~20GB)
- Correct Python environment and cache directories are used

The setup script will:

- Create a Python virtual environment
- Install all required packages with CUDA support
- Set up proper cache directories for models
- Optionally pre-cache Whisper models (~1.5GB download)
- **Ask if you want to set up speaker attribution** (optional)
- Verify all dependencies are working

The setup script now **includes an optional step for speaker attribution**. When prompted during setup, you can:
- Choose "yes" to set up pyannote immediately (guided setup)
- Choose "no" to skip and run `python scripts/setup_pyannote.py` later

**⏱️ Total setup time:** 15-30 minutes (including optional speaker attribution)

**📖 For detailed speaker attribution setup:** See [PYANNOTE_SETUP_GUIDE.md](PYANNOTE_SETUP_GUIDE.md)

### Environment Activation (Per Session)

After initial setup, activate the environment for each session:

```bash
source activate_project_env.sh
```

## Usage

### 🚀 Quick Reference

**For HPC Production Use (Recommended):**
```bash
# Multiple files (batch)
./HPC_scripts/submit_transcription.sh --mask-personal-names

# Single file with custom name
./HPC_scripts/submit_transcription.sh --single-file audio_input/interview.wav --output-name "client_call" --mask-personal-names
```

**For Local Testing/Development:**
```bash
# Direct Python execution (no queue, runs immediately)
python transcription.py "audio_input/test.wav" --mask-personal-names

# With language specification for Spanish transcription
python transcription.py "audio_input/test.wav" --mask-personal-names --language spanish

# With audio enhancement enabled (optional, improves quality but takes longer)
python transcription.py "audio_input/test.wav" --mask-personal-names --enhance-audio

# With repetition fixing for cleaner output
python transcription.py "audio_input/test.wav" --mask-personal-names --fix-spurious-repetitions

# With custom output name
python transcription.py "audio_input/interview.wav" --mask-personal-names --output-name "client_meeting"
```

### Quick Start - Batch Processing

The simplest way to process multiple audio files:

```bash
# Place audio files (.wav, .mp3, .m4a, .flac, .ogg, .aac) in audio_input/ directory
# Submit batch job with name masking enabled
HPC_scripts/submit_transcription.sh --mask-personal-names

# Submit batch job with repetition fixing for cleaner transcripts
HPC_scripts/submit_transcription.sh --fix-spurious-repetitions

# Submit batch job with both name masking and repetition fixing
HPC_scripts/submit_transcription.sh --mask-personal-names --fix-spurious-repetitions

# Submit batch job with name masking and save logs and enhanced audio
HPC_scripts/submit_transcription.sh --mask-personal-names --save-name-masking-logs --save-enhanced-audio

# Submit batch job with multilingual name masking (all languages)
HPC_scripts/submit_transcription.sh --mask-personal-names

# Submit batch job with specific languages for targeted masking
HPC_scripts/submit_transcription.sh --mask-personal-names --languages-for-name-masking english spanish

# Submit batch job with Chinese and Hindi for Asian content
HPC_scripts/submit_transcription.sh --mask-personal-names --languages-for-name-masking chinese hindi

# Submit batch job with Facebook first names + specific language surnames
HPC_scripts/submit_transcription.sh --mask-personal-names --use-facebook-names-for-masking --languages-for-name-masking english french

# Submit batch job without name masking
HPC_scripts/submit_transcription.sh
```

The system automatically:

- Detects all audio files in `audio_input/`
- Determines the correct number of parallel jobs
- Submits the SLURM job array
- Processes files in parallel on available GPUs

### Single File Processing with Custom Names

Process a specific audio file with optional custom output naming:

```bash
# Basic single file transcription
HPC_scripts/submit_transcription.sh --single-file audio_input/interview.wav --force-english --mask-personal-names

# Single file with custom output name
HPC_scripts/submit_transcription.sh --single-file audio_input/recording_2024_10_03.wav --output-name "client_interview_oct" --mask-personal-names

# Single file without name masking
HPC_scripts/submit_transcription.sh --single-file audio_input/myfile.mp3 --force-english
```

**Single File Mode Features:**
- **`--single-file <path>`**: Specify exact file to transcribe (supports all audio formats)
- **`--output-name <name>`**: Custom name for output files (without extension)
- **No array jobs**: Submits single SLURM job instead of job array
- **Same processing**: Uses identical transcription pipeline as batch mode
- **GPU acceleration**: Automatically uses GPU if available, falls back to CPU

**Output files** will be named:
- With custom name: `output/transcripts/{custom_name}_transcript.txt` and `.docx`
- Without custom name: `output/transcripts/{original_filename}_transcript.txt` and `.docx`

### Direct Python Processing (Local/Interactive)

For **local development, testing, or interactive use** (runs immediately on current machine):

```bash
# Basic transcription (runs locally, no HPC queue)
python transcription.py "audio_input/myfile.wav"

# With name masking (runs locally)
python transcription.py "audio_input/myfile.wav" --mask-personal-names

# With repetition fixing to remove Whisper artifacts (runs locally)
python transcription.py "audio_input/myfile.wav" --fix-spurious-repetitions

# With both name masking and repetition fixing (runs locally)
python transcription.py "audio_input/myfile.wav" --mask-personal-names --fix-spurious-repetitions

# With name masking and save logs and enhanced audio (runs locally)
python transcription.py "audio_input/myfile.wav" --mask-personal-names --save-name-masking-logs --save-enhanced-audio

# With comprehensive Facebook names database (runs locally, review output carefully)
python transcription.py "audio_input/myfile.wav" --mask-personal-names --use-facebook-names-for-masking --save-name-masking-logs

# With name masking but excluding specific names (e.g., public figures)
python transcription.py "audio_input/myfile.wav" --mask-personal-names --exclude-names-from-masking "Einstein,Darwin,Shakespeare"

# With name masking using exclusion file
python transcription.py "audio_input/myfile.wav" --mask-personal-names --exclude-names-file excluded_names.txt

# With custom output name (runs locally)
python transcription.py "audio_input/myfile.wav" --mask-personal-names --output-name "my_custom_name"

# With custom model (runs locally)
python transcription.py "audio_input/myfile.wav" --model "openai/whisper-large-v3"
```

**When to use Python direct:**
- ✅ Testing on small files locally
- ✅ Development and debugging
- ✅ Quick one-off transcriptions
- ❌ **NOT for HPC clusters** (bypasses job scheduler)
- ❌ **NOT for large files** (may overwhelm login nodes)

### HPC Single File Processing (Recommended for Production)

For **production use on HPC clusters** (submits to SLURM queue with proper resource allocation):

```bash
# Single file via HPC job system (recommended)
./HPC_scripts/submit_transcription.sh --single-file audio_input/interview.wav --force-english --mask-personal-names

# Single file with repetition fixing for cleaner transcripts
./HPC_scripts/submit_transcription.sh --single-file audio_input/interview.wav --fix-spurious-repetitions --mask-personal-names

# Single file with custom output name via HPC
./HPC_scripts/submit_transcription.sh --single-file audio_input/recording.wav --output-name "client_interview_oct" --mask-personal-names
```

**When to use HPC single file:**
- ✅ **Production transcription on HPC clusters**
- ✅ **Proper resource allocation** (GPU, memory, time limits)
- ✅ **Queue management** (doesn't overwhelm cluster)
- ✅ **Same environment as batch jobs** (consistent results)
- ✅ **Full logging and monitoring**

### Key Differences Summary

| Method | Execution | Resource Management | Use Case |
|--------|-----------|-------------------|----------|
| **Python Direct** | Immediate, local | Manual/none | Development, testing, small files |
| **HPC Single File** | Queued, scheduled | SLURM managed | Production, large files, cluster use |
| **HPC Batch** | Queued, parallel | SLURM managed | Multiple files, production |

### Advanced Batch Processing

For direct SLURM submission (requires manual array size):

```bash
# Count audio files first
AUDIO_COUNT=$(find audio_input \( -name "*.wav" -o -name "*.WAV" \) -type f | wc -l)

# Submit with correct array size
sbatch --array=1-$AUDIO_COUNT HPC_scripts/batch_transcription.sh --mask-personal-names
```

## Monitoring Jobs

```bash
# Check job status
squeue --me

# Detailed job information
sacct -j <job_id> --format=JobID,JobName,State,ExitCode,Start,End,Elapsed

# View real-time logs
tail -f transcription_<job_id>_<task_id>.out
```

## Output Structure

```
output/
├── transcriptions/                    # Processed transcription files
│   ├── filename_transcription.txt     # Base transcript (always created)
│   ├── filename_transcription.docx    # Base Word document (always created)
│   ├── filename_transcription_with_speakers.txt   # With speaker labels (if --speaker-attribution enabled)
│   └── filename_transcription_with_speakers.docx  # Speaker-attributed Word doc (if --speaker-attribution enabled)
└── enhanced_audio/                    # Processed audio files (if --save-enhanced-audio enabled)
    └── filename_enhanced.wav
```

**Note:** When speaker attribution is enabled, you get **both** regular and speaker-attributed versions. This gives you flexibility to use whichever format suits your needs.

## Processing Pipeline

1. **Audio Enhancement**: Signal conditioning and noise reduction
2. **Transcription**: ML-based speech-to-text conversion
3. **Automatic Quality Improvements**:
   - **Repetition Detection**: Removes conspicuous repetitions typically caused by AI transcription glitches (e.g., sentences repeated 80+ times)
   - **Optional Repetition Fixing**: Additional filtering with `--fix-spurious-repetitions` flag to remove subtle repetitive patterns and artifacts introduced by Whisper models
   - **Punctuation Correction**: Fixes spacing issues around punctuation marks, quotation marks and parentheses
   - **Smart Name Masking**: Production-grade privacy protection with global database (730K+ first names, 980K+ surnames)
     - Intelligent filtering prevents masking common English words like "The", "Okay", "Yeah", "Well", "But"  
     - Case-insensitive detection covers names regardless of capitalization
     - Surname-specific detection with [SURNAME] placeholder
     - Comprehensive exclusion list for conversation words, prepositions and common nouns
4. **Text Processing**: Additional cleaning, correction and privacy protection
5. **Output Generation**: Formatted document creation

## Configuration Parameters

| Parameter         | Default                   | Description                           |
| ----------------- | ------------------------- | ------------------------------------- |
| Model             | `openai/whisper-large-v3` | Default transcription model           |
| Sampling Rate     | 16kHz                     | Audio processing frequency            |
| Gain              | 3.61x                     | Signal amplification factor           |
| Compression Ratio | 4:1                       | Dynamic range compression             |
| Noise Alpha       | 2.0                       | Spectral subtraction coefficient      |
| Name Masking      | Optional                  | Privacy protection for personal names |

## Command Line Options

Both `transcription.py` and `HPC_scripts/submit_transcription.sh` support the same options:

```bash
# Direct Python execution
python transcription.py <audio_file> [options]

# HPC batch submission (batch mode - all files in audio_input/)
HPC_scripts/submit_transcription.sh [options]

# HPC single file submission (specify which file to process)
HPC_scripts/submit_transcription.sh --single-file <audio_file> [options]
```

### Available Options

| Option | Description |
|--------|-------------|
| `--model MODEL` | HuggingFace model ID (default: openai/whisper-large-v3) |
| `--output-name <name>` | Custom name for output files (without extension) |
| `--language LANG` | Specify transcription language (e.g., `english`, `spanish`, `french`). Default: auto-detect language |
| `--enhance-audio` | Enable audio enhancement for better transcription quality (disabled by default) |
| `--mask-personal-names` | Enable personal name masking (OFF by default) |
| `--fix-spurious-repetitions` | Remove spurious repetitions introduced by Whisper models (OFF by default) |
| `--save-name-masking-logs` | Save detailed name replacement logs to `name_masking_logs/` directory (OFF by default) |
| `--save-enhanced-audio` | Save enhanced audio files to `output/enhanced_audio/` directory (OFF by default) |
| `--use-facebook-names-for-masking` | Use comprehensive Facebook first names database (~730K names) for masking (OFF by default). **Warning:** Higher false positive rate; requires manual review. The curated internal database is recommended for most use cases. |
| `--use-facebook-surnames-for-masking` | Use comprehensive Facebook surnames database (~980K surnames) for masking (OFF by default). **Warning:** Higher false positive rate; requires manual review. The curated internal database is recommended for most use cases. |
| `--languages-for-name-masking LANG ...` | Select specific languages for curated name database (choices: `english`, `chinese`, `french`, `german`, `hindi`, `spanish`, `italian`, `arabic`, `polynesian`; default: all 9 languages) |
| `--exclude-common-english-words-from-name-masking` | Exclude common English words (e.g., "will", "long", "art", "hall") from name masking database. **Default: ON when `--language english` is specified, OFF otherwise.** Prevents false positives where common words are incorrectly masked as names. |
| `--exclude-names-from-masking "name1,name2,..."` | Comma-separated list of specific names to exclude from masking (case-insensitive). Useful for preserving public figures, celebrities or specific participants. Example: `--exclude-names-from-masking "Einstein,Darwin,Newton"` |
| `--exclude-names-file path/to/file.txt` | Path to file containing names to exclude from masking (one name per line, case-insensitive). Can be combined with `--exclude-names-from-masking`. |
| `--speaker-attribution` | Enable speaker diarisation (attribution) using pyannote/speaker-diarization-3.1 (OFF by default). Requires HuggingFace token. **Produces two versions:** base transcript + speaker-attributed transcript. **Note:** Accuracy strongly depends on recording quality, number of speakers, and degree of similarity across speakers. |
| `-h, --help` | Show help message |

**Note:** The `--single-file` option is only available for HPC scripts, not for direct Python execution.

### scripts/download_model.py

Pre-downloads models to avoid network timeouts during batch processing. Should be run on login node before submitting batch jobs.

```bash
# Download default models (openai/whisper-large-v3 + pyannote/speaker-diarization-3.1)
python scripts/download_model.py

# Download specific models (note: model names use American spelling)
python scripts/download_model.py --model "openai/whisper-medium" --diarisation-model "pyannote/speaker-diarization"
```

**Usage in workflow:**

1. Run `python scripts/download_model.py` on login node to cache models
2. Submit batch jobs with confidence that models are already downloaded

This solves the common issue where batch jobs fail due to model download timeouts or network connectivity problems.

### Language Specification

**Problem:** Whisper models may occasionally switch to other languages due to phonetic similarities, or you may want to process content in a specific language.

**Solution:** Use the `--language` argument to specify the transcription language:

```bash
# For batch processing with English language
HPC_scripts/submit_transcription.sh --language english

# For single files with Spanish language
HPC_scripts/submit_transcription.sh --single-file "audio_input/Interview 1.WAV" --language spanish

# For automatic language detection (default behaviour)
HPC_scripts/submit_transcription.sh
```

**Supported languages:** `english`, `spanish`, `french`, `german`, `italian`, `portuguese`, `chinese`, `japanese`, `korean`, `arabic`, and many others supported by Whisper.

This allows the model to transcribe in the specified language or automatically detect the language when no `--language` argument is provided.

### Repetition Fixing

**Problem:** Whisper models sometimes introduce spurious repetitions or get stuck in repetitive patterns, especially with challenging audio or when processing longer segments.

**Examples of repetition artifacts:**
- Repeated phrases: "And then, and then, and then he said..."
- Stuck patterns: "The the the meeting will start"
- Echo effects: "Hello hello, how are you you?"
- Loop artifacts: Entire sentences repeated multiple times

**Solution:** Use the `--fix-spurious-repetitions` flag to enable advanced repetition detection and removal:

```bash
# For single files with Python
python transcription.py "audio_input/interview.wav" --fix-spurious-repetitions

# For batch processing
HPC_scripts/submit_transcription.sh --fix-spurious-repetitions

# Combined with other options
HPC_scripts/submit_transcription.sh --mask-personal-names --fix-spurious-repetitions --force-english
```

**How it works:**
- Detects and removes repetitive word patterns
- Identifies and fixes stuck transcription loops
- Preserves intentional repetitions (like emphasis or natural speech patterns)
- Uses context-aware algorithms to distinguish between artifacts and genuine repetition

**When to use:**
- ✅ Poor quality audio with background noise
- ✅ Long audio files (>30 minutes) where models may get unstable
- ✅ Technical or challenging content where models struggle
- ✅ When you notice repetitive artifacts in initial transcriptions
- ❌ High-quality, short audio files (may not be necessary)

### Speaker Attribution

**Feature:** Automatic speaker diarisation (also called speaker attribution) using pyannote/speaker-diarization-3.1 model from HuggingFace.

**Technical Note:** *Diarisation* is the technical term for determining "who spoke when" in an audio recording. In this context, *attribution* means the same thing—assigning speech segments to different speakers. Both terms are used interchangeably.

**Output format:** When speaker attribution is enabled, the system produces **two sets of transcripts**:

1. **Base transcripts** (standard filenames):
   - `filename_transcript.txt`
   - `filename_transcript.docx`
   - Clean transcription without speaker labels
   - Use for readability or when speaker identity not needed

2. **Speaker-attributed transcripts** (with `_with_speakers` suffix):
   - `filename_transcript_with_speakers.txt`
   - `filename_transcript_with_speakers.docx`
   - Includes speaker labels like `[SPEAKER_00]`, `[SPEAKER_01]`, etc. before each speaker's segment
   - Use for analysing who said what

**Why both versions?** Speaker labels can make transcripts harder to read, so clean versions are provided alongside attributed versions. You can choose which to use based on your needs.

**📖 Setup Guide:** See [PYANNOTE_SETUP_GUIDE.md](PYANNOTE_SETUP_GUIDE.md) for complete setup instructions and troubleshooting.

**Quick Setup:**
```bash
python scripts/setup_pyannote.py  # Interactive setup wizard (10-15 minutes)
```

**Usage:**
```bash
# For single files with Python
python transcription.py "interview.wav" --speaker-attribution

# For batch processing
HPC_scripts/submit_transcription.sh --speaker-attribution

# Combined with other options
HPC_scripts/submit_transcription.sh --mask-personal-names --speaker-attribution --language english
```

⚠️ **Accuracy Factors:**
- **Recording quality**: Clear audio with minimal background noise produces better results
- **Number of speakers**: Works best with 2-4 speakers; accuracy decreases with more speakers
- **Speaker similarity**: Similar-sounding voices (e.g., same gender, age, accent) are harder to distinguish
- **Speaker overlap**: Simultaneous speech reduces attribution accuracy
- **Microphone setup**: Single microphone recordings are more challenging than multi-mic setups

**When to use:**
- ✅ Multi-speaker interviews or focus groups
- ✅ Panel discussions or meetings
- ✅ Conversations with distinct voices
- ✅ High-quality recordings with clear speakers
- ❌ Single speaker recordings (unnecessary)
- ❌ Poor quality audio with heavy background noise
- ❌ Many speakers with similar voices

**Example output:**

**Base transcript** (`filename_transcript.txt`):
```
Hello and welcome to today's interview. Thank you for joining us.

Thank you for having me. I'm excited to be here.

Let's start with your background. Can you tell us about your research?

Certainly. I've been working on computational linguistics for the past five years...
```

**Speaker-attributed transcript** (`filename_transcript_with_speakers.txt`):
```
[SPEAKER_00] Hello and welcome to today's interview. Thank you for joining us.

[SPEAKER_01] Thank you for having me. I'm excited to be here.

[SPEAKER_00] Let's start with your background. Can you tell us about your research?

[SPEAKER_01] Certainly. I've been working on computational linguistics for the past five years...
```

**Need help?** See [PYANNOTE_SETUP_GUIDE.md](PYANNOTE_SETUP_GUIDE.md) for:
- Step-by-step setup instructions
- Common issues and solutions
- HPC-specific guidance
- Performance optimisation tips

## Optional Output Features

### Name Masking Logs

By default, when name masking is enabled, the system tracks which names were replaced but doesn't save detailed logs. Use `--save-name-masking-logs` to enable comprehensive logging:

**Feature:**
- Saves detailed CSV logs to `name_masking_logs/` directory (in project root)
- Tracks every name replacement with context sentences
- Includes replacement order, original text and masked version

**When to use:**
- ✅ When you need audit trails for privacy compliance
- ✅ For reviewing masking accuracy and false positives
- ✅ When processing sensitive content requiring documentation
- ❌ For casual transcription where detailed logs aren't needed

**Example:**
```bash
# Save name masking logs
python transcription.py "interview.wav" --mask-personal-names --save-name-masking-logs
HPC_scripts/submit_transcription.sh --mask-personal-names --save-name-masking-logs
```

### Enhanced Audio Files

By default, the system enhances audio for better transcription but doesn't save the enhanced files. Use `--save-enhanced-audios` to preserve them:

**Feature:**
- Saves enhanced audio files to `output/enhanced_audio/` directory
- Files include noise reduction, amplification and optimisation
- Useful for quality verification or reprocessing

**When to use:**
- ✅ When you want to verify audio enhancement quality
- ✅ For reprocessing with different transcription models
- ✅ When archiving enhanced versions for future use
- ❌ To save disk space (enhanced files can be 2x original size)

**Example:**
```bash
# Save enhanced audio files
python transcription.py "interview.wav" --save-enhanced-audio
HPC_scripts/submit_transcription.sh --save-enhanced-audio
```

**Note:** Both features are OFF by default to conserve storage space and focus on essential transcription output.

## Multilingual Name Masking Database

### Overview

The system includes a comprehensive multilingual name database loaded from `data/curated_names.csv` with carefully curated names from 6 major languages, providing safer and more targeted name masking compared to the massive Facebook global database. The CSV format allows easy expansion and maintenance of the name database.

### Supported Languages

- **English**: 185 first names, 41 surnames (common English names)
- **Chinese**: 95 first names, 40 surnames (romanized Pinyin)  
- **French**: 106 first names, 25 surnames (popular French names)
- **German**: 80 first names, 30 surnames (common German names)
- **Hindi**: 96 first names, 28 surnames (romanized Indian names)
- **Spanish**: 105 first names, 34 surnames (Hispanic names)

**Total Coverage**: 618 first names, 184 surnames across all languages

### Default Behaviour

**Without language specification (RECOMMENDED):**
- Uses ALL 6 languages for comprehensive coverage
- Balanced approach between coverage and false positives
- Suitable for international content with diverse speakers

### Language Selection Options

Use the `--languages-for-name-masking` argument to select specific languages for the curated database:

```bash
# Use all languages (default behaviour)
python transcription.py interview.wav --mask-personal-names

# Use only English names
python transcription.py interview.wav --mask-personal-names --languages-for-name-masking english

# Use multiple specific languages
python transcription.py interview.wav --mask-personal-names --languages-for-name-masking english spanish

# Use Chinese and Hindi for Asian content
python transcription.py interview.wav --mask-personal-names --languages-for-name-masking chinese hindi

# HPC batch with language selection
HPC_scripts/submit_transcription.sh --mask-personal-names --languages-for-name-masking english french german
```

### Language Selection Examples

#### All Languages (Default):
```
Input:  "Hello Maria Rodriguez, this is John Smith and Wei Chen speaking with Raj Patel and François Dubois."
Output: "Hello [NAME] [SURNAME], this is [NAME] [SURNAME] and [SURNAME] [SURNAME] speaking with [NAME] [SURNAME] and François [SURNAME]."
```

#### English Only:
```
Input:  "Hello Maria Rodriguez, this is John Smith and Wei Chen speaking with Raj Patel and François Dubois."
Output: "Hello Maria [SURNAME], this is [NAME] [SURNAME] and Wei Chen speaking with Raj Patel and François Dubois."
```

#### Chinese + Spanish Only:
```
Input:  "Li Wei and Zhang Yu were talking to Carlos Martinez and Ana Rodriguez."
Output: "[SURNAME] [SURNAME] and [SURNAME] [SURNAME] were talking to [NAME] [SURNAME] and [NAME] [SURNAME]."
```

### When to Use Language Selection

**✅ Use specific languages when:**
- You know the linguistic background of speakers
- Processing content with specific regional focus
- Minimizing false positives for particular language contexts
- Working with specialised international content

**✅ Use all languages (default) when:**
- Processing diverse international content
- Uncertain about speaker backgrounds
- Maximum name coverage is needed
- Working with multicultural environments

### Technical Implementation

- **Unicode Support**: Proper handling of non-Latin scripts
- **Romanization**: Chinese (Pinyin) and Hindi names in Latin script
- **Alphabetical Organisation**: Names sorted within each language set
- **Memory Efficient**: Only selected languages loaded into memory
- **Quality Control**: ~200 carefully selected popular names per language

### Combining with Facebook Database

You can combine language selection with Facebook database options:

```bash
# Facebook first names + selected languages for surnames
python transcription.py interview.wav --mask-personal-names --use-facebook-names-for-masking --languages-for-name-masking english spanish

# Facebook surnames + selected languages for first names  
python transcription.py interview.wav --mask-personal-names --use-facebook-surnames-for-masking --languages-for-name-masking chinese hindi

# Both Facebook databases + language selection (for curated backup)
python transcription.py interview.wav --mask-personal-names --use-facebook-names-for-masking --use-facebook-surnames-for-masking --languages-for-name-masking english
```

**Note**: When Facebook databases are enabled, the `--languages-for-name-masking` parameter affects the curated database used as a backup/supplement.

### Common English Word Filtering

**Problem**: Some legitimate names (like "Will", "Art", "Long", "Hall") are also common English words, leading to false positives where normal text is incorrectly masked.

**Example of the problem:**
```
Input:  "They will continue to art class in the long hall."
Output (without filtering): "They [NAME] continue to [NAME] class in the [NAME] [SURNAME]."
Output (with filtering):    "They will continue to art class in the long hall."
```

**Solution**: The `--exclude-common-english-words-from-name-masking` flag filters out ~200 common English words from the name masking database.

#### Smart Default Behaviour

The system automatically applies intelligent defaults:

- **English transcripts (`--language english`)**: Filtering is **ON by default** to prevent false positives
- **Other languages**: Filtering is **OFF by default** to preserve legitimate names (e.g., Chinese names "An" and "Long")
- **No language specified**: Filtering is **OFF by default** (auto-detect mode assumes multilingual)

#### Usage Examples

```bash
# English transcript - filtering enabled automatically
python transcription.py interview.wav --mask-personal-names --language english
# Output: "will continue" stays as-is, actual names like "Pablo" → [NAME]

# Chinese transcript - filtering disabled automatically  
python transcription.py interview.wav --mask-personal-names --language chinese
# Output: Chinese name "An" → [NAME], English word "an" → [NAME] (Chinese "An" preserved)

# Override default for English (disable filtering)
python transcription.py interview.wav --mask-personal-names --language english --exclude-common-english-words-from-name-masking=false
# Output: "will continue" → "[NAME] continue" (filtering disabled)

# HPC batch processing with automatic filtering
HPC_scripts/submit_transcription.sh --mask-personal-names --language english
```

#### Filtered Words

The system filters ~200 common English words including (but not limited to):
- **Articles/pronouns**: an, will, as, may, can, is, are, was
- **Common verbs**: long, art, drew, page, grant
- **Location words**: hall, hunt, west, woods, north, south
- **Time words**: june, may, august, winter, spring
- **Other**: parker, ward, amber, grace, holly, ivy, rose, ruby, fox

This prevents sentences like "We will long for grace and art" from becoming "We [NAME] [NAME] for [NAME] and [NAME]".

#### When to Use

**✅ Enable filtering (or use `--language english`) when:**
- Transcribing English-language audio
- False positives are causing readability issues
- Common words like "will", "may", "long" appear frequently in context

**✅ Disable filtering (or avoid `--language english`) when:**
- Transcribing non-English audio with English loanwords
- Names like Chinese "An" or "Long" are expected
- Working with international speakers using English names
- Processing multilingual content with diverse name origins

### Excluding Specific Names from Masking

Sometimes you may want to preserve certain names in your transcripts whilst masking others. This is useful for keeping public figures, celebrities or specific participants identifiable.

**Use case**: Mask most names for privacy but preserve well-known public figures (e.g., "Einstein", "Darwin") or specific participants for reference.

#### Command-Line Options

**Option 1: Comma-separated list**
```bash
python transcription.py interview.wav --mask-personal-names \
  --exclude-names-from-masking "Einstein,Darwin,Newton"

# HPC batch processing
HPC_scripts/submit_transcription.sh --mask-personal-names \
  --exclude-names-from-masking "Einstein,Curie"
```

**Option 2: File with name list** (one name per line)
```bash
python transcription.py interview.wav --mask-personal-names \
  --exclude-names-file excluded_names.txt

# HPC batch processing
HPC_scripts/submit_transcription.sh --mask-personal-names \
  --exclude-names-file excluded_names.txt
```

**Option 3: Combine both methods**
```bash
python transcription.py interview.wav --mask-personal-names \
  --exclude-names-file celebrities.txt \
  --exclude-names-from-masking "ResearcherName"
```

#### Behaviour

- **Case-insensitive**: "Einstein", "einstein", "EINSTEIN" all treated identically
- **Applies to both first and surnames**: Excluded names removed from both databases
- **Works with all database options**: Compatible with curated and Facebook databases
- **Only specified names excluded**: All other names still masked normally

#### When to Use

**✅ Recommended for:**
- Content referencing well-known public figures (Einstein, Shakespeare, Darwin)
- Preserving specific participants whilst masking others
- Educational materials where certain names provide essential context
- Names already in public domain

**❌ Avoid when:**
- All participants require equal privacy protection
- Unsure which names should be preserved
- Processing highly sensitive content requiring maximum privacy

### Audio Enhancement

Audio enhancement is **optional** and disabled by default for faster processing.

**When to enable:** Use the `--enhance-audio` flag when working with low-quality audio that could benefit from noise reduction and signal conditioning:

```bash
# For single files with audio enhancement
python transcription.py "audio_input/noisy_interview.wav" --enhance-audio --mask-personal-names

# For batch processing with audio enhancement
HPC_scripts/submit_transcription.sh --enhance-audio --mask-personal-names

# Save enhanced audio files for inspection or reuse
python transcription.py "audio_input/interview.wav" --enhance-audio --save-enhanced-audio
```

**Performance impact:** Audio enhancement adds processing time but can significantly improve transcription quality for:

- ✅ Noisy recordings with background sound
- ✅ Low-volume or distant speech
- ✅ Recordings with audio compression artifacts
- ❌ High-quality studio recordings (may not be necessary)

**Default behaviour:** When `--enhance-audio` is not specified, the system processes audio directly without enhancement for faster transcription.

## Facebook Names Database Option

### Overview

The system includes optional comprehensive names databases sourced from Facebook's `names-dataset` package, containing over **1.7 million names**:
- **730,000+ first names** from 106 countries
- **980,000+ surnames** from global datasets

**Database Source:** The names database is provided by Philippe Remy's `name-dataset` project, available at: https://github.com/philipperemy/name-dataset

**⚠️ IMPORTANT: These options are DISABLED by default** due to high false positive rates when masking common English words.

### Current Default Behaviour

**Without Facebook database flags (RECOMMENDED):**
- Uses curated database loaded from `data/curated_names.csv` (1,793 carefully selected names across 9 languages)
- Organised by language: `english`, `chinese`, `french`, `german`, `hindi`, `spanish`, `italian`, `arabic`, `polynesian`
- Each entry tagged as 'first' or 'last' name with language code
- Significantly reduced false positives (common English words excluded)
- Better precision for privacy protection
- Maintains conversation flow and readability
- Easily expandable by adding entries to CSV file

### Enabling Facebook Names Databases

**New Granular Control (Breaking Change):**
- `--use-facebook-names-for-masking`: Use Facebook's 730K+ first names database only
- `--use-facebook-surnames-for-masking`: Use Facebook's 980K+ surnames database only
- **Use both flags together** for full Facebook database coverage
- **Higher risk of false positives** when enabled

### Usage Examples

```bash
# Default behaviour (recommended) - uses curated names only
python transcription.py interview.wav --mask-personal-names

# HPC batch with curated names (recommended)
HPC_scripts/submit_transcription.sh --mask-personal-names

# Enable Facebook FIRST NAMES only (surnames remain curated)
python transcription.py interview.wav --mask-personal-names --use-facebook-names-for-masking

# Enable Facebook SURNAMES only (first names remain curated) 
python transcription.py interview.wav --mask-personal-names --use-facebook-surnames-for-masking

# Enable BOTH Facebook databases (comprehensive but more false positives)
python transcription.py interview.wav --mask-personal-names --use-facebook-names-for-masking --use-facebook-surnames-for-masking

# HPC batch with Facebook first names only
HPC_scripts/submit_transcription.sh --mask-personal-names --use-facebook-names-for-masking

# HPC batch with both Facebook databases
HPC_scripts/submit_transcription.sh --mask-personal-names --use-facebook-names-for-masking --use-facebook-surnames-for-masking
```

### When to Use Facebook Names Database

**⚠️ Warning:** The Facebook database option significantly increases false positives compared to the curated database. Manual quality review is essential when using this option.

**✅ Consider using when:**
- Processing international content with diverse name origins beyond the 9 supported languages
- Maximum name coverage is critical for privacy compliance
- You can manually review transcripts for false positives
- Processing technical or formal content with fewer conversation words

**❌ Avoid when:**
- Processing conversational speech with common English words
- Automated processing without manual review capability
- Readability and natural flow are priorities
- Working with informal interviews or casual conversations

### Expected Differences

#### Default Curated Database:
```
Speaker: "The meeting will begin soon. Thank you for joining, Mark."
Output:  "[NAME] meeting will begin soon. [NAME] you for joining, [NAME]."
```
*(Note: "The", "Thank", and "Mark" all detected as potential names)*

### Required Special Attention

**When using `--use-facebook-names-for-masking`, carefully review:**

1. **Transcripts:** Check for over-masking of common words
   - Look for `[NAME]` and `[SURNAME]` replacing common words
   - Verify conversation flow remains readable
   - Check if context clues remain for understanding

2. **Name Masking Logs:** Use `--save-name-masking-logs` for detailed tracking
   - Review `name_masking_logs/` CSV files for false positives
   - Audit masked terms to identify problematic patterns
   - Use logs to fine-tune masking for specific content types

3. **Quality Control Workflow:**
   ```bash
   # Enable detailed logging when using Facebook database
   python transcription.py interview.wav --mask-personal-names --use-facebook-names-for-masking --save-name-masking-logs
   
   # Review the logs before finalizing
   ls name_masking_logs/
   # Check: interview_name_changes_YYYY-MM-DD_HHMMSS.csv
   ```

### Technical Implementation

- **Default:** `load_global_names(use_facebook_database=False)`
- **Facebook Enabled:** `load_global_names(use_facebook_database=True)`
- **Memory Impact:** Facebook database requires ~50MB additional RAM
- **Processing Speed:** Minimal impact on transcription performance

### Recommendation

**For most users:** Stick with the default curated database (1,793 names across 9 languages) for better balance of privacy protection and readability. The curated database provides comprehensive coverage for English, Chinese, French, German, Hindi, Spanish, Italian, Arabic and Polynesian names whilst minimising false positives. Only enable the Facebook database when comprehensive global name coverage beyond these languages is absolutely essential and you can invest time in manual quality review.

## Error Handling

### Processing Modes: Batch vs Single File

**IMPORTANT:** The system supports two processing approaches:

#### 1. Batch Processing (Recommended for Multiple Files)

Process ALL audio files in the `audio_input/` directory:

```bash
# Processes all files with default settings
HPC_scripts/submit_transcription.sh

# With name masking enabled
HPC_scripts/submit_transcription.sh --mask-personal-names

# Force English-only transcription
HPC_scripts/submit_transcription.sh --language english --mask-personal-names

# Combine multiple options
HPC_scripts/submit_transcription.sh --mask-personal-names --language english --fix-spurious-repetitions
```

The system automatically detects all audio files and creates appropriate job arrays.

#### 2. Single File Processing

Process one specific audio file:

```bash
# Using submit_transcription.sh (recommended)
HPC_scripts/submit_transcription.sh --single-file audio_input/interview.wav --mask-personal-names

# With custom output name
HPC_scripts/submit_transcription.sh --single-file audio_input/recording.wav --output-name "client_meeting" --mask-personal-names
```

### Common Issues

The system implements comprehensive error handling including:

- Network connectivity validation for model downloads
- Audio file format verification and conversion
- Memory management for large file processing
- Automatic retry mechanisms for transient failures
- Graceful fallback from GPU to CPU processing

## Performance Characteristics

- Single file processing: ~40 minutes per hour of audio
- Batch processing: Linear scaling with available GPU resources
- Memory usage: 8-16GB per concurrent job
- Disk I/O: Enhanced audio files require 2x original file size

## Troubleshooting

### Common Issues

1. **"Audio file not found" error**

   - Ensure audio files are in `audio_input/` directory
   - Check file extensions (`.wav`, `.mp3`, `.m4a`, etc.)
   - Use `HPC_scripts/submit_transcription.sh` to auto-detect files

2. **Model download failures**

   - Check internet connectivity
   - Verify HuggingFace model name
   - Use default model: `openai/whisper-large-v3`

3. **GPU memory errors**

   - Reduce batch size or use CPU processing
   - Check available GPU memory with `nvidia-smi`

4. **SLURM job failures**
   - Check resource allocation in batch script
   - Verify account and partition settings
   - Monitor job logs for specific errors

## Technical Specifications

- Default Model: OpenAI Whisper Large v3
- Alternative Models: Any HuggingFace Whisper variant
- Framework: PyTorch with HuggingFace Transformers
- Audio Processing: librosa with custom enhancement pipeline
- Document Generation: python-docx with structured formatting
- Job Scheduling: SLURM with dynamic array job support

## Script Reference

### Core Processing Scripts

- **transcription.py**: Main transcription engine with enhanced metadata, language forcing and name masking
- **scripts/download_model.py**: Downloads and caches HuggingFace models locally to prevent batch job timeouts

### Environment Setup Scripts

- **scripts/setup_environment.sh**: One-time environment setup for new users (creates virtual environment, installs dependencies)
- **activate_project_env.sh**: Activates project environment for interactive use
- **activate_project_env_single.sh**: Alternative environment activation (purges modules first)

### Testing and Development Scripts

- **tests/test_transcription.py**: Unit tests for core transcription functions

### Package Configuration

- **setup.py**: Package installation and dependency management
- **requirements.txt**: Python dependencies list

## Directory Structure

```
├── transcription.py              # Main processing script
├── setup.py                      # Package configuration
├── requirements.txt              # Python dependencies
├── hf_token.txt                  # HuggingFace authentication token
│
├── scripts/                      # Utility and setup scripts
│   ├── download_model.py         # Model pre-download utility
│   ├── install_requirements.py   # Dependency installer
│   ├── setup_pyannote.py         # Speaker diarization setup
│   ├── setup_environment.sh      # Environment setup
│   ├── setup_arc_structure.sh    # ARC directory structure setup
│   ├── verify_arc_upload.sh      # File upload verification
│   └── README.md                 # Scripts documentation
│
├── HPC_scripts/                  # HPC cluster scripts (SLURM)
│   ├── batch_transcription.sh    # SLURM batch job script
│   ├── submit_transcription.sh   # Job submission script
│   └── README.md                 # HPC-specific documentation
│
├── src/                          # Core library modules
│   ├── transcription_pipeline.py # Core transcription logic
│   ├── audio_processor.py        # Audio processing utilities
│   ├── utils.py                  # General utilities
│   ├── audio_enhancer.py         # Audio enhancement tools
│   ├── enhanced_audio_processor.py # Advanced audio processing
│   ├── enhanced_speaker_attribution.py # Speaker identification
│   └── enhanced_text_processing_v2.py # Text post-processing
├── tests/                        # Unit tests
│   └── test_transcription.py
├── audio_input/                  # Source audio files (.wav/.mp3/.m4a/.flac/.ogg/.aac)
├── docker_container/             # Docker deployment files
│   ├── Dockerfile
│   └── docker-entrypoint.sh
├── config.csv                    # Configuration file
├── DEPLOYMENT_GUIDE.md           # Deployment instructions
├── DOCUMENTATION_INDEX.md        # Documentation overview
├── OPEN_SOURCE_SUMMARY.md        # Open source information
├── TECHNICAL_SPECIFICATIONS.md   # Technical details
└── README.md                     # This documentation
```

1. **File Organisation**

   - Place all audio files in `audio_input/`
   - Use `.wav` format for best compatibility
   - Avoid special characters in filenames

2. **Resource Management**

   - Use `HPC_scripts/submit_transcription.sh` for automatic job sizing
   - Monitor GPU usage with `nvidia-smi`
   - Check disk space before large batch jobs

3. **Privacy and Security**
   - Use `--mask-personal-names` for sensitive content
   - Review output files before sharing
   - Archive or delete intermediate files

## Version History

Current version implements:

- **Enhanced Quality Control**: Automatic detection and correction of transcription artifacts
  - Massive repetition removal for AI-generated glitches
  - Punctuation spacing corrections
  - Context-aware name masking to prevent false positives
- Simplified batch submission workflow
- Dynamic audio file detection
- Standard CLI argument conventions
- Comprehensive error handling and logging
- Support for both default and custom models

## Technical Details

### Core Functions

The system is built around key processing functions:

- **Audio Enhancement**: Applies spectral noise reduction, dynamic range compression and signal amplification
- **Model Loading**: Supports default OpenAI Whisper models and custom HuggingFace variants
- **Text Processing**: Comprehensive spelling corrections and Unicode cleanup
- **Privacy Protection**: English personal name masking
- **Output Generation**: Creates both plain text (.txt) and formatted Word (.docx) documents



### Internal Architecture

The system uses modular Python components:

- `src/audio_processor.py`: Audio enhancement and conditioning
- `src/transcription_pipeline.py`: ML model integration and inference
- `src/utils.py`: Text processing and output formatting
- `transcription.py`: Main CLI interface and workflow orchestration



## Open Source Deployment

This workflow is designed to be easily deployable across different HPC environments and local systems. Anonymised templates and containerization options are provided for broad research community use.

### Deployment Options

#### 1. HPC Cluster Deployment

For SLURM-based HPC environments with GPU acceleration:

```bash
# Use anonymised templates in anon_HPC_scripts/
cp anon_HPC_scripts/batch_transcription_template.sh HPC_scripts/batch_transcription.sh
cp anon_HPC_scripts/activate_env_template.sh activate_project_env.sh
cp anon_HPC_scripts/submit_batch_template.sh submit_batch.sh

# Configure for your environment
# Edit paths, SLURM accounts and module names as needed
```

**Setup Steps:**

1. Update `YOUR_SLURM_ACCOUNT` in batch scripts
2. Set `YOUR_PROJECT_DIRECTORY` in environment scripts
3. Adjust Python module versions for your cluster
4. Configure GPU partition and resource limits

#### 2. Docker Container Deployment

For containerized deployment with GPU support:

```bash
# Build the container
docker build -t speech-transcription .

# Run with GPU support
docker run --gpus all \
  -v /path/to/audio:/app/audio_input \
  -v /path/to/output:/app/output \
  speech-transcription

# Run specific file
docker run --gpus all \
  -v /path/to/audio:/app/audio_input \
  -v /path/to/output:/app/output \
  speech-transcription audio_input/file.wav --mask-personal-names
```

**Container Features:**

- NVIDIA CUDA support for GPU acceleration
- Automatic audio file detection and batch processing
- Volume mounting for audio input and transcription output
- Built-in quality improvements and text processing

#### 3. Local Installation

For direct installation on local systems:

```bash
# Clone repository
git clone https://github.com/pablobernabeu/secure_local_HPC_speech_transcription.git
cd speech_transcription

# Install dependencies
pip install -r requirements.txt

# Run transcription
python transcription.py audio_file.wav --mask-personal-names --force-english
```

### Configuration Templates

The `anon_HPC_scripts/` directory contains anonymised versions of HPC-specific scripts:

- `batch_transcription_template.sh` - SLURM batch processing template
- `activate_env_template.sh` - Environment activation template
- `submit_batch_template.sh` - Job submission template
- `single_file_transcription_template.sh` - Single file processing template
- `download_model_template.py` - Model download template
- `HPC_SETUP_GUIDE.md` - Comprehensive setup documentation
- `README_template.md` - Template documentation

### Customization Guide

#### For Different HPC Systems

1. **SLURM Parameters**: Adjust resource requests (memory, time, partition)
2. **Module System**: Update Python module names and versions
3. **Storage Paths**: Configure project directories and cache locations
4. **Account Settings**: Replace placeholder account information

#### For Different Models

- Default: `openai/whisper-large-v3` (high accuracy)
- Specialized: `rishabhjain16/whisper_large_v2_to_pf10h` (British children's speech)
- Custom: Any HuggingFace Whisper variant

#### For Different Languages

- Use `--force-english` to prevent language switching
- Remove `--force-english` for multilingual transcription
- Adjust name masking lists for different languages

### Community Contributions

This workflow is designed for research community use. Contributions welcome for:

- Additional HPC scheduler support (PBS, LSF, etc.)
- Language-specific name masking improvements
- Model optimisation for specific domains
- Audio format support expansion
- Quality improvement algorithms

### Performance Optimisation

#### HPC Environments

- **Parallel Processing**: Linear scaling with available GPU nodes
- **Model Caching**: One-time download, persistent across jobs
- **Resource Efficiency**: Automatic CPU fallback when GPUs unavailable

#### Container Deployments

- **GPU Acceleration**: NVIDIA Docker runtime required
- **Memory Management**: Automatic cleanup between files
- **Batch Processing**: Automatic detection of multiple audio files

### Quality Features

All deployment methods include enhanced quality improvements:

- **Repetition Detection**: Removes AI-generated artifacts (e.g., repeated sentences)
- **Punctuation Correction**: Fixes spacing around punctuation marks
- **Enhanced Name Masking**: Production-grade privacy protection with intelligent filtering
  - **Global Database**: 730K+ first names and 980K+ surnames from 106 countries
  - **Smart Filtering**: Prevents masking of common English words (e.g., "The", "Okay", "Yeah", "Well", "But", "Move", "Thank")
  - **Case-Insensitive Detection**: Identifies names regardless of capitalization
  - **Surname Recognition**: Distinguishes surnames with [SURNAME] placeholder
  - **Title Preservation**: Maintains professional titles with [TITLE] placeholder
  - **Comprehensive Exclusions**: Filters out conversation words, prepositions, verbs and common nouns
- **Text Processing**: Comprehensive spelling corrections and formatting

These improvements address common issues in AI transcription systems, including overly aggressive name masking that previously replaced common English words, providing production-ready output suitable for research applications.

### Deployment Comparison

| Feature                 | HPC Cluster               | Docker Container            | Local Installation        |
| ----------------------- | ------------------------- | --------------------------- | ------------------------- |
| **Performance**         | Highest (multi-GPU)       | High (single GPU)           | Variable (CPU/GPU)        |
| **Scalability**         | Excellent (100s of files) | Good (batch processing)     | Limited (single files)    |
| **Setup Complexity**    | High (cluster-specific)   | Medium (Docker required)    | Low (pip install)         |
| **Resource Management** | Automatic (SLURM)         | Manual (container limits)   | Manual (system resources) |
| **Reproducibility**     | Cluster-dependent         | Excellent (containerized)   | Environment-dependent     |
| **Accessibility**       | Requires HPC access       | Requires Docker + GPU       | Universal                 |
| **Ideal Use Case**      | Large research projects   | Development + small batches | Individual files          |

### Quick Start Examples

#### Process Single File (Local)

```bash
python transcription.py interview.wav --mask-personal-names --force-english
```

#### Process Multiple Files (Docker)

```bash
docker run --gpus all \
  -v ./audio_input:/app/audio_input \
  -v ./transcriptions:/app/output \
  speech-transcription
```

#### Process Large Dataset (HPC)

```bash
# Configure for your environment first
sbatch HPC_scripts/batch_transcription.sh
```

### Citation

If you use this workflow in your research, please cite:

```bibtex
@software{speech_transcription_workflow,
  title={Secure and Scalable Speech Transcription for Local and HPC},
  author={Pablo Bernabeu},
  year={2025},
  url={https://github.com/pablobernabeu/secure_local_HPC_speech_transcription}
}
```

### Licence

This project was developed by Dr Pablo Bernabeu at the Department of Education at the University of Oxford. It is licenced under the [Creative Commons Attribution 4.0 International licence](https://creativecommons.org/licences/by/4.0/legalcode.en). 

### Support

For issues and questions:

- Check the HPC_SETUP_GUIDE.md for detailed setup instructions
- Review Docker logs for container troubleshooting
- Submit issues on GitHub for community support
