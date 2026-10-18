# Using the workflow on Oxford ARC

This guide records how the workflow runs on the University of Oxford's
Advanced Research Computing (ARC) service, the reference environment for
the project. The same scripts can be adapted to another SLURM cluster
with [hpc/HPC_SETUP_GUIDE.md](hpc/HPC_SETUP_GUIDE.md). Command-line
examples that apply to any cluster are in
[docs/hpc_usage.md](docs/hpc_usage.md), and the evaluation jobs behind the
manuscript are mapped in [hpc/README.md](hpc/README.md).

## Storage layout

The workflow splits its files between two places. The repository, which
holds the code and receives the transcripts, is cloned into your home
directory. The Python environment, the model caches and the recordings
live in project storage under `$DATA`, whose quota is far larger than
the home directory's. `activate_project_env_arc.sh` connects the two:
it sets `PERSONAL_DIR` to the repository (from its own location, so the
clone directory can have any name) and `PROJECT_DIR` to
`$DATA/speech_transcription_env`, points `HF_HOME`, `TORCH_HOME`,
`PIP_CACHE_DIR` and `PYTHONUSERBASE` into project storage, turns the user
site off (`PYTHONNOUSERSITE=1`, because the account's `~/.local` holds a
CPU torch 2.8.0 and transformers 4.56.2 that would otherwise shadow the
environment), and activates the conda environment at
`$PROJECT_DIR/bin/python` or, failing that, a virtual environment at
`$PROJECT_DIR/venv`. Without sourcing it, `python` on ARC is not the
environment the results came from.

```
~/<your clone>/                          # the repository
├── activate_project_env_arc.sh
├── hpc/                                 # SLURM scripts
├── logs/                                # SLURM logs and frozen file lists
├── output/transcripts/                  # transcripts are written here
└── name_masking_logs/                   # with --save-name-masking-logs

$DATA/speech_transcription_env/          # project storage
├── audio_input/                         # recordings to transcribe
├── bin/ ...                             # the conda environment
├── .huggingface_cache/                  # HF_HOME: model weights
└── .torch_cache/                        # TORCH_HOME
```

The activation script also creates `transcription_output/` in project
storage and exports `TRANSCRIPTION_OUTPUT_DIR`, but nothing in the
workflow writes there; transcripts go to `output/transcripts/` in the
repository.

## First session

Clone the repository into your home directory and activate the
environment:

```bash
git clone https://github.com/pablobernabeu/secure_local_HPC_speech_transcription.git ~/paper_speech_transcription
cd ~/paper_speech_transcription
source activate_project_env_arc.sh
```

The default branch is the current code. To rerun the code behind a
particular archived version, check out that commit instead. Activate the
environment in every new session, and before installing any package, so
that packages go to project storage and not to the home quota. If the
environment does not exist yet, [docs/hpc_usage.md](docs/hpc_usage.md)
describes the installer.

## Transcribing recordings

Copy the recordings into the input directory, either from your own
machine or from elsewhere on ARC:

```bash
# From your own machine; <data> is the value of $DATA on ARC (echo $DATA there)
scp interview.wav USER_NAME@arc-login.arc.ox.ac.uk:<data>/speech_transcription_env/audio_input/

# On ARC
cp /path/to/interview.wav "$DATA/speech_transcription_env/audio_input/"
```

WAV, MP3, M4A, FLAC, OGG and AAC files are picked up. Then submit from
the repository:

```bash
cd ~/paper_speech_transcription

# Every recording in audio_input/
hpc/submit_transcription.sh --mask-personal-names --language english

# With repetition fixing and a saved masking log
hpc/submit_transcription.sh --mask-personal-names --fix-spurious-repetitions \
    --save-name-masking-logs

# One recording, with its own output name
hpc/submit_transcription.sh \
    --single-file "$DATA/speech_transcription_env/audio_input/interview.wav" \
    --output-name "client_call" --mask-personal-names

# Name masking restricted to two languages of the dictionary
hpc/submit_transcription.sh --mask-personal-names \
    --languages-for-name-masking english spanish
```

The wrapper freezes the list of recordings, submits one CPU task per
recording to the `htc` cluster's `short` partition, and prints the
commands for monitoring the job. To transcribe a directory other than
`audio_input/`, set `TRANSCRIPTION_AUDIO_DIR` before submitting.

## Monitoring and results

```bash
squeue -M htc -u $USER
tail -f logs/transcription_<job_id>_<task_id>.out
sacct -M htc -j <job_id> --format=JobID,JobName,State,ExitCode,Elapsed
```

Each task logs to `logs/transcription_<job_id>_<task_id>.out` and `.err`
in the repository, and at the end lists the files it wrote. The
transcripts are in `output/transcripts/` in the repository, named after
each recording (or after `--output-name`). To copy them to your own
machine:

```bash
scp -r USER_NAME@arc-login.arc.ox.ac.uk:paper_speech_transcription/output/transcripts ./local_folder/
```

## Speaker diarisation on ARC

Speaker diarisation (`--speaker-attribution`) needs the pyannote model
weights cached before a job starts, because ARC compute nodes have no
outbound internet access. Fetch them once from the login node, which does:

```bash
source ~/paper_speech_transcription/activate_project_env_arc.sh
python ~/paper_speech_transcription/setup/cache_pyannote_arc.py
```

The script finds your HuggingFace token through the workflow's shared
lookup: the `HF_TOKEN`, `HUGGINGFACE_TOKEN` or `HUGGING_FACE_HUB_TOKEN`
environment variables first, then `hf_token.txt` in the repository root,
then the token file under `HF_HOME`. It stores the token in
`$HF_HOME/token` with owner-only permissions (`--no-save-token` skips
this, and a different token already stored there is kept unless you pass
`--overwrite-token`), then downloads `pyannote/speaker-diarization-3.1`,
`pyannote/segmentation-3.0` and `pyannote/wespeaker-voxceleb-resnet34-LM`,
plus any further pyannote model the pipeline's configuration names, at
their `main` revision. `transcription.py`, which the case-study job
runs, loads the pipeline at `main`, and any loaded pipeline loads its
segmentation and embedding models at `main`, because the configuration
names them without a revision. The DER and anonymisation jobs load the
pipeline itself, and the fine-tuning job the segmentation model, at the
revision pinned in `evaluation/revisions.py`. The
downloads go where pyannote.audio 3.x looks for them: `$PYANNOTE_CACHE`,
or `~/.cache/torch/pyannote` when that is unset, as it is in the jobs.
(An earlier version downloaded into `$HF_HOME/hub/`, which pyannote never
reads, so the jobs downloaded the weights again.) Each snapshot is
compared with its pin. If the Hub has moved on, the pinned snapshot is
fetched as well and the script exits 2 with a warning, because a new run
could then load a different snapshot from the committed results. A download
keeps any file the cache already holds, so when the cached pipeline
`config.yaml` is damaged the script names it, says which files to delete
or where to restore it from, and exits 3 (see
[TROUBLESHOOTING.md](TROUBLESHOOTING.md)). It uses
`huggingface_hub.snapshot_download`, so it needs no GPU.

The token must be a "Read" token from https://huggingface.co/settings/tokens,
belonging to an account that has accepted the terms at
https://huggingface.co/pyannote/speaker-diarization-3.1 and
https://huggingface.co/pyannote/segmentation-3.0. Write it with `printf`,
which adds no trailing newline or Windows line ending:

```bash
printf '%s' 'hf_your_token_here' > ~/paper_speech_transcription/hf_token.txt
```

`hf_token.txt` is ignored by git. To check the token before caching:

```bash
curl -s -H "Authorization: Bearer $(cat ~/paper_speech_transcription/hf_token.txt)" \
     https://huggingface.co/api/whoami-v2 | grep -o '"name":"[^"]*"'
```

A response containing your user name confirms the token. The older
`/api/whoami` endpoint returns 401 for some accounts even when the token
is valid, so use `/api/whoami-v2`.

## When something goes wrong

If the wrapper reports no audio files, check the directory it names:
`ls -lh "$DATA/speech_transcription_env/audio_input/"`. If a task stops
at once saying the activation script or `transcription.py` was not
found, it was submitted from outside the repository; `hpc/submit_transcription.sh`
submits from the repository root whatever directory you call it from. A
task that exits 2 within seconds failed its preflight, and the report near
the top of its log names each failed check and its remedy. The jobs never
install or repair packages themselves. To run `python -m preflight` by
hand, activate the environment in an interactive session on a compute
node: the login nodes cap virtual memory at 2 GB, under which the
environment's CUDA build of torch cannot load. It checks torch,
transformers, audio decoding, pyannote, the HuggingFace token and where
each package loads from, and suggests a remedy for each failure.
`quota -s` shows how much of each quota is used.
