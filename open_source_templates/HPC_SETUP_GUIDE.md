# HPC Setup Guide for Speech Transcription Workflow

This guide helps you adapt the speech transcription workflow for your specific HPC environment.

## Prerequisites

- Access to an HPC cluster with SLURM job scheduler
- GPU nodes (recommended for performance)
- Python 3.11+ with module system
- Storage space for models and audio files (~50GB recommended)

## Step 1: Environment Setup

### 1.1 Create Project Directory
```bash
# Choose your project location
export PROJECT_DIR="/path/to/your/project/speech_transcription"
mkdir -p $PROJECT_DIR
cd $PROJECT_DIR
```

### 1.2 Clone Repository
```bash
git clone https://github.com/your-username/speech_transcription.git .
```

### 1.3 Set Up Python Environment
```bash
# Load Python module (adjust version for your HPC)
module load Python/3.12.3-GCCcore-13.3.0

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install requirements
pip install -r requirements.txt
```

## Step 2: Configure HPC Scripts

### 2.1 Update SLURM Account
Edit `HPC_scripts/batch_transcription.sh`:
```bash
#SBATCH --account=YOUR_SLURM_ACCOUNT  # Replace with your account
```

### 2.2 Update Project Paths
Edit `activate_project_env.sh`:
```bash
export PROJECT_DIR="/path/to/your/project/speech_transcription"
```

### 2.3 Adjust Resource Requirements
Modify SLURM parameters based on your cluster:
- `--partition`: Your GPU partition name
- `--mem`: Available memory per node
- `--time`: Maximum job time
- `--gres`: GPU specification

## Step 3: Directory Structure
```
your_project/
├── audio_input/           # Place .wav files here
├── HPC_scripts/          # SLURM batch scripts
│   └── batch_transcription.sh
├── output/               # Generated automatically
│   ├── transcriptions/   # .txt and .docx files
│   └── enhanced_audio/   # Processed audio
├── transcription.py      # Main script
├── activate_project_env.sh
├── requirements.txt
└── README.md
```

## Step 4: Usage

### Single File
```bash
python transcription.py audio_input/file.wav --mask-names --force-english
```

### Batch Processing
```bash
# Submit all files in audio_input/
./submit_batch.sh --mask-names --force-english

# Monitor jobs
squeue --me

# Check specific job output
tail -f transcription_<job_id>_<task_id>.out
```

## Step 5: Customization

### Model Selection
- Default: `openai/whisper-large-v3`
- Custom: `--model your/huggingface/model`

### Quality Features
- Name masking: `--mask-names`
- Force English: `--force-english`
- Enhanced processing: Always enabled

### Resource Optimization
- Adjust `--cpus-per-task` based on your nodes
- Modify `--mem` for your available memory
- Set appropriate `--time` limits

## Troubleshooting

### Common Issues
1. **Module not found**: Update Python module name in `activate_project_env.sh`
2. **Permission denied**: Check SLURM account and partition access
3. **GPU unavailable**: Script automatically falls back to CPU
4. **Storage full**: Ensure adequate space for models and outputs

### Support
- Check logs in transcription output files
- Review SLURM job status with `squeue` and `sacct`
- Validate audio file formats (WAV supported)

## Performance Notes
- GPU processing: 2-5 minutes per hour of audio
- CPU fallback: 10-20 minutes per hour of audio
- Model downloads: One-time per model (cached)
- Parallel processing: Linear scaling with available GPUs
