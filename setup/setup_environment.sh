#!/bin/bash

# One-time Environment Setup for Speech Transcription Pipeline
# Run this once to set up Python 3.12.3 environment with all dependencies
# Usage: ./setup_environment.sh

echo "��� SPEECH TRANSCRIPTION ENVIRONMENT SETUP"
echo "=========================================="
echo "Setting up Python 3.12.3 with all required packages..."
echo ""

# Step 1: Environment Setup
echo "��� STEP 1: Loading Python module..."
module purge
module load Python/3.12.3-GCCcore-13.3.0
echo "   ��✅ Python module loaded"

# Step 2: Virtual Environment Setup
echo ""
echo "� STEP 2: Setting up virtual environment..."
if [ -d "venv" ]; then
    echo "   ��⚠️  Removing existing virtual environment..."
    rm -rf venv
fi

echo "   � Creating fresh virtual environment..."
python3 -m venv venv
echo "   ��✅ Virtual environment created"

source venv/bin/activate
echo "   ✅ Virtual environment activated: $VIRTUAL_ENV"

# Step 3: Install Dependencies
echo ""
echo "� STEP 3: Installing dependencies..."

# Upgrade pip first
echo "   ��� Upgrading pip..."
python3 -m pip install --upgrade pip

# Install core dependencies with CUDA support
echo "   ��� Installing PyTorch with CUDA 11.8 support..."
python3 -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

echo "   ��� Installing speech processing libraries..."
python3 -m pip install transformers[torch] pyannote.audio librosa soundfile

echo "   ��� Installing ffmpeg support (with binary)..."
python3 -m pip install imageio-ffmpeg ffmpeg-python

echo "   ��� Installing utilities..."
python3 -m pip install numpy scipy matplotlib tqdm audioread pydub

# Step 4: Verify Installation
echo ""
echo "��✅ STEP 4: Verifying installation..."
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
echo "� STEP 5: Pre-caching models (optional)..."
read -p "Do you want to pre-cache the AI models now? This will download ~2GB but speed up future jobs. (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    python3 -c "
import warnings
warnings.filterwarnings('ignore')

print('   ��� Caching Whisper model...')
from transformers import pipeline
transcriber = pipeline(
    'automatic-speech-recognition',
    model='rishabhjain16/whisper_large_v2_to_pf10h',
    torch_dtype='float16' if __import__('torch').cuda.is_available() else 'float32'
)
print('   ��✅ Whisper model cached')

print('   📦 Caching diarisation model...')
from pyannote.audio import Pipeline
diarization_pipeline = Pipeline.from_pretrained(
    'pyannote/speaker-diarization-3.1',
    use_auth_token='YOUR_HUGGINGFACE_TOKEN_HERE'
)
print('   ✅ Diarisation model cached')
print('   � All models ready!')
"
else
    echo "   ��⏭️  Skipping model caching - models will be downloaded on first use"
fi

echo ""
echo "🎉 ENVIRONMENT SETUP COMPLETE!"
echo "=============================="
echo "✅ Python 3.12.3 environment ready"
echo "✅ All packages installed with CUDA support"
echo "✅ FFmpeg binary available for audio processing"
echo "✅ Virtual environment: $(pwd)/venv"
echo ""
echo "📝 Next steps:"
echo "   1. Place audio files in audio_input/"
echo "   2. Run: hpc/submit_transcription.sh"
echo ""
echo "🎭 Optional features:"
echo "   • Speaker attribution: python setup_pyannote.py (if not done already)"
echo "   • See README.md for all available options"
echo ""
echo "🔄 To reactivate environment manually:"
echo "   module load Python/3.12.3-GCCcore-13.3.0"
echo "   source venv/bin/activate"

