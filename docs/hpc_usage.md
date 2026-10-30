# Transcribing on an HPC cluster

This page covers transcribing your own recordings with the SLURM scripts
in `hpc/`. The Oxford ARC specifics (storage layout, first-time setup,
the diarisation model cache) are in
[ARC_USAGE_GUIDE.md](../ARC_USAGE_GUIDE.md), and
[hpc/HPC_SETUP_GUIDE.md](../hpc/HPC_SETUP_GUIDE.md) covers moving the
scripts to another cluster. The evaluation jobs behind the manuscript
are mapped in [hpc/README.md](../hpc/README.md).

## How a submission works

`hpc/submit_transcription.sh` runs on the login node and only submits. In
batch mode it lists the recordings in the input directory, writes the
sorted list to `logs/filelist_<timestamp>_<pid>.txt`, and submits a job array
with one task per recording. Each task runs `hpc/batch_transcription.sh`,
which activates the environment, reads its own entry from that frozen
list, runs `python -m preflight` and then `transcription.py` on the
recording. Freezing the list means that adding or removing recordings
while tasks are queued cannot change which file a task transcribes. A
task whose preflight fails (no torch, transformers below its floor, a
package loaded from outside the environment) stops with exit 2 before
transcribing. A missing GPU is only a warning there, since none is used.

The input directory is `$TRANSCRIPTION_AUDIO_DIR` when that variable is
set, and `$DATA/speech_transcription_env/audio_input` otherwise. The
wrapper stops with an error if neither is available or the directory
holds no audio. It picks up `.wav`, `.mp3`, `.m4a`, `.flac`, `.ogg` and
`.aac` files in any letter case.

The worker runs on CPU only. It empties `CUDA_VISIBLE_DEVICES` before
Python starts, loads no CUDA module and requests no GPU, so a GPU
partition gives it nothing. The GPU jobs in `hpc/` are the evaluation
jobs. Each task gets 4 CPUs, 08:00:00 of wall time and 32G of memory
unless you pass `--time-limit` or `--memory`. `--time-limit` is the only
time limit: the worker has no internal timeout, so the whole allocation is
available to the transcription. The jobs go to the `htc` cluster's `short`
partition, whose limit is 12 hours.

## Batch mode

```bash
# Every recording in the input directory, with name masking
hpc/submit_transcription.sh --mask-personal-names --language english

# Repetition fixing and a saved masking log as well
hpc/submit_transcription.sh --mask-personal-names --fix-spurious-repetitions \
    --save-name-masking-logs

# Only the English and Spanish sections of the name dictionary
hpc/submit_transcription.sh --mask-personal-names \
    --languages-for-name-masking english spanish

# A different input directory, longer tasks and more memory
TRANSCRIPTION_AUDIO_DIR=/path/to/recordings \
    hpc/submit_transcription.sh --time-limit 12:00:00 --memory 64G
```

`--time-limit` takes SLURM's `HH:MM:SS` format and `--memory` a size with
a unit, such as `16G` or `64G`. Both apply to every task in the array.

## A single recording

```bash
hpc/submit_transcription.sh --single-file /path/to/interview.wav \
    --output-name "interview_2024" --mask-personal-names --language english
```

The path is resolved relative to the directory you run the command from.
`--output-name` sets the base name of the output files and is accepted
only with `--single-file`. In batch mode, each recording keeps its own
name.

## Options

The wrapper consumes `--single-file`, `--output-name`, `--time-limit` and
`--memory` itself and passes every other option to `transcription.py`
unchanged, so the options are those listed by `python transcription.py
--help` and in the [README](../README.md#command-line-options). It
checks each option against that list before submitting, so a mistyped
option fails at once, before it can wait hours in the queue.
`hpc/submit_transcription.sh --help` prints the wrapper's own summary.

## Outputs and logs

The transcripts are written to `output/transcripts/` inside the
repository: `<name>_transcript.txt` and `.docx` always, and the further
files listed in the README's output structure when `--timestamps`,
`--speaker-attribution` or `--mask-personal-names` ask for them. The
masking logs, with `--save-name-masking-logs`, go to `name_masking_logs/`
in the repository. These directories hold participants' speech and names
and are ignored by git.

```bash
squeue -M htc -u $USER
tail -f logs/transcription_<job_id>_<task_id>.out
sacct -M htc -j <job_id> --format=JobID,JobName,State,ExitCode,Elapsed
```

Each task writes `logs/transcription_<job_id>_<task_id>.out` and `.err`.
A single-file submission is not an array, and SLURM fills the task field
with a placeholder, so match it with `logs/transcription_<job_id>_*.out`.
The wrapper prints the exact monitoring commands after it submits.

## Submitting the worker directly

`hpc/batch_transcription.sh` can be submitted on its own, from the
repository root. With `--single-file <path>`, it transcribes that file.
As an array job without a file list it lists
`$DATA/speech_transcription_env/audio_input` when the task starts, which
is only safe if nothing is added or removed while tasks are queued:

```bash
N=$(find "$DATA/speech_transcription_env/audio_input" -type f \
      \( -iname '*.wav' -o -iname '*.mp3' -o -iname '*.m4a' \
         -o -iname '*.flac' -o -iname '*.ogg' -o -iname '*.aac' \) | wc -l)
sbatch --array=1-$N hpc/batch_transcription.sh --mask-personal-names
```

A direct submission uses the worker's own settings, 10:00:00 and 40G.
The wrapper is the safer route.

## First-time setup

On ARC, activate the project environment before installing anything, so
that packages go to project storage, outside your home quota:

```bash
source activate_project_env_arc.sh
python setup/install_requirements.py
```

`setup/install_requirements.py` installs `requirements.txt` into the
active environment, checks that the core packages import and offers to
run the speaker-attribution wizard, which can also be run later. It does
not create an environment, and it installs whatever torch build
`requirements.txt` resolves to, with no CUDA index
([setup/README.md](../setup/README.md) has the details). To reproduce the
ARC job environment as it stood on 2026-09-26, when it was frozen,
install `requirements-lock.txt` instead (it needs
`--extra-index-url https://download.pytorch.org/whl/cu121`) and check it
with `python -m preflight --lock requirements-lock.txt`. The jobs never
install anything themselves, so the environment must be complete before
the first submission. Speaker attribution on compute nodes, which have no
internet access, also needs the model weights cached beforehand (see
[ARC_USAGE_GUIDE.md](../ARC_USAGE_GUIDE.md#speaker-diarisation-on-arc)
and [PYANNOTE_SETUP_GUIDE.md](../PYANNOTE_SETUP_GUIDE.md)).

To fetch the Whisper weights on the login node before a batch, so that no
task waits on a download:

```bash
python setup/download_model.py                               # openai/whisper-large-v3
python setup/download_model.py --model openai/whisper-medium
```

It downloads into `$HF_HOME`, which the activation script sets, and runs
the model once on a second of silence to confirm it loads.

## When a task fails

Read the task's `.out` and `.err` files in `logs/` first. A task that
stops at once with "transcription.py not found" or "Activation script not
found" was submitted from outside the repository. "No audio files found"
at submission means the input directory is empty or not the one you
meant, and the wrapper prints which directory it read. A task that ends in
SLURM's `TIMEOUT` state needs a larger `--time-limit`, and one killed for
memory a larger `--memory`. A task that exits 2 within seconds failed its
preflight, and the report near the top of its `.out` names each failed
check and its remedy. To run the same check by hand, run
`source activate_project_env_arc.sh && python -m preflight` in an
interactive session on a compute node, which the
[ARC user guide](https://arc-user-guide.readthedocs.io/) describes how to
start. On a login node the check reports torch as broken, because the ARC
login nodes cap virtual memory at 2 GB, under which the environment's
CUDA build of torch cannot load.

For the cluster itself, see the
[ARC user guide](https://arc-user-guide.readthedocs.io/).
