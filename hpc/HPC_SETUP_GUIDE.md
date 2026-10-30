# Porting the workflow to another HPC cluster

This guide is for administrators and users moving the workflow to a SLURM
cluster other than the University of Oxford's ARC. On ARC itself, follow
[ARC_USAGE_GUIDE.md](../ARC_USAGE_GUIDE.md) instead. The map of every job
script, what it needs and what it writes, is in [README.md](README.md).

## What the scripts assume

Every script in `hpc/` was written for ARC and carries its settings in its
`#SBATCH` lines: `--clusters=htc`, `--partition=short`, and a time,
memory and (for the evaluation jobs) `--gres=gpu:1` request of its own.

The scripts find the repository through `SLURM_SUBMIT_DIR`, so they must
be submitted from the repository root, and the clone directory can have
any name. Each one sources `hpc/common/arc_common.sh` and calls
`arc_activate`, which runs `module purge`, loads `Anaconda3/2025.06-1`
(and `CUDA/13.0.2` for the GPU jobs), then sources
`activate_project_env_arc.sh` from the repository root and aborts if it is
missing. The module versions are ARC's, so on another cluster set
`ARC_ANACONDA_MODULE` and `ARC_CUDA_MODULE` to your site's names before
`sbatch`. A module that cannot be loaded is reported and skipped, and a
cluster without a `module` command runs on the Python on the path. The
preflight that follows decides whether the job can run.

Every job then runs `python -m preflight` (with `--gpu-required` in the
GPU jobs) and stops with exit 2 when it fails. No job installs or repairs
packages, so the environment must be complete before the first
submission.

`activate_project_env_arc.sh` is the one place where the site layout is
written down. It expects an environment variable `$DATA` pointing at
project storage and sets `PROJECT_DIR="$DATA/speech_transcription_env"`,
with the model caches (`HF_HOME`, `TORCH_HOME`) and pip's cache under it.
It turns off the user site (`PYTHONNOUSERSITE=1`), so that nothing in
`~/.local` can shadow the environment, and activates the Python
environment it finds there: a conda environment at
`$PROJECT_DIR/bin/python`, or a virtual environment at
`$PROJECT_DIR/venv`. If neither exists, it stops with an error.

## Setting up

Clone the repository and create the environment under your project
storage. With a virtual environment, for example:

```bash
git clone https://github.com/pablobernabeu/secure_local_HPC_speech_transcription.git
cd secure_local_HPC_speech_transcription

export DATA=/path/to/project/storage          # if your site does not set it
mkdir -p "$DATA/speech_transcription_env"
module load Python                            # a Python 3.11 or later module
python -m venv "$DATA/speech_transcription_env/venv"
source activate_project_env_arc.sh
pip install -r requirements.txt
```

`setup.py` requires Python 3.11 or later, and the ARC environment that
produced the committed results runs Python 3.12. `requirements.txt` states
floors, not the exact versions of that environment. To build the same
environment, install the lock instead, which needs Linux and the CUDA 12.1
wheel index:

```bash
pip install -r requirements-lock.txt \
    --extra-index-url https://download.pytorch.org/whl/cu121
python -m preflight --lock requirements-lock.txt   # every pin must match
```

For GPU jobs, run `python -m preflight --gpu-required` on a GPU node to
confirm the environment before spending GPU time.

A virtual environment links against the Python it was created with, so
the activation script loads that module before activating the venv:
`ARC_PYTHON_MODULE`, by default `Python/3.12.3-GCCcore-13.3.0` (the module
`setup/setup_environment.sh` uses on ARC). On another cluster, export
`ARC_PYTHON_MODULE` with the full name of the module you created the venv
with, in the shell you submit from. The script stops if the activated
Python is older than 3.11.

If your site has no `$DATA`, either export one before sourcing the script
or edit `PROJECT_DIR` in `activate_project_env_arc.sh`. Changing
`PROJECT_DIR` moves the environment and the model caches. It does not
move the default input directory of `hpc/submit_transcription.sh`, which
is `$DATA/speech_transcription_env/audio_input`. Set
`TRANSCRIPTION_AUDIO_DIR` to point it elsewhere.

## Adjusting the job settings

Edit the `#SBATCH` lines to your cluster: remove or replace
`--clusters=htc`, and set `--partition`, `--gres` and any GPU constraint
to what your site uses. Scripts that do not request a GPU
(`batch_transcription.sh`, `aggregate_sweep.sh`, `evaluate_wer.sh`,
`run_tests.sh`, `submit_ami_cache.sh`) need only a CPU partition.

ARC does not require an account line when a user has one project. Users
with more than one choose which to charge by passing `--account` to
`sbatch`, as the evaluation scripts' usage lines do. If your cluster
requires an account, pass `--account` on the command line or add
`#SBATCH --account=YOUR_ACCOUNT` to the scripts.

`hpc/submit_transcription.sh` passes its own `--time` and `--mem` to
`sbatch` (defaults 08:00:00 and 32G, changed with `--time-limit` and
`--memory`), which override the values in `batch_transcription.sh`. The
transcription worker runs on CPU: it empties `CUDA_VISIBLE_DEVICES`
before starting Python and requests no GPU, so a GPU partition gives it
nothing.

## Running and monitoring

```bash
# Transcribe every recording in the input directory
hpc/submit_transcription.sh --mask-personal-names --language english

# Watch the jobs and their logs
squeue --me
tail -f logs/transcription_<job_id>_<task_id>.out
```

The transcripts are written to `output/transcripts/` inside the
repository. Every job script writes its SLURM log to `logs/` in the
repository, named after the job, for example
`logs/transcription_<job_id>_<task_id>.out` and `.err`.

## When something fails

A job that stops at once with "Activation script not found" or "No
Python environment found" was submitted from outside the repository, or
the environment is not where the activation script looks. A job that
stops within seconds with exit 2 failed its preflight: the report at the
top of its log names each failing check and its remedy. On a GPU job, the
usual causes are a node with no usable CUDA device (the report says
whether torch is a CUDA build) or a CPU-only torch. A package loaded from
outside the environment shows as an `isolation` failure. Apply the
remedy from a login node and resubmit, since no job repairs the
environment itself.

This guide gives no run times. Before sizing a larger run, run one
recording, or one evaluation job with its `LIMIT`-style override, and
read the elapsed time from `sacct -j <job_id> --format=JobID,Elapsed`.
