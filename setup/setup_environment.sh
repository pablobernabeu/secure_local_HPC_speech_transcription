#!/bin/bash

# One-time Environment Setup for Speech Transcription Pipeline
# Run this once to set up Python 3.12.3 environment with all dependencies
# Usage: ./setup_environment.sh
#
# The venv is created in the CURRENT directory as ./venv.
# activate_project_env_arc.sh, which every job sources, looks only for
# $DATA/speech_transcription_env/bin/python (the conda environment the
# committed results used) or $DATA/speech_transcription_env/venv, so run this
# from $DATA/speech_transcription_env or the jobs will not find the venv.
#
# The packages come from requirements-lock.txt, the pip freeze of the ARC
# job environment behind the committed results, with the CUDA 12.1 wheel
# index for torch and torchaudio. The script used to install an unpinned
# torch, torchvision and torchaudio from that index and a short unpinned
# list, without requirements.txt, so python-docx, names-dataset, jiwer and
# datasets were missing and two runs could build different environments
# (audit findings CORE-21, DEPS-03). Step 4 now checks every pin with
# `python -m preflight --lock`. The lock was taken under Python 3.12.12; this
# venv uses the Python/3.12.3 module, the same minor version. Run the script
# in an interactive session on a compute node: the ARC login nodes cap
# virtual memory at 2 GB, under which the CUDA build of torch cannot load,
# so Step 4 fails there.
#
# The script stops at the first failing step (set -e) instead of reporting
# success regardless.

set -euo pipefail

# The repository is located from this script, because the script is run from
# $DATA/speech_transcription_env (above), where the repository's modules are
# not importable from the current directory.
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "SPEECH TRANSCRIPTION ENVIRONMENT SETUP"
echo "=========================================="
echo "Setting up Python 3.12.3 with all required packages..."
echo ""

EXPECTED_ENV_DIR="${DATA:-}/speech_transcription_env"
if [[ -z "${DATA:-}" || "$(pwd)" != "$EXPECTED_ENV_DIR" ]]; then
    echo "⚠️  Creating ./venv in $(pwd)."
    echo "   The job scripts look for the venv in $EXPECTED_ENV_DIR/venv and will"
    echo "   not find this one unless you run the script from there."
    echo ""
fi

# Step 1: Environment Setup
echo "STEP 1: Loading Python module..."
module purge
module load Python/3.12.3-GCCcore-13.3.0
echo "   Python module loaded"

# Step 2: Virtual Environment Setup
echo ""
echo "STEP 2: Setting up virtual environment..."
if [ -d "venv" ]; then
    echo "   Removing existing virtual environment..."
    rm -rf venv
fi

echo "   Creating fresh virtual environment..."
python3 -m venv venv
echo "   Virtual environment created"

# venv's activate script is not written for `set -u`.
set +u
source venv/bin/activate
set -u
echo "   ✅ Virtual environment activated: $VIRTUAL_ENV"

# Step 3: Install Dependencies
echo ""
echo "STEP 3: Installing dependencies..."

# Upgrade pip first. pip itself is not in the lock (pip freeze omits it) and
# does not change which versions get installed.
echo "   Upgrading pip..."
python3 -m pip install --upgrade pip

# The exact environment behind the committed results, CUDA builds included.
echo "   Installing requirements-lock.txt (CUDA 12.1 builds of torch and torchaudio)..."
python3 -m pip install -r "$REPO_DIR/requirements-lock.txt" \
    --extra-index-url https://download.pytorch.org/whl/cu121

# Step 4: Verify Installation
echo ""
echo "STEP 4: Verifying installation..."
# Every installed version must equal its pin. Run from the repository so
# preflight is importable; a login node's missing GPU is only a warning.
(cd "$REPO_DIR" && python3 -m preflight --lock requirements-lock.txt)
python3 -c "
import torch
print(f'   ✅ PyTorch {torch.__version__} (CUDA: {torch.cuda.is_available()})')
import transformers
print(f'   ✅ Transformers {transformers.__version__}')
import pyannote.audio
print(f'   ✅ Pyannote.audio available')
import librosa
print(f'   ✅ Librosa {librosa.__version__}')
import soundfile
print(f'   ✅ SoundFile {soundfile.__version__}')
try:
    import imageio_ffmpeg
    ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
    print(f'   ✅ FFmpeg binary available at: {ffmpeg_path}')
except ImportError:
    print(f'   ❌ FFmpeg binary not available')
print(f'   ✅ All libraries successfully loaded!')
"

# Step 5: Cache Models (Optional)
echo ""
echo "STEP 5: Pre-caching models (optional)..."
# Asked only on a terminal; a non-interactive run (e.g. a batch job) skips
# caching instead of reading an empty answer.
REPLY="n"
if [[ -t 0 ]]; then
    read -p "Do you want to pre-cache the models now? This will download ~2GB but speed up future jobs. (y/n): " -n 1 -r
    echo
fi
if [[ $REPLY =~ ^[Yy]$ ]]; then
    # The diarisation model is gated. The token comes from the shared lookup
    # (preflight.resolve_hf_token: environment, then the repository's
    # hf_token.txt, which setup/setup_pyannote.py writes, then HF_HOME); do
    # not hardcode it. The old lookup read setup/hf_token.txt, where nothing
    # writes the token any more. preflight is imported from REPO_DIR, not
    # from the current directory (audit finding CORE-R6).
    #
    # This step is optional, so its failure (no network, gated terms not
    # accepted) is reported and does not abort the setup under set -e; the
    # models then download on first use.
    REPO_DIR="$REPO_DIR" python3 -c "
import os, sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, os.environ['REPO_DIR'])

print('   Caching Whisper model...')
from transformers import pipeline
from evaluation.revisions import revision_for
transcriber = pipeline(
    'automatic-speech-recognition',
    model='openai/whisper-large-v3',
    revision=revision_for('openai/whisper-large-v3'),
    torch_dtype='float16' if __import__('torch').cuda.is_available() else 'float32'
)
print('   Whisper model cached')

from preflight import resolve_hf_token
hf_token = resolve_hf_token()[0]

if hf_token:
    print('   Caching diarisation model...')
    from pyannote.audio import Pipeline
    from evaluation.hub_loading import pinned_checkpoint, token_kwargs
    checkpoint, pin = pinned_checkpoint(Pipeline.from_pretrained,
                                        'pyannote/speaker-diarization-3.1')
    diarization_pipeline = Pipeline.from_pretrained(
        checkpoint, **pin, **token_kwargs(Pipeline.from_pretrained, hf_token))
    if diarization_pipeline is None:
        # pyannote 3.x returns None when the gated terms are not accepted.
        print('   Diarisation model NOT cached: accept the conditions of')
        print('   pyannote/speaker-diarization-3.1 and pyannote/segmentation-3.0.')
    else:
        print('   Diarisation model cached')
else:
    print('   No HuggingFace token found - skipping diarisation model.')
    print('   Run: python setup/setup_pyannote.py to configure speaker attribution.')
print('   Models ready!')
" || echo "   Optional model caching failed; the models will download on first use."
else
    echo "   Skipping model caching - models will be downloaded on first use"
fi

echo ""
# Reached only if every step above succeeded (set -e). CUDA availability is
# what STEP 4 printed; a login node without a GPU reports False there.
echo "🎉 ENVIRONMENT SETUP COMPLETE!"
echo "=============================="
echo "✅ Python 3.12.3 environment ready"
echo "✅ Packages installed from requirements-lock.txt (CUDA 12.1 wheels; see STEP 4)"
echo "✅ Virtual environment: $(pwd)/venv"
echo ""
echo "📝 Next steps:"
echo "   1. Place audio files in audio_input/"
echo "   2. Run: hpc/submit_transcription.sh"
echo ""
echo "🎭 Optional features:"
echo "   • Speaker attribution: python setup/setup_pyannote.py (if not done already)"
echo "   • See README.md for all available options"
echo ""
echo "🔄 To reactivate environment manually:"
echo "   module load Python/3.12.3-GCCcore-13.3.0"
echo "   source venv/bin/activate"

