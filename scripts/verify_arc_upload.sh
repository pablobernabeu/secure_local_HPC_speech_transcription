#!/bin/bash
# verify_arc_upload.sh
# Quick verification that all files are in place on ARC

echo "========================================"
echo "ARC Upload Verification"
echo "========================================"
echo ""

# Check base directory
echo "📁 Base Directory:"
pwd
echo ""

# Check scripts
echo "📜 Scripts Directory:"
echo "-----------------------------------"
if [ -d "scripts" ]; then
    echo "✅ scripts/ exists"
    SCRIPT_COUNT=$(ls scripts/*.py scripts/*.sh 2>/dev/null | wc -l)
    echo "   Found $SCRIPT_COUNT script files"
    echo ""
    echo "   Python scripts:"
    ls -1 scripts/*.py 2>/dev/null | sed 's/^/      /'
    echo ""
    echo "   Shell scripts:"
    ls -1 scripts/*.sh 2>/dev/null | sed 's/^/      /'
else
    echo "❌ scripts/ directory not found!"
fi
echo ""

# Check data
echo "📊 Data Directory:"
echo "-----------------------------------"
if [ -d "data" ]; then
    echo "✅ data/ exists"
    echo "   Files:"
    ls -lh data/ 2>/dev/null | tail -n +2 | sed 's/^/      /'
    echo ""
    if [ -f "data/curated_names.csv" ]; then
        NAMES_COUNT=$(wc -l < data/curated_names.csv)
        echo "   ✅ curated_names.csv: $NAMES_COUNT lines"
    else
        echo "   ❌ curated_names.csv not found!"
    fi
else
    echo "❌ data/ directory not found!"
fi
echo ""

# Check configs
echo "⚙️  Configs Directory:"
echo "-----------------------------------"
if [ -d "configs" ]; then
    echo "✅ configs/ exists"
    ls -lh configs/ 2>/dev/null | tail -n +2 | sed 's/^/      /'
    if [ -f "configs/requirements.txt" ]; then
        echo "   ✅ requirements.txt found"
    else
        echo "   ⚠️  requirements.txt not found"
    fi
else
    echo "❌ configs/ directory not found!"
fi
echo ""

# Check environment scripts
echo "🔧 Environment Scripts:"
echo "-----------------------------------"
for script in activate_project_env_arc.sh setup_arc_structure.sh check_arc_modules.sh; do
    if [ -f "$script" ]; then
        echo "   ✅ $script"
    else
        echo "   ❌ $script not found"
    fi
done
echo ""

# Check symlink to data storage
echo "🔗 Data Storage Link:"
echo "-----------------------------------"
if [ -L "data_storage" ]; then
    TARGET=$(readlink data_storage)
    echo "   ✅ data_storage → $TARGET"
else
    echo "   ⚠️  data_storage symlink not found"
    echo "      (will be created by setup_arc_structure.sh)"
fi
echo ""

# Check project space
echo "💾 Project Space ($DATA/speech_transcription_env/):"
echo "-----------------------------------"
PROJECT_DIR="$DATA/speech_transcription_env"
if [ -d "$PROJECT_DIR" ]; then
    echo "   ✅ Project directory exists"
    du -sh "$PROJECT_DIR" 2>/dev/null
    
    # Check key subdirectories
    for dir in venv audio_input transcription_output .huggingface_cache; do
        if [ -d "$PROJECT_DIR/$dir" ]; then
            SIZE=$(du -sh "$PROJECT_DIR/$dir" 2>/dev/null | awk '{print $1}')
            echo "   ✅ $dir/ ($SIZE)"
        else
            echo "   ⚠️  $dir/ not created yet"
        fi
    done
else
    echo "   ⚠️  Project directory not created yet"
    echo "      Run: ./setup_arc_structure.sh"
fi
echo ""

# Check Python availability
echo "🐍 Python Check:"
echo "-----------------------------------"
if command -v python3 &> /dev/null; then
    echo "   ✅ python3: $(python3 --version)"
    echo "   Location: $(which python3)"
else
    echo "   ❌ python3 not found in PATH"
fi
echo ""

# Check if environment is activated
echo "🌟 Environment Status:"
echo "-----------------------------------"
if [ -n "$VIRTUAL_ENV" ]; then
    echo "   ✅ Virtual environment ACTIVE"
    echo "   Location: $VIRTUAL_ENV"
    echo "   Python: $(python --version)"
else
    echo "   ℹ️  Virtual environment not activated"
    echo "   Run: source activate_project_env_arc.sh"
fi
echo ""

# Summary
echo "========================================"
echo "Summary"
echo "========================================"
TOTAL_SCRIPTS=$(ls scripts/*.py scripts/*.sh 2>/dev/null | wc -l)
TOTAL_DATA=$(ls data/* 2>/dev/null | wc -l)
TOTAL_CONFIGS=$(ls configs/* 2>/dev/null | wc -l)

echo "✅ Scripts: $TOTAL_SCRIPTS files"
echo "✅ Data files: $TOTAL_DATA files"
echo "✅ Config files: $TOTAL_CONFIGS files"
echo ""

if [ -f "data/curated_names.csv" ] && [ $TOTAL_SCRIPTS -ge 5 ]; then
    echo "🎉 Upload verification PASSED!"
    echo ""
    echo "Next steps:"
    echo "1. Run: source activate_project_env_arc.sh"
    echo "2. Install packages: pip install -r configs/requirements.txt"
    echo "3. Test transcription on a sample audio file"
else
    echo "⚠️  Some files may be missing"
    echo "Check the output above for details"
fi
echo ""
