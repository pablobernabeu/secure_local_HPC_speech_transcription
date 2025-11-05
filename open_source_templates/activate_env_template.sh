#!/bin/bash

# Activate project-specific Python environment
export PROJECT_DIR="YOUR_PROJECT_DIRECTORY"
export PYTHONUSERBASE="$PROJECT_DIR/.python_user"
export PIP_CACHE_DIR="$PROJECT_DIR/.pip_cache"
export HF_HOME="$PROJECT_DIR/.huggingface_cache"
export TRANSFORMERS_CACHE="$PROJECT_DIR/.huggingface_cache"
export TORCH_HOME="$PROJECT_DIR/.torch_cache"
export PIP_CONFIG_FILE="$PROJECT_DIR/venv/pip_conf/pip.conf"

# Enable same name autoswapping to avoid conflicts
export LMOD_DISABLE_SAME_NAME_AUTOSWAP=no

# Load Python module (adjust version as needed for your HPC)
module load Python/3.12.3-GCCcore-13.3.0

# Activate virtual environment
source "$PROJECT_DIR/venv/bin/activate"

echo "□□✅ Project environment activated!"
echo "   Virtual env: $VIRTUAL_ENV"
echo "   Python cache: $PYTHONUSERBASE"
echo "   HuggingFace cache: $HF_HOME"
