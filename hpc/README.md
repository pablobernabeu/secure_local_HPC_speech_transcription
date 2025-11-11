# ARC HPC Scripts

This directory contains SLURM job scripts specifically adapted for the Oxford ARC HPC cluster environment.

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

## Scripts Overview

### submit_batch.sh

Enhanced batch job submission script with:

- Automatic audio file detection
- ARC-specific GPU constraints
- Proper cluster targeting (`--clusters=htc`)
- Intelligent resource allocation

### batch_transcription.sh

Individual job processor with:

- ARC environment module loading
- Conda environment activation from `$DATA`
- GPU verification and monitoring
- Comprehensive error handling
- Timeout protection (3 hours per job)

## Usage

### Basic batch processing

```bash
# Process all audio files in audio_input/
./hpc/submit_batch.sh

# With name masking enabled
./hpc/submit_batch.sh --mask-names

# With custom model
./hpc/submit_batch.sh --model "openai/whisper-large-v3"

# Force English-only transcription
./hpc/submit_batch.sh --force-english

# Combine options
./hpc/submit_batch.sh --mask-names --force-english --model "openai/whisper-large-v3"
```

### Monitoring jobs

```bash
# Check job status on HTC cluster
squeue --me --clusters=htc

# Detailed job information
sacct -j <job_id> --format=JobID,JobName,State,ExitCode,Start,End,Elapsed

# View real-time logs
tail -f slurm-<job_id>_<task_id>.out
```

## Environment Requirements

### Prerequisites

1. Conda environment created in `$DATA/speech_transcription_env`
2. All dependencies installed (PyTorch with CUDA 11.8, transformers, etc.)
3. Audio files placed in `audio_input/` directory

### Module Loading

Scripts automatically load appropriate modules:

- Python 3.11.3 or 3.10.8 (as available)
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
   - Jobs automatically timeout after 3 hours
   - Consider splitting large files
   - Use medium partition for longer jobs

### Job Monitoring

Scripts provide comprehensive logging:

- Environment verification
- GPU detection and specs
- Processing progress
- Output file creation
- Performance metrics

## Performance Optimization

### Tips for Better Performance

1. **Pre-download models**: Run `python download_model.py` on login node
2. **Batch processing**: Use array jobs for multiple files
3. **Resource matching**: Choose appropriate GPU generation for your needs
4. **Storage location**: Use `$DATA` for large environments and cache

### Expected Performance

- **Single file**: ~40 minutes per hour of audio
- **GPU acceleration**: 3-5x faster than CPU-only
- **Batch efficiency**: Linear scaling with available resources

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

