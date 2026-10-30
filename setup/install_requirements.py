#!/usr/bin/env python3
"""
Quick dependency installer for HPC environment.
This script installs required packages and provides clear feedback.
"""

import subprocess
import sys
import os
from pathlib import Path

def check_hpc_environment():
    """Check HPC-specific environment setup."""
    print("\n🖥️  Checking HPC environment...")

    # Check if we're on an HPC system. These paths cover common cluster layouts,
    # including the Lmod software tree and per-user scratch areas.
    hpc_indicators = [
        "/apps",
        "/data",
    ]

    on_hpc = (any(os.path.exists(path) for path in hpc_indicators)
              or bool(os.environ.get('SLURM_JOB_ID')))

    if on_hpc:
        print("   ✅ HPC environment detected")

        python_path = subprocess.run(['which', 'python3'], capture_output=True, text=True)
        if python_path.returncode == 0:
            print(f"   Python location: {python_path.stdout.strip()}")

            if 'GCCcore' in python_path.stdout or '/apps' in python_path.stdout:
                print("   ✅ Python module appears to be loaded")
            else:
                print("   ⚠️  Python may not be from the project environment")
                print("   💡 On ARC the project runs a conda Python 3.12; try: "
                      "source activate_project_env_arc.sh")

        # Check library path
        ld_lib_path = os.environ.get('LD_LIBRARY_PATH', '')
        if any(token in ld_lib_path for token in ('/apps', 'GCCcore')):
            print("   ✅ Library paths appear configured")
        else:
            print("   ⚠️  Library paths may not be configured")
            print("   💡 This might cause 'libpython' errors during installation")

        return True
    else:
        print("   ℹ️  Not on HPC system")
        return False

def install_requirements():
    """Install requirements with better error handling."""
    print("📦 Installing Speech Transcription Dependencies")
    print("=" * 50)

    # Check HPC environment (it prints its own advice)
    check_hpc_environment()

    # Check if requirements.txt exists
    if not os.path.exists('requirements.txt'):
        print("❌ requirements.txt not found!")
        print("Make sure you're in the repository root directory")
        return False

    print("📋 Found requirements.txt")

    # Read requirements to show what will be installed. Comment and blank
    # lines are not packages, so they are not counted (CORE-18).
    with open('requirements.txt', encoding='utf-8') as f:
        requirements = [line.strip() for line in f
                        if line.strip() and not line.strip().startswith('#')]

    print(f"📊 Will install {len(requirements)} packages:")
    for req in requirements[:10]:  # Show first 10
        if req.strip():
            print(f"   - {req.strip()}")
    if len(requirements) > 10:
        print(f"   ... and {len(requirements) - 10} more")

    print("\n🚀 Starting installation...")

    try:
        # Upgrade pip first
        print("1. Upgrading pip...")
        result = subprocess.run([
            sys.executable, '-m', 'pip', 'install', '--upgrade', 'pip'
        ], capture_output=True, text=True, timeout=300)

        if result.returncode == 0:
            print("   ✅ pip upgraded successfully")
        else:
            print("   ⚠️  pip upgrade had issues, continuing...")

        # Install requirements
        print("2. Installing requirements...")
        result = subprocess.run([
            sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'
        ], capture_output=True, text=True, timeout=1800)  # 30 minutes timeout

        if result.returncode == 0:
            print("   ✅ All requirements installed successfully!")

            # Show what was installed
            if result.stdout:
                lines = result.stdout.split('\n')
                successful_installs = [line for line in lines if 'Successfully installed' in line]
                if successful_installs:
                    print("   📦 Installed packages:")
                    for line in successful_installs[-3:]:  # Show last few
                        print(f"      {line.strip()}")

            return True
        else:
            print("   ❌ Installation failed!")
            print("\nError output:")
            print(result.stderr)

            # Try to provide helpful suggestions
            error_text = result.stderr.lower()
            if 'libpython' in error_text and 'cannot open shared object file' in error_text:
                print("\n💡 HPC Library Path Issue:")
                print("   This is a common HPC issue. Try these steps:")
                print("   1. module restore")
                print("   2. source activate_project_env_arc.sh")
                print("      (activates the project's conda Python 3.12)")
                print("   3. Re-run this installer")
            elif 'no module named' in error_text:
                print("\n💡 Suggestions:")
                print("   - Make sure you're in a virtual environment")
                print("   - Try: source venv/bin/activate")
            elif 'permission denied' in error_text:
                print("\n💡 Suggestions:")
                print("   - Check file permissions")
                print("   - Make sure you have write access to the environment")
            elif 'timeout' in error_text or 'connection' in error_text:
                print("\n💡 Suggestions:")
                print("   - Check internet connection")
                print("   - Try again (downloads can be slow on HPC)")

            return False

    except subprocess.TimeoutExpired:
        print("   ❌ Installation timed out (took more than 30 minutes)")
        print("   This can happen on slow networks - try again")
        return False
    except Exception as e:
        print(f"   ❌ Installation error: {e}")
        return False

def check_critical_imports():
    """Check if critical packages can be imported."""
    print("\n🧪 Testing critical imports...")

    critical_packages = [
        'torch',
        'transformers',
        'librosa',
        'soundfile',
        'numpy'
    ]

    success_count = 0

    for package in critical_packages:
        try:
            __import__(package)
            print(f"   ✅ {package}")
            success_count += 1
        except ImportError:
            print(f"   ❌ {package}")

    print(f"\n📊 Import test: {success_count}/{len(critical_packages)} packages working")

    if success_count == len(critical_packages):
        print("🎉 All critical packages are working!")
        return True
    else:
        print("⚠️  Some packages failed to import")
        return False

def setup_pyannote_optional():
    """Ask user if they want to set up pyannote now."""
    print("\n" + "=" * 60)
    print("🎭 Speaker Attribution Setup (Optional)")
    print("=" * 60)
    print("\nThis allows you to identify who said what in multi-speaker recordings.")
    print("Requires: HuggingFace account + model access (free)")
    print("Time: ~10-15 minutes (includes ~2GB model download)")
    print("\nYou can skip this and run 'python setup/setup_pyannote.py' later.")
    print()

    response = input("Set up speaker attribution now? (y/N): ").strip().lower()

    if response == 'y':
        print("\n🚀 Running pyannote setup wizard...")
        # Resolved from this file: the wizard lives beside it in setup/, not
        # in the current directory (the repository root), so the bare name
        # made Python exit 2 before the wizard ran (CORE-18).
        wizard = Path(__file__).resolve().parent / 'setup_pyannote.py'
        if not wizard.is_file():
            print(f"⚠️  {wizard} not found")
            return False
        try:
            result = subprocess.run([sys.executable, str(wizard)], timeout=1800)
            if result.returncode == 0:
                print("✅ Speaker attribution is ready!")
                return True
            else:
                print("⚠️  Speaker attribution setup incomplete")
                print("Run 'python setup/setup_pyannote.py' later to complete setup")
                return False
        except subprocess.TimeoutExpired:
            print("⚠️  Setup took too long (>30 minutes)")
            return False
        except Exception as e:
            print(f"⚠️  Setup failed: {e}")
            return False
    else:
        print("⏭️  Skipping speaker attribution setup")
        print("💡 Run 'python setup/setup_pyannote.py' later to enable this feature")
        return False


def main():
    """Main installation function."""
    print("Welcome to HPC Speech Transcription Setup!")
    print()

    in_venv = hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix')
                                              and sys.base_prefix != sys.prefix)
    if not in_venv and not os.environ.get('VIRTUAL_ENV'):
        print("⚠️  Warning: You don't appear to be in a virtual environment")
        print("It's recommended to use a virtual environment:")
        print("   python3 -m venv venv")
        print("   source venv/bin/activate")
        print()

        response = input("Continue anyway? (y/N): ").strip().lower()
        if response != 'y':
            print("Setup cancelled. Set up virtual environment first.")
            return

    # Install requirements
    install_success = install_requirements()

    if install_success:
        # Test imports
        import_success = check_critical_imports()

        if import_success:
            # Offer to set up pyannote
            setup_pyannote_optional()

            print("\n🎯 Setup Complete!")
            print("=" * 60)
            print("✅ All dependencies installed")
            print("✅ Core imports working")
            print()
            print("📝 Next Steps:")
            print("   1. Locally: python transcription.py <recording>")
            print("   2. On ARC: copy recordings to the project-space audio_input/")
            print("      directory and submit hpc/batch_transcription.sh")
            print()
            print("📚 Documentation:")
            print("   • README.md - Main usage guide")
            print("   • PYANNOTE_SETUP_GUIDE.md - Speaker attribution help")
        else:
            print("\n⚠️  Installation completed but some imports failed")
            print("You may need to troubleshoot individual packages")
    else:
        print("\n❌ Installation failed")
        print("Check the error messages above and try again")
        sys.exit(1)

if __name__ == "__main__":
    main()

