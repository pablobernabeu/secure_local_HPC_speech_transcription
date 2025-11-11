#!/usr/bin/env python3
"""
Download speech transcription models to project cache.
Usage: python3 download_model.py [--model "MODEL_NAME"]
Default: openai/whisper-large-v3
"""

import sys
import os
from transformers import pipeline
import argparse

def download_model(model_name="openai/whisper-large-v3"):
    """Download a model to the project cache directory."""
    
    print(f">> Downloading {model_name} model to project cache...")
    print(f"   Cache location: {os.environ.get('HF_HOME', 'default')}")
    
    try:
        # Download model using the same pipeline configuration as transcription
        transcriber = pipeline(
            "automatic-speech-recognition",
            model=model_name,
            torch_dtype="float32",  # CPU-compatible for download
            device=-1,  # Use CPU for download
            return_timestamps=False,
            chunk_length_s=15,
            stride_length_s=2,
            ignore_warning=True
        )
        
        print(f"SUCCESS: Model {model_name} download completed successfully!")
        print(f"   Model cached in project space: {os.environ.get('HF_HOME')}")
        
        # Test that the model loads correctly
        print(">> Testing model load...")
        test_result = transcriber("Test audio")  # This will fail but confirms model loads
        
    except Exception as e:
        if "requires the same input length" in str(e) or "test audio" in str(e).lower():
            # This error is expected - it means the model loaded successfully
            print("SUCCESS: Model load test successful!")
            print(f"SUCCESS: Model {model_name} is ready for use in transcription jobs!")
        else:
            print(f"ERROR: Download failed: {e}")
            return False
    
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download speech transcription models")
    parser.add_argument('--model', type=str, default="openai/whisper-large-v3",
                       help='HuggingFace model name (default: openai/whisper-large-v3)')
    
    args = parser.parse_args()
    
    print("Model Download Utility")
    print("=====================")
    print(f"Target model: {args.model}")
    print(f"Cache directory: {os.environ.get('HF_HOME', 'Not set - check environment!')}")
    print("")
    
    success = download_model(args.model)
    
    if success:
        print("")
        print("COMPLETE: Download finished! You can now run transcription jobs:")
        print(f'   ./submit_batch.sh --model "{args.model}"')
    
    sys.exit(0 if success else 1)
