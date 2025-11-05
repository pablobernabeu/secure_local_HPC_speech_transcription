FROM nvidia/cuda:12.1-devel-ubuntu22.04

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV HF_HOME=/app/.huggingface_cache
ENV TRANSFORMERS_CACHE=/app/.huggingface_cache
ENV TORCH_HOME=/app/.torch_cache

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    ffmpeg \
    sox \
    libsox-fmt-all \
    git \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Create working directory
WORKDIR /app

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy application code
COPY transcription.py .
COPY src/ ./src/

# Create necessary directories
RUN mkdir -p audio_input output/transcripts output/enhanced_audio

# Set up entrypoint
COPY docker-entrypoint.sh .
RUN chmod +x docker-entrypoint.sh

ENTRYPOINT ["./docker-entrypoint.sh"]
