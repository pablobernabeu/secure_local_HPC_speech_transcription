# HPC Usage Guide

## ARC HPC Scripts

This guide covers usage of the transcription system on HPC (High-Performance Computing) clusters, with specific adaptations for the Oxford ARC HPC cluster environment.

## Key Adaptations for ARC

### GPU Configuration

Based on the [ARC user guide GPU constraints](https://arc-user-guide.readthedocs.io/en/latest/job-scheduling.html#list-of-configured-gpu-related-constraints), these scripts implement:

- **Cluster targeting**: `--clusters=htc` (GPUs only available on HTC cluster)
- **GPU resource requests**: `--gres=gpu:1`
- **GPU generation constraints**: `--constraint='gpu_gen:Ampere|gpu_gen:Volta|gpu_gen:Turing'`
- **GPU memory requirements**: `--constraint='gpu_mem:>=16GB'`

### Available GPU Types on ARC

According to ARC documentation:

- **P100**: Pascal generation, 16GB memory
- **V100**: Volta generation, 32GB memory
- **RTX (Titan RTX)**: Turing generation, 24GB memory
- **RTX8000**: Turing generation, 48GB memory
- **A100**: Ampere generation, 40GB/80GB memory

### Partition Strategy

- **short**: Default partition (max 12 hours) for most transcription jobs
- **medium**: For longer jobs (max 48 hours)
- **interactive**: For testing and model downloads

## Quick Start - Batch Processing

The simplest way to process multiple audio files:

```bash
# Place audio files (.wav, .mp3, .m4a, .flac, .ogg, .aac) in audio_input/ directory
# Submit batch job with name masking enabled
hpc/submit_transcription.sh --mask-personal-names

# Submit batch job with repetition fixing for cleaner transcripts
hpc/submit_transcription.sh --fix-spurious-repetitions

# Submit batch job with both name masking and repetition fixing
hpc/submit_transcription.sh --mask-personal-names --fix-spurious-repetitions

# Submit batch job with name masking and save logs and enhanced audio
hpc/submit_transcription.sh --mask-personal-names --save-name-masking-logs --save-enhanced-audio

# Submit batch job with multilingual name masking (the six default languages)
hpc/submit_transcription.sh --mask-personal-names

# Submit batch job with specific languages for targeted masking
hpc/submit_transcription.sh --mask-personal-names --languages-for-name-masking english spanish

# Submit batch job with Chinese and Hindi for Asian content
hpc/submit_transcription.sh --mask-personal-names --languages-for-name-masking chinese hindi

# Submit batch job with Facebook first names + specific language surnames
hpc/submit_transcription.sh --mask-personal-names --use-facebook-names-for-masking --languages-for-name-masking english french

# Submit batch job with custom time limit for long audio files (6 hours per file)
hpc/submit_transcription.sh --mask-personal-names --time-limit 06:00:00

# Submit batch job with custom memory allocation (64GB per job)
hpc/submit_transcription.sh --mask-personal-names --memory 64G

# Submit batch job without name masking
hpc/submit_transcription.sh
```

The system automatically:

- Detects all audio files in `audio_input/`
- Determines the correct number of parallel jobs
- Submits the SLURM job array
- Processes files in parallel on available GPUs

## Single File Processing with Custom Names

Process a specific audio file with optional custom output naming:

```bash
# Basic single file transcription
hpc/submit_transcription.sh --single-file audio_input/interview.wav --language english --mask-personal-names

# Single file with custom output name
hpc/submit_transcription.sh --single-file audio_input/recording_2024_10_03.wav --output-name "client_interview_oct" --mask-personal-names

# Single file with custom time limit for very long audio (10 hours)
hpc/submit_transcription.sh --single-file audio_input/long_interview.wav --time-limit 10:00:00 --mask-personal-names

# Single file with speaker attribution and high memory (128GB)
hpc/submit_transcription.sh --single-file audio_input/meeting.wav --speaker-attribution --memory 128G

# Single file with both custom time and memory
hpc/submit_transcription.sh --single-file audio_input/conference.wav --time-limit 08:00:00 --memory 64G --mask-personal-names

# Single file without name masking
hpc/submit_transcription.sh --single-file audio_input/myfile.mp3 --language english
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

## HPC Single File Processing (Recommended for Production)

For **production use on HPC clusters** (submits to SLURM queue with proper resource allocation):

```bash
# Single file via HPC job system (recommended)
./hpc/submit_transcription.sh --single-file audio_input/interview.wav --language english --mask-personal-names

# Single file with repetition fixing for cleaner transcripts
./hpc/submit_transcription.sh --single-file audio_input/interview.wav --fix-spurious-repetitions --mask-personal-names

# Single file with custom output name via HPC
./hpc/submit_transcription.sh --single-file audio_input/recording.wav --output-name "client_interview_oct" --mask-personal-names
```

**When to use HPC single file:**
- ✅ **Production transcription on HPC clusters**
- ✅ **Proper resource allocation** (GPU, memory, time limits)
- ✅ **Queue management** (doesn't overwhelm cluster)
- ✅ **Same environment as batch jobs** (consistent results)
- ✅ **Full logging and monitoring**

## Advanced Batch Processing

For direct SLURM submission (requires manual array size):

```bash
# Count audio files first
AUDIO_COUNT=$(find audio_input \( -name "*.wav" -o -name "*.WAV" \) -type f | wc -l)

# Submit with correct array size
sbatch --array=1-$AUDIO_COUNT hpc/batch_transcription.sh --mask-personal-names
```

## Custom Time Limits

**Problem:** Some audio files may be very long or processing may take longer than expected, causing jobs to timeout before completion.

**Solution:** Use the `--time-limit` argument to specify a custom maximum time *per audio file* in SLURM format:

```bash
# For batch processing with 6 hour limit per file
hpc/submit_transcription.sh --time-limit 06:00:00 --mask-personal-names

# For single long file with 10 hour limit
hpc/submit_transcription.sh --single-file audio_input/long_interview.wav --time-limit 10:00:00

# For short files with 1 hour limit
hpc/submit_transcription.sh --time-limit 01:00:00 --language english
```

**Default time limits** (when `--time-limit` not specified):
- **GPU mode**: 2 hours per file
- **CPU mode**: 8 hours per file (automatically used when GPU unavailable)

**When to use custom time limits:**
- ✅ Very long audio files (>2 hours of recording)
- ✅ Processing repeatedly times out with default limits
- ✅ Complex audio requiring extra processing time
- ✅ When using speaker attribution on long files
- ❌ Short audio files (<30 minutes) - defaults are sufficient

**Format:** Use SLURM time format `HH:MM:SS`:
- `01:30:00` = 1.5 hours
- `04:00:00` = 4 hours
- `06:00:00` = 6 hours
- `10:00:00` = 10 hours

## Custom Memory Allocation

**Problem:** Very long audio files, speaker attribution, or complex processing may require more memory than the default allocation.

**Solution:** Use the `--memory` argument to specify a custom memory allocation per job:

```bash
# For batch processing with 64GB memory per job
hpc/submit_transcription.sh --memory 64G --mask-personal-names

# For speaker attribution with high memory requirements
hpc/submit_transcription.sh --single-file audio_input/long_meeting.wav --speaker-attribution --memory 128G

# For standard processing with custom memory
hpc/submit_transcription.sh --memory 32G --language english
```

**Default memory limits** (when `--memory` not specified):
- **GPU mode**: 16G per job
- **CPU mode**: 32G per job (automatically used when GPU unavailable)

**When to use custom memory:**
- ✅ Very long audio files (>4 hours of recording)
- ✅ Using speaker attribution (especially with multiple speakers)
- ✅ Jobs fail with "out of memory" errors
- ✅ Processing high-quality/high-bitrate audio
- ❌ Short audio files (<1 hour) - defaults are sufficient

**Format:** Use SLURM memory format with unit suffix:
- `16G` = 16 gigabytes
- `32G` = 32 gigabytes
- `64G` = 64 gigabytes
- `128G` = 128 gigabytes

## Monitoring Jobs

```bash
# Check job status
squeue --me

# Check job status on HTC cluster specifically
squeue --me --clusters=htc

# Detailed job information
sacct -j <job_id> --format=JobID,JobName,State,ExitCode,Start,End,Elapsed

# View real-time logs
tail -f transcription_<job_id>_<task_id>.out
```

## Environment Requirements

### Prerequisites

1. Conda environment created in `$DATA/speech_transcription_env`
2. All dependencies installed (PyTorch with CUDA 11.8, transformers, etc.)
3. Audio files placed in `audio_input/` directory

### Module Loading

Scripts automatically load appropriate modules:

- Python 3.12 (recommended for production)
- CUDA 11.8.0 or latest available
- Falls back gracefully if specific versions unavailable

## Resource Allocation

### Default Settings

- **Memory**: 32GB per job
- **CPUs**: 4 cores per task
- **GPU**: 1 GPU with >=16GB memory
- **Time limit**: 12 hours (short partition)

### GPU Memory Requirements

Different models have different memory needs:

- **whisper-base**: ~2GB GPU memory
- **whisper-large-v3**: ~6-8GB GPU memory
- **Custom models**: Variable, hence >=16GB constraint

## Error Handling

### Common Issues and Solutions

1. **"No GPU detected"**

   - Ensure job submitted to HTC cluster: `--clusters=htc`
   - Check GPU constraints are properly applied

2. **"Environment not found"**

   - Verify conda environment exists in `$DATA/speech_transcription_env`
   - Run setup script if needed

3. **Module loading failures**

   - Scripts fall back to default versions
   - Check `module avail` for available versions

4. **Timeout errors**
   - Jobs may timeout based on partition limits
   - Consider using custom time limits with `--time-limit`
   - Use medium partition for longer jobs

5. **Model download failures**

   - Check internet connectivity
   - Verify HuggingFace model name
   - Pre-download models using `python setup/download_model.py`

6. **Out of memory errors**
   - Increase memory allocation with `--memory` flag
   - Use CPU mode if GPU memory insufficient
   - Process shorter audio segments

### Job Monitoring

Scripts provide comprehensive logging:

- Environment verification
- GPU detection and specs
- Processing progress
- Output file creation
- Performance metrics

## Performance Optimization

### Tips for Better Performance

1. **Pre-download models**: Run `python setup/download_model.py` on login node
2. **Batch processing**: Use array jobs for multiple files
3. **Resource matching**: Choose appropriate GPU generation for your needs
4. **Storage location**: Use `$DATA` for large environments and cache

### Expected Performance

- **Single file**: ~40 minutes per hour of audio
- **GPU acceleration**: 3-5x faster than CPU-only
- **Batch efficiency**: Linear scaling with available resources

## Initial Setup for HPC

**HPC (CRITICAL - Read Carefully!):**

```bash
# Clone the repository
git clone <repository-url>
cd secure_local_HPC_speech_transcription

# CRITICAL: Activate environment BEFORE running setup
# This ensures packages install to project space, not your personal quota
# Note: $DATA is an environment variable set by your HPC system
source activate_project_env.sh

# Now run setup
python setup/install_requirements.py
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
- Choose "no" to skip and run `python setup/setup_pyannote.py` later

**⏱️ Total setup time:** 15-30 minutes (including optional speaker attribution)

**📖 For detailed speaker attribution setup:** See [PYANNOTE_SETUP_GUIDE.md](../PYANNOTE_SETUP_GUIDE.md)

### Environment Activation (Per Session)

After initial setup, activate the environment for each session:

```bash
source activate_project_env.sh
```

## Troubleshooting

### Debug Steps

1. Check SLURM output files: `slurm-<jobid>_<taskid>.out`
2. Verify GPU allocation: `scontrol show job <jobid>`
3. Test environment manually: `srun -p interactive --gres=gpu:1 --pty /bin/bash`
4. Check disk space: `df -h $DATA`

### Contact Support

For ARC-specific issues, consult:

- [ARC User Guide](https://arc-user-guide.readthedocs.io/)
- [ARC Support](https://www.arc.ox.ac.uk/support)
