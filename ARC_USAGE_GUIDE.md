# Oxford ARC Usage Guide

## Quick Start

### 1. Initial Setup (One-time)

All scripts are already uploaded to your ARC account in the following structure:

```
~/speech_transcription/
├── activate_project_env_arc.sh    # Environment activation
├── scripts/
│   ├── submit_transcription.sh    # Job submission script
│   ├── batch_transcription.sh     # SLURM batch script
│   ├── transcription.py           # Main transcription engine
│   ├── batch_processor_with_masking.py
│   ├── enhanced_speaker_attribution.py
│   ├── clean_transcription.py
│   ├── download_model.py
│   ├── config.py
│   └── create_config.py
├── data/
│   ├── curated_names.csv          # 1,728 names database
│   └── config.csv
└── configs/
    └── requirements.txt

$DATA/speech_transcription_env/    # Project space (large files)
├── audio_input/                   # PUT YOUR AUDIO FILES HERE
├── transcription_output/          # Transcripts appear here
├── .huggingface_cache/           # Model cache
└── .torch_cache/                 # PyTorch cache
```

### 2. Activate Environment

Every time you log in to ARC:

```bash
cd ~/speech_transcription
source activate_project_env_arc.sh
```

This activates your conda environment and sets up all necessary paths.

### 3. Upload Audio Files

Copy your audio files to the project space:

```bash
# From your local machine:
scp your_audio.wav USER_NAME@arc-login.arc.ox.ac.uk:$DATA/speech_transcription_env/audio_input/

# Or on ARC, if you have files elsewhere:
cp /path/to/your/audio.wav $AUDIO_INPUT_DIR/
```

Supported formats: WAV, MP3, M4A, FLAC, OGG, AAC

### 4. Run Transcriptions

**The commands from README.md work exactly as documented!**

From your `~/speech_transcription` directory:

#### Batch Processing (Multiple Files)

Process all files in `audio_input/`:

```bash
cd ~/speech_transcription/scripts
./submit_transcription.sh --mask-names --save-name-masking-logs --force-english --fix-repetitions
```

#### Single File Processing

Process one specific file:

```bash
cd ~/speech_transcription/scripts
./submit_transcription.sh --single-file audio_input/interview.wav --output-name "client_call" --mask-personal-names
```

### 5. Monitor Jobs

```bash
# Check job status
squeue -u $USER

# View real-time logs
tail -f transcription_*.out

# Check detailed job info
sacct -j <job_id> --format=JobID,JobName,State,ExitCode,Elapsed
```

### 6. Get Results

Your transcripts will be in:

```bash
$DATA/speech_transcription_env/transcription_output/
```

Download them to your local machine:

```bash
# From your local machine:
scp -r USER_NAME@arc-login.arc.ox.ac.uk:'$DATA/speech_transcription_env/transcription_output/*' ./local_folder/
```

## All README.md Commands Work!

The scripts are designed to be fully compatible with all examples in README.md. Just run them from `~/speech_transcription/scripts/`:

```bash
# Example 1: Basic batch with name masking
./submit_transcription.sh --mask-personal-names

# Example 2: With all quality features
./submit_transcription.sh --mask-personal-names --fix-spurious-repetitions --save-name-masking-logs

# Example 3: Single file with custom output name
./submit_transcription.sh --single-file audio_input/interview.wav --output-name "meeting_notes" --mask-personal-names

# Example 4: Force English transcription
./submit_transcription.sh --force-english --mask-personal-names

# Example 5: Multilingual name masking
./submit_transcription.sh --mask-personal-names --languages-for-name-masking english spanish
```

## Directory Structure Explained

### Personal Space (`~/speech_transcription/`)
- **Quota**: Limited (~20GB)
- **Contents**: Scripts, configs, small data files
- **Purpose**: Lightweight files that don't change much

### Project Space (`$DATA/speech_transcription_env/`)
- **Quota**: Large (~200GB+)
- **Contents**: Audio files, models, outputs, caches
- **Purpose**: Heavy data files and outputs

## Troubleshooting

### "No audio files found"
```bash
# Check if files are in the right place:
ls -lh $AUDIO_INPUT_DIR/

# If empty, copy files there:
cp /path/to/audio/* $AUDIO_INPUT_DIR/
```

### "Environment not activated"
```bash
cd ~/speech_transcription
source activate_project_env_arc.sh
```

### "Script not found"
```bash
# Make sure you're in the scripts directory:
cd ~/speech_transcription/scripts

# Or use full path:
~/speech_transcription/scripts/submit_transcription.sh --mask-personal-names
```

### Check package installation
```bash
python -c "import torch; print('✅ PyTorch:', torch.__version__)"
python -c "import transformers; print('✅ Transformers:', transformers.__version__)"
```

## Next Steps

1. ✅ Environment activated
2. ⏳ Upload audio files to `$AUDIO_INPUT_DIR`
3. ⏳ Verify packages installed (torch, transformers)
4. ⏳ Run test transcription
5. ⏳ Review output quality

## Support

For issues:
1. Check `transcription_*.out` and `transcription_*.err` log files
2. Verify environment activation: `which python` should show conda environment path
3. Check available disk space: `quota -s`
4. Review job status: `squeue -u $USER`
