# =============================================================================
# setup/Dockerfile  -  container image for running transcription.py on a GPU
#
# Purpose: a self-contained image of the transcription pipeline for machines
# without the ARC environment. It produced none of the committed results,
# which all ran in the ARC conda environment.
#
# UNBUILT AND UNVERIFIED. No container runtime was available where this file
# was written (neither locally nor on ARC), so it has never been built or
# run. The base digest below was read from Docker Hub; everything else
# follows the documented behaviour of apt, the deadsnakes PPA and pip, and a
# first build may still fail. Treat the first successful build as the test.
#
# Build (from the repository root, so the COPY paths resolve):
#   docker build -f setup/Dockerfile -t speech-transcription .
#
# Run (transcribes every recording in ./audio, writes to ./output):
#   docker run --gpus all \
#       -v "$PWD/audio:/app/audio_input" -v "$PWD/output:/app/output" \
#       speech-transcription
#   # one file, explicit options:
#   docker run --gpus all -v "$PWD/audio:/app/audio_input" \
#       speech-transcription /app/audio_input/rec.wav --timestamps
#
# What is pinned (audit finding DEPS-14):
#   - The base image, by the digest of the multi-architecture manifest list
#     that nvidia/cuda:12.1.1-devel-ubuntu22.04 resolved to on Docker Hub on
#     2026-09-26 (registry-1.docker.io, Docker-Content-Digest header, and
#     the SHA-256 of the manifest body recomputed to the same value). Its
#     linux/amd64 image is
#     sha256:327c9e046fbf662275be0934742f7e5412f9b24402ee90bf4d649c1a21707912.
#     A tag can be moved; the digest cannot.
#   - Python 3.12, the minor version of the ARC environment, from the
#     deadsnakes PPA, because Ubuntu 22.04's own python3 is 3.10, below
#     setup.py's python_requires>=3.11 and preflight's floor.
#   - Every Python package, from requirements-lock.txt, the pip freeze of the
#     ARC job environment, with the PyTorch cu121 index for the +cu121
#     builds of torch and torchaudio.
# What is not pinned: the apt packages (Ubuntu and deadsnakes) are whatever
# the archives serve at build time, so two builds can differ in ffmpeg, sox
# or the Python 3.12 patch release. TODO: pin them through
# snapshot.ubuntu.com once a build can be verified.
# =============================================================================
FROM nvidia/cuda:12.1.1-devel-ubuntu22.04@sha256:7012e535a47883527d402da998384c30b936140c05e2537158c80b8143ee7425

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
# HF_HOME is the current cache root; TRANSFORMERS_CACHE is deprecated and removed.
ENV HF_HOME=/app/.huggingface_cache
ENV TORCH_HOME=/app/.torch_cache

# System dependencies, then Python 3.12 from the deadsnakes PPA.
RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common \
        gpg-agent \
        ffmpeg \
        sox \
        libsox-fmt-all \
        git \
        wget \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
        python3.12 \
        python3.12-venv \
        python3.12-dev \
    && rm -rf /var/lib/apt/lists/*

# A virtual environment keeps the pinned packages apart from the system
# Python, and its bin/ first on the PATH makes `python` and `python3` (which
# docker-entrypoint.sh calls) the 3.12 interpreter. VIRTUAL_ENV lets
# preflight's isolation check hold the image to its own environment.
RUN python3.12 -m venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH=/opt/venv/bin:$PATH

# Create working directory
WORKDIR /app

# The exact versions of the ARC job environment. requirements.txt holds only
# floors, so installing it would resolve whatever PyPI serves on the day.
COPY requirements-lock.txt .
RUN pip install --no-cache-dir -r requirements-lock.txt \
        --extra-index-url https://download.pytorch.org/whl/cu121

# Copy application code. transcription.py imports audio_io, confidence and
# provenance inside try/except blocks that only print a warning, so leaving
# any of them out yields an image that "succeeds" without manifests or review
# flags. The other top-level modules are copied so the image holds the whole
# pipeline (name masking, redaction, anonymisation, preflight).
COPY transcription.py audio_io.py confidence.py provenance.py preflight.py \
     ner_masking.py audio_redaction.py voice_anonymisation.py ./
COPY evaluation/ ./evaluation/
COPY data/ ./data/

# Build-time check: the image fails to build rather than failing at run time
# when an installed version differs from the lock or a package loads from
# outside the venv. There is no GPU during a build, so CUDA is only a
# warning here.
RUN python -m preflight --lock requirements-lock.txt

# Create necessary directories
RUN mkdir -p audio_input output/transcripts output/enhanced_audio

# Set up entrypoint
COPY setup/docker-entrypoint.sh .
RUN chmod +x docker-entrypoint.sh

ENTRYPOINT ["./docker-entrypoint.sh"]
