#!/usr/bin/env python3
"""
Download a speech transcription model to the project cache, and check it loads.

Usage: python3 setup/download_model.py [--model "MODEL_NAME"]
Default: openai/whisper-large-v3

The files the transformers pipeline loads are fetched with
``huggingface_hub.snapshot_download`` into ``$HF_HOME``, restricted to
:data:`WEIGHT_PATTERNS`, at the revision ``evaluation.revisions`` pins for
the model (the branch head for a model it does not list). Loadability is
then confirmed by running the ASR pipeline on one second of silence, and
any exception counts as failure. The
previous check called the pipeline on a string that was not a file and
treated the resulting error as success when its message happened to contain
the input text, which depended on how transformers words that error (audit
finding CORE-25).

Exit code: 0 when the model downloads and runs, 1 otherwise.
"""

import argparse
import os
import sys
from pathlib import Path

# The script runs as setup/download_model.py, so the repository root (where
# evaluation.revisions lives) is not on sys.path by default.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from evaluation.revisions import revision_for

DEFAULT_MODEL = "openai/whisper-large-v3"

# What the pipeline actually loads: the JSON/TXT configuration, tokenizer and
# preprocessor files, and the safetensors weights (single file or shards).
# An unrestricted snapshot of openai/whisper-large-v3 is about 25 GB, because
# the repository also carries Flax, PyTorch .bin and fp32 copies of the same
# weights that transformers never reads; this set is about 3.1 GB (audit
# finding CORE-R1). 'model-*.safetensors' is spelt with the hyphen on purpose:
# 'model*.safetensors' would also match the model.fp32-0000N-of-0000M shards.
# A checkpoint published without safetensors still works, because the load
# check below makes the pipeline fetch its .bin weights itself.
WEIGHT_PATTERNS = ["*.json", "*.txt", "model.safetensors", "model-*.safetensors"]


def download_model(model_name=DEFAULT_MODEL):
    """Download *model_name* and run it once on silence.

    Returns True on success, False on any failure (the error is printed).
    Side effects: network download into the HuggingFace cache, limited to
    the files matching :data:`WEIGHT_PATTERNS`.
    """
    print(f">> Downloading {model_name} model to project cache...")
    print(f"   Cache location: {os.environ.get('HF_HOME', 'default')}")

    # The revision the committed results used (None, i.e. the branch head,
    # for a model the paper did not benchmark). Fetching 'main' instead
    # would cache whatever the Hub serves today (audit finding DEPS-16).
    revision = revision_for(model_name)
    if revision:
        print(f"   Revision: {revision}")

    try:
        from huggingface_hub import snapshot_download
        path = snapshot_download(model_name, revision=revision,
                                 allow_patterns=WEIGHT_PATTERNS)
        print(f"SUCCESS: Model {model_name} downloaded to {path}")
    except Exception as e:
        print(f"ERROR: Download failed: {e}")
        return False

    try:
        import numpy as np
        from transformers import pipeline

        print(">> Testing model load...")
        transcriber = pipeline(
            "automatic-speech-recognition",
            model=model_name,
            revision=revision,
            torch_dtype="float32",  # CPU-compatible for the check
            device=-1,
        )
        transcriber({"raw": np.zeros(16000, dtype=np.float32),
                     "sampling_rate": 16000})
    except Exception as e:
        print(f"ERROR: Model downloaded but failed to load or run: {e}")
        return False

    print(f"SUCCESS: Model {model_name} is ready for use in transcription jobs!")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download speech transcription models")
    parser.add_argument('--model', type=str, default=DEFAULT_MODEL,
                        help=f'HuggingFace model name (default: {DEFAULT_MODEL})')

    args = parser.parse_args()

    print("Model Download Utility")
    print("=====================")
    print(f"Target model: {args.model}")
    print(f"Cache directory: {os.environ.get('HF_HOME', 'Not set - check environment!')}")
    print("")

    success = download_model(args.model)

    if success:
        print("")
        print("COMPLETE: Download finished! You can now run transcription jobs, e.g.:")
        print(f'   python transcription.py <recording> --model "{args.model}"')

    sys.exit(0 if success else 1)
