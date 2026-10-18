#!/usr/bin/env python3
"""
PyAnnote Setup and Verification Script
======================================

This script sets up pyannote.audio for speaker diarization.
It handles the steps that commonly trip people up:
1. HuggingFace token configuration
2. Model access approval
3. Package installation verification
4. Model download and caching
5. Quick functionality test

Run this ONCE during initial setup to ensure speaker attribution works.
"""

import os
import sys
import tempfile
from pathlib import Path

# The token lives in the repository root, where every consumer looks
# (transcription, the DER and timestamp benchmarks, the HPC job scripts,
# cache_pyannote_arc.py). This script used to read and write setup/hf_token.txt,
# which nothing else reads (audit finding CORE-12).
_REPO_ROOT = Path(__file__).resolve().parent.parent
TOKEN_FILE = _REPO_ROOT / 'hf_token.txt'
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _load_pipeline(Pipeline, model_id, token):
    """Load *model_id* at its pinned revision with the token keyword it takes.

    The revision is the one evaluation/revisions.py records, so the cache
    this step fills holds the snapshot the benchmarks load; the keyword is
    ``use_auth_token`` on pyannote 3.x and ``token`` on 4.x (audit findings
    DEPS-04, DEPS-10).
    """
    from evaluation.hub_loading import pinned_checkpoint, token_kwargs  # noqa: PLC0415

    checkpoint, pin = pinned_checkpoint(Pipeline.from_pretrained, model_id)
    return Pipeline.from_pretrained(
        checkpoint, **pin, **token_kwargs(Pipeline.from_pretrained, token))


def print_header(text):
    """Print a formatted header."""
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70 + "\n")


def print_step(number, text):
    """Print a numbered step."""
    print(f"\n{'─' * 70}")
    print(f"Step {number}: {text}")
    print('─' * 70)


def check_pyannote_installed():
    """Check if pyannote.audio is installed."""
    print_step(1, "Checking pyannote.audio installation")

    try:
        import pyannote.audio
        version = pyannote.audio.__version__
        print(f"✅ pyannote.audio is installed (version {version})")
        return True
    except ImportError:
        print("❌ pyannote.audio is NOT installed")
        return False


def install_pyannote():
    """Install pyannote.audio and dependencies."""
    print("\nInstalling pyannote.audio and required dependencies...")
    print("This may take a few minutes...\n")

    # Check if in virtual environment
    in_venv = hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)
    if not in_venv and not os.environ.get('VIRTUAL_ENV'):
        print("⚠️  WARNING: Not in a virtual environment!")
        print("On HPC: Make sure you've activated the environment:")
        print("  source activate_project_env_arc.sh")
        print("\nInstallation will use system/user site-packages.")
        response = input("Continue anyway? (y/N): ").strip().lower()
        if response != 'y':
            return False

    import subprocess

    packages = [
        "pyannote.audio>=3.1.0",
        "torch>=2.0.0",
        "torchaudio>=2.0.0",
        "speechbrain>=0.5.14",
    ]

    try:
        for package in packages:
            print(f"Installing {package}...")
            # Use python -m pip to ensure it installs into the active environment
            # NOT using --user flag to avoid personal space on HPC
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", package],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                print(f"⚠️  Warning: {package} installation had issues")
                print(result.stderr[:500])  # Show first 500 chars of error
            else:
                print(f"✅ {package} installed successfully")

        print("\n✅ All packages installed!")

        # Show where packages were installed
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", "pyannote.audio"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if line.startswith('Location:'):
                    print(f"   Installed to: {line.split(':', 1)[1].strip()}")
                    break

        return True

    except Exception as e:
        print(f"\n❌ Installation failed: {e}")
        print("\nTry manual installation:")
        print("  pip install pyannote.audio torch torchaudio speechbrain")
        return False


def get_hf_token():
    """Return the HuggingFace token, or None.

    Uses the workflow's shared lookup, preflight.resolve_hf_token, so this
    wizard and the tools that later need the token agree on where it is
    (CORE-13).
    """
    from preflight import resolve_hf_token  # noqa: PLC0415
    return resolve_hf_token()[0]


def save_token_file(token, path=TOKEN_FILE):
    """Write *token* to *path* readable by the owner only (mode 0600).

    Side effect: creates or truncates *path*.
    """
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(token)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def setup_hf_token():
    """Interactive HuggingFace token setup."""
    print_step(2, "HuggingFace Token Setup")

    # Check if token already exists
    existing_token = get_hf_token()
    if existing_token:
        print(f"✅ HuggingFace token found: hf_...{existing_token[-4:]}")
        response = input("\nUse existing token? (y/n): ").strip().lower()
        if response == 'y':
            return existing_token

    # Provide instructions
    print("\n📝 To use pyannote speaker diarization, you need a HuggingFace token.")
    print("\nHow to get your token:")
    print("  1. Go to: https://huggingface.co/settings/tokens")
    print("  2. Click 'New token' → 'Read' access is sufficient")
    print("  3. Copy the token (starts with 'hf_...')")
    print("\nThen you must accept the pyannote model licence:")
    print("  1. Visit: https://huggingface.co/pyannote/speaker-diarization-3.1")
    print("  2. Click 'Agree and access repository'")
    print("  3. Also visit: https://huggingface.co/pyannote/segmentation-3.0")
    print("  4. Click 'Agree and access repository' there too")

    # Get token from user
    print("\n" + "─" * 70)
    token = input("Enter your HuggingFace token (or press Enter to skip): ").strip()

    if not token:
        print("\n⚠️  Skipped token setup")
        print("Speaker attribution will NOT work without a token.")
        print("You can run this script again later to set it up.")
        return None

    # Validate token format
    if not token.startswith('hf_'):
        print("\n⚠️  Warning: Token should start with 'hf_'")
        print("Your token may not work correctly.")

    # Save token to file
    try:
        token_file = save_token_file(token)
        print(f"\n✅ Token saved to: {token_file}")

        # Also set environment variable for the rest of this wizard only;
        # later runs find the token through the file above.
        os.environ['HF_TOKEN'] = token
        print("✅ Token set for this setup session")

    except Exception as e:
        print(f"\n❌ Failed to save token: {e}")
        print(f"\nYou can manually create {TOKEN_FILE} with your token.")

    return token


def verify_model_access(token):
    """Verify access to pyannote models."""
    print_step(3, "Verifying Model Access")

    if not token:
        print("❌ No token available - skipping model access verification")
        return False

    print("Checking access to pyannote/speaker-diarization-3.1...")

    try:
        from huggingface_hub import HfApi
        api = HfApi()

        # Try to access the model info
        model_id = "pyannote/speaker-diarization-3.1"
        try:
            api.model_info(model_id, token=token)
            print(f"✅ Access confirmed to {model_id}")
            return True
        except Exception as e:
            error_str = str(e).lower()
            if 'gated' in error_str or 'access' in error_str or '401' in error_str or '403' in error_str:
                print("\n❌ Model access denied!")
                print("\nYou need to accept the model licence:")
                print(f"  1. Visit: https://huggingface.co/{model_id}")
                print("  2. Click 'Agree and access repository'")
                print("  3. Also visit: https://huggingface.co/pyannote/segmentation-3.0")
                print("  4. Click 'Agree and access repository' there too")
                print("\nAfter accepting, run this script again.")
                return False
            else:
                print(f"⚠️  Unexpected error: {e}")
                return False

    except ImportError:
        print("Installing huggingface_hub...")
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "huggingface_hub"])
        print("Please run this script again.")
        return False


def download_and_cache_models(token):
    """Download and cache pyannote models."""
    print_step(4, "Downloading and Caching Models")

    if not token:
        print("❌ No token available - skipping model download")
        return False

    print("This will download ~2GB of models (one-time operation)...")
    # pyannote.audio 3.x caches in $PYANNOTE_CACHE or ~/.cache/torch/pyannote,
    # not under HF_HOME as this message used to say (CORE-R3).
    from preflight import pyannote_cache_dir  # noqa: PLC0415
    print(f"Models will be cached in {pyannote_cache_dir()}")

    try:
        from pyannote.audio import Pipeline

        model_id = "pyannote/speaker-diarization-3.1"
        print(f"\nLoading {model_id}...")
        print("(This may take 5-10 minutes on first run)")

        pipeline = _load_pipeline(Pipeline, model_id, token)
        # pyannote 3.x returns None instead of raising when the gated
        # model's terms have not been accepted for this token.
        if pipeline is None:
            raise RuntimeError(
                f"{model_id} did not load: accept its conditions on the Hub "
                "for the account that owns this token, then run this again.")

        print("\n✅ Model downloaded and cached successfully!")
        print(f"   Model: {model_id}")
        print("   Future runs will be much faster (uses cached model)")

        return True

    except Exception as e:
        error_str = str(e).lower()
        if 'gated' in error_str or 'access' in error_str:
            print("\n❌ Model access still denied!")
            print("Make sure you've accepted BOTH model licences:")
            print("  • https://huggingface.co/pyannote/speaker-diarization-3.1")
            print("  • https://huggingface.co/pyannote/segmentation-3.0")
        else:
            print(f"\n❌ Model loading failed: {e}")

        return False


def test_pyannote_functionality(token):
    """Test pyannote with a simple audio example."""
    print_step(5, "Testing Pyannote Functionality")

    if not token:
        print("❌ No token available - skipping functionality test")
        return False

    print("Creating a test audio file...")

    try:
        import numpy as np
        import soundfile as sf

        # Create a simple test audio (1 second of silence at 16kHz)
        sample_rate = 16000
        duration = 1.0
        audio_data = np.zeros(int(sample_rate * duration))

        # A private temporary directory, removed on success and on failure.
        # A fixed name in the shared temp directory (the previous choice) was
        # left behind by a failed run and then could not be overwritten by
        # the next user on the same login node (audit finding CORE-R5).
        with tempfile.TemporaryDirectory(prefix="setup_pyannote_",
                                         ignore_cleanup_errors=True) as tmp:
            test_audio_path = Path(tmp) / "test_pyannote.wav"
            sf.write(test_audio_path, audio_data, sample_rate)

            print(f"✅ Test audio created: {test_audio_path}")

            # Test pyannote
            print("\nRunning pyannote pipeline on test audio...")
            from pyannote.audio import Pipeline

            pipeline = _load_pipeline(Pipeline, "pyannote/speaker-diarization-3.1",
                                      token)
            if pipeline is None:
                # pyannote 3.x returns None, after printing its own notice,
                # when the gated conditions have not been accepted.
                raise RuntimeError(
                    "Pipeline.from_pretrained returned None; accept the "
                    "conditions of every pyannote model listed above")

            # Run diarization (will be quick on 1 second of audio)
            diarization = pipeline(str(test_audio_path))

        print("✅ Pyannote pipeline executed successfully!")
        print(f"   Result: {len(list(diarization.itertracks()))} segments detected")
        print("   (0 segments is expected for silence)")
        print("✅ Test audio cleaned up")

        return True

    except Exception as e:
        print(f"\n❌ Functionality test failed: {e}")
        print("\nThis might be due to:")
        print("  • Missing audio libraries (soundfile, librosa)")
        print("  • GPU/CUDA issues (try CPU mode)")
        print("  • Model loading issues")

        return False


def print_summary(results):
    """Print setup summary."""
    print_header("Setup Summary")

    print("Status of each component:\n")

    steps = [
        ("pyannote.audio installed", results.get('installed', False)),
        ("HuggingFace token configured", results.get('token', False)),
        ("Model access verified", results.get('access', False)),
        ("Models downloaded and cached", results.get('cached', False)),
        ("Functionality test passed", results.get('tested', False)),
    ]

    for step, status in steps:
        icon = "✅" if status else "❌"
        print(f"  {icon} {step}")

    all_success = all(status for _, status in steps)

    print("\n" + "─" * 70)
    if all_success:
        print("🎉 SUCCESS! Speaker attribution is ready to use!")
        print("\nYou can now use the --speaker-attribution flag:")
        print("  python transcription.py input.wav --speaker-attribution")
    else:
        print("⚠️  Setup incomplete - speaker attribution may not work")
        print("\nMissing components:")
        for step, status in steps:
            if not status:
                print(f"  • {step}")

        print("\nNext steps:")
        if not results.get('token'):
            print("  1. Get a HuggingFace token: https://huggingface.co/settings/tokens")
            print("  2. Accept model licences:")
            print("     • https://huggingface.co/pyannote/speaker-diarization-3.1")
            print("     • https://huggingface.co/pyannote/segmentation-3.0")
            print("  3. Run this script again: python setup/setup_pyannote.py")
        else:
            print("  • Check error messages above for specific issues")
            print("  • Try running: pip install --upgrade pyannote.audio")

    print("=" * 70)


def main():
    """Main setup workflow."""
    print_header("PyAnnote Speaker Diarization Setup")

    print("This script will help you set up speaker attribution (diarization).")
    print("It will guide you through:")
    print("  1. Package installation")
    print("  2. HuggingFace token configuration")
    print("  3. Model access verification")
    print("  4. Model download and caching")
    print("  5. Functionality testing")

    input("\nPress Enter to begin...")

    results = {}

    # Step 1: Check/install pyannote
    is_installed = check_pyannote_installed()
    if not is_installed:
        response = input("\nInstall pyannote.audio now? (y/n): ").strip().lower()
        if response == 'y':
            is_installed = install_pyannote()

    results['installed'] = is_installed

    if not is_installed:
        print("\n❌ Cannot proceed without pyannote.audio")
        print("Install it manually: pip install pyannote.audio")
        print_summary(results)
        return

    # Step 2: Setup token
    token = setup_hf_token()
    results['token'] = bool(token)

    if not token:
        print_summary(results)
        return

    # Step 3: Verify model access
    has_access = verify_model_access(token)
    results['access'] = has_access

    if not has_access:
        print_summary(results)
        return

    # Step 4: Download and cache models
    is_cached = download_and_cache_models(token)
    results['cached'] = is_cached

    if not is_cached:
        print_summary(results)
        return

    # Step 5: Test functionality
    is_working = test_pyannote_functionality(token)
    results['tested'] = is_working

    # Final summary
    print_summary(results)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Setup interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
