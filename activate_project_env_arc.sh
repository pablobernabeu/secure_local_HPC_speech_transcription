#!/bin/bash

# Activate project-specific Python environment for Oxford ARC Architecture:
#   - Personal space (~): Scripts, code, configs (this file location)
#   - Project space ($DATA): Large files, models, cache, audio, outputs
#
# Sourced, not executed, by every job script (through arc_activate in
# hpc/common/arc_common.sh) and by hand in an interactive session. Returns 1
# when no usable environment is found, so a job stops instead of running on
# whatever Python happens to be on the PATH.

# Personal space: lightweight files, scripts, code.
# Resolved from the script's own location so the name of the clone directory
# does not need to be hard-coded.
# Assigned before it is exported, so a failed cd is not masked by export's
# own exit status (shellcheck SC2155).
PERSONAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PERSONAL_DIR

# Project space: heavy files, models, cache, data
export PROJECT_DIR="$DATA/speech_transcription_env"
# PYTHONUSERBASE sends a stray `pip install --user` to project storage
# rather than to the home quota. PYTHONNOUSERSITE keeps every user site off
# sys.path, whatever PYTHONUSERBASE says: the account's ~/.local holds torch
# 2.8.0+cpu and transformers 4.56.2, which shadow the environment whenever
# the user site is enabled with its default location (audit finding
# DEPS-02). The .python_user directory was checked on 2026-09-26 and is
# empty, so no job loses a package by this.
export PYTHONUSERBASE="$PROJECT_DIR/.python_user"
export PYTHONNOUSERSITE=1
export PIP_CACHE_DIR="$PROJECT_DIR/.pip_cache"
export HF_HOME="$PROJECT_DIR/.huggingface_cache"
export TORCH_HOME="$PROJECT_DIR/.torch_cache"

# Audio and output directories (large files in $DATA)
export AUDIO_INPUT_DIR="$PROJECT_DIR/audio_input"
export TRANSCRIPTION_OUTPUT_DIR="$PROJECT_DIR/transcription_output"

# Create directories if they don't exist
mkdir -p "$PERSONAL_DIR"
mkdir -p "$PROJECT_DIR"
mkdir -p "$PYTHONUSERBASE"
mkdir -p "$PIP_CACHE_DIR"
mkdir -p "$HF_HOME"
mkdir -p "$TORCH_HOME"
mkdir -p "$AUDIO_INPUT_DIR"
mkdir -p "$TRANSCRIPTION_OUTPUT_DIR"

# Enable same name autoswapping to avoid conflicts
export LMOD_DISABLE_SAME_NAME_AUTOSWAP=no

# The interpreter floor, as in setup.py's python_requires and preflight.py.
_ARC_PYTHON_FLOOR="3.11"

if [ -d "$PROJECT_DIR/bin" ] && [ -f "$PROJECT_DIR/bin/python" ]; then
    # The conda environment behind every committed result (Python 3.12). It
    # carries its own interpreter, so no Python module is loaded. Its python
    # finds its own site-packages; an earlier PYTHONPATH entry naming
    # lib/python3.11/site-packages pointed at a directory that does not exist
    # in this Python 3.12 environment (checked 2026-09-26, audit finding
    # SHELL-07) and has been removed.
    echo "Activating conda environment at $PROJECT_DIR"
    export PATH="$PROJECT_DIR/bin:$PATH"
    VIRTUAL_ENV="$PROJECT_DIR"
    export VIRTUAL_ENV
elif [ -f "$PROJECT_DIR/venv/bin/activate" ]; then
    # A venv built by setup/setup_environment.sh links against the Python
    # module it was created with, so that exact module is loaded. The old
    # fallback loaded whichever of Python 3.12, 3.11 or 3.10 `module spider`
    # listed first, which could be a different build from the venv's, or one
    # below the floor, without a word (SHELL-07).
    _ARC_PYTHON_MODULE="${ARC_PYTHON_MODULE:-Python/3.12.3-GCCcore-13.3.0}"
    if ! module load "$_ARC_PYTHON_MODULE" 2>/dev/null; then
        echo "⚠️  Could not load $_ARC_PYTHON_MODULE, the module setup/setup_environment.sh builds the venv with"
    fi
    echo "Activating venv at $PROJECT_DIR/venv"
    # The venv's activate script is created on ARC, outside the repository,
    # so ShellCheck has nothing to follow (SC1091).
    # shellcheck source=/dev/null
    source "$PROJECT_DIR/venv/bin/activate"
else
    echo "⚠️  No Python environment found at $PROJECT_DIR"
    echo "Expected either:"
    echo "  - Conda environment: $PROJECT_DIR/bin/python"
    echo "  - Venv: $PROJECT_DIR/venv/bin/activate"
    return 1
fi

# Verify activation: the environment's own python must be first on the PATH
# and meet the interpreter floor, or the job stops here.
if ! command -v python &> /dev/null; then
    echo "❌ Failed to activate environment"
    echo "   Python not found in PATH after activation"
    return 1
fi
if ! python -c "import sys; sys.exit(0 if sys.version_info >= tuple(int(p) for p in '$_ARC_PYTHON_FLOOR'.split('.')) else 1)" 2>/dev/null; then
    echo "❌ $(python --version 2>&1) at $(command -v python) is below the Python $_ARC_PYTHON_FLOOR floor"
    echo "   Expected the environment at $PROJECT_DIR (conda bin/python or venv/)."
    return 1
fi

echo "✅ Project environment activated!"
echo ""
echo "Directory Structure:"
echo "  Personal space (scripts): $PERSONAL_DIR"
echo "  Project space (data):     $PROJECT_DIR"
echo ""
echo "Environment:"
echo "  Environment type:   $([ -d "$PROJECT_DIR/conda-meta" ] && echo "Conda" || echo "Venv")"
echo "  Environment path:   $VIRTUAL_ENV"
echo "  Python version:     $(python --version)"
echo "  Python location:    $(command -v python)"
echo "  User site:          disabled (PYTHONNOUSERSITE=1)"
echo "  HuggingFace cache:  $HF_HOME"
echo "  Audio input:        $AUDIO_INPUT_DIR"
echo "  Transcription out:  $TRANSCRIPTION_OUTPUT_DIR"
# The search path goes into every job log, so a package loaded from outside
# the environment shows up there without a separate probe.
echo "  sys.path:           $(python -c 'import sys; print(sys.path)' 2>&1)"
