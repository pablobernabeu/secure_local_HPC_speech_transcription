# PyAnnote Speaker Diarisation Setup Guide

## About Speaker Diarisation

**Speaker diarisation** (also called speaker attribution) is the technical term for determining "who spoke when" in an audio recording. This guide helps you set up the pyannote.audio models to enable automatic speaker identification in your transcripts.

**Note on terminology:** The model names (e.g., `pyannote/speaker-diarization-3.1`) use American spelling, but we use British spelling (diarisation) in documentation.

## Quick Setup (Recommended)

### During Initial Installation (Easiest)

Speaker attribution setup is now **integrated into the main setup**:

```bash
# Local/Development
python scripts/install_requirements.py
# OR
./setup_environment.sh

# HPC (IMPORTANT: Activate environment first!)
source activate_project_env.sh
python scripts/install_requirements.py
```

When prompted during installation, choose "yes" to set up speaker attribution. The wizard guides you through everything automatically.

### Standalone Setup (If You Skipped It)

If you skipped speaker attribution during initial setup:

**Local/Development:**
```bash
python scripts/setup_pyannote.py
```

**HPC (CRITICAL: Activate environment first!):**
```bash
# ALWAYS activate environment before running setup
source activate_project_env.sh

# Now run setup
python scripts/setup_pyannote.py
```

**⚠️ HPC IMPORTANT:** Always activate `activate_project_env.sh` before running any setup scripts. This ensures:
- Packages install to project space (not your personal quota)
- Correct Python environment is used
- Cache directories point to project locations

This interactive script will guide you through:
1. ✅ Installing pyannote.audio and dependencies
2. ✅ Setting up your HuggingFace token
3. ✅ Verifying model access
4. ✅ Downloading and caching models (~2GB)
5. ✅ Testing functionality

**Time required:** 10-15 minutes (mostly downloading)

---

## ⚠️ HPC Setup - CRITICAL INFORMATION

### ALWAYS Activate Environment First

On HPC systems, **you MUST activate the project environment** before running any setup:

```bash
source activate_project_env.sh
```

**Why this is critical:**
- ✅ Installs packages to **project space** (shared quota)
- ❌ Without it: Installs to **personal space** (your limited quota)
- ✅ Sets correct cache directories for models
- ✅ Uses project's virtual environment

**Correct HPC workflow:**
```bash
# 1. Activate environment (REQUIRED!)
source activate_project_env.sh

# 2. Run setup
python scripts/setup_pyannote.py
```

**Wrong workflow (will fill personal space):**
```bash
# ❌ DON'T DO THIS - skips environment activation
python scripts/setup_pyannote.py
```

**Check installation location:**
```bash
# After installing, verify where packages went
pip show pyannote.audio | grep Location

# Should show project path, e.g.:
# Location: /cluster/projects/nn10008k/youruser/speech_transcription/venv/lib/python3.12/site-packages
```

---

## Manual Setup (If script fails)

### Step 1: Install PyAnnote

```bash
pip install pyannote.audio>=3.1.0
```

**Dependencies** (usually auto-installed):
- `torch>=2.0.0`
- `torchaudio>=2.0.0`
- `speechbrain>=0.5.14`
- `huggingface_hub`

**Verify installation:**
```bash
python -c "import pyannote.audio; print(pyannote.audio.__version__)"
```

Should print: `3.1.0` or higher

---

### Step 2: Get HuggingFace Token

1. **Create an account** at [https://huggingface.co](https://huggingface.co) (if you don't have one)

2. **Generate a token:**
   - Go to: [https://huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)
   - Click "New token"
   - Name it something like "pyannote-access"
   - Select "Read" access (Write not needed)
   - Click "Generate"
   - **Copy the token** (starts with `hf_...`)

3. **Accept model licences** (REQUIRED):
   
   Visit **BOTH** of these pages and click "Agree and access repository":
   - [https://huggingface.co/pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1) (note: model name uses American spelling)
   - [https://huggingface.co/pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0)
   
   ⚠️ **Both licences must be accepted!** The diarisation model depends on the segmentation model.

---

### Step 3: Configure Token

Choose **ONE** of these methods:

#### Method A: Token File (Recommended)
Create a file called `hf_token.txt` in your project directory:

```bash
echo "hf_your_actual_token_here" > hf_token.txt
```

#### Method B: Environment Variable
Add to your shell profile (`~/.bashrc` or `~/.bash_profile`):

```bash
export HF_TOKEN="hf_your_actual_token_here"
```

Then reload: `source ~/.bashrc`

#### Method C: HPC Job Script
In your SLURM script, add before running Python:

```bash
export HF_TOKEN="hf_your_actual_token_here"
# or
export HUGGINGFACE_TOKEN="hf_your_actual_token_here"
```

---

### Step 4: Download Models

Models are downloaded automatically on first use, but you can pre-download:

```bash
python -c "
from pyannote.audio import Pipeline
import os

token = os.environ.get('HF_TOKEN') or open('hf_token.txt').read().strip()
pipeline = Pipeline.from_pretrained(
    'pyannote/speaker-diarization-3.1',
    use_auth_token=token
)
print('Models downloaded and cached!')
"
```

**What gets downloaded:**
- Main diarisation model: `pyannote/speaker-diarization-3.1` (~1.5GB) (model name uses American spelling)
- Segmentation model: `pyannote/segmentation-3.0` (~500MB)
- Voice activity detection models
- Speaker embedding models

**Cache location:** `~/.cache/huggingface/hub/`

---

### Step 5: Test Setup

Quick test to verify everything works:

```bash
python -c "
from pyannote.audio import Pipeline
import numpy as np
import soundfile as sf
import os

# Get token
token = os.environ.get('HF_TOKEN') or open('hf_token.txt').read().strip()

# Create test audio (1 second silence)
sf.write('test.wav', np.zeros(16000), 16000)

# Run pipeline
pipeline = Pipeline.from_pretrained(
    'pyannote/speaker-diarization-3.1',
    use_auth_token=token
)
result = pipeline('test.wav')

print('✅ PyAnnote is working!')
print(f'Segments detected: {len(list(result.itertracks()))}')

# Cleanup
import os
os.remove('test.wav')
"
```

Expected output: `✅ PyAnnote is working!`

---

## Common Issues and Solutions

### 1. "401 Unauthorized" or "Access Denied"

**Problem:** Token is not valid or model licences not accepted

**Solutions:**
- ✅ Verify token starts with `hf_` and is not truncated
- ✅ Accept licences at **BOTH** model pages:
  - https://huggingface.co/pyannote/speaker-diarization-3.1
  - https://huggingface.co/pyannote/segmentation-3.0
- ✅ Wait 5 minutes after accepting licences (propagation delay)
- ✅ Check token has "Read" permissions
- ✅ Try regenerating token if problems persist

**Test token:**
```bash
python -c "
from huggingface_hub import HfApi
import os
token = os.environ.get('HF_TOKEN') or open('hf_token.txt').read().strip()
api = HfApi()
info = api.model_info('pyannote/speaker-diarization-3.1', token=token)
print('✅ Token works! Access granted.')
"
```

---

### 2. "No module named 'pyannote'"

**Problem:** pyannote.audio not installed

**Solution:**
```bash
pip install pyannote.audio
```

**If that fails:**
```bash
pip install --upgrade pip
pip install pyannote.audio==3.1.0
```

**If still failing (dependency conflicts):**
```bash
# Create fresh virtual environment
python -m venv venv_pyannote
source venv_pyannote/bin/activate
pip install pyannote.audio torch torchaudio
```

---

### 3. "CUDA out of memory" or GPU Issues

**Problem:** Model is too large for GPU, or GPU not available

**Solution A: Force CPU mode**
```python
import torch
from pyannote.audio import Pipeline

pipeline = Pipeline.from_pretrained(
    'pyannote/speaker-diarization-3.1',
    use_auth_token=token
)

# Force CPU
pipeline = pipeline.to(torch.device('cpu'))
```

**Solution B: Reduce batch size**
```python
# In transcription.py, modify perform_speaker_diarization():
diarization = pipeline(audio_path, batch_size=1)  # Reduce from default
```

**Solution C: Request GPU in SLURM**
```bash
#SBATCH --gres=gpu:1
#SBATCH --partition=gpu
```

---

### 4. "SSL: CERTIFICATE_VERIFY_FAILED"

**Problem:** Network/firewall blocking HuggingFace downloads

**Solution A: Set SSL verification**
```bash
export CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
```

**Solution B: HPC proxy settings**
```bash
export HTTP_PROXY=http://proxy.institution.edu:8080
export HTTPS_PROXY=http://proxy.institution.edu:8080
```

**Solution C: Download on local machine, transfer to HPC**
```bash
# Local machine:
python -c "
from pyannote.audio import Pipeline
Pipeline.from_pretrained('pyannote/speaker-diarization-3.1', use_auth_token='hf_...')
"

# Then tar the cache and transfer:
cd ~/.cache
tar -czf huggingface.tar.gz huggingface/
scp huggingface.tar.gz user@hpc:~/.cache/
```

---

### 5. Models Download Slowly or Timeout

**Problem:** Large model downloads failing

**Solutions:**
- ✅ Use wired connection (not WiFi)
- ✅ Download during off-peak hours
- ✅ Increase timeout:
  ```python
  import huggingface_hub
  huggingface_hub.constants.HF_HUB_DOWNLOAD_TIMEOUT = 600  # 10 minutes
  ```
- ✅ Resume interrupted downloads (automatic with huggingface_hub)

---

### 6. "No speakers detected" in output

**Problem:** Diarisation runs but finds 0 speakers

**Possible causes:**
- ✅ Audio file is actually silent/empty
- ✅ Audio quality too poor (check with audio editor)
- ✅ Single speaker (use `min_speakers=1` parameter)
- ✅ Sample rate issue (pyannote expects 16kHz)

**Debug:**
```python
import librosa
import soundfile as sf

# Load and check audio
audio, sr = librosa.load('your_file.wav', sr=16000)
print(f"Duration: {len(audio)/sr:.1f}s")
print(f"RMS level: {np.sqrt(np.mean(audio**2)):.4f}")
print(f"Silent: {np.all(audio == 0)}")

# Resample if needed
if sr != 16000:
    sf.write('resampled.wav', audio, 16000)
```

---

### 7. "Model loading is slow every time"

**Problem:** Models not being cached properly

**Check cache:**
```bash
ls -lh ~/.cache/huggingface/hub/
```

Should show `models--pyannote--speaker-diarization-3.1` directory (note: model name uses American spelling).

**Fix cache permissions:**
```bash
chmod -R u+rwX ~/.cache/huggingface/
```

**Set explicit cache dir:**
```bash
export HF_HOME=/path/to/writable/cache
export TRANSFORMERS_CACHE=$HF_HOME
```

---

### 8. HPC-Specific: Module Conflicts

**Problem:** System modules interfering with pyannote

**Solution:**
```bash
# Clear modules
module purge

# Load only what you need
module load Python/3.11.3-GCCcore-12.3.0
module load CUDA/12.1.1  # If using GPU

# Verify clean environment
module list
```

---

## Best Practices

### For HPC Environments

1. **Pre-download models before batch jobs:**
   ```bash
   # Interactive session
   srun --time=1:00:00 --mem=8G bash
   python scripts/setup_pyannote.py
   ```

2. **Use token file, not environment variables:**
   - More portable across jobs
   - No risk of exposing token in job scripts
   - Easy to update

3. **Request appropriate resources:**
   ```bash
   # CPU job (slower but always works)
   #SBATCH --cpus-per-task=4
   #SBATCH --mem=16G
   
   # GPU job (faster)
   #SBATCH --gres=gpu:1
   #SBATCH --mem=8G
   ```

4. **Check logs for token issues:**
   ```bash
   grep -i "token\|unauthorized\|401" logs/*.err
   ```

---

### For Local Development

1. **Use virtual environment:**
   ```bash
   python -m venv venv_transcription
   source venv_transcription/bin/activate
   pip install -r requirements.txt
   ```

2. **Keep token secure:**
   - Add `hf_token.txt` to `.gitignore`
   - Never commit tokens to git
   - Use read-only tokens (not write)

3. **Test with small audio first:**
   - 10-30 seconds of audio
   - Verify before processing hours of recordings

---

## Usage Examples

### Basic Usage

```bash
python transcription.py input.wav --speaker-attribution
```

### With Other Options

```bash
python transcription.py input.wav \
  --speaker-attribution \
  --mask-personal-names \
  --fix-spurious-repetitions \
  --language English
```

### HPC Batch Processing

```bash
bash HPC_scripts/submit_transcription.sh \
  --speaker-attribution \
  --audio-dir audio_input/ \
  --output-dir transcriptions/
```

---

## Expected Output Format

**Without speaker attribution:**
```
Hello everyone, welcome to our meeting. Thank you for joining us today.
Let's start with the first agenda item...
```

**With speaker attribution:**
```
[SPEAKER_00] Hello everyone, welcome to our meeting.
[SPEAKER_01] Thank you for joining us today.
[SPEAKER_00] Let's start with the first agenda item...
```

**Notes:**
- Speaker labels (SPEAKER_00, SPEAKER_01, etc.) are arbitrary
- The same speaker should get consistent labels throughout
- Labels don't correspond to specific people (just "speaker A", "speaker B", etc.)

---

## Performance Notes

### Processing Times (Approximate)

| Duration | CPU (4 cores) | GPU (1x V100) |
|----------|---------------|---------------|
| 10 min   | ~5 min        | ~1 min        |
| 1 hour   | ~30 min       | ~5 min        |
| 2 hours  | ~60 min       | ~10 min       |

**Note:** Diarisation adds ~50% overhead vs. transcription-only

### Resource Requirements

**Minimum:**
- 8GB RAM (CPU mode)
- 4GB VRAM (GPU mode)
- 3GB disk space (cached models)

**Recommended:**
- 16GB RAM (CPU mode)
- 8GB VRAM (GPU mode)
- 10GB disk space (room for multiple jobs)

---

## Getting Help

1. **Run diagnostics:**
   ```bash
   python scripts/setup_pyannote.py  # Will identify issues
   ```

2. **Check logs:**
   ```bash
   # Recent transcription logs
   ls -lt logs/*.err | head -5
   cat logs/most_recent_job.err
   ```

3. **Common log patterns:**
   - `"No HuggingFace token found"` → Run setup_pyannote.py
   - `"401 Unauthorized"` → Accept model licences
   - `"CUDA out of memory"` → Use CPU mode
   - `"No module named 'pyannote'"` → Install package

4. **Test in isolation:**
   ```bash
   python -c "from pyannote.audio import Pipeline; print('OK')"
   ```

---

## Comparison with Other Tools

| Feature | PyAnnote | Alternative |
|---------|----------|-------------|
| Accuracy | ⭐⭐⭐⭐⭐ Excellent | Varies |
| Setup | ⭐⭐⭐ Moderate | Easier/Harder |
| Speed | ⭐⭐⭐⭐ Fast | Varies |
| License | MIT (Free) | Often Commercial |
| Support | Active | Varies |

**Why PyAnnote?**
- State-of-the-art accuracy
- Well-maintained
- Free and open-source
- Good documentation
- Active community

**Trade-off:** Requires HuggingFace account and model acceptance (one-time setup)

---

## Frequently Asked Questions

### Do I need a GPU?
No, CPU mode works fine. GPU is faster but not required.

### How much does it cost?
Free! HuggingFace tokens and pyannote models are free.

### Can I process multiple files?
Yes, our batch processing supports it automatically.

### How accurate is it?
Very accurate for:
- Clear recordings (low background noise)
- 2-4 speakers
- Distinct voices

Less accurate for:
- 5+ speakers
- Similar voices
- Overlapping speech
- Poor audio quality

### Can it identify specific people?
No, it only separates speakers (SPEAKER_00, SPEAKER_01, etc.). It doesn't do voice recognition.

### Do I need internet access?
Only for initial setup (downloading models). After that, works offline.

### Can I use my institution's HuggingFace org?
Yes, any HuggingFace token with read access works.

---

## Additional Resources

- **PyAnnote Documentation:** https://github.com/pyannote/pyannote-audio
- **HuggingFace Hub:** https://huggingface.co/pyannote
- **Model Card:** https://huggingface.co/pyannote/speaker-diarization-3.1 (note: model name uses American spelling)
- **Academic Paper:** https://arxiv.org/abs/2104.04045

---

## Quick Reference Commands

```bash
# Setup
python scripts/setup_pyannote.py

# Test
python -c "from pyannote.audio import Pipeline; print('OK')"

# Check token
cat hf_token.txt

# View cache
ls -lh ~/.cache/huggingface/hub/

# Clear cache (if corrupted)
rm -rf ~/.cache/huggingface/hub/models--pyannote*

# Run transcription
python transcription.py input.wav --speaker-attribution
```

---

**Need help?** Run `python scripts/setup_pyannote.py` and it will guide you through troubleshooting.
