# Setup scripts

This directory holds the scripts that install the dependencies, fetch
model weights and build a container. Run them from the repository root.
On Oxford ARC, run `source activate_project_env_arc.sh` first, so that
packages and caches go to project storage.

## `install_requirements.py`

```bash
python setup/install_requirements.py
```

Installs `requirements.txt` into the active Python environment: it
upgrades pip, runs `pip install -r requirements.txt`, checks that torch,
transformers, librosa, soundfile and numpy import, and then offers to run
the speaker-attribution wizard below. It does not create an environment:
outside one it warns and asks before continuing. It installs whatever
torch build `requirements.txt` resolves to and adds no CUDA index, so for
GPU use install a CUDA build of torch and torchaudio yourself
(`python -m preflight` prints the command). It must be run from the
repository root, where it looks for `requirements.txt`.

## `setup_environment.sh`

```bash
cd "$DATA/speech_transcription_env" && bash ~/paper_speech_transcription/setup/setup_environment.sh
```

An ARC-specific alternative that builds a virtual environment from
scratch. It runs `module load Python/3.12.3-GCCcore-13.3.0`, so it fails
on a machine without that module, and creates `./venv` in the current
directory, deleting any venv already there. The job scripts find it only
when that directory is `$DATA/speech_transcription_env`, and the script
warns when it is not. It installs `requirements-lock.txt`, the `pip
freeze` of the ARC job environment, with the CUDA 12.1 wheel index for
the `+cu121` builds of torch and torchaudio, then checks every pin with
`python -m preflight --lock requirements-lock.txt` and imports the core
packages. The lock was taken under Python 3.12.12, and the module
provides 3.12.3, the same minor version. Run it in an interactive
session on a compute node: the ARC login nodes cap virtual memory at
2 GB, under which the CUDA build of torch cannot load, so the check fails
there. It stops at the first failing step. On a terminal it then offers
to pre-cache the Whisper model and, when the shared token lookup
(`preflight.resolve_hf_token`) finds a token, the diarisation model. That
lookup reads the `HF_TOKEN`, `HUGGINGFACE_TOKEN` and
`HUGGING_FACE_HUB_TOKEN` variables, then `hf_token.txt` in the repository
root, then the token file under `$HF_HOME`. A failure in this optional
step is reported and does not undo the setup. The committed results were
produced in the ARC conda environment, not in a venv built by this
script.

## `setup_pyannote.py`

```bash
python setup/setup_pyannote.py
```

The interactive wizard for speaker attribution, which
[PYANNOTE_SETUP_GUIDE.md](../PYANNOTE_SETUP_GUIDE.md) describes. It
checks that pyannote.audio is installed, and offers to install it if not,
with torch and torchaudio in one pip call at the specifiers
`requirements.txt` gives them (pyannote.audio below 4). It asks for a HuggingFace token and saves it to `hf_token.txt` in the
repository root, checks that the token can reach
`pyannote/speaker-diarization-3.1`, downloads and caches the pipeline,
and runs it on a short test signal.

## `cache_pyannote_arc.py`

```bash
python setup/cache_pyannote_arc.py [--no-save-token] [--overwrite-token]
```

Downloads the diarisation pipeline, its segmentation model and its
speaker-embedding model, plus any further pyannote model the pipeline's
configuration names, with no GPU. The files go where pyannote.audio 3.x
reads them, which is not the Hugging Face hub cache: pyannote loads from
`$PYANNOTE_CACHE`, or `~/.cache/torch/pyannote` when that is unset, and no
job sets it. An earlier version downloaded into `$HF_HOME/hub`, which no
job read, so a compute node still tried to download.

The loaders do not all ask for the same revision. The DER benchmark (and
the DER sweep, through it), the anonymisation benchmark,
`setup_pyannote.py` and `setup_environment.sh` load the pipeline at the
commit pinned in `evaluation/revisions.py`. The fine-tuning script loads
the segmentation model at its pin and scores the result through the DER
benchmark. `transcription.py` loads the pipeline at `main`. Whichever
revision the pipeline is loaded at, its configuration names the
segmentation and embedding models without one, so they load at `main`,
and so does the embedding model the anonymisation benchmark loads
directly when the pipeline will not load. Each repository is therefore
fetched at `main`, which also records the branch for an offline load to
resolve, and its commit is compared with the pinned revision. When they
differ, the Hub has moved since the committed results: the pinned
snapshot is downloaded as well and the script exits 2.

A download skips a file the cache already holds, so a damaged one
survives a re-run. The script therefore checks for two kinds of damage: a
cached pipeline `config.yaml` that cannot load or no longer matches the
file the Hub served, and a file in the pipeline's `blobs` directory that
no longer hashes to the name it is stored under. For either, it names the
file to delete or restore and exits 3, so that the run does not report
success. It exits 1 without a token or a cache directory, and 0
otherwise.

It finds the token through the workflow's shared lookup and stores it in
`$HF_HOME/token` with owner-only permissions, unless `--no-save-token` is
given. A different token already stored there is kept unless
`--overwrite-token` is given. Written for the ARC login node, whose
compute nodes cannot download, but it works on any machine with network
access.

## `download_model.py`

```bash
python setup/download_model.py                               # openai/whisper-large-v3
python setup/download_model.py --model openai/whisper-medium
```

Downloads a Whisper model into `$HF_HOME` with
`huggingface_hub.snapshot_download`, limited to the configuration,
tokeniser and safetensors files the transformers pipeline loads (about
3 GB for Large v3, against about 25 GB for the whole repository). It then
runs the model once on a second of silence to confirm that it loads, and
exits non-zero if either step fails. It fetches the default branch, not
the revision pinned in `evaluation/revisions.py`. It downloads no
pyannote model, so use `cache_pyannote_arc.py` for those.

## `Dockerfile` and `docker-entrypoint.sh`

```bash
docker build -f setup/Dockerfile -t speech-transcription .

# Transcribe every recording in ./audio into ./output
docker run --gpus all \
    -v "$PWD/audio:/app/audio_input" -v "$PWD/output:/app/output" \
    speech-transcription

# One file, with explicit options
docker run --gpus all -v "$PWD/audio:/app/audio_input" \
    speech-transcription /app/audio_input/rec.wav --timestamps
```

**The image has never been built or run.** No container runtime was
available where the Dockerfile was written, locally or on ARC, so treat
the first successful build as its test. As written, it starts from
`nvidia/cuda:12.1.1-devel-ubuntu22.04`, pinned by the digest that tag
resolved to on Docker Hub on 2026-09-26, and adds Python 3.12 from the
deadsnakes PPA, since Ubuntu 22.04's own Python 3.10 is below the
workflow's 3.11 floor. It installs `requirements-lock.txt` into a virtual
environment with the CUDA 12.1 wheel index and copies the top-level
modules, `evaluation/`, `data/` and `versions.csv`. `transcription.py`
reads the release it records in every transcript and run manifest from
`versions.csv`. The build then runs
`python -m preflight --lock requirements-lock.txt`, so an installed
version that differs from the lock fails the build. The apt packages
(ffmpeg, sox and the Python patch release among them) are not pinned, so
two builds can differ there.

With no arguments, the entry point transcribes every recording in
`/app/audio_input` with name masking and English as the language. With
arguments, it runs `transcription.py` once with them. It exits non-zero
when a transcription fails, when there is nothing to transcribe, or when
the provenance, review-flag or audio modules cannot be imported. The
image produced none of the committed results, which all ran in the ARC
conda environment.
